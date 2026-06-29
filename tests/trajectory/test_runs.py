from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pi_harness.trajectory.runs import (
    RunSummary,
    get_run,
    init_runs_table,
    mark_run_status,
    register_run,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    p = tmp_path / "traj.db"
    init_runs_table(p)
    return p


def test_register_and_get(db: Path):
    started = datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc)
    register_run(
        run_id="run-1",
        spec_id="spec-x",
        topology="sequential",
        sync_mode="per_agent",
        session_id=None,
        goal="ship it",
        team_name="team-1",
        started_at=started,
        run_spec_json="{}",
        db_path=db,
    )
    row = get_run("run-1", db_path=db)
    assert row is not None
    assert row["status"] == "running"
    assert row["topology"] == "sequential"
    assert row["spec_id"] == "spec-x"
    assert row["parent_run_id"] is None
    assert row["started_at"] == started.isoformat()


def test_mark_status(db: Path):
    register_run(
        run_id="run-2",
        spec_id=None,
        topology="parallel",
        sync_mode="per_agent",
        session_id=None,
        goal="g",
        team_name="t",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        run_spec_json="{}",
        db_path=db,
    )
    ended = datetime(2026, 5, 28, 11, 0, tzinfo=timezone.utc)
    mark_run_status("run-2", "succeeded", ended_at=ended, db_path=db)
    row = get_run("run-2", db_path=db)
    assert row["status"] == "succeeded"
    assert row["ended_at"] == ended.isoformat()


def test_branch_lineage_columns(db: Path):
    register_run(
        run_id="child",
        spec_id="spec-x",
        topology="sequential",
        sync_mode="per_agent",
        session_id=None,
        goal="g",
        team_name="t",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        run_spec_json="{}",
        parent_run_id="run-1",
        branch_from_step="s-3",
        overrides={"topology": "parallel"},
        db_path=db,
    )
    row = get_run("child", db_path=db)
    assert row["parent_run_id"] == "run-1"
    assert row["branch_from_step"] == "s-3"
    assert row["overrides"]["topology"] == "parallel"


def test_get_unknown_returns_none(db: Path):
    assert get_run("nope", db_path=db) is None


def test_query_run_summaries_joins_events_and_cost(db: Path):
    from pi_harness.trajectory.runs import query_run_summaries
    from pi_harness.trajectory.schema import TrajectoryEvent
    from pi_harness.trajectory.store import write_event

    register_run(
        run_id="run-1", spec_id="s", topology="sequential", sync_mode="per_agent",
        session_id=None, goal="g", team_name="t",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc), run_spec_json="{}", db_path=db,
    )
    for i, agent in enumerate(["a", "b"]):
        write_event(
            TrajectoryEvent(
                run_id="run-1", agent_id=agent, step_id=f"s-{i}",
                ts=datetime(2026, 5, 28, 0, i, tzinfo=timezone.utc), model="gpt-5-mini",
                tool="edit", input={}, output={}, duration_ms=1, tokens_in=1_000_000,
                tokens_out=0, outcome="success", classification="tool_call",
            ),
            db_path=db,
        )
    summaries = query_run_summaries(db_path=db)
    assert len(summaries) == 1
    s = summaries[0]
    assert s.run_id == "run-1"
    assert s.agent_count == 2
    assert s.event_count == 2
    assert s.total_tokens_in == 2_000_000
    assert s.total_cost_usd == pytest.approx(0.5)  # 2M in * 0.25/1M


def test_query_run_summaries_no_events_is_zero(db: Path):
    from pi_harness.trajectory.runs import query_run_summaries

    register_run(
        run_id="empty", spec_id=None, topology="x", sync_mode="per_agent", session_id=None,
        goal="g", team_name="t", started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        run_spec_json="{}", db_path=db,
    )
    s = query_run_summaries(db_path=db)[0]
    assert s.agent_count == 0
    assert s.event_count == 0
    assert s.total_cost_usd == 0.0


def test_query_run_summaries_status_filter(db: Path):
    from pi_harness.trajectory.runs import query_run_summaries

    register_run(
        run_id="r-run", spec_id=None, topology="x", sync_mode="per_agent", session_id=None,
        goal="g", team_name="t", started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        run_spec_json="{}", status="running", db_path=db,
    )
    register_run(
        run_id="r-done", spec_id=None, topology="x", sync_mode="per_agent", session_id=None,
        goal="g", team_name="t", started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        run_spec_json="{}", status="succeeded", db_path=db,
    )
    running = query_run_summaries(status="running", db_path=db)
    assert {s.run_id for s in running} == {"r-run"}


def test_query_run_summaries_prefers_self_reported_cost(db: Path):
    """When a captured event carries pi's own cost_usd, it's used directly
    (not re-computed via the model price table). Avoids drift when models
    aren't in cost.py's MODEL_PRICES."""
    from pi_harness.trajectory.runs import query_run_summaries
    from pi_harness.trajectory.schema import TrajectoryEvent
    from pi_harness.trajectory.store import write_event

    register_run(
        run_id="r-pi", spec_id=None, topology="adhoc", sync_mode="per_agent",
        session_id=None, goal="g", team_name="t",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        run_spec_json="{}", db_path=db,
    )
    # A model NOT in MODEL_PRICES; cost.event_cost would return 0 for it.
    write_event(
        TrajectoryEvent(
            run_id="r-pi", agent_id="a", step_id="turn-1",
            ts=datetime(2026, 5, 28, tzinfo=timezone.utc), model="gpt-5.4-mini",
            tool="", input={}, output={"cost_usd": 0.0042},
            duration_ms=0, tokens_in=100, tokens_out=50,
            outcome="success", classification="message",
        ),
        db_path=db,
    )
    s = query_run_summaries(db_path=db)[0]
    assert s.total_cost_usd == pytest.approx(0.0042)


def test_run_summary_is_dataclass():
    # sanity: RunSummary constructs with the documented fields
    s = RunSummary(
        run_id="r", status="running", topology="sequential",
        started_at=None, ended_at=None, agent_count=0,
        total_tokens_in=0, total_tokens_out=0, total_cost_usd=0.0,
        event_count=0, parent_run_id=None, branch_from_step=None,
        goal=None, spec_id=None, wall_clock_s=None, sovereign=False,
    )
    assert s.run_id == "r"


def test_wall_clock_seconds_computed_from_timestamps(db: Path):
    """A finished run reports total wall-clock seconds = ended_at - started_at."""
    from pi_harness.trajectory.runs import get_run_summary

    started = datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc)
    register_run(
        run_id="wc-done", spec_id=None, topology="sequential", sync_mode="per_agent",
        session_id=None, goal="g", team_name="t", started_at=started,
        run_spec_json="{}", db_path=db,
    )
    # 12.5s later (12 seconds + 500_000 microseconds)
    ended = datetime(2026, 5, 28, 10, 0, 12, 500_000, tzinfo=timezone.utc)
    mark_run_status("wc-done", "succeeded", ended_at=ended, db_path=db)

    s = get_run_summary("wc-done", db_path=db)
    assert s is not None
    assert s.wall_clock_s == pytest.approx(12.5)


def test_wall_clock_none_while_running(db: Path):
    """A run with no ended_at (still running) reports wall_clock_s == None."""
    from pi_harness.trajectory.runs import get_run_summary

    register_run(
        run_id="wc-running", spec_id=None, topology="sequential", sync_mode="per_agent",
        session_id=None, goal="g", team_name="t",
        started_at=datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc),
        run_spec_json="{}", status="running", db_path=db,
    )
    s = get_run_summary("wc-running", db_path=db)
    assert s is not None
    assert s.wall_clock_s is None
