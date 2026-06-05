from datetime import datetime, timezone

from pi_harness.trajectory.schema import TrajectoryEvent
from pi_harness.observability import bridge

CTX = bridge.RunContext(run_id="run-x", team_name="team-a", topology="pipeline")
TS = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)


def _ev(**kw):
    base = dict(run_id="run-x", agent_id="planner", step_id="s", ts=TS, model="claude-opus-4-8",
                tool="", input={}, output={}, duration_ms=0, tokens_in=0, tokens_out=0,
                outcome="success", classification="message")
    base.update(kw)
    return TrajectoryEvent(**base)


def test_translate_tool_call():
    ev = _ev(classification="tool_call", tool="bash", step_id="call_1", input={"command": "ls"})
    env = bridge.translate(ev, CTX, seq=3)
    assert env["type"] == "tool_call"
    assert env["pool"] == "run-x"
    assert env["tags"] == ["team-a", "pipeline"]
    assert env["agent_name"] == "planner"
    assert env["session_id"] == "run-x:planner"
    assert env["seq"] == 3
    assert env["ts"] == "2026-06-05T12:00:00.000Z"
    assert env["payload"]["tool_name"] == "bash"
    assert env["payload"]["args"] == {"command": "ls"}


def test_translate_message_carries_prose():
    ev = _ev(classification="message", step_id="turn-1", tokens_in=100, tokens_out=20,
             output={"cost_usd": 0.01, "stopReason": "stop", "text": "done.", "thinking": ""})
    env = bridge.translate(ev, CTX, seq=5)
    assert env["type"] == "assistant_message"
    assert env["payload"]["text"] == "done."
    assert env["payload"]["usage"]["cost_total"] == 0.01
    assert env["payload"]["usage"]["output"] == 20
    assert env["payload"]["stop_reason"] == "stop"


def test_translate_tool_result_extracts_text_and_error():
    ev = _ev(classification="tool_result", tool="bash", step_id="call_1", outcome="error",
             output={"content": [{"type": "text", "text": "boom"}]})
    env = bridge.translate(ev, CTX, seq=1)
    assert env["payload"]["content_text"] == "boom"
    assert env["payload"]["is_error"] is True


def test_event_id_is_deterministic():
    ev = _ev(classification="tool_call", tool="bash", step_id="call_1")
    a = bridge.translate(ev, CTX, seq=1, row_id=42)
    b = bridge.translate(ev, CTX, seq=1, row_id=42)
    assert a["event_id"] == b["event_id"]   # idempotent re-tail
