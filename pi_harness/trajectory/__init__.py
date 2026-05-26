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
