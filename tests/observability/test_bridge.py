from datetime import datetime, timedelta, timezone

from pi_harness.trajectory.schema import TrajectoryEvent
from pi_harness.trajectory import runs as runs_mod
from pi_harness.trajectory import store as store_mod
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


def test_translate_message_forwards_timing():
    """Per-turn timing captured into output (latency/TTFT/gen/tps) is forwarded
    onto the assistant_message so the fork shows it (it already renders latency_ms)."""
    ev = _ev(classification="message", step_id="turn-1", tokens_in=10, tokens_out=100,
             output={"text": "hi", "cost_usd": 0, "latency_ms": 2500,
                     "prefill_ms": 500, "generation_ms": 2000, "output_tps": 50.0})
    p = bridge.translate(ev, CTX, seq=1)["payload"]
    assert p["latency_ms"] == 2500
    assert p["prefill_ms"] == 500
    assert p["generation_ms"] == 2000
    assert p["output_tps"] == 50.0


def test_translate_message_omits_absent_timing():
    """Runs captured before timing (or tool-only turns) carry no timing fields —
    don't emit null noise."""
    ev = _ev(classification="message", step_id="turn-1", output={"text": "hi", "cost_usd": 0})
    p = bridge.translate(ev, CTX, seq=1)["payload"]
    assert "latency_ms" not in p and "prefill_ms" not in p and "output_tps" not in p


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


def test_envelopes_for_run_emits_thinking_event_before_message():
    """When a turn carries reasoning, emit a native fork `thinking` event (which
    the fork already renders) just before the assistant_message, so reasoning is
    visible and ordered before the answer."""
    rows = [
        (1, _ev(agent_id="planner", classification="message", step_id="turn-1",
                output={"text": "answer", "thinking": "let me reason", "cost_usd": 0})),
    ]
    envs = bridge.envelopes_for_run(rows, CTX)
    types = [e["type"] for e in envs]
    assert types == ["session_start", "turn_start", "thinking", "assistant_message", "turn_end"]
    think = next(e for e in envs if e["type"] == "thinking")
    assert think["payload"]["text"] == "let me reason"
    assert think["session_id"] == "run-x:planner"
    assert [e["seq"] for e in envs] == [0, 1, 2, 3, 4]


def test_envelopes_for_run_no_thinking_event_when_empty():
    """Empty/encrypted thinking (the gpt-5.4-mini default) emits no thinking event."""
    rows = [
        (1, _ev(agent_id="planner", classification="message", step_id="turn-1",
                output={"text": "answer", "thinking": "", "cost_usd": 0})),
    ]
    types = [e["type"] for e in bridge.envelopes_for_run(rows, CTX)]
    assert "thinking" not in types
    assert types == ["session_start", "turn_start", "assistant_message", "turn_end"]


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


def test_backfill_run_reads_store_and_posts(monkeypatch):
    posted = []
    monkeypatch.setattr(bridge, "post_events",
                        lambda envs, url, token, *, timeout=15.0: posted.extend(envs) or {"ingested": len(envs), "rejected": []})
    monkeypatch.setattr(bridge, "_load_run_context",
                        lambda run_id, db_path=None: CTX)
    rows = [(1, _ev(agent_id="planner", classification="message", step_id="turn-1",
                    output={"text": "hi", "cost_usd": 0}))]
    monkeypatch.setattr(bridge, "_read_rows", lambda run_id, db_path=None: rows)
    result = bridge.backfill_run("run-x", url="http://x", token="t")
    # session_start, turn_start, assistant_message, turn_end
    assert result.sent == 4
    assert result.ingested == 4  # tallied from the fork's response, not len(envs)
    assert result.rejected == 0
    assert posted[0]["type"] == "session_start"


def test_backfill_run_counts_fork_rejections(monkeypatch):
    """A re-run ships the same deterministic ids; the fork dedupes them, so the
    result must report sent>0 with ingested==0 (the gap the live smoke exposed)."""
    monkeypatch.setattr(bridge, "post_events",
                        lambda envs, url, token, *, timeout=15.0: {"ingested": 0, "rejected": [e["event_id"] for e in envs]})
    monkeypatch.setattr(bridge, "_load_run_context", lambda run_id, db_path=None: CTX)
    rows = [(1, _ev(agent_id="planner", classification="message", step_id="turn-1",
                    output={"text": "hi", "cost_usd": 0}))]
    monkeypatch.setattr(bridge, "_read_rows", lambda run_id, db_path=None: rows)
    result = bridge.backfill_run("run-x", url="http://x", token="t")
    assert result.sent == 4
    assert result.ingested == 0
    assert result.rejected == 4


def test_translate_task_transition_normalizes_from_to():
    """task_transition -> custom with a flat, self-describing payload (from/to/
    task_id/subject) so the fork renders 'task X: in_progress -> completed'
    without knowing mannschaft/ClawTeam internals. Mirrors the REAL producer
    shape in capture.diff_task_states (input.prev_status, output.status+raw)."""
    ev = _ev(classification="task_transition", step_id="clawteam-t1-completed",
             agent_id="builder",
             input={"task_id": "t1", "prev_status": "in_progress"},
             output={"task_id": "t1", "status": "completed",
                     "raw": {"subject": "seq-001-builder", "description": "Write smoke_out.txt"}})
    p = bridge.translate(ev, CTX, seq=2)["payload"]
    assert p["custom_type"] == "task_transition"
    assert p["data"] == {
        "task_id": "t1", "from": "in_progress", "to": "completed",
        "subject": "seq-001-builder", "description": "Write smoke_out.txt",
    }


def test_translate_task_transition_first_sighting_has_null_from():
    """A never-seen task has prev_status=None (producer seeds the run); 'from' is
    None so the fork can render it as a fresh task."""
    ev = _ev(classification="task_transition",
             input={"task_id": "t2", "prev_status": None},
             output={"task_id": "t2", "status": "pending", "raw": {"subject": "seq-000-leader"}})
    p = bridge.translate(ev, CTX, seq=0)["payload"]
    assert p["data"]["from"] is None
    assert p["data"]["to"] == "pending"
    assert p["data"]["subject"] == "seq-000-leader"


def test_translate_custom_other_kinds_keep_raw_io():
    """guide_fired / sensor_fired (no normalized schema yet) keep their raw
    input/output so no detail is lost."""
    ev = _ev(classification="guide_fired", input={"guide": "g1"}, output={"detail": "x"})
    p = bridge.translate(ev, CTX, seq=1)["payload"]
    assert p["custom_type"] == "guide_fired"
    assert p["data"] == {"input": {"guide": "g1"}, "output": {"detail": "x"}}


def test_translate_tool_result_falls_back_to_json_when_no_content():
    """When a tool_result output carries no content[] list, content_text falls
    back to the JSON blob so the envelope is still informative."""
    ev = _ev(classification="tool_result", tool="bash", step_id="c1",
             output={"exitCode": 0, "stdout": "ok"})
    env = bridge.translate(ev, CTX, seq=1)
    assert env["payload"]["content_text"] == '{"exitCode": 0, "stdout": "ok"}'
    assert env["payload"]["is_error"] is False


def test_translate_tolerates_malformed_output_without_raising():
    """audit #29 on the bridge side: output is JSON-decoded from SQLite and may be
    any shape — a corrupted row must yield a valid envelope, never raise."""
    # message with non-str text / non-int tokens / non-dict output all coerce safely
    ev = _ev(classification="message", step_id="turn-1", tokens_in="oops", tokens_out=None,
             output={"text": 123, "thinking": None, "cost_usd": "lots", "stopReason": 7})
    env = bridge.translate(ev, CTX, seq=0)
    assert env["payload"]["text"] == ""        # non-str text dropped
    assert env["payload"]["thinking"] == ""
    assert env["payload"]["stop_reason"] == "stop"  # non-str stopReason -> default
    assert env["payload"]["usage"]["input"] == 0    # non-int tokens coerced
    assert env["payload"]["usage"]["cost_total"] == 0.0
    # tool_result with output that isn't even a dict must not raise
    ev2 = _ev(classification="tool_result", tool="bash", step_id="c1", output={})
    ev2.output = "a corrupted string blob"  # bypass dataclass typing, as SQLite JSON could
    env2 = bridge.translate(ev2, CTX, seq=1)
    assert isinstance(env2["payload"]["content_text"], str)


def test_envelopes_for_run_is_idempotent():
    """Re-running the same rows yields byte-identical envelopes (deterministic
    event_ids + seq) so re-tails dedupe against the fork (spec §11)."""
    rows = [
        (1, _ev(agent_id="planner", classification="tool_call", tool="bash", step_id="c1")),
        (2, _ev(agent_id="planner", classification="message", step_id="turn-1",
                output={"text": "done", "cost_usd": 0})),
    ]
    a = bridge.envelopes_for_run(rows, CTX)
    b = bridge.envelopes_for_run(rows, CTX)
    assert [e["event_id"] for e in a] == [e["event_id"] for e in b]
    assert a == b  # fully identical, not just ids


def test_iso_preserves_non_utc_offset():
    """_iso() rewrites only the UTC '+00:00' to 'Z'; other offsets stay intact so
    swimlane wall-clock spacing is faithful (guards against a normalize-to-UTC regression)."""
    assert bridge._iso(datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)) == "2026-06-05T12:00:00.000Z"
    tz_530 = timezone(timedelta(hours=5, minutes=30))
    assert bridge._iso(datetime(2026, 6, 5, 12, 0, tzinfo=tz_530)) == "2026-06-05T12:00:00.000+05:30"


def test_backfill_run_real_store_contract(tmp_path, monkeypatch):
    """Spec §11 e2e: exercise the REAL store/runs read path (not monkeypatched)
    against a throwaway SQLite DB — catches drift in query_events_after / get_run
    signatures that the unit tests' mocks would hide. No ClawTeam, no live fork."""
    db = tmp_path / "trajectory.db"
    store_mod.init_db(db)
    runs_mod.register_run(
        run_id="run-x", spec_id=None, topology="pipeline", sync_mode=None,
        session_id=None, goal=None, team_name="team-a",
        started_at=TS, run_spec_json="{}", db_path=db,
    )
    store_mod.write_event(
        _ev(agent_id="planner", classification="tool_call", tool="bash", step_id="c1",
            input={"command": "ls"}), db_path=db)
    store_mod.write_event(
        _ev(agent_id="planner", classification="message", step_id="turn-1",
            output={"text": "done", "cost_usd": 0.01}), db_path=db)

    captured = []
    monkeypatch.setattr(bridge, "post_events",
                        lambda envs, url, token, *, timeout=15.0: captured.extend(envs) or {"ingested": len(envs), "rejected": []})

    result = bridge.backfill_run("run-x", url="http://x", token="t", db_path=db)
    # session_start, turn_start, tool_call, turn_end? -> tool_call doesn't close a turn;
    # then turn_start(reused)/message/turn_end. Order: session_start, turn_start,
    # tool_call, assistant_message, turn_end == 5 envelopes for one agent.
    types = [e["type"] for e in captured]
    assert types == ["session_start", "turn_start", "tool_call", "assistant_message", "turn_end"]
    assert result.sent == 5 and result.ingested == 5
    # RunContext was loaded from the REAL runs table:
    assert captured[0]["pool"] == "run-x"
    assert captured[0]["tags"] == ["team-a", "pipeline"]

    # Idempotency against the real path: re-run yields identical event_ids.
    again = []
    monkeypatch.setattr(bridge, "post_events",
                        lambda envs, url, token, *, timeout=15.0: again.extend(envs) or {"ingested": 0, "rejected": [e["event_id"] for e in envs]})
    result2 = bridge.backfill_run("run-x", url="http://x", token="t", db_path=db)
    assert [e["event_id"] for e in again] == [e["event_id"] for e in captured]
    assert result2.sent == 5 and result2.ingested == 0 and result2.rejected == 5
