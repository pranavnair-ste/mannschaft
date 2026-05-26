# Trajectory Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a SQLite-backed event log that captures pi-coding-agent's tool stream and ClawTeam task transitions for every harness run, doubling as the workflow checkpointer (replacing LangGraph).

**Architecture:** A single-machine SQLite database at `~/.pi-harness/trajectory.db` stores normalized `TrajectoryEvent` rows. Async writes via `aiosqlite` (capture pipelines), sync reads via `sqlite3` (query API). Two capture sources feed it: pi-agent's stdout JSONL stream (per-tool detail) and a 2-second poll of `clawteam task list --json` (task state transitions).

**Tech Stack:** Python 3.10+, `aiosqlite` (async writes), stdlib `sqlite3` (sync reads), stdlib `json` / `dataclasses` / `datetime`, `pytest` + `pytest-asyncio` for tests. Depends on `pi_harness.config.Config` and `pi_harness.clawteam.client` from Plan 1.

---

## Task 0 — Branch setup and dependency audit

- [x] **0.1** Create a feature branch off `main`.

  Run:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft
  git checkout -b feat/trajectory-store
  ```

  Expected: `Switched to a new branch 'feat/trajectory-store'`.

- [x] **0.2** Verify Plan 1 outputs exist (this plan depends on them).

  Run:
  ```bash
  ls pi_harness/__init__.py pi_harness/config.py pi_harness/clawteam/client.py
  ```

  Expected: all three files listed without error. If any are missing, stop and confirm Plan 1 is complete before continuing.

- [x] **0.3** Add `aiosqlite` to `pyproject.toml` under `[project] dependencies` (alphabetically with existing deps).

  Edit `/Users/pranavnair/Desktop/Personal/mannschaft/pyproject.toml`:
  - Locate the `dependencies = [...]` array.
  - Add the line `  "aiosqlite>=0.20.0",` in alphabetical order.

  Then run:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft
  uv sync
  ```

  Expected: `aiosqlite` installed; no errors. If Plan 1 used a different dependency-declaration format (e.g. `[tool.poetry.dependencies]`), match that format instead — the requirement is that `import aiosqlite` works in the next step.

- [x] **0.4** Smoke-check the dependency.

  Run:
  ```bash
  uv run python -c "import aiosqlite; print(aiosqlite.__version__)"
  ```

  Expected: a version string >= `0.20.0` is printed.

- [x] **0.5** Commit the dependency bump.

  Run:
  ```bash
  git add pyproject.toml uv.lock
  git commit -m "chore(trajectory): add aiosqlite dependency"
  ```

  Expected: one commit recorded.

---

## Task 1 — Package skeleton + first failing test

- [x] **1.1** Create the package directories.

  Run:
  ```bash
  mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory
  mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory
  ```

  Expected: both directories exist.

- [x] **1.2** Write `pi_harness/trajectory/__init__.py`.

  Create `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/__init__.py`:
  ```python
  """Trajectory store: SQLite event log + capture pipelines.

  Public re-exports for downstream plans (improve-agent, guards, dashboard).
  """
  from pi_harness.trajectory.schema import TrajectoryEvent
  from pi_harness.trajectory.store import (
      init_db,
      write_event,
      query_events,
      query_runs,
      query_agent_steps,
  )

  __all__ = [
      "TrajectoryEvent",
      "init_db",
      "write_event",
      "query_events",
      "query_runs",
      "query_agent_steps",
  ]
  ```

- [x] **1.3** Write `tests/trajectory/__init__.py` (empty marker file).

  Create `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/__init__.py` containing exactly one blank line.

- [x] **1.4** Add the first failing test that imports the not-yet-built schema.

  Create `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/test_schema.py`:
  ```python
  """Tests for pi_harness.trajectory.schema."""
  from __future__ import annotations

  import json
  from datetime import datetime, timezone

  import pytest

  from pi_harness.trajectory.schema import TrajectoryEvent


  def _sample_event(**overrides) -> TrajectoryEvent:
      base = dict(
          run_id="run-1",
          agent_id="builder",
          step_id="step-001",
          ts=datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc),
          model="gpt-x-fast",
          tool="bash",
          input={"cmd": "ls"},
          output={"stdout": "a\nb\n"},
          duration_ms=42,
          tokens_in=10,
          tokens_out=5,
          outcome="success",
          classification="tool_call",
          corpus_refs=["entry-a", "entry-b"],
          corpus_cited=["entry-a"],
      )
      base.update(overrides)
      return TrajectoryEvent(**base)


  def test_event_defaults_empty_corpus_lists():
      ev = TrajectoryEvent(
          run_id="r",
          agent_id="a",
          step_id="s",
          ts=datetime(2026, 5, 25, tzinfo=timezone.utc),
          model="m",
          tool="",
          input={},
          output={},
          duration_ms=0,
          tokens_in=0,
          tokens_out=0,
          outcome="success",
          classification="message",
      )
      assert ev.corpus_refs == []
      assert ev.corpus_cited == []


  def test_to_row_serializes_dicts_and_lists_as_json():
      ev = _sample_event()
      row = ev.to_row()
      assert row["run_id"] == "run-1"
      assert json.loads(row["input"]) == {"cmd": "ls"}
      assert json.loads(row["output"]) == {"stdout": "a\nb\n"}
      assert json.loads(row["corpus_refs"]) == ["entry-a", "entry-b"]
      assert json.loads(row["corpus_cited"]) == ["entry-a"]
      # ts must be ISO-8601 with timezone
      assert row["ts"] == "2026-05-25T12:00:00+00:00"


  def test_from_row_round_trips():
      original = _sample_event()
      row = original.to_row()
      restored = TrajectoryEvent.from_row(row)
      assert restored == original


  def test_from_row_round_trips_with_empty_corpus_refs():
      original = _sample_event(corpus_refs=[], corpus_cited=[])
      restored = TrajectoryEvent.from_row(original.to_row())
      assert restored.corpus_refs == []
      assert restored.corpus_cited == []


  def test_outcome_rejects_invalid_literal():
      with pytest.raises(ValueError):
          TrajectoryEvent(
              run_id="r",
              agent_id="a",
              step_id="s",
              ts=datetime(2026, 5, 25, tzinfo=timezone.utc),
              model="m",
              tool="",
              input={},
              output={},
              duration_ms=0,
              tokens_in=0,
              tokens_out=0,
              outcome="oopsie",  # not in the allowed set
              classification="message",
          )


  def test_ts_must_be_timezone_aware():
      with pytest.raises(ValueError):
          TrajectoryEvent(
              run_id="r",
              agent_id="a",
              step_id="s",
              ts=datetime(2026, 5, 25, 12, 0, 0),  # naive
              model="m",
              tool="",
              input={},
              output={},
              duration_ms=0,
              tokens_in=0,
              tokens_out=0,
              outcome="success",
              classification="message",
          )
  ```

- [x] **1.5** Run the test — confirm it fails for the expected reason.

  Run:
  ```bash
  uv run pytest tests/trajectory/test_schema.py -v
  ```

  Expected: collection error or `ModuleNotFoundError: No module named 'pi_harness.trajectory.schema'`. This is the red phase.

- [x] **1.6** Commit the skeleton + failing test.

  Run:
  ```bash
  git add pi_harness/trajectory/__init__.py tests/trajectory/__init__.py tests/trajectory/test_schema.py
  git commit -m "test(trajectory): scaffold trajectory package and failing schema tests"
  ```

  Expected: one commit recorded.

---

## Task 2 — `TrajectoryEvent` dataclass

- [x] **2.1** Implement `pi_harness/trajectory/schema.py`.

  Create `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/schema.py`:
  ```python
  """TrajectoryEvent dataclass + SQLite row serialization."""
  from __future__ import annotations

  import json
  from dataclasses import dataclass, field
  from datetime import datetime
  from typing import Any, Literal, Mapping

  Outcome = Literal["success", "error", "blocked", "timeout"]

  _VALID_OUTCOMES: frozenset[str] = frozenset(
      {"success", "error", "blocked", "timeout"}
  )

  # Classification is a free-form string in storage so the harness can add new
  # event kinds without a migration, but v1 emitters MUST pick from this set.
  # Capture pipelines and guards reuse these constants to avoid typos.
  CLASSIFICATIONS: frozenset[str] = frozenset(
      {
          "tool_call",
          "tool_result",
          "message",
          "task_transition",
          "guide_fired",
          "sensor_fired",
      }
  )


  @dataclass
  class TrajectoryEvent:
      """A single point in a run's trajectory.

      One row per: tool call, tool result, agent message, ClawTeam task
      transition, guide firing, or sensor firing. See `CLASSIFICATIONS` for the
      canonical v1 event kinds.

      `corpus_refs` / `corpus_cited` are populated by Plan 3 (corpus); Plan 2
      stores them as empty lists.
      """

      run_id: str
      agent_id: str
      step_id: str
      ts: datetime
      model: str
      tool: str  # "" for non-tool events
      input: Mapping[str, Any]
      output: Mapping[str, Any]
      duration_ms: int
      tokens_in: int
      tokens_out: int
      outcome: Outcome
      classification: str
      corpus_refs: list[str] = field(default_factory=list)
      corpus_cited: list[str] = field(default_factory=list)

      def __post_init__(self) -> None:
          if self.outcome not in _VALID_OUTCOMES:
              raise ValueError(
                  f"outcome must be one of {sorted(_VALID_OUTCOMES)}, "
                  f"got {self.outcome!r}"
              )
          if self.ts.tzinfo is None:
              raise ValueError("ts must be timezone-aware (use UTC)")

      def to_row(self) -> dict[str, Any]:
          """Serialize for SQLite. List/dict fields become JSON strings."""
          return {
              "run_id": self.run_id,
              "agent_id": self.agent_id,
              "step_id": self.step_id,
              "ts": self.ts.isoformat(),
              "model": self.model,
              "tool": self.tool,
              "input": json.dumps(dict(self.input), sort_keys=True),
              "output": json.dumps(dict(self.output), sort_keys=True),
              "duration_ms": self.duration_ms,
              "tokens_in": self.tokens_in,
              "tokens_out": self.tokens_out,
              "outcome": self.outcome,
              "classification": self.classification,
              "corpus_refs": json.dumps(list(self.corpus_refs)),
              "corpus_cited": json.dumps(list(self.corpus_cited)),
          }

      @classmethod
      def from_row(cls, row: Mapping[str, Any]) -> "TrajectoryEvent":
          """Deserialize a SQLite row (mapping or sqlite3.Row) back to an event."""
          return cls(
              run_id=row["run_id"],
              agent_id=row["agent_id"],
              step_id=row["step_id"],
              ts=datetime.fromisoformat(row["ts"]),
              model=row["model"],
              tool=row["tool"],
              input=json.loads(row["input"]) if row["input"] else {},
              output=json.loads(row["output"]) if row["output"] else {},
              duration_ms=int(row["duration_ms"]),
              tokens_in=int(row["tokens_in"]),
              tokens_out=int(row["tokens_out"]),
              outcome=row["outcome"],
              classification=row["classification"],
              corpus_refs=json.loads(row["corpus_refs"]) if row["corpus_refs"] else [],
              corpus_cited=json.loads(row["corpus_cited"]) if row["corpus_cited"] else [],
          )
  ```

- [x] **2.2** Run schema tests — they must all pass.

  Run:
  ```bash
  uv run pytest tests/trajectory/test_schema.py -v
  ```

  Expected: 6 passed.

- [x] **2.3** Commit.

  Run:
  ```bash
  git add pi_harness/trajectory/schema.py
  git commit -m "feat(trajectory): TrajectoryEvent dataclass with JSON row serialization"
  ```

  Expected: one commit recorded.

---

## Task 3 — Store: failing tests for `init_db` + `write_event`

- [x] **3.1** Write `tests/trajectory/test_store.py` covering `init_db` idempotency, `write_event`, `query_events` ordering, and `query_runs` ordering.

  Create `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/test_store.py`:
  ```python
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
  ```

- [x] **3.2** Run — confirm failure.

  Run:
  ```bash
  uv run pytest tests/trajectory/test_store.py -v
  ```

  Expected: `ModuleNotFoundError` or import failure for `pi_harness.trajectory.store`.

- [x] **3.3** Commit the failing tests.

  Run:
  ```bash
  git add tests/trajectory/test_store.py
  git commit -m "test(trajectory): failing tests for init_db, write_event, query_*"
  ```

---

## Task 4 — Implement `store.py`

- [x] **4.1** Create `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/store.py`.

  Write:
  ```python
  """SQLite-backed trajectory store.

  Single-machine v1: one db file at ~/.pi-harness/trajectory.db (configurable
  via pi_harness.config.Config.trajectory_db_path). Async writes are available
  via `awrite_event` for capture pipelines; the sync `write_event` wraps it for
  test code and one-off use.

  Schema versioning: `_migrations(version INTEGER PRIMARY KEY, applied_at TEXT)`.
  v1 inserts version=1 and creates `trajectory_events` + its indexes. Future
  migrations append rows and run their DDL only if their version is absent.
  """
  from __future__ import annotations

  import asyncio
  import os
  import sqlite3
  from contextlib import contextmanager
  from datetime import datetime
  from pathlib import Path
  from typing import Any, Iterator

  import aiosqlite

  from pi_harness.trajectory.schema import TrajectoryEvent

  SCHEMA_VERSION = 1

  _CREATE_MIGRATIONS = """
  CREATE TABLE IF NOT EXISTS _migrations (
      version INTEGER PRIMARY KEY,
      applied_at TEXT NOT NULL
  )
  """

  _CREATE_EVENTS = """
  CREATE TABLE IF NOT EXISTS trajectory_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id TEXT NOT NULL,
      agent_id TEXT NOT NULL,
      step_id TEXT NOT NULL,
      ts TEXT NOT NULL,
      model TEXT NOT NULL,
      tool TEXT NOT NULL,
      input TEXT NOT NULL,
      output TEXT NOT NULL,
      duration_ms INTEGER NOT NULL,
      tokens_in INTEGER NOT NULL,
      tokens_out INTEGER NOT NULL,
      outcome TEXT NOT NULL,
      classification TEXT NOT NULL,
      corpus_refs TEXT NOT NULL,
      corpus_cited TEXT NOT NULL
  )
  """

  _CREATE_IDX_RUN_TS = (
      "CREATE INDEX IF NOT EXISTS idx_events_run_ts "
      "ON trajectory_events(run_id, ts)"
  )
  _CREATE_IDX_RUN_AGENT_STEP = (
      "CREATE INDEX IF NOT EXISTS idx_events_run_agent_step "
      "ON trajectory_events(run_id, agent_id, step_id)"
  )

  _INSERT_EVENT = """
  INSERT INTO trajectory_events
      (run_id, agent_id, step_id, ts, model, tool, input, output,
       duration_ms, tokens_in, tokens_out, outcome, classification,
       corpus_refs, corpus_cited)
  VALUES
      (:run_id, :agent_id, :step_id, :ts, :model, :tool, :input, :output,
       :duration_ms, :tokens_in, :tokens_out, :outcome, :classification,
       :corpus_refs, :corpus_cited)
  """


  def _resolve_db_path(db_path: Path | str | None) -> Path:
      if db_path is not None:
          return Path(db_path)
      # Fallback for callers that don't pass a path. The harness's normal entry
      # points (capture pipelines, API) always pass Config.trajectory_db_path
      # explicitly; this default exists so tools and ad-hoc scripts work too.
      return Path.home() / ".pi-harness" / "trajectory.db"


  @contextmanager
  def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
      conn = sqlite3.connect(db_path)
      conn.row_factory = sqlite3.Row
      try:
          yield conn
      finally:
          conn.close()


  def init_db(db_path: Path | str | None = None) -> Path:
      """Create the trajectory db and indexes. Idempotent."""
      path = _resolve_db_path(db_path)
      path.parent.mkdir(parents=True, exist_ok=True)
      with _connect(path) as conn:
          conn.execute(_CREATE_MIGRATIONS)
          conn.execute(_CREATE_EVENTS)
          conn.execute(_CREATE_IDX_RUN_TS)
          conn.execute(_CREATE_IDX_RUN_AGENT_STEP)
          existing = conn.execute(
              "SELECT 1 FROM _migrations WHERE version = ?",
              (SCHEMA_VERSION,),
          ).fetchone()
          if existing is None:
              conn.execute(
                  "INSERT INTO _migrations (version, applied_at) VALUES (?, ?)",
                  (SCHEMA_VERSION, datetime.utcnow().isoformat()),
              )
          conn.commit()
      return path


  async def awrite_event(
      event: TrajectoryEvent,
      *,
      db_path: Path | str | None = None,
  ) -> None:
      """Async write — for capture pipelines."""
      path = _resolve_db_path(db_path)
      async with aiosqlite.connect(path) as conn:
          await conn.execute(_INSERT_EVENT, event.to_row())
          await conn.commit()


  def write_event(
      event: TrajectoryEvent,
      *,
      db_path: Path | str | None = None,
  ) -> None:
      """Sync write — convenience wrapper for tests and ad-hoc calls.

      Uses sqlite3 directly (not asyncio.run) to stay reentrant-safe when
      callers are already inside an event loop.
      """
      path = _resolve_db_path(db_path)
      with _connect(path) as conn:
          conn.execute(_INSERT_EVENT, event.to_row())
          conn.commit()


  def query_events(
      *,
      run_id: str | None = None,
      agent_id: str | None = None,
      since: datetime | None = None,
      limit: int | None = None,
      db_path: Path | str | None = None,
  ) -> list[TrajectoryEvent]:
      """Return events ordered by (ts asc, step_id asc).

      All filter params optional — pass none to dump the whole table (capped by
      `limit` if provided).
      """
      path = _resolve_db_path(db_path)
      clauses: list[str] = []
      params: list[Any] = []
      if run_id is not None:
          clauses.append("run_id = ?")
          params.append(run_id)
      if agent_id is not None:
          clauses.append("agent_id = ?")
          params.append(agent_id)
      if since is not None:
          if since.tzinfo is None:
              raise ValueError("since must be timezone-aware")
          clauses.append("ts >= ?")
          params.append(since.isoformat())
      where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
      limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
      sql = (
          f"SELECT * FROM trajectory_events {where} "
          f"ORDER BY ts ASC, step_id ASC {limit_clause}"
      )
      with _connect(path) as conn:
          rows = conn.execute(sql, params).fetchall()
      return [TrajectoryEvent.from_row(r) for r in rows]


  def query_runs(
      *,
      limit: int | None = None,
      db_path: Path | str | None = None,
  ) -> list[dict[str, Any]]:
      """Return one record per run_id, ordered by latest event ts desc.

      Each record: {run_id, latest_ts (datetime), event_count (int),
                    agent_ids (list[str])}.
      """
      path = _resolve_db_path(db_path)
      limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
      sql = f"""
      SELECT
          run_id,
          MAX(ts)   AS latest_ts,
          COUNT(*)  AS event_count,
          GROUP_CONCAT(DISTINCT agent_id) AS agent_ids
      FROM trajectory_events
      GROUP BY run_id
      ORDER BY latest_ts DESC
      {limit_clause}
      """
      with _connect(path) as conn:
          rows = conn.execute(sql).fetchall()
      return [
          {
              "run_id": r["run_id"],
              "latest_ts": datetime.fromisoformat(r["latest_ts"]),
              "event_count": int(r["event_count"]),
              "agent_ids": (
                  sorted((r["agent_ids"] or "").split(","))
                  if r["agent_ids"]
                  else []
              ),
          }
          for r in rows
      ]


  def query_agent_steps(
      run_id: str,
      agent_id: str,
      *,
      db_path: Path | str | None = None,
  ) -> list[TrajectoryEvent]:
      """Events for one (run_id, agent_id), ordered by (ts asc, step_id asc)."""
      return query_events(
          run_id=run_id, agent_id=agent_id, db_path=db_path
      )


  # `asyncio` re-exported so capture pipelines can `from store import asyncio`
  # without a second import (matches the rest of pi_harness).
  __all__ = [
      "SCHEMA_VERSION",
      "init_db",
      "write_event",
      "awrite_event",
      "query_events",
      "query_runs",
      "query_agent_steps",
      "asyncio",
      "os",
  ]
  ```

- [x] **4.2** Run the store tests.

  Run:
  ```bash
  uv run pytest tests/trajectory/test_store.py -v
  ```

  Expected: 11 passed.

- [x] **4.3** Run the schema tests too — they must still pass.

  Run:
  ```bash
  uv run pytest tests/trajectory -v
  ```

  Expected: 17 passed (6 schema + 11 store).

- [x] **4.4** Commit.

  Run:
  ```bash
  git add pi_harness/trajectory/store.py
  git commit -m "feat(trajectory): SQLite store with init_db, write_event, query_* and indexes"
  ```

---

## Task 5 — Capture: failing tests for pi-agent stream + ClawTeam polling

- [x] **5.1** Write `tests/trajectory/test_capture.py` (unit, mocked).

  Create `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/test_capture.py`:
  ```python
  """Unit tests for capture pipelines. No real subprocesses; streams are mocked."""
  from __future__ import annotations

  import asyncio
  import io
  import json
  from datetime import datetime, timezone
  from pathlib import Path
  from typing import AsyncIterator
  from unittest.mock import patch

  import pytest

  from pi_harness.trajectory.capture import (
      capture_clawteam_transitions,
      capture_pi_agent_stream,
      normalize_pi_agent_event,
  )
  from pi_harness.trajectory.schema import TrajectoryEvent
  from pi_harness.trajectory.store import init_db, query_events


  pytestmark = pytest.mark.asyncio


  async def _async_iter(lines: list[str]) -> AsyncIterator[str]:
      for line in lines:
          yield line


  @pytest.fixture
  def db_path(tmp_path: Path) -> Path:
      path = tmp_path / "trajectory.db"
      init_db(path)
      return path


  # --- normalize_pi_agent_event -------------------------------------------------

  def test_normalize_tool_call_event():
      raw = {
          "type": "tool_call",
          "tool": "bash",
          "input": {"cmd": "ls"},
          "output": None,
          "duration_ms": 0,
          "tokens_in": 0,
          "tokens_out": 0,
          "step_id": "step-001",
          "ts": "2026-05-25T12:00:00+00:00",
          "model": "gpt-x-fast",
      }
      ev = normalize_pi_agent_event(
          raw, run_id="run-1", agent_id="builder", fallback_step_seq=0
      )
      assert isinstance(ev, TrajectoryEvent)
      assert ev.classification == "tool_call"
      assert ev.tool == "bash"
      assert ev.input == {"cmd": "ls"}
      assert ev.output == {}
      assert ev.run_id == "run-1"
      assert ev.agent_id == "builder"
      assert ev.step_id == "step-001"


  def test_normalize_tool_result_event():
      raw = {
          "type": "tool_result",
          "tool": "bash",
          "output": {"stdout": "hi\n", "exit_code": 0},
          "duration_ms": 12,
          "outcome": "success",
          "ts": "2026-05-25T12:00:01+00:00",
          "model": "gpt-x-fast",
      }
      ev = normalize_pi_agent_event(
          raw, run_id="run-1", agent_id="builder", fallback_step_seq=1
      )
      assert ev.classification == "tool_result"
      assert ev.outcome == "success"
      assert ev.duration_ms == 12

  def test_normalize_message_event_has_empty_tool():
      raw = {
          "type": "message",
          "content": "Hello world",
          "ts": "2026-05-25T12:00:02+00:00",
          "model": "gpt-x-fast",
          "tokens_in": 5,
          "tokens_out": 7,
      }
      ev = normalize_pi_agent_event(
          raw, run_id="run-1", agent_id="builder", fallback_step_seq=2
      )
      assert ev.classification == "message"
      assert ev.tool == ""
      assert ev.tokens_in == 5
      assert ev.tokens_out == 7


  def test_normalize_unknown_outcome_falls_back_to_success():
      raw = {
          "type": "tool_result",
          "tool": "bash",
          "ts": "2026-05-25T12:00:00+00:00",
          "model": "m",
          # no outcome field
      }
      ev = normalize_pi_agent_event(
          raw, run_id="r", agent_id="a", fallback_step_seq=0
      )
      assert ev.outcome == "success"


  def test_normalize_error_outcome_passes_through():
      raw = {
          "type": "tool_result",
          "tool": "bash",
          "ts": "2026-05-25T12:00:00+00:00",
          "model": "m",
          "outcome": "error",
      }
      ev = normalize_pi_agent_event(
          raw, run_id="r", agent_id="a", fallback_step_seq=0
      )
      assert ev.outcome == "error"


  def test_normalize_uses_fallback_step_id_when_missing():
      raw = {
          "type": "message",
          "content": "no step id",
          "ts": "2026-05-25T12:00:00+00:00",
          "model": "m",
      }
      ev = normalize_pi_agent_event(
          raw, run_id="r", agent_id="a", fallback_step_seq=42
      )
      assert ev.step_id == "step-000042"


  # --- capture_pi_agent_stream --------------------------------------------------

  async def test_capture_pi_agent_stream_writes_events(db_path: Path):
      lines = [
          json.dumps(
              {
                  "type": "tool_call",
                  "tool": "bash",
                  "input": {"cmd": "ls"},
                  "ts": "2026-05-25T12:00:00+00:00",
                  "model": "gpt-x-fast",
                  "step_id": "step-001",
              }
          ),
          json.dumps(
              {
                  "type": "tool_result",
                  "tool": "bash",
                  "output": {"stdout": "a\nb\n"},
                  "duration_ms": 7,
                  "outcome": "success",
                  "ts": "2026-05-25T12:00:01+00:00",
                  "model": "gpt-x-fast",
                  "step_id": "step-001",
              }
          ),
      ]
      await capture_pi_agent_stream(
          run_id="run-1",
          agent_id="builder",
          stream=_async_iter(lines),
          db_path=db_path,
      )
      events = query_events(run_id="run-1", db_path=db_path)
      assert len(events) == 2
      assert events[0].classification == "tool_call"
      assert events[1].classification == "tool_result"


  async def test_capture_pi_agent_stream_skips_blank_and_invalid_lines(
      db_path: Path,
  ):
      lines = [
          "",
          "   ",
          "not valid json {{",
          json.dumps(
              {
                  "type": "message",
                  "content": "ok",
                  "ts": "2026-05-25T12:00:00+00:00",
                  "model": "m",
              }
          ),
      ]
      await capture_pi_agent_stream(
          run_id="run-1",
          agent_id="builder",
          stream=_async_iter(lines),
          db_path=db_path,
      )
      events = query_events(run_id="run-1", db_path=db_path)
      assert len(events) == 1
      assert events[0].classification == "message"


  # --- capture_clawteam_transitions ---------------------------------------------

  async def test_capture_clawteam_transitions_emits_on_state_change(
      db_path: Path,
  ):
      # Real ClawTeam 0.2.x task JSON uses `task_id` and `status` (not `id`/`state`),
      # with status values pending|in_progress|completed|blocked (no `done`/`failed`).
      polls = [
          # poll 0
          [
              {"task_id": "t1", "owner": "builder", "status": "pending"},
              {"task_id": "t2", "owner": "reviewer", "status": "pending"},
          ],
          # poll 1: t1 moves to in_progress
          [
              {"task_id": "t1", "owner": "builder", "status": "in_progress"},
              {"task_id": "t2", "owner": "reviewer", "status": "pending"},
          ],
          # poll 2: t1 completed, t2 in_progress
          [
              {"task_id": "t1", "owner": "builder", "status": "completed"},
              {"task_id": "t2", "owner": "reviewer", "status": "in_progress"},
          ],
      ]

      call_idx = {"i": 0}

      async def fake_list_tasks(team_name: str) -> list[dict]:
          i = call_idx["i"]
          call_idx["i"] += 1
          if i >= len(polls):
              raise asyncio.CancelledError()
          return polls[i]

      with patch(
          "pi_harness.trajectory.capture._clawteam_list_tasks",
          side_effect=fake_list_tasks,
      ):
          task = asyncio.create_task(
              capture_clawteam_transitions(
                  run_id="run-1",
                  team_name="demo",
                  db_path=db_path,
                  poll_interval_s=0.0,
              )
          )
          try:
              await asyncio.wait_for(task, timeout=2.0)
          except asyncio.CancelledError:
              pass
          except asyncio.TimeoutError:
              task.cancel()

      events = query_events(run_id="run-1", db_path=db_path)
      # Expect baseline (2) + transitions across polls 1 & 2 (3 transitions)
      assert len(events) >= 3
      transitions = [
          e for e in events if e.classification == "task_transition"
      ]
      # At least t1: pending -> in_progress -> completed, t2: pending -> in_progress
      states_for_t1 = [
          e.output["status"]
          for e in transitions
          if e.output.get("task_id") == "t1"
      ]
      assert "in_progress" in states_for_t1
      assert "completed" in states_for_t1
  ```

- [x] **5.2** Run — confirm failure.

  Run:
  ```bash
  uv run pytest tests/trajectory/test_capture.py -v
  ```

  Expected: `ModuleNotFoundError: No module named 'pi_harness.trajectory.capture'`.

- [x] **5.3** Commit.

  Run:
  ```bash
  git add tests/trajectory/test_capture.py
  git commit -m "test(trajectory): failing tests for capture_pi_agent_stream + clawteam transitions"
  ```

---

## Task 6 — Implement `capture.py`

- [x] **6.1** Confirm Plan 1's `ClawTeamClient.list_tasks` is available.

  Plan 1 exposes `list_tasks` as an **instance method** on `ClawTeamClient` (not a module-level function). Run:
  ```bash
  uv run python -c "from pi_harness.clawteam.client import ClawTeamClient; assert hasattr(ClawTeamClient, 'list_tasks'); print('ok')"
  ```
  Expected: `ok`. The capture module below builds a `ClawTeamClient` from `Config` and calls `client.list_tasks(team_name)` from a thread-pool wrapper.

- [x] **6.2** Create `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/capture.py`.

  Write:
  ```python
  """Capture pipelines: pi-agent stdout JSONL + ClawTeam task polling.

  Assumed pi-agent JSON event schema (one event per stdout line):
      {
          "type":          str,      # "tool_call" | "tool_result" | "message"
          "tool":          str,      # optional; required when type starts with "tool_"
          "input":         dict,     # optional
          "output":        dict,     # optional
          "duration_ms":   int,      # optional, default 0
          "tokens_in":     int,      # optional, default 0
          "tokens_out":    int,      # optional, default 0
          "outcome":       str,      # optional; one of TrajectoryEvent's Outcome
          "step_id":       str,      # optional; falls back to "step-<seq:06d>"
          "ts":            str,      # ISO-8601 with tz; required
          "model":         str,      # required
      }

  If pi-coding-agent's actual event names differ (e.g. "assistant_message" vs
  "message"), adjust the `_TYPE_MAP` constant below. Unknown `type` values map
  to classification "message" so we never drop data.
  """
  from __future__ import annotations

  import asyncio
  import json
  import logging
  from datetime import datetime, timezone
  from pathlib import Path
  from typing import Any, AsyncIterator, Mapping

  from pi_harness.clawteam.client import ClawTeamClient
  from pi_harness.config import Config, load_config
  from pi_harness.trajectory.schema import TrajectoryEvent, _VALID_OUTCOMES
  from pi_harness.trajectory.store import awrite_event


  async def _clawteam_list_tasks(team_name: str, *, client: ClawTeamClient | None = None) -> list[Mapping[str, Any]]:
      """Async wrapper over Plan 1's `ClawTeamClient.list_tasks` (sync subprocess).

      Tests patch this symbol directly. When called without an explicit client,
      builds one from a freshly loaded :class:`Config` (caller must have
      ``OPENAI_API_KEY`` set, the same env the team launch requires).
      """
      if client is None:
          client = ClawTeamClient(load_config(env_file=None))
      return await asyncio.to_thread(client.list_tasks, team_name)

  log = logging.getLogger(__name__)

  # pi-agent type string -> TrajectoryEvent.classification
  _TYPE_MAP: dict[str, str] = {
      "tool_call": "tool_call",
      "tool_result": "tool_result",
      "message": "message",
      "assistant_message": "message",
      "user_message": "message",
  }


  def normalize_pi_agent_event(
      raw: Mapping[str, Any],
      *,
      run_id: str,
      agent_id: str,
      fallback_step_seq: int,
  ) -> TrajectoryEvent:
      """Normalize one pi-agent JSON event into a TrajectoryEvent.

      `fallback_step_seq` is used to build a step_id when the raw event omits one.
      """
      type_str = str(raw.get("type", "message"))
      classification = _TYPE_MAP.get(type_str, "message")

      outcome = str(raw.get("outcome", "success"))
      if outcome not in _VALID_OUTCOMES:
          outcome = "success"

      step_id = str(raw.get("step_id") or f"step-{fallback_step_seq:06d}")

      ts_raw = raw.get("ts")
      if ts_raw is None:
          ts = datetime.now(timezone.utc)
      else:
          ts = datetime.fromisoformat(str(ts_raw))
          if ts.tzinfo is None:
              ts = ts.replace(tzinfo=timezone.utc)

      tool = str(raw.get("tool") or "")
      if classification == "message":
          tool = ""

      return TrajectoryEvent(
          run_id=run_id,
          agent_id=agent_id,
          step_id=step_id,
          ts=ts,
          model=str(raw.get("model", "")),
          tool=tool,
          input=dict(raw.get("input") or {}),
          output=dict(raw.get("output") or {}),
          duration_ms=int(raw.get("duration_ms") or 0),
          tokens_in=int(raw.get("tokens_in") or 0),
          tokens_out=int(raw.get("tokens_out") or 0),
          outcome=outcome,
          classification=classification,
          corpus_refs=list(raw.get("corpus_refs") or []),
          corpus_cited=list(raw.get("corpus_cited") or []),
      )


  async def capture_pi_agent_stream(
      *,
      run_id: str,
      agent_id: str,
      stream: AsyncIterator[str],
      db_path: Path | str | None = None,
  ) -> int:
      """Read JSONL from `stream`, normalize, write to the trajectory store.

      Returns the count of successfully written events. Malformed lines are
      logged and skipped — capture never raises into the caller, because losing
      the stream means losing the run's audit trail.
      """
      written = 0
      seq = 0
      async for raw_line in stream:
          line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode().strip()
          if not line:
              continue
          try:
              raw = json.loads(line)
          except json.JSONDecodeError as exc:
              log.warning("capture: skipping non-JSON line: %s", exc)
              continue
          if not isinstance(raw, dict):
              log.warning("capture: skipping non-object event: %r", raw)
              continue
          try:
              ev = normalize_pi_agent_event(
                  raw,
                  run_id=run_id,
                  agent_id=agent_id,
                  fallback_step_seq=seq,
              )
          except Exception as exc:  # noqa: BLE001 — never let bad events kill capture
              log.exception("capture: failed to normalize event: %s", exc)
              continue
          try:
              await awrite_event(ev, db_path=db_path)
              written += 1
          except Exception as exc:  # noqa: BLE001
              log.exception("capture: failed to write event: %s", exc)
          seq += 1
      return written


  async def capture_clawteam_transitions(
      *,
      run_id: str,
      team_name: str,
      db_path: Path | str | None = None,
      poll_interval_s: float = 2.0,
  ) -> None:
      """Poll `clawteam task list --json` every `poll_interval_s` seconds.

      Emits a "task_transition" event whenever a task's `state` field changes
      relative to the previous poll. The very first poll seeds the state cache
      and emits a transition event per task with prev_state=None so downstream
      consumers always see the run's starting fan-out.

      Runs until cancelled. Errors from `_clawteam_list_tasks` (subprocess
      failures, JSON parse errors) are logged and the loop retries.
      """
      last_state: dict[str, str] = {}
      first_poll = True

      while True:
          try:
              tasks = await _clawteam_list_tasks(team_name)
          except asyncio.CancelledError:
              raise
          except Exception as exc:  # noqa: BLE001
              log.exception("capture: clawteam poll failed: %s", exc)
              await asyncio.sleep(poll_interval_s)
              continue

          now = datetime.now(timezone.utc)
          for idx, task in enumerate(tasks):
              # Real ClawTeam 0.2.x JSON uses `task_id`/`status`/`owner` field names.
              task_id = str(task.get("task_id") or task.get("id") or "")
              if not task_id:
                  continue
              status = str(task.get("status") or task.get("state") or "")
              prev = last_state.get(task_id)
              if first_poll or prev != status:
                  ev = TrajectoryEvent(
                      run_id=run_id,
                      agent_id=str(task.get("owner") or task.get("agent") or "") or "_team",
                      step_id=f"clawteam-{task_id}-{status}",
                      ts=now,
                      model="",
                      tool="",
                      input={"task_id": task_id, "prev_status": prev},
                      output={
                          "task_id": task_id,
                          "status": status,
                          "raw": task,
                      },
                      duration_ms=0,
                      tokens_in=0,
                      tokens_out=0,
                      outcome="success",
                      classification="task_transition",
                  )
                  try:
                      await awrite_event(ev, db_path=db_path)
                  except Exception as exc:  # noqa: BLE001
                      log.exception(
                          "capture: failed writing task_transition: %s", exc
                      )
                  last_state[task_id] = status
          first_poll = False
          await asyncio.sleep(poll_interval_s)
  ```

- [x] **6.3** (resolved) The original draft assumed Plan 1 exported `list_tasks` as a module-level function. It doesn't — it's an instance method on `ClawTeamClient`. The wrapper `_clawteam_list_tasks` above bridges sync→async via `asyncio.to_thread`, and tests can patch it directly.

- [x] **6.4** Run the capture unit tests.

  Run:
  ```bash
  uv run pytest tests/trajectory/test_capture.py -v
  ```

  Expected: 9 passed.

- [x] **6.5** Run the entire trajectory test suite to make sure nothing regressed.

  Run:
  ```bash
  uv run pytest tests/trajectory -v
  ```

  Expected: 26 passed (6 schema + 11 store + 9 capture).

- [x] **6.6** Commit.

  Run:
  ```bash
  git add pi_harness/trajectory/capture.py
  git commit -m "feat(trajectory): pi-agent JSONL + ClawTeam polling capture pipelines"
  ```

---

## Task 7 — Wire `Config.trajectory_db_path` into `init_db`'s default

- [x] **7.1** Confirm Plan 1's `Config` exposes a `trajectory_db_path` attribute.

  Run:
  ```bash
  uv run python -c "from pi_harness.config import Config; c = Config.load(); print(c.trajectory_db_path)"
  ```

  Expected: a path printed (e.g. `~/.pi-harness/trajectory.db` expanded). If `Config.load()` is named differently, replace it with whatever Plan 1 provides (e.g. `Config()` or `Config.from_env()`). If `trajectory_db_path` is missing, stop and reconcile with Plan 1 before proceeding.

- [x] **7.2** Add a small bootstrap helper to `pi_harness/trajectory/store.py` that uses Config when called with no args from the harness.

  In `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/store.py`, add a new function below `init_db`:
  ```python
  def init_db_from_config() -> Path:
      """Convenience: init the db at Config.trajectory_db_path.

      Used by the harness's startup wiring. Tests and ad-hoc callers should
      pass an explicit `db_path` to `init_db` instead.
      """
      # Local import to avoid a hard dep cycle if config.py itself imports
      # anything from pi_harness.trajectory in the future.
      from pi_harness.config import Config

      cfg = Config.load()
      return init_db(cfg.trajectory_db_path)
  ```

  Also append `"init_db_from_config",` to `__all__`.

- [x] **7.3** Add a test that exercises `init_db_from_config` against a temp path via monkeypatching.

  Append to `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/test_store.py`:
  ```python
  def test_init_db_from_config_uses_config_path(tmp_path, monkeypatch):
      from pi_harness import config as cfg_mod
      from pi_harness.trajectory import store as store_mod

      target = tmp_path / "from_cfg.db"

      class StubCfg:
          trajectory_db_path = target

      monkeypatch.setattr(cfg_mod.Config, "load", staticmethod(lambda: StubCfg()))
      created = store_mod.init_db_from_config()
      assert created == target
      assert target.exists()
  ```

- [x] **7.4** If Plan 1's `Config` does not have a `.load()` classmethod, replace `staticmethod(lambda: StubCfg())` in the test with whatever constructor pattern Plan 1 used (e.g. `monkeypatch.setattr(cfg_mod, "Config", lambda *_: StubCfg())`). The test's intent is "swap out the real Config-loading path with a stub that exposes `trajectory_db_path`".

- [x] **7.5** Run.

  Run:
  ```bash
  uv run pytest tests/trajectory -v
  ```

  Expected: 27 passed.

- [x] **7.6** Commit.

  Run:
  ```bash
  git add pi_harness/trajectory/store.py tests/trajectory/test_store.py
  git commit -m "feat(trajectory): init_db_from_config bootstrap helper"
  ```

---

## Task 8 — Smoke test: real ClawTeam team produces ≥10 events

The Plan 1 smoke test (`tests/test_smoke_launch.py`) already validates the launch/cleanup flow with a built-in `pi-smoke` 2-agent template. This task reuses the same template + Plan 1's `ClawTeamClient` to drive a real run and verify that `capture_clawteam_transitions` records at least 10 events during it.

- [x] **8.1** Confirm Plan 1's `ClawTeamClient` exposes the team-lifecycle methods we need.

  Run:
  ```bash
  uv run python -c "
  from pi_harness.clawteam.client import ClawTeamClient
  for m in ('launch_team', 'cleanup_team', 'list_tasks', 'install_template', 'register_profile'):
      assert hasattr(ClawTeamClient, m), m
  print('ok')
  "
  ```
  Expected: `ok`.

- [x] **8.2** Confirm Plan 1's `clawteam_profile.build_profile_specs` is available and the smoke test reuses its specs.

  Run:
  ```bash
  uv run python -c "from pi_harness.clawteam_profile import build_profile_specs, PROFILE_NAME_FAST; print(PROFILE_NAME_FAST)"
  ```
  Expected: `pi-openai-fast`.

- [x] **8.3** Create the smoke test.

  Create `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/test_capture_e2e.py`:
  ```python
  """End-to-end smoke test: launch a real ClawTeam team via Plan 1's client,
  capture events into a fresh trajectory db, assert ≥10 events land within 120s.

  Marked `smoke` — skipped in default CI; run with:
      OPENAI_API_KEY=sk-... uv run pytest tests/trajectory/test_capture_e2e.py -m smoke -v --timeout=240
  """
  from __future__ import annotations

  import asyncio
  import os
  import shutil
  import textwrap
  import uuid
  from dataclasses import replace
  from datetime import datetime, timezone
  from pathlib import Path

  import pytest

  from pi_harness.trajectory.capture import capture_clawteam_transitions
  from pi_harness.trajectory.store import init_db, query_events

  pytestmark = [pytest.mark.smoke, pytest.mark.asyncio]


  def _detect_executor() -> str:
      override = os.environ.get("PI_HARNESS_SMOKE_EXECUTOR", "").strip()
      aliases = {
          "pi-coding-agent": ["pi", "pi-coding-agent"],
          "pi": ["pi", "pi-coding-agent"],
          "codex": ["codex"],
      }
      candidates = aliases.get(override, [override]) if override else ["codex", "pi", "pi-coding-agent"]
      for cand in candidates:
          if cand and shutil.which(cand):
              return cand
      pytest.skip("No coding-agent CLI on PATH; install @openai/codex or @mariozechner/pi-coding-agent")


  @pytest.mark.timeout(240)
  async def test_clawteam_smoke_emits_at_least_10_events(tmp_path: Path):
      from pi_harness.clawteam import ClawTeamClient
      from pi_harness.clawteam_profile import build_profile_specs
      from pi_harness.config import load_config

      if not os.environ.get("OPENAI_API_KEY", "").startswith("sk-"):
          pytest.skip("OPENAI_API_KEY not set; smoke test skipped")
      if not shutil.which("clawteam") or not shutil.which("tmux"):
          pytest.skip("clawteam or tmux missing from PATH")

      executor = _detect_executor()

      # Sandbox ClawTeam state per-test so we don't disturb the user's ~/.clawteam.
      state_dir = tmp_path / "clawteam-state"
      os.environ["PI_HARNESS_CLAWTEAM_STATE_DIR"] = str(state_dir)
      cfg = load_config(env_file=None)
      client = ClawTeamClient(cfg)

      # Register profiles with the detected executor as the agent command.
      for spec in build_profile_specs(cfg):
          client.register_profile(replace(spec, command=executor))

      # Install the same minimal 2-agent template Plan 1's smoke uses.
      template_toml = textwrap.dedent(f"""
          [template]
          name = "pi-smoke"
          description = "2-agent smoke template (reused by trajectory smoke)."
          command = ["{executor}"]
          backend = "tmux"

          [template.leader]
          name = "leader"
          type = "orchestrator"
          task = '''Create one task assigned to builder titled "write-hello". Body: "Write hello.txt with HELLO, then mark completed." Then poll `clawteam task list {{team_name}}` every 15s. Exit when the builder task is completed.'''

          [[template.agents]]
          name = "builder"
          type = "builder"
          task = '''When you receive "write-hello", create hello.txt at the worktree root with HELLO, then mark the task completed.'''
      """).strip() + "\n"
      template_path = client.install_template("pi-smoke", template_toml)

      db_path = tmp_path / "smoke.db"
      init_db(db_path)
      run_id = f"smoke-{datetime.now(timezone.utc).isoformat()}"
      team_name = f"trajectory-smoke-{uuid.uuid4().hex[:8]}"

      try:
          client.launch_team(
              template="pi-smoke",
              team_name=team_name,
              goal="Write hello.txt with the word HELLO.",
          )
          poller = asyncio.create_task(
              capture_clawteam_transitions(
                  run_id=run_id,
                  team_name=team_name,
                  db_path=db_path,
                  poll_interval_s=2.0,
              )
          )

          # Wait up to 120s for the team to produce events.
          deadline = asyncio.get_event_loop().time() + 120.0
          while asyncio.get_event_loop().time() < deadline:
              await asyncio.sleep(2.0)
              events = query_events(run_id=run_id, db_path=db_path)
              if len(events) >= 10:
                  break

          poller.cancel()
          try:
              await poller
          except asyncio.CancelledError:
              pass
      finally:
          try:
              client.cleanup_team(team_name)
          except Exception:
              pass
          # Plan 1's install_template writes to ~/.clawteam/templates regardless of
          # data-dir; clean it up so we don't leak global state.
          try:
              template_path.unlink(missing_ok=True)
          except Exception:
              pass

      events = query_events(run_id=run_id, db_path=db_path)
      assert (
          len(events) >= 10
      ), f"smoke: expected >=10 events in 120s, got {len(events)}"
  ```

- [x] **8.4** Register the `smoke` marker in `pyproject.toml` (or `pytest.ini` if that's what Plan 1 set up) so pytest doesn't warn about it.

  Edit `/Users/pranavnair/Desktop/Personal/mannschaft/pyproject.toml`. Under `[tool.pytest.ini_options]` (create the section if it doesn't exist), ensure:
  ```toml
  [tool.pytest.ini_options]
  markers = [
      "smoke: end-to-end tests requiring real external processes (ClawTeam, pi-agent)",
  ]
  asyncio_mode = "auto"
  ```

  If `markers` or `asyncio_mode` already exist, merge — don't duplicate.

- [x] **8.5** Verify the smoke test is collected but skipped by default.

  Run:
  ```bash
  uv run pytest tests/trajectory -v
  ```

  Expected: 27 passed, 1 skipped (or deselected) — the e2e test is excluded because it is marked `smoke`. If the smoke test ran and failed because no ClawTeam binary is on PATH, that's also acceptable for this step; the user explicitly runs it via `-m smoke`.

- [x] **8.6** Run the smoke test (requires `clawteam` CLI on PATH).

  Run:
  ```bash
  uv run pytest tests/trajectory/test_capture_e2e.py -m smoke -v
  ```

  Expected: 1 passed within ~120s. If `clawteam` isn't installed locally, the test will fail at `launch_team` — document this as a developer-machine prerequisite in `pyproject.toml`'s readme section, not here.

- [x] **8.7** Commit.

  Run:
  ```bash
  git add tests/trajectory/test_capture_e2e.py pyproject.toml
  git commit -m "test(trajectory): smoke test ensures >=10 events from a real ClawTeam run"
  ```

---

## Task 9 — Documentation: assumed pi-agent event schema + migration approach

- [x] **9.1** Re-read the docstring at the top of `pi_harness/trajectory/capture.py`. Confirm it documents the assumed pi-agent event schema. If it does not, update it now — the engineer maintaining this file must be able to adjust to pi-agent's actual format without spelunking.

- [x] **9.2** Re-read the module docstring of `pi_harness/trajectory/store.py`. Confirm it documents:
  - The `_migrations` table structure.
  - That v1 inserts version=1 and creates `trajectory_events` plus its indexes.
  - That future migrations append a row and run their DDL only if their version is absent.

  If any of these are missing, add them to the module docstring.

- [x] **9.3** Run the full trajectory test suite one last time.

  Run:
  ```bash
  uv run pytest tests/trajectory -v
  ```

  Expected: 27 passed.

- [x] **9.4** If any docstrings changed, commit.

  Run:
  ```bash
  git status
  ```

  If `capture.py` or `store.py` are modified, run:
  ```bash
  git add pi_harness/trajectory/capture.py pi_harness/trajectory/store.py
  git commit -m "docs(trajectory): document pi-agent event schema and migration strategy"
  ```

  Otherwise skip the commit.

---

## Task 10 — Final verification

- [x] **10.1** Run the full project test suite (not just trajectory) — must not regress Plan 1.

  Run:
  ```bash
  uv run pytest -v
  ```

  Expected: all Plan 1 tests pass + 27 trajectory tests pass + 1 smoke skipped.

- [x] **10.2** Confirm the package layout matches the spec.

  Run:
  ```bash
  find pi_harness/trajectory tests/trajectory -type f | sort
  ```

  Expected output (exactly these files):
  ```
  pi_harness/trajectory/__init__.py
  pi_harness/trajectory/capture.py
  pi_harness/trajectory/schema.py
  pi_harness/trajectory/store.py
  tests/trajectory/__init__.py
  tests/trajectory/test_capture.py
  tests/trajectory/test_capture_e2e.py
  tests/trajectory/test_schema.py
  tests/trajectory/test_store.py
  ```

- [x] **10.3** Acceptance criteria checklist:

  - [x] (1) `init_db` creates schema on first call; idempotent — covered by `test_init_db_creates_schema` + `test_init_db_is_idempotent`.
  - [x] (2) `query_runs()` returns runs ordered by latest event ts desc — covered by `test_query_runs_orders_by_latest_event_desc`.
  - [x] (3) `query_events(run_id=X)` returns events ordered by `(ts asc, step_id asc)` — covered by `test_query_events_orders_by_ts_then_step_id`.
  - [x] (4) `corpus_refs` / `corpus_cited` round-trip cleanly — covered by `test_corpus_refs_round_trip_through_json` + `test_from_row_round_trips`.
  - [x] (5) Smoke test: real ClawTeam team produces ≥10 events in 60s — covered by `test_clawteam_smoke_emits_at_least_10_events`.

  All five must be passing (acceptance criterion 5 may be skipped in environments without `clawteam` on PATH but must pass on the engineer's dev machine before merging).

- [x] **10.4** Push the branch and open the PR.

  Run:
  ```bash
  git push -u origin feat/trajectory-store
  ```

  Then open a PR using the project's normal flow. Title: `feat(trajectory): SQLite trajectory store + capture pipelines (Plan 2)`. Body summarizes the schema, the two capture sources, and the smoke-test prerequisite.

---

## Deliverable summary

Files produced (all absolute paths):
- `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/__init__.py`
- `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/schema.py`
- `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/store.py`
- `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/capture.py`
- `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/__init__.py`
- `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/test_schema.py`
- `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/test_store.py`
- `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/test_capture.py`
- `/Users/pranavnair/Desktop/Personal/mannschaft/tests/trajectory/test_capture_e2e.py`

Mutations to existing files:
- `/Users/pranavnair/Desktop/Personal/mannschaft/pyproject.toml` (add `aiosqlite` dep; register `smoke` marker; set `asyncio_mode = "auto"`).

Public surface exported from `pi_harness.trajectory`:
- `TrajectoryEvent`, `init_db`, `init_db_from_config`, `write_event`, `awrite_event`, `query_events`, `query_runs`, `query_agent_steps`, `capture_pi_agent_stream`, `capture_clawteam_transitions`, `normalize_pi_agent_event`.
