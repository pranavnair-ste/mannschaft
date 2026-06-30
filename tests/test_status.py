# tests/test_status.py
from __future__ import annotations

from datetime import datetime, timezone


def _seed(db_path):
    # Mirror the real trajectory write API (see pi_harness/trajectory/runs.py
    # and tests/trajectory/test_runs.py): register_run takes the full
    # keyword-only run metadata, and events are written with store.write_event
    # (not "append_event"). mark_run_status would update the terminal state but
    # the read-side assertions only need a registered (running) run + one event.
    from pi_harness.trajectory.runs import register_run
    from pi_harness.trajectory.schema import TrajectoryEvent
    from pi_harness.trajectory.store import write_event

    register_run(
        run_id="run-x",
        spec_id="s",
        topology="sequential",
        sync_mode="per_agent",
        session_id=None,
        goal="g",
        team_name="t",
        started_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        run_spec_json="{}",
        db_path=db_path,
    )
    ev = TrajectoryEvent(
        run_id="run-x", agent_id="builder", step_id="1",
        ts=datetime(2026, 6, 30, tzinfo=timezone.utc), model="qwen",
        tool="edit", input={}, output={}, duration_ms=10,
        tokens_in=5, tokens_out=7, outcome="success",
        classification="tool_result",
    )
    write_event(ev, db_path=db_path)


def test_build_status_none_for_missing_run(tmp_path):
    from pi_harness.status import build_status
    assert build_status("nope", db_path=tmp_path / "t.db") is None


def test_build_status_reports_core_fields(tmp_path):
    from pi_harness.status import build_status
    db = tmp_path / "t.db"
    _seed(db)
    st = build_status("run-x", db_path=db)
    assert st["run_id"] == "run-x"
    assert "status" in st
    assert st["tokens_out"] >= 7
    assert any(a["agent_id"] == "builder" for a in st["agents"])


def test_render_status_human_is_one_block(tmp_path):
    from pi_harness.status import build_status, render_status_human
    db = tmp_path / "t.db"
    _seed(db)
    out = render_status_human(build_status("run-x", db_path=db))
    assert "run-x" in out
    assert "builder" in out


def test_build_status_surfaces_persisted_run_branch(tmp_path):
    """The git run branch persisted by register_run must reach build_status,
    and render_status_human must show it."""
    from pi_harness.status import build_status, render_status_human
    from pi_harness.trajectory.runs import register_run

    db = tmp_path / "t.db"
    register_run(
        run_id="run-branchy",
        spec_id="s",
        topology="sequential",
        sync_mode="per_agent",
        session_id=None,
        goal="g",
        team_name="t",
        started_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        run_spec_json="{}",
        run_branch="run/branchy-uuid",
        db_path=db,
    )
    st = build_status("run-branchy", db_path=db)
    assert st["branch"] == "run/branchy-uuid"
    assert "run/branchy-uuid" in render_status_human(st)


def test_build_status_branch_none_for_in_place_run(tmp_path):
    """An --in-place run registers no run_branch, so status reports None."""
    from pi_harness.status import build_status
    db = tmp_path / "t.db"
    _seed(db)  # seeds run-x WITHOUT a run_branch
    assert build_status("run-x", db_path=db)["branch"] is None
