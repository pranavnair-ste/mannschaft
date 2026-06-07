"""Bridge: translate mannschaft TrajectoryEvent rows into pi-observability fork
ObsEventEnvelopes and POST them. The translator is a pure function; the tailer is
the only stateful/IO piece. Deterministic uuid5 event_ids make re-tails idempotent
against the fork's event_id PK + UNIQUE(session_id, seq)."""
from __future__ import annotations

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from pi_harness.trajectory import runs as runs_mod
from pi_harness.trajectory import store as store_mod
from pi_harness.trajectory.schema import TrajectoryEvent

log = logging.getLogger(__name__)

# Fixed namespace so event_ids are stable across processes/restarts.
_NS = uuid.UUID("6f0d8a4e-0c2b-4e8a-9b1a-7c2d3e4f5a6b")
MAX_TEXT = 32_000  # fork MAX_TEXT_FIELD / MAX_RESULT_BYTES

DEFAULT_URL = os.environ.get("OBS_SERVER_URL", "http://127.0.0.1:43190")
DEFAULT_TOKEN = os.environ.get("OBS_AUTH_TOKEN", "")

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class RunContext:
    run_id: str
    team_name: str | None
    topology: str | None

    @property
    def pool(self) -> str:
        return self.run_id

    @property
    def tags(self) -> list[str]:
        return [t for t in (self.team_name, self.topology) if t]


def _iso(ts) -> str:
    # tz-aware UTC datetime -> ISO-8601 with ms + Z
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _provider_for(model: str) -> str:
    m = (model or "").lower()
    if m.startswith(("gpt", "o")):
        return "openai"
    if m.startswith("claude"):
        return "anthropic"
    return "unknown"


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _truncate(s: Any) -> str:
    """Byte-cap a string to the fork's field limit. Coerces non-str defensively:
    output comes from JSON in SQLite, so a corrupted row must never abort a whole
    run's backfill (audit #29)."""
    if not isinstance(s, str):
        s = "" if s is None else str(s)
    encoded = s.encode()
    if len(encoded) <= MAX_TEXT:
        return s
    return encoded[:MAX_TEXT].decode(errors="ignore")


def _was_truncated(s: str) -> bool:
    return isinstance(s, str) and len(s.encode()) > MAX_TEXT


def _result_raw(output: Any) -> str:
    """Best-effort human text from a tool_result output blob. Tolerates any shape
    json.loads could yield (audit #29): non-dict output, content not a list, or
    parts missing/with non-str 'text'."""
    if not isinstance(output, dict):
        return json.dumps(output, default=str)
    content = output.get("content")
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        joined = "".join(p for p in parts if isinstance(p, str) and p)
        if joined:
            return joined
    return json.dumps(output, default=str)


def _eid(ctx: RunContext, agent_id: str, *parts: Any) -> str:
    return str(uuid.uuid5(_NS, ":".join(str(p) for p in (ctx.run_id, agent_id, *parts))))


def _base(ev: TrajectoryEvent, ctx: RunContext, etype: str, seq: int, eid: str, payload: dict) -> dict:
    return {
        "event_id": eid,
        "ts": _iso(ev.ts),
        "type": etype,
        "session_id": f"{ctx.run_id}:{ev.agent_id}",
        "cwd": "",
        "agent_name": ev.agent_id,
        "pool": ctx.pool,
        "tags": ctx.tags,
        "provider": _provider_for(ev.model),
        "model": ev.model or "",
        "seq": seq,
        "payload": payload,
    }


def translate(ev: TrajectoryEvent, ctx: RunContext, *, seq: int, row_id: int = 0) -> dict:
    """One trajectory row -> one fork envelope. row_id makes the event_id unique
    per source row; same (row_id, seq) -> same event_id (idempotent).

    `output`/`input` are JSON-decoded from SQLite and may be any shape, so every
    access is defensive — a single corrupted row can't abort the run (audit #29)."""
    out = dict(ev.output) if isinstance(ev.output, dict) else {}
    inp = dict(ev.input) if isinstance(ev.input, dict) else {}
    if ev.classification == "tool_call":
        eid = _eid(ctx, ev.agent_id, "tool_call", row_id, ev.step_id)
        return _base(ev, ctx, "tool_call", seq, eid, {
            "tool_call_id": ev.step_id, "tool_name": ev.tool,
            "args": inp, "args_truncated": False})
    if ev.classification == "tool_result":
        eid = _eid(ctx, ev.agent_id, "tool_result", row_id, ev.step_id)
        raw = _result_raw(out)
        return _base(ev, ctx, "tool_result", seq, eid, {
            "tool_call_id": ev.step_id, "tool_name": ev.tool,
            "content_text": _truncate(raw), "content_truncated": _was_truncated(raw),
            "is_error": ev.outcome == "error"})
    if ev.classification == "message":
        eid = _eid(ctx, ev.agent_id, "message", row_id, ev.step_id)
        text = out.get("text", "")
        thinking = out.get("thinking", "")
        stop = out.get("stopReason")
        payload = {
            "text": _truncate(text if isinstance(text, str) else ""),
            "thinking": _truncate(thinking if isinstance(thinking, str) else ""),
            "tool_call_ids": [],
            "stop_reason": stop if isinstance(stop, str) and stop else "stop",
            "usage": {"input": _as_int(ev.tokens_in), "output": _as_int(ev.tokens_out),
                      "cache_read": 0, "cache_write": 0,
                      "total_tokens": _as_int(ev.tokens_in) + _as_int(ev.tokens_out),
                      "cost_total": _as_float(out.get("cost_usd", 0.0))}}
        # Forward per-turn timing when present (capture omits it on old runs /
        # tool-only turns). Numeric-guard since output is JSON from SQLite.
        for key in ("latency_ms", "prefill_ms", "generation_ms", "output_tps"):
            val = out.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                payload[key] = val
        return _base(ev, ctx, "assistant_message", seq, eid, payload)
    # task_transition / guide_fired / sensor_fired -> custom
    eid = _eid(ctx, ev.agent_id, "custom", row_id, ev.classification)
    return _base(ev, ctx, "custom", seq, eid, {
        "custom_type": ev.classification, "data": _custom_data(ev.classification, inp, out)})


def _custom_data(classification: str, inp: dict, out: dict) -> dict:
    """Self-describing payload for custom events so the fork renders them without
    knowing mannschaft/ClawTeam internals. task_transition is flattened to
    from/to/task_id/subject (and the bulky ``raw`` task object is dropped); other
    kinds keep their raw input/output until they get a normalized schema."""
    if classification == "task_transition":
        raw = out.get("raw") if isinstance(out.get("raw"), dict) else {}
        return {
            "task_id": out.get("task_id") or inp.get("task_id") or "",
            "from": inp.get("prev_status"),   # None for a never-seen task
            "to": out.get("status"),
            "subject": raw.get("subject") or "",
            "description": raw.get("description") or "",
        }
    return {"input": inp, "output": out}


def _thinking_envelope(ev: TrajectoryEvent, ctx: RunContext, seq: int, row_id: int, thinking: str) -> dict:
    """A native fork `thinking` event for a turn's reasoning. The fork already
    renders this type; emitting it (vs. a sidecar field on assistant_message)
    reuses that renderer and orders reasoning before the answer."""
    eid = _eid(ctx, ev.agent_id, "thinking", row_id, ev.step_id)
    return _base(ev, ctx, "thinking", seq, eid, {"text": _truncate(thinking)})


def _synth(ctx: RunContext, agent_id: str, ts, etype: str, seq: int, kind: str, payload: dict) -> dict:
    eid = str(uuid.uuid5(_NS, ":".join((ctx.run_id, agent_id, kind))))
    fake = TrajectoryEvent(run_id=ctx.run_id, agent_id=agent_id, step_id="", ts=ts,
                           model="", tool="", input={}, output={}, duration_ms=0,
                           tokens_in=0, tokens_out=0, outcome="success", classification="message")
    env = _base(fake, ctx, etype, seq, eid, payload)
    return env


def envelopes_for_run(rows: list[tuple[int, TrajectoryEvent]], ctx: RunContext) -> list[dict]:
    """Ordered envelopes for a whole run. Per agent: one session_start, then
    turn_start/<events>/turn_end groups. seq is monotonic per session from 0.
    Deterministic — recomputable on restart (idempotent against the fork)."""
    seq: dict[str, int] = {}
    started: set[str] = set()
    turn_open: dict[str, bool] = {}
    turn_idx: dict[str, int] = {}
    out: list[dict] = []

    def nxt(sid: str) -> int:
        n = seq.get(sid, 0)
        seq[sid] = n + 1
        return n

    for row_id, ev in rows:
        sid = f"{ctx.run_id}:{ev.agent_id}"
        if sid not in started:
            started.add(sid)
            turn_open[sid] = False
            turn_idx[sid] = 1
            out.append(_synth(ctx, ev.agent_id, ev.ts, "session_start", nxt(sid),
                              "session", {"reason": "new"}))
        if not turn_open[sid]:
            out.append(_synth(ctx, ev.agent_id, ev.ts, "turn_start", nxt(sid),
                              f"turn:{turn_idx[sid]}:start", {"turn_index": turn_idx[sid]}))
            turn_open[sid] = True
        if ev.classification == "message":
            thinking = ev.output.get("thinking") if isinstance(ev.output, dict) else None
            if isinstance(thinking, str) and thinking.strip():
                out.append(_thinking_envelope(ev, ctx, nxt(sid), row_id, thinking))
        out.append(translate(ev, ctx, seq=nxt(sid), row_id=row_id))
        if ev.classification == "message":
            out.append(_synth(ctx, ev.agent_id, ev.ts, "turn_end", nxt(sid),
                              f"turn:{turn_idx[sid]}:end", {"turn_index": turn_idx[sid]}))
            turn_open[sid] = False
            turn_idx[sid] += 1
    return out


@dataclass(frozen=True)
class BackfillResult:
    """Honest accounting: how many envelopes we shipped vs. how many the fork
    actually stored. The remainder were already present — idempotent dedupe via
    the deterministic event_ids — so a re-run reports sent>0, ingested==0."""
    sent: int
    ingested: int
    rejected: int


def post_events(envelopes: list[dict], url: str, token: str, *, timeout: float = 15.0) -> dict:
    """POST a batch to the fork's /events; return its {"ingested", "rejected"}.
    Raises urllib.error.URLError/HTTPError on transport failure or non-2xx — a
    backfill against an unreachable fork must fail loudly, not silently."""
    req = urllib.request.Request(
        f"{url}/events", data=json.dumps(envelopes).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.load(resp)
    return body if isinstance(body, dict) else {}


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRYABLE_STATUS
    if isinstance(exc, urllib.error.URLError):  # conn refused / DNS / reset (HTTPError handled above)
        return True
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    return False


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    try:
        val = exc.headers.get("Retry-After") if exc.headers else None
        return float(int(val)) if val and val.strip().isdigit() else None
    except Exception:
        return None


def post_events_with_retry(envelopes: list[dict], url: str, token: str, *,
                           timeout: float = 15.0, max_attempts: int = 4,
                           base_delay: float = 0.5, factor: float = 2.0,
                           max_delay: float = 30.0, sleep=time.sleep) -> dict:
    """POST with exponential backoff on retryable transport errors. Permanent
    failures (4xx other than 408/429) re-raise immediately; transient ones
    (conn refused / timeout / 5xx / 429) retry up to max_attempts, honoring a
    parseable integer Retry-After header on 429."""
    attempt = 0
    while True:
        try:
            return post_events(envelopes, url, token, timeout=timeout)
        except Exception as exc:
            attempt += 1
            if attempt >= max_attempts or not _is_retryable(exc):
                raise
            delay = min(max_delay, base_delay * (factor ** (attempt - 1)))
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                ra = _retry_after_seconds(exc)
                if ra is not None:
                    delay = min(max_delay, ra)
            sleep(delay)


def _read_rows(run_id: str, db_path=None) -> list[tuple[int, TrajectoryEvent]]:
    return store_mod.query_events_after(run_id, 0, db_path=db_path)


def _load_run_context(run_id: str, db_path=None) -> RunContext:
    rec = runs_mod.get_run(run_id, db_path=db_path) or {}
    return RunContext(run_id=run_id, team_name=rec.get("team_name"), topology=rec.get("topology"))


def backfill_run(run_id: str, *, url: str = DEFAULT_URL, token: str = DEFAULT_TOKEN,
                 db_path=None) -> BackfillResult:
    """Translate ALL rows of run_id and POST them (batches of 50), tallying the
    fork's real ingest/reject counts. Idempotent: re-running ships the same
    deterministic event_ids, which the fork dedupes (sent>0, ingested==0)."""
    ctx = _load_run_context(run_id, db_path=db_path)
    rows = _read_rows(run_id, db_path=db_path)
    envs = envelopes_for_run(rows, ctx)
    ingested = 0
    rejected = 0
    for i in range(0, len(envs), 50):
        resp = post_events_with_retry(envs[i:i + 50], url, token)
        ingested += _as_int(resp.get("ingested", 0))
        rej = resp.get("rejected")
        rejected += len(rej) if isinstance(rej, list) else 0
    return BackfillResult(sent=len(envs), ingested=ingested, rejected=rejected)


_TERMINAL = {"succeeded", "failed", "cancelled"}


def tail_once(run_id: str, last_count: int, *, url: str, token: str, db_path=None) -> int:
    """Re-translate the WHOLE run and POST only the new envelope tail.

    ``envelopes_for_run`` is deterministic and append-only as rows grow: the
    seq/event_id of any already-emitted envelope never changes when new rows
    arrive. So we re-translate everything each tick and ship only
    ``envs[last_count:]`` (in batches of 50). Translating a new-rows-only slice
    would reset seq to 0 and mint different event_ids -> UNIQUE(session_id, seq)
    collisions. Returns the new total envelope count; a no-op when nothing new."""
    ctx = _load_run_context(run_id, db_path=db_path)
    rows = _read_rows(run_id, db_path=db_path)
    envs = envelopes_for_run(rows, ctx)
    new = envs[last_count:]
    for i in range(0, len(new), 50):
        post_events_with_retry(new[i:i + 50], url, token)
    return len(envs)


def follow_runs(*, url: str, token: str, db_path=None, poll_interval: float = 1.0,
                sleep=time.sleep, stop=None, max_polls=None) -> None:
    """Live-tail every run in the registry, shipping new envelopes each tick.

    Each poll enumerates ``query_run_summaries`` and ``tail_once``s every
    not-yet-``done`` run. A run is marked ``done`` once it reaches a terminal
    status AND a subsequent poll added nothing new (so the final tail always
    drains). Stops when ``stop()`` is truthy, after ``max_polls`` polls, or never
    (daemon). ``sleep(poll_interval)`` runs at the loop bottom (0.0 = no-op)."""
    counts: dict[str, int] = {}
    done: set[str] = set()
    polls = 0
    while True:
        for summary in runs_mod.query_run_summaries(db_path=db_path):
            rid = summary.run_id
            if rid in done:
                continue
            before = counts.get(rid, 0)
            try:
                counts[rid] = tail_once(rid, before, url=url, token=token, db_path=db_path)
            except Exception as exc:
                # One unreachable/erroring run (e.g. the fork not yet up at launch,
                # or a transient outage that outlasts post_events' retry budget) must
                # NOT kill the whole daemon — it would take the supervised stack down
                # with it. Log and retry on the next poll; `counts[rid]` is unchanged,
                # so the same tail re-ships (idempotent via deterministic event_ids).
                log.warning("bridge: tailing run %s failed, will retry next poll: %s", rid, exc)
                continue
            status = (runs_mod.get_run(rid, db_path=db_path) or {}).get("status")
            if status in _TERMINAL and counts[rid] == before:
                done.add(rid)
        polls += 1
        if stop is not None and stop():
            return
        if max_polls is not None and polls >= max_polls:
            return
        sleep(poll_interval)
