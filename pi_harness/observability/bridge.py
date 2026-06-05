"""Bridge: translate mannschaft TrajectoryEvent rows into pi-observability fork
ObsEventEnvelopes and POST them. The translator is a pure function; the tailer is
the only stateful/IO piece. Deterministic uuid5 event_ids make re-tails idempotent
against the fork's event_id PK + UNIQUE(session_id, seq)."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from pi_harness.trajectory.schema import TrajectoryEvent

# Fixed namespace so event_ids are stable across processes/restarts.
_NS = uuid.UUID("6f0d8a4e-0c2b-4e8a-9b1a-7c2d3e4f5a6b")
MAX_TEXT = 32_000  # fork MAX_TEXT_FIELD / MAX_RESULT_BYTES


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


def _truncate(s: str) -> str:
    return s if len(s.encode()) <= MAX_TEXT else s.encode()[:MAX_TEXT].decode(errors="ignore")


def _result_text(output: dict) -> str:
    content = output.get("content")
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        joined = "".join(p for p in parts if p)
        if joined:
            return _truncate(joined)
    return _truncate(json.dumps(output))


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
    per source row; same (row_id, seq) -> same event_id (idempotent)."""
    out = dict(ev.output)
    if ev.classification == "tool_call":
        eid = _eid(ctx, ev.agent_id, "tool_call", row_id, ev.step_id)
        return _base(ev, ctx, "tool_call", seq, eid, {
            "tool_call_id": ev.step_id, "tool_name": ev.tool,
            "args": dict(ev.input), "args_truncated": False})
    if ev.classification == "tool_result":
        eid = _eid(ctx, ev.agent_id, "tool_result", row_id, ev.step_id)
        return _base(ev, ctx, "tool_result", seq, eid, {
            "tool_call_id": ev.step_id, "tool_name": ev.tool,
            "content_text": _result_text(out), "content_truncated": False,
            "is_error": ev.outcome == "error"})
    if ev.classification == "message":
        eid = _eid(ctx, ev.agent_id, "message", row_id, ev.step_id)
        return _base(ev, ctx, "assistant_message", seq, eid, {
            "text": _truncate(out.get("text", "") or ""),
            "thinking": _truncate(out.get("thinking", "") or ""),
            "tool_call_ids": [],
            "stop_reason": out.get("stopReason") or "stop",
            "usage": {"input": ev.tokens_in, "output": ev.tokens_out,
                      "cache_read": 0, "cache_write": 0,
                      "total_tokens": ev.tokens_in + ev.tokens_out,
                      "cost_total": out.get("cost_usd", 0.0)}})
    # task_transition / guide_fired / sensor_fired -> custom
    eid = _eid(ctx, ev.agent_id, "custom", row_id, ev.classification)
    return _base(ev, ctx, "custom", seq, eid, {
        "custom_type": ev.classification, "data": {"input": dict(ev.input), "output": out}})


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
        out.append(translate(ev, ctx, seq=nxt(sid), row_id=row_id))
        if ev.classification == "message":
            out.append(_synth(ctx, ev.agent_id, ev.ts, "turn_end", nxt(sid),
                              f"turn:{turn_idx[sid]}:end", {"turn_index": turn_idx[sid]}))
            turn_open[sid] = False
            turn_idx[sid] += 1
    return out
