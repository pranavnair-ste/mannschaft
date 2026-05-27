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


def test_run_summary_is_dataclass():
    # sanity: RunSummary constructs with the documented fields
    s = RunSummary(
        run_id="r", status="running", topology="sequential",
        started_at=None, ended_at=None, agent_count=0,
        total_tokens_in=0, total_tokens_out=0, total_cost_usd=0.0,
        event_count=0, parent_run_id=None, branch_from_step=None,
        goal=None, spec_id=None,
    )
    assert s.run_id == "r"
