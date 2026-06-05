"""Parse pi (pi-coding-agent) NDJSON event stream into TrajectoryEvent instances.

Built against the REAL pi 0.73.1 ``--mode json`` output verified in
``docs/captures/pi-stdout-json.ndjson`` and documented in CAPTURE_FORMAT.md.

Mapping (see CAPTURE_FORMAT.md §4):
    tool_execution_start -> classification="tool_call"   (input=args, tool=toolName)
    tool_execution_end   -> classification="tool_result" (output=result, outcome from isError)
    turn_end (assistant) -> classification="message"     (model, usage.input/output, cost)

``tool_execution_*`` events carry no model field, so the parser latches the
most recent assistant ``message_start.message.model`` onto subsequent tool
events. Streaming ``message_update`` deltas and thinking blocks are skipped:
``turn_end`` is the canonical post-completion view.

Pi events have no per-event timestamp; ``now_fn`` injects a clock so tests can
freeze time. In the live wrapper this is ``datetime.now(tz=UTC)``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Iterable, Iterator

from pi_harness.trajectory.schema import TrajectoryEvent


# message_update sub-types (assistantMessageEvent.type) that mark the first
# output token for TTFT. Tool-call deltas are excluded per the design (timing is
# about prose/reasoning generation).
_CONTENT_DELTAS: frozenset[str] = frozenset(
    {"text_start", "text_delta", "thinking_start", "thinking_delta"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _assistant_text_and_thinking(msg: dict) -> tuple[str, str]:
    """Pull user-facing text and (usually empty) thinking from message.content[].

    content parts: {"type":"text","text":...}, {"type":"thinking","thinking":...},
    {"type":"toolCall",...}. Tool-only turns have no text part -> "". Defensive:
    malformed content must never raise (audit #29)."""
    content = msg.get("content")
    if not isinstance(content, list):
        return "", ""
    texts, thinks = [], []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif part.get("type") == "thinking" and isinstance(part.get("thinking"), str):
            thinks.append(part["thinking"])
    return "".join(texts), "".join(thinks)


class PiEventParser:
    """Stream parser: feed one NDJSON line at a time, yield TrajectoryEvents."""

    def __init__(
        self,
        *,
        run_id: str,
        agent_id: str,
        now_fn: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.run_id = run_id
        self.agent_id = agent_id
        self._now = now_fn
        self._current_model: str = ""
        self._turn_index: int = 0
        # Per-turn timing state. pi events carry no per-event ts, so now_fn()
        # stamps the wall-clock arrival of turn_start and the first content delta;
        # _turn_message diffs them against turn_end to derive TTFT/generation/tps.
        self._turn_start_t: datetime | None = None
        self._first_delta_t: datetime | None = None

    def feed(self, line: str) -> Iterator[TrajectoryEvent]:
        """Parse one line. Invalid JSON / unknown events yield nothing."""
        line = line.strip()
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return

        event_type = event.get("type")
        if event_type == "message_start":
            self._latch_model(event)
            return
        if event_type == "turn_start":
            self._turn_index += 1
            self._turn_start_t = self._now()
            self._first_delta_t = None
            return
        if event_type == "message_update":
            self._note_delta(event)
            return
        if event_type == "tool_execution_start":
            yield self._tool_call(event)
            return
        if event_type == "tool_execution_end":
            yield self._tool_result(event)
            return
        if event_type == "turn_end":
            ev = self._turn_message(event)
            if ev is not None:
                yield ev
            return
        # session / agent_start / agent_end / message_end -> skip

    def _note_delta(self, event: dict) -> None:
        """Record the wall-clock arrival of the FIRST text/thinking delta in the
        current turn (for TTFT). Cheap: returns immediately once latched, so the
        ~hundred message_update events per turn don't each call now_fn()."""
        if self._first_delta_t is not None:
            return
        ame = event.get("assistantMessageEvent")
        sub = ame.get("type") if isinstance(ame, dict) else None
        if sub in _CONTENT_DELTAS:
            self._first_delta_t = self._now()

    def _latch_model(self, event: dict) -> None:
        msg = event.get("message") or {}
        if msg.get("role") == "assistant":
            self._current_model = str(msg.get("model", "") or "")

    def _tool_call(self, event: dict) -> TrajectoryEvent:
        return TrajectoryEvent(
            run_id=self.run_id,
            agent_id=self.agent_id,
            step_id=str(event.get("toolCallId", "")),
            ts=self._now(),
            model=self._current_model,
            tool=str(event.get("toolName", "")),
            input=dict(event.get("args") or {}),
            output={},
            duration_ms=0,
            tokens_in=0,
            tokens_out=0,
            outcome="success",  # pre-tool call; result determines true outcome
            classification="tool_call",
        )

    def _tool_result(self, event: dict) -> TrajectoryEvent:
        result = event.get("result") or {}
        is_error = bool(event.get("isError"))
        return TrajectoryEvent(
            run_id=self.run_id,
            agent_id=self.agent_id,
            step_id=str(event.get("toolCallId", "")),
            ts=self._now(),
            model=self._current_model,
            tool=str(event.get("toolName", "")),
            input={},
            output=dict(result),
            duration_ms=0,
            tokens_in=0,
            tokens_out=0,
            outcome="error" if is_error else "success",
            classification="tool_result",
        )

    def _turn_message(self, event: dict) -> TrajectoryEvent | None:
        msg = event.get("message") or {}
        if msg.get("role") != "assistant":
            return None
        usage = msg.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        cost_obj = usage.get("cost")
        cost = cost_obj.get("total", 0.0) if isinstance(cost_obj, dict) else 0.0
        # Coerce defensively: a malformed usage/cost number from pi must not
        # raise and abort the whole capture stream (audit #29).
        text, thinking = _assistant_text_and_thinking(msg)
        now = self._now()
        tokens_out = _safe_int(usage.get("output", 0))
        output = {
            "cost_usd": _safe_float(cost),
            "stopReason": msg.get("stopReason"),
            "responseId": msg.get("responseId"),
            "text": text,
            "thinking": thinking,
        }
        output.update(self._turn_timing(end=now, tokens_out=tokens_out))
        ev = TrajectoryEvent(
            run_id=self.run_id,
            agent_id=self.agent_id,
            step_id=f"turn-{self._turn_index}",
            ts=now,
            model=str(msg.get("model", "") or self._current_model),
            tool="",
            input={},
            output=output,
            duration_ms=0,
            tokens_in=_safe_int(usage.get("input", 0)),
            tokens_out=tokens_out,
            outcome="success",
            classification="message",
        )
        # Reset per-turn timing so a stray turn_end can't reuse a stale start.
        self._turn_start_t = None
        self._first_delta_t = None
        return ev

    def _turn_timing(self, *, end: datetime, tokens_out: int) -> dict:
        """TTFT (prefill_ms), generation_ms, output_tps, and total latency_ms for
        the turn, from the latched wall-clock arrivals. Returns {} when no
        turn_start was seen; omits prefill/generation/tps when no content delta
        arrived (e.g. a tool-only turn). Never raises."""
        start = self._turn_start_t
        if start is None:
            return {}
        timing: dict = {"latency_ms": round((end - start).total_seconds() * 1000)}
        first = self._first_delta_t
        if first is not None:
            gen_ms = (end - first).total_seconds() * 1000
            timing["prefill_ms"] = round((first - start).total_seconds() * 1000)
            timing["generation_ms"] = round(gen_ms)
            if gen_ms > 0 and tokens_out > 0:
                timing["output_tps"] = round(tokens_out / (gen_ms / 1000), 2)
        return timing


def events_from_stream(
    lines: Iterable[str],
    *,
    run_id: str,
    agent_id: str,
    now_fn: Callable[[], datetime] = _utc_now,
) -> Iterator[TrajectoryEvent]:
    """Convenience: parse an iterable of NDJSON lines."""
    parser = PiEventParser(run_id=run_id, agent_id=agent_id, now_fn=now_fn)
    for line in lines:
        yield from parser.feed(line)
