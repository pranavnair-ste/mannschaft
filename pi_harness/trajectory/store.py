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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import aiosqlite

from pi_harness.trajectory.schema import TrajectoryEvent

SCHEMA_VERSION = 1

# Paths whose schema has been initialized in THIS process. Consulted by init_db
# (and runs.init_runs_table) so read paths — e.g. dashboard polling — never
# re-issue CREATE TABLE/INDEX DDL, which would take a write lock on every call
# (audit #8). Keyed by the resolved db path string.
_initialized_dbs: set[str] = set()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """WAL + busy_timeout so the API reader can run concurrently with agent
    writers, and brief writer contention blocks-and-retries instead of
    immediately raising 'database is locked' (audit #7/#16/#36)."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")

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
        # expanduser so an ad-hoc caller passing the documented default *string*
        # ("~/.pi-harness/trajectory.db") writes to $HOME, not a literal ./~ dir.
        return Path(db_path).expanduser()
    # Fallback for callers that don't pass a path. The harness's normal entry
    # points (capture pipelines, API) always pass Config.trajectory_db_path
    # explicitly; this default exists so tools and ad-hoc scripts work too.
    return Path.home() / ".pi-harness" / "trajectory.db"


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        _apply_pragmas(conn)
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> Path:
    """Create the trajectory db and indexes. Idempotent.

    Runs its DDL at most once per path per process (see ``_initialized_dbs``) so
    hot read paths never pay for — or take a write lock from — repeated DDL.
    """
    path = _resolve_db_path(db_path)
    if str(path) in _initialized_dbs:
        return path
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
                (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
            )
        conn.commit()
    _initialized_dbs.add(str(path))
    return path


async def awrite_event(
    event: TrajectoryEvent,
    *,
    db_path: Path | str | None = None,
) -> None:
    """Async write — for capture pipelines."""
    path = _resolve_db_path(db_path)
    async with aiosqlite.connect(path, timeout=30.0) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=30000")
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


def query_events_after(
    run_id: str,
    after_id: int,
    *,
    limit: int | None = None,
    db_path: Path | str | None = None,
) -> list[tuple[int, TrajectoryEvent]]:
    """Events for ``run_id`` whose rowid > ``after_id``, ordered by rowid.

    The autoincrement ``id`` is the only monotonic append cursor — (ts, step_id)
    is NOT monotonic across concurrent writers — so this is what a live tailer
    must page on to avoid skipping or re-sending out-of-order inserts (audit #24).
    Returns ``(id, event)`` pairs.
    """
    path = _resolve_db_path(db_path)
    limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
    sql = (
        "SELECT * FROM trajectory_events WHERE run_id = ? AND id > ? "
        f"ORDER BY id ASC {limit_clause}"
    )
    with _connect(path) as conn:
        rows = conn.execute(sql, (run_id, int(after_id))).fetchall()
    return [(int(r["id"]), TrajectoryEvent.from_row(r)) for r in rows]


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
        COUNT(*)  AS event_count
    FROM trajectory_events
    GROUP BY run_id
    ORDER BY latest_ts DESC
    {limit_clause}
    """
    with _connect(path) as conn:
        rows = conn.execute(sql).fetchall()
        # Distinct agent ids per run, fetched as rows rather than via
        # GROUP_CONCAT-and-split so an agent_id containing a comma is not
        # mis-parsed into multiple ids (audit #40).
        agent_rows = conn.execute(
            "SELECT run_id, agent_id FROM trajectory_events GROUP BY run_id, agent_id"
        ).fetchall()
    agents_by_run: dict[str, list[str]] = {}
    for ar in agent_rows:
        agents_by_run.setdefault(ar["run_id"], []).append(ar["agent_id"])
    return [
        {
            "run_id": r["run_id"],
            "latest_ts": datetime.fromisoformat(r["latest_ts"]),
            "event_count": int(r["event_count"]),
            "agent_ids": sorted(agents_by_run.get(r["run_id"], [])),
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


def init_db_from_config() -> Path:
    """Convenience: init the db at Config.trajectory_db_path.

    Used by the harness's startup wiring. Tests and ad-hoc callers should
    pass an explicit `db_path` to `init_db` instead.

    Plan 1 exposes its loader as the module-level :func:`load_config`
    function (not ``Config.load()``); we call it with ``env_file=None`` so
    callers must already have the required env vars in process.
    """
    # Local import to avoid a hard dep cycle if config.py itself imports
    # anything from pi_harness.trajectory in the future.
    from pi_harness.config import load_config

    cfg = load_config(env_file=None)
    return init_db(cfg.trajectory_db_path)


# `asyncio` re-exported so capture pipelines can `from store import asyncio`
# without a second import (matches the rest of pi_harness).
__all__ = [
    "SCHEMA_VERSION",
    "init_db",
    "init_db_from_config",
    "write_event",
    "awrite_event",
    "query_events",
    "query_events_after",
    "query_runs",
    "query_agent_steps",
    "asyncio",
    "os",
]
