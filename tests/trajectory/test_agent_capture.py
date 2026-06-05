from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pi_harness.trajectory.agent_capture import (
    PiEventParser,
    events_from_stream,
)
from pi_harness.trajectory.schema import TrajectoryEvent


SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "captures" / "pi-stdout-json.ndjson"


def test_turn_message_captures_text_and_thinking():
    line = json.dumps({
        "type": "turn_end",
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-8",
            "stopReason": "stop",
            "usage": {"input": 100, "output": 20, "cost": {"total": 0.01}},
            "content": [
                {"type": "thinking", "thinking": "weighing options", "thinkingSignature": "sig"},
                {"type": "text", "text": "Here is the answer."},
            ],
        },
    })
    parser = PiEventParser(run_id="r", agent_id="a")
    events = list(parser.feed(line))
    assert len(events) == 1
    out = events[0].output
    assert out["text"] == "Here is the answer."
    assert out["thinking"] == "weighing options"
    assert out["cost_usd"] == 0.01  # existing fields preserved


def test_turn_message_text_empty_on_tool_only_turn():
    line = json.dumps({
        "type": "turn_end",
        "message": {"role": "assistant", "model": "gpt-5.4-mini", "stopReason": "toolUse",
                    "usage": {"input": 5, "output": 5},
                    "content": [{"type": "toolCall", "id": "c1", "name": "ls", "arguments": {}}]},
    })
    out = list(PiEventParser(run_id="r", agent_id="a").feed(line))[0].output
    assert out["text"] == ""        # tool-only turns legitimately have no prose
    assert out["thinking"] == ""


def test_turn_message_tolerates_malformed_usage():
    """Malformed usage/cost numbers must not crash the parser and abort the
    whole capture stream (#29)."""
    p = PiEventParser(run_id="r", agent_id="a")
    line = json.dumps({
        "type": "turn_end",
        "message": {
            "role": "assistant", "model": "m",
            "usage": {"input": "NaN", "output": None, "cost": "oops"},
        },
    })
    events = list(p.feed(line))  # must not raise
    assert len(events) == 1
    ev = events[0]
    assert ev.tokens_in == 0 and ev.tokens_out == 0
    assert ev.output["cost_usd"] == 0.0


@pytest.fixture
def fixed_now():
    return datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)


def test_parse_real_sample_emits_tool_call_and_result(fixed_now):
    """Against the captured pi 0.73.1 sample, the parser emits at least one
    tool_call / tool_result / message triple in the right order."""
    text = SAMPLE.read_text()
    events = list(events_from_stream(
        text.splitlines(), run_id="run-x", agent_id="agent-1", now_fn=lambda: fixed_now,
    ))
    classifications = [e.classification for e in events]
    assert classifications.count("tool_call") >= 1
    assert classifications.count("tool_result") >= 1
    assert classifications.count("message") >= 1
    # tool_call precedes its matching tool_result (same step_id)
    tc = next(e for e in events if e.classification == "tool_call")
    tr = next(e for e in events if e.classification == "tool_result" and e.step_id == tc.step_id)
    assert tc.tool == tr.tool == "ls"
    assert tc.input == {"path": "/tmp", "limit": 500}
    # tool_result.output preserves the structured pi result
    assert "content" in tr.output
    assert tr.output["content"][0]["text"].startswith("_probe2.js")
    assert tr.outcome == "success"


def test_message_event_carries_usage_and_cost(fixed_now):
    text = SAMPLE.read_text()
    events = list(events_from_stream(
        text.splitlines(), run_id="r", agent_id="a", now_fn=lambda: fixed_now,
    ))
    messages = [e for e in events if e.classification == "message"]
    assert messages, "expected at least one assistant turn_end message"
    m = messages[0]
    assert m.tokens_in > 0
    assert m.tokens_out > 0
    assert m.model == "gpt-5.4-mini"
    # cost is preserved from pi's own usage.cost.total
    assert m.output["cost_usd"] > 0
    assert "stopReason" in m.output


def test_parser_latches_model_for_tool_events(fixed_now):
    """tool_execution_start/end have no model field; the parser latches the
    most recent assistant model_start/end onto subsequent tool events."""
    text = SAMPLE.read_text()
    events = list(events_from_stream(
        text.splitlines(), run_id="r", agent_id="a", now_fn=lambda: fixed_now,
    ))
    tc = next(e for e in events if e.classification == "tool_call")
    assert tc.model == "gpt-5.4-mini"


def test_tool_result_iserror_maps_to_error_outcome(fixed_now):
    """A synthetic tool_execution_end with isError=True must produce outcome='error'."""
    parser = PiEventParser(run_id="r", agent_id="a", now_fn=lambda: fixed_now)
    parser.feed('{"type":"tool_execution_start","toolCallId":"x","toolName":"bash","args":{"cmd":"false"}}')
    out = list(parser.feed(
        '{"type":"tool_execution_end","toolCallId":"x","toolName":"bash",'
        '"result":{"content":[{"type":"text","text":"oops"}]},"isError":true}'
    ))
    res = next(e for e in out if e.classification == "tool_result")
    assert res.outcome == "error"


def test_unknown_event_types_are_skipped(fixed_now):
    parser = PiEventParser(run_id="r", agent_id="a", now_fn=lambda: fixed_now)
    out = list(parser.feed('{"type":"agent_start"}'))
    assert out == []
    out = list(parser.feed('{"type":"session","version":3,"id":"s","timestamp":"x","cwd":"."}'))
    assert out == []


def test_invalid_json_lines_skipped(fixed_now):
    parser = PiEventParser(run_id="r", agent_id="a", now_fn=lambda: fixed_now)
    assert list(parser.feed("not json at all")) == []
    assert list(parser.feed("")) == []


def test_emitted_events_are_real_trajectoryevents(fixed_now):
    """Sanity: every emitted item is a TrajectoryEvent with a tz-aware ts."""
    text = SAMPLE.read_text()
    events = list(events_from_stream(
        text.splitlines(), run_id="r", agent_id="a", now_fn=lambda: fixed_now,
    ))
    for e in events:
        assert isinstance(e, TrajectoryEvent)
        assert e.ts.tzinfo is not None
        assert e.run_id == "r"
        assert e.agent_id == "a"
