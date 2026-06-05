"""Tests for pi_harness.trajectory.store. Uses a temp-file SQLite db."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pi_harness.trajectory.schema import TrajectoryEvent
from pi_harness.trajectory.store import (
    init_db,
    query_agent_steps,
    query_events,
    query_events_after,
    query_runs,
    write_event,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "trajectory.db"
    init_db(path)
    return path


def _ev(
    *,
    run_id: str = "run-1",
    agent_id: str = "builder",
    step_id: str = "step-001",
    ts: datetime | None = None,
    tool: str = "bash",
    outcome: str = "success",
    classification: str = "tool_call",
    corpus_refs: list[str] | None = None,
    corpus_cited: list[str] | None = None,
) -> TrajectoryEvent:
    return TrajectoryEvent(
        run_id=run_id,
        agent_id=agent_id,
        step_id=step_id,
        ts=ts or datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc),
        model="gpt-x-fast",
        tool=tool,
        input={"x": 1},
        output={"y": 2},
        duration_ms=1,
        tokens_in=1,
        tokens_out=1,
        outcome=outcome,
        classification=classification,
        corpus_refs=corpus_refs or [],
        corpus_cited=corpus_cited or [],
    )


def test_query_events_after_pages_by_rowid(db_path: Path):
    """The rowid cursor returns only newer rows, in insertion order, regardless
    of ts (the monotonic append cursor a live tailer must use, audit #24)."""
    # Insert out of ts order: a later-inserted event has an EARLIER timestamp.
    t_new = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    t_old = t_new - timedelta(hours=1)
    write_event(_ev(step_id="first", ts=t_new), db_path=db_path)
    write_event(_ev(step_id="second", ts=t_old), db_path=db_path)  # earlier ts, later rowid

    page = query_events_after("run-1", 0, db_path=db_path)
    assert [e.step_id for _id, e in page] == ["first", "second"]  # insertion order
    ids = [i for i, _e in page]
    assert ids == sorted(ids)  # monotonic

    # Cursor past the first row yields only the second (no skip/re-send).
    rest = query_events_after("run-1", ids[0], db_path=db_path)
    assert [e.step_id for _id, e in rest] == ["second"]
    # Cursor past the last row yields nothing.
    assert query_events_after("run-1", ids[-1], db_path=db_path) == []


def test_init_db_creates_schema(tmp_path: Path):
    path = tmp_path / "fresh.db"
    assert not path.exists()
    init_db(path)
    assert path.exists()
    with sqlite3.connect(path) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "trajectory_events" in tables
    assert "_migrations" in tables


def test_init_db_is_idempotent(tmp_path: Path):
    path = tmp_path / "idem.db"
    init_db(path)
    init_db(path)  # must not raise
    init_db(path)
    with sqlite3.connect(path) as conn:
        rows = list(conn.execute("SELECT version FROM _migrations"))
    assert rows == [(1,)]


def test_write_event_and_query_events_round_trip(db_path: Path):
    ev = _ev(corpus_refs=["a", "b"], corpus_cited=["a"])
    write_event(ev, db_path=db_path)
    events = query_events(run_id="run-1", db_path=db_path)
    assert len(events) == 1
    assert events[0] == ev


def test_query_events_orders_by_ts_then_step_id(db_path: Path):
    t0 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    # same ts, different step_id
    write_event(_ev(step_id="step-002", ts=t0), db_path=db_path)
    write_event(_ev(step_id="step-001", ts=t0), db_path=db_path)
    # later ts
    write_event(
        _ev(step_id="step-003", ts=t0 + timedelta(seconds=1)),
        db_path=db_path,
    )
    events = query_events(run_id="run-1", db_path=db_path)
    assert [e.step_id for e in events] == ["step-001", "step-002", "step-003"]


def test_query_events_filters_by_agent(db_path: Path):
    write_event(_ev(agent_id="builder", step_id="b1"), db_path=db_path)
    write_event(_ev(agent_id="reviewer", step_id="r1"), db_path=db_path)
    events = query_events(run_id="run-1", agent_id="reviewer", db_path=db_path)
    assert len(events) == 1
    assert events[0].agent_id == "reviewer"


def test_query_events_filters_since(db_path: Path):
    t0 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    write_event(_ev(step_id="early", ts=t0), db_path=db_path)
    write_event(
        _ev(step_id="late", ts=t0 + timedelta(seconds=10)),
        db_path=db_path,
    )
    events = query_events(
        run_id="run-1",
        since=t0 + timedelta(seconds=5),
        db_path=db_path,
    )
    assert [e.step_id for e in events] == ["late"]


def test_query_events_limit(db_path: Path):
    t0 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        write_event(
            _ev(step_id=f"s{i:03d}", ts=t0 + timedelta(seconds=i)),
            db_path=db_path,
        )
    events = query_events(run_id="run-1", limit=3, db_path=db_path)
    assert len(events) == 3
    assert [e.step_id for e in events] == ["s000", "s001", "s002"]


def test_query_runs_orders_by_latest_event_desc(db_path: Path):
    t0 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    # run-old: latest event at t0
    write_event(_ev(run_id="run-old", step_id="o1", ts=t0), db_path=db_path)
    # run-new: latest event at t0 + 60s
    write_event(
        _ev(run_id="run-new", step_id="n1", ts=t0 + timedelta(seconds=60)),
        db_path=db_path,
    )
    # run-mid: latest at t0 + 30s
    write_event(
        _ev(run_id="run-mid", step_id="m1", ts=t0 + timedelta(seconds=30)),
        db_path=db_path,
    )
    runs = query_runs(db_path=db_path)
    assert [r["run_id"] for r in runs] == ["run-new", "run-mid", "run-old"]


def test_query_runs_limit(db_path: Path):
    t0 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        write_event(
            _ev(run_id=f"run-{i}", step_id=f"s{i}", ts=t0 + timedelta(seconds=i)),
            db_path=db_path,
        )
    runs = query_runs(limit=2, db_path=db_path)
    assert len(runs) == 2


def test_query_agent_steps(db_path: Path):
    t0 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    write_event(
        _ev(agent_id="builder", step_id="b2", ts=t0 + timedelta(seconds=1)),
        db_path=db_path,
    )
    write_event(_ev(agent_id="builder", step_id="b1", ts=t0), db_path=db_path)
    write_event(_ev(agent_id="reviewer", step_id="r1", ts=t0), db_path=db_path)
    steps = query_agent_steps("run-1", "builder", db_path=db_path)
    assert [s.step_id for s in steps] == ["b1", "b2"]


def test_corpus_refs_round_trip_through_json(db_path: Path):
    ev = _ev(
        corpus_refs=["alpha", "beta", "gamma"],
        corpus_cited=["beta"],
    )
    write_event(ev, db_path=db_path)
    restored = query_events(run_id="run-1", db_path=db_path)[0]
    assert restored.corpus_refs == ["alpha", "beta", "gamma"]
    assert restored.corpus_cited == ["beta"]


def test_indexes_exist(db_path: Path):
    with sqlite3.connect(db_path) as conn:
        idx = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert "idx_events_run_ts" in idx
    assert "idx_events_run_agent_step" in idx


def test_init_db_from_config_uses_config_path(tmp_path, monkeypatch):
    """``init_db_from_config`` must call Plan 1's loader and use the resulting
    ``trajectory_db_path``. Plan 1's loader is the module-level
    ``load_config`` function (not ``Config.load()``), so we patch that."""
    from pi_harness.trajectory import store as store_mod

    target = tmp_path / "from_cfg.db"

    class StubCfg:
        trajectory_db_path = target

    # The helper does `from pi_harness.config import load_config` at call time;
    # patch the module attribute so the local-binding inside the helper
    # resolves to our stub.
    import pi_harness.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "load_config", lambda *a, **kw: StubCfg())
    created = store_mod.init_db_from_config()
    assert created == target
    assert target.exists()
