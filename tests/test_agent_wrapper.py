from __future__ import annotations

import io
from pathlib import Path

import pytest

from pi_harness.agent_wrapper import _build_argv, consume_stream
from pi_harness.trajectory.store import init_db, query_events


SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "captures" / "pi-stdout-json.ndjson"


def test_build_argv_pi_includes_stdin_safe_flags():
    argv = _build_argv("pi", ["my prompt"])
    assert argv[0] == "pi"
    assert "--print" in argv
    assert "--mode" in argv and "json" in argv
    assert "--no-session" in argv
    # the prompt is appended at the end
    assert argv[-1] == "my prompt"


def test_build_argv_codex_passthrough():
    assert _build_argv("codex", ["x"]) == ["codex", "x"]


def test_build_argv_unknown_executor_raises():
    with pytest.raises(ValueError, match="unknown executor"):
        _build_argv("nope", [])


def test_consume_stream_writes_events_to_db(tmp_path: Path):
    db = tmp_path / "traj.db"
    init_db(db)
    lines = SAMPLE.read_text().splitlines()
    count = consume_stream(lines, run_id="r-wrap", agent_id="agent-wrap", db_path=db, tee_to=None)
    assert count > 0
    events = query_events(run_id="r-wrap", db_path=db)
    classifications = {e.classification for e in events}
    assert {"tool_call", "tool_result", "message"}.issubset(classifications)
    # the captured ls tool call landed
    tc = next(e for e in events if e.classification == "tool_call")
    assert tc.tool == "ls"


def test_consume_stream_tees_lines(tmp_path: Path):
    db = tmp_path / "traj.db"
    init_db(db)
    out = io.StringIO()
    lines = ['{"type":"agent_start"}', '{"type":"turn_start"}']
    consume_stream(lines, run_id="r", agent_id="a", db_path=db, tee_to=out)
    # both lines mirrored to tee_to with trailing newlines
    assert out.getvalue().count("\n") == 2
    assert '"type":"agent_start"' in out.getvalue()


def test_consume_stream_swallows_write_errors(tmp_path: Path, monkeypatch):
    """Capture must never break the run, even if the trajectory write fails."""
    import pi_harness.agent_wrapper as wrap

    def _boom(event, *, db_path=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(wrap, "write_event", _boom)
    # one tool_execution_start line so feed yields one event the failing write_event will see
    lines = ['{"type":"tool_execution_start","toolCallId":"x","toolName":"ls","args":{}}']
    # must not raise
    count = consume_stream(lines, run_id="r", agent_id="a", db_path=tmp_path / "x.db", tee_to=None)
    assert count == 0  # write failed so nothing counted
