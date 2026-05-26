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
