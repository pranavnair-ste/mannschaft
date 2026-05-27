"""Run registry: one row per run, persisted alongside ``trajectory_events``.

Coordinator.launch inserts a row (status="running"); wait_for_completion
updates it (succeeded/failed). The dashboard reads run summaries by joining
this table with aggregated event token counts (cost derived via
``cost.event_cost``). Stores the serialized RunSpec so branch (Phase 2) can
reload it verbatim.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pi_harness.trajectory.cost import event_cost
from pi_harness.trajectory.store import _connect, _resolve_db_path, init_db

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    spec_id TEXT,
    parent_run_id TEXT,
    branch_from_step TEXT,
    overrides TEXT,
    goal TEXT,
    topology TEXT,
    sync_mode TEXT,
    session_id TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    team_name TEXT,
    run_spec_json TEXT
)
"""


@dataclass
class RunSummary:
    run_id: str
    status: str
    topology: str | None
    started_at: datetime | None
    ended_at: datetime | None
    agent_count: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    event_count: int
    parent_run_id: str | None
    branch_from_step: str | None
    goal: str | None
    spec_id: str | None


def init_runs_table(db_path: Path | str | None = None) -> Path:
    """Create the ``runs`` table (and the events schema it lives beside). Idempotent.

    The registry and ``trajectory_events`` share one db file; ensuring both
    here means a single init call yields a consistent schema for the dashboard
    summary join.
    """
    path = _resolve_db_path(db_path)
    init_db(path)  # ensures trajectory_events + indexes exist too
    with _connect(path) as conn:
        conn.execute(_CREATE_RUNS)
        conn.commit()
    return path


def register_run(
    *,
    run_id: str,
    spec_id: str | None,
    topology: str | None,
    sync_mode: str | None,
    session_id: str | None,
    goal: str | None,
    team_name: str | None,
    started_at: datetime,
    run_spec_json: str,
    parent_run_id: str | None = None,
    branch_from_step: str | None = None,
    overrides: dict[str, Any] | None = None,
    status: str = "running",
    db_path: Path | str | None = None,
) -> None:
    """Insert (or replace) a run row. Called at launch with status="running"."""
    path = _resolve_db_path(db_path)
    init_runs_table(path)
    with _connect(path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, spec_id, parent_run_id, branch_from_step, overrides, goal,
                topology, sync_mode, session_id, status, started_at, ended_at,
                team_name, run_spec_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                spec_id,
                parent_run_id,
                branch_from_step,
                json.dumps(overrides) if overrides is not None else None,
                goal,
                topology,
                sync_mode,
                session_id,
                status,
                started_at.isoformat(),
                None,
                team_name,
                run_spec_json,
            ),
        )
        conn.commit()


def mark_run_status(
    run_id: str,
    status: str,
    *,
    ended_at: datetime | None = None,
    db_path: Path | str | None = None,
) -> None:
    """Update a run's status (and optional ended_at). Called at completion."""
    path = _resolve_db_path(db_path)
    with _connect(path) as conn:
        conn.execute(
            "UPDATE runs SET status = ?, ended_at = ? WHERE run_id = ?",
            (status, ended_at.isoformat() if ended_at else None, run_id),
        )
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("overrides"):
        d["overrides"] = json.loads(d["overrides"])
    return d


def get_run(run_id: str, *, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Return the raw run row as a dict (overrides JSON-decoded), or None."""
    path = _resolve_db_path(db_path)
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def query_run_summaries(
    *,
    status: str | None = None,
    limit: int | None = None,
    db_path: Path | str | None = None,
) -> list[RunSummary]:
    """Join registry rows with aggregated event stats; derive cost per run."""
    path = _resolve_db_path(db_path)
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
    out: list[RunSummary] = []
    with _connect(path) as conn:
        run_rows = conn.execute(
            f"SELECT * FROM runs {where} ORDER BY started_at DESC {limit_clause}",
            params,
        ).fetchall()
        for r in run_rows:
            agg = conn.execute(
                """SELECT COUNT(*) AS n,
                          COUNT(DISTINCT agent_id) AS agents,
                          COALESCE(SUM(tokens_in), 0) AS tin,
                          COALESCE(SUM(tokens_out), 0) AS tout
                   FROM trajectory_events WHERE run_id = ?""",
                (r["run_id"],),
            ).fetchone()
            ev_rows = conn.execute(
                "SELECT model, tokens_in, tokens_out FROM trajectory_events WHERE run_id = ?",
                (r["run_id"],),
            ).fetchall()
            cost = sum(
                event_cost(e["model"], e["tokens_in"], e["tokens_out"]) for e in ev_rows
            )
            out.append(
                RunSummary(
                    run_id=r["run_id"],
                    status=r["status"],
                    topology=r["topology"],
                    started_at=datetime.fromisoformat(r["started_at"])
                    if r["started_at"]
                    else None,
                    ended_at=datetime.fromisoformat(r["ended_at"])
                    if r["ended_at"]
                    else None,
                    agent_count=int(agg["agents"]),
                    total_tokens_in=int(agg["tin"]),
                    total_tokens_out=int(agg["tout"]),
                    total_cost_usd=cost,
                    event_count=int(agg["n"]),
                    parent_run_id=r["parent_run_id"],
                    branch_from_step=r["branch_from_step"],
                    goal=r["goal"],
                    spec_id=r["spec_id"],
                )
            )
    return out
