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


def test_envelopes_for_run_synthesizes_session_and_turns():
    rows = [
        (1, _ev(agent_id="planner", classification="tool_call", tool="bash", step_id="c1", input={"command": "ls"})),
        (2, _ev(agent_id="planner", classification="tool_result", tool="bash", step_id="c1",
                output={"content": [{"type": "text", "text": "ok"}]})),
        (3, _ev(agent_id="planner", classification="message", step_id="turn-1",
                output={"cost_usd": 0.01, "stopReason": "stop", "text": "done", "thinking": ""})),
    ]
    envs = bridge.envelopes_for_run(rows, CTX)
    types = [e["type"] for e in envs]
    assert types == ["session_start", "turn_start", "tool_call", "tool_result",
                     "assistant_message", "turn_end"]
    # seq is monotonic per session starting at 0
    assert [e["seq"] for e in envs] == [0, 1, 2, 3, 4, 5]
    assert all(e["session_id"] == "run-x:planner" for e in envs)


def test_envelopes_for_run_separates_agents():
    rows = [
        (1, _ev(agent_id="a1", classification="message", step_id="turn-1", output={"text": "x", "cost_usd": 0})),
        (2, _ev(agent_id="a2", classification="message", step_id="turn-1", output={"text": "y", "cost_usd": 0})),
    ]
    envs = bridge.envelopes_for_run(rows, CTX)
    a1 = [e for e in envs if e["session_id"] == "run-x:a1"]
    a2 = [e for e in envs if e["session_id"] == "run-x:a2"]
    assert [e["seq"] for e in a1] == [0, 1, 2, 3]  # session_start, turn_start, msg, turn_end
    assert [e["seq"] for e in a2] == [0, 1, 2, 3]
