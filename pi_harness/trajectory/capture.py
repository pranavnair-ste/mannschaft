"""Capture pipelines: pi-agent stdout JSONL + ClawTeam task polling.

Assumed pi-agent JSON event schema (one event per stdout line):
    {
        "type":          str,      # "tool_call" | "tool_result" | "message"
        "tool":          str,      # optional; required when type starts with "tool_"
        "input":         dict,     # optional
        "output":        dict,     # optional
        "duration_ms":   int,      # optional, default 0
        "tokens_in":     int,      # optional, default 0
        "tokens_out":    int,      # optional, default 0
        "outcome":       str,      # optional; one of TrajectoryEvent's Outcome
        "step_id":       str,      # optional; falls back to "step-<seq:06d>"
        "ts":            str,      # ISO-8601 with tz; required
        "model":         str,      # required
    }

If pi-coding-agent's actual event names differ (e.g. "assistant_message" vs
"message"), adjust the `_TYPE_MAP` constant below. Unknown `type` values map
to classification "message" so we never drop data.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

from pi_harness.clawteam.client import ClawTeamClient
from pi_harness.config import Config, load_config
from pi_harness.trajectory.schema import TrajectoryEvent, _VALID_OUTCOMES
from pi_harness.trajectory.store import awrite_event


async def _clawteam_list_tasks(team_name: str, *, client: ClawTeamClient | None = None) -> list[Mapping[str, Any]]:
    """Async wrapper over Plan 1's `ClawTeamClient.list_tasks` (sync subprocess).

    Tests patch this symbol directly. When called without an explicit client,
    builds one from a freshly loaded :class:`Config` (caller must have
    ``OPENAI_API_KEY`` set, the same env the team launch requires).
    """
    if client is None:
        client = ClawTeamClient(load_config(env_file=None))
    return await asyncio.to_thread(client.list_tasks, team_name)

log = logging.getLogger(__name__)

# pi-agent type string -> TrajectoryEvent.classification
_TYPE_MAP: dict[str, str] = {
    "tool_call": "tool_call",
    "tool_result": "tool_result",
    "message": "message",
    "assistant_message": "message",
    "user_message": "message",
}


def normalize_pi_agent_event(
    raw: Mapping[str, Any],
    *,
    run_id: str,
    agent_id: str,
    fallback_step_seq: int,
) -> TrajectoryEvent:
    """Normalize one pi-agent JSON event into a TrajectoryEvent.

    `fallback_step_seq` is used to build a step_id when the raw event omits one.
    """
    type_str = str(raw.get("type", "message"))
    classification = _TYPE_MAP.get(type_str, "message")

    outcome = str(raw.get("outcome", "success"))
    if outcome not in _VALID_OUTCOMES:
        outcome = "success"

    step_id = str(raw.get("step_id") or f"step-{fallback_step_seq:06d}")

    ts_raw = raw.get("ts")
    if ts_raw is None:
        ts = datetime.now(timezone.utc)
    else:
        ts = datetime.fromisoformat(str(ts_raw))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

    tool = str(raw.get("tool") or "")
    if classification == "message":
        tool = ""

    return TrajectoryEvent(
        run_id=run_id,
        agent_id=agent_id,
        step_id=step_id,
        ts=ts,
        model=str(raw.get("model", "")),
        tool=tool,
        input=dict(raw.get("input") or {}),
        output=dict(raw.get("output") or {}),
        duration_ms=int(raw.get("duration_ms") or 0),
        tokens_in=int(raw.get("tokens_in") or 0),
        tokens_out=int(raw.get("tokens_out") or 0),
        outcome=outcome,
        classification=classification,
        corpus_refs=list(raw.get("corpus_refs") or []),
        corpus_cited=list(raw.get("corpus_cited") or []),
    )


async def capture_pi_agent_stream(
    *,
    run_id: str,
    agent_id: str,
    stream: AsyncIterator[str],
    db_path: Path | str | None = None,
) -> int:
    """Read JSONL from `stream`, normalize, write to the trajectory store.

    Returns the count of successfully written events. Malformed lines are
    logged and skipped — capture never raises into the caller, because losing
    the stream means losing the run's audit trail.
    """
    written = 0
    seq = 0
    async for raw_line in stream:
        line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode().strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            log.warning("capture: skipping non-JSON line: %s", exc)
            continue
        if not isinstance(raw, dict):
            log.warning("capture: skipping non-object event: %r", raw)
            continue
        try:
            ev = normalize_pi_agent_event(
                raw,
                run_id=run_id,
                agent_id=agent_id,
                fallback_step_seq=seq,
            )
        except Exception as exc:  # noqa: BLE001 — never let bad events kill capture
            log.exception("capture: failed to normalize event: %s", exc)
            continue
        try:
            await awrite_event(ev, db_path=db_path)
            written += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("capture: failed to write event: %s", exc)
        seq += 1
    return written


def diff_task_states(
    prev_state: dict[str, str],
    tasks: list[Mapping[str, Any]],
    *,
    run_id: str,
    now: datetime,
) -> list[TrajectoryEvent]:
    """Return a task_transition event for each task whose status changed since
    the last poll (a never-seen task counts as a change, prev_status=None).

    ``prev_state`` (task_id -> status) is updated in place. Shared by
    ``capture_clawteam_transitions`` (async) and the Coordinator's sync wait
    callback so both agree on what counts as a transition.
    """
    events: list[TrajectoryEvent] = []
    for task in tasks:
        # Real ClawTeam 0.2.x JSON uses `task_id`/`status`/`owner` field names.
        task_id = str(task.get("task_id") or task.get("id") or "")
        if not task_id:
            continue
        status = str(task.get("status") or task.get("state") or "")
        prev = prev_state.get(task_id)
        if prev == status:
            continue
        events.append(
            TrajectoryEvent(
                run_id=run_id,
                agent_id=str(task.get("owner") or task.get("agent") or "") or "_team",
                step_id=f"clawteam-{task_id}-{status}",
                ts=now,
                model="",
                tool="",
                input={"task_id": task_id, "prev_status": prev},
                output={"task_id": task_id, "status": status, "raw": task},
                duration_ms=0,
                tokens_in=0,
                tokens_out=0,
                outcome="success",
                classification="task_transition",
            )
        )
        prev_state[task_id] = status
    return events


async def capture_clawteam_transitions(
    *,
    run_id: str,
    team_name: str,
    db_path: Path | str | None = None,
    poll_interval_s: float = 2.0,
) -> None:
    """Poll `clawteam task list --json` every `poll_interval_s` seconds and write
    a "task_transition" event whenever a task's status changes (the first poll
    emits one per task with prev_status=None, seeding the run's fan-out).

    Runs until cancelled. Errors from `_clawteam_list_tasks` (subprocess
    failures, JSON parse errors) are logged and the loop retries.
    """
    last_state: dict[str, str] = {}

    while True:
        try:
            tasks = await _clawteam_list_tasks(team_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("capture: clawteam poll failed: %s", exc)
            await asyncio.sleep(poll_interval_s)
            continue

        now = datetime.now(timezone.utc)
        for ev in diff_task_states(last_state, tasks, run_id=run_id, now=now):
            try:
                await awrite_event(ev, db_path=db_path)
            except Exception as exc:  # noqa: BLE001
                log.exception("capture: failed writing task_transition: %s", exc)
        await asyncio.sleep(poll_interval_s)
