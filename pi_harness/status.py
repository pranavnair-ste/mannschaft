# pi_harness/status.py
"""Concise, agent-consumable status for a single run.

Reads the trajectory store (never a live ClawTeam team, which may be torn down)
so `ms status <run_id>` works during and after a run. The dispatch skill reads
the --json form to narrate team progress in the chat.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pi_harness.trajectory.runs import get_run, get_run_summary
from pi_harness.trajectory.store import query_events


def format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def build_status(run_id: str, *, db_path: Any = None) -> dict | None:
    summary = get_run_summary(run_id, db_path=db_path)
    if summary is None:
        return None
    row = get_run(run_id, db_path=db_path) or {}
    # The git run branch (run/<uuid>) is persisted on the runs row by
    # register_run at launch; None for --in-place runs. The .get stays defensive
    # in case a legacy row dict predates the column.
    branch = row.get("run_branch")

    events = query_events(run_id=run_id, db_path=db_path)
    last_by_agent: dict[str, Any] = {}
    task_transitions = 0
    for e in events:  # ordered ts asc -> last write wins
        last_by_agent[e.agent_id] = e
        if e.classification == "task_transition":
            task_transitions += 1

    if summary.wall_clock_s is not None:
        elapsed = summary.wall_clock_s
    elif summary.started_at is not None:
        end = summary.ended_at or datetime.now(timezone.utc)
        elapsed = (end - summary.started_at).total_seconds()
    else:
        elapsed = None

    return {
        "run_id": run_id,
        "status": summary.status,
        "agent_count": summary.agent_count or len(last_by_agent),
        "tokens_in": summary.total_tokens_in,
        "tokens_out": summary.total_tokens_out,
        "cost_usd": summary.total_cost_usd,
        "sovereign": summary.sovereign,
        "elapsed_s": elapsed,
        "branch": branch,
        "task_transitions": task_transitions,
        "agents": [
            {
                "agent_id": aid,
                "last_classification": e.classification,
                "last_tool": e.tool or None,
                "last_outcome": e.outcome,
                "last_ts": e.ts.isoformat() if e.ts else None,
            }
            for aid, e in sorted(last_by_agent.items())
        ],
    }


def render_status_human(status: dict) -> str:
    cost = "$0.00 (sovereign)" if status["sovereign"] else f"${status['cost_usd']:.4f}"
    head = (
        f"{status['run_id']} · status={status['status']} · "
        f"{status['agent_count']} agents · "
        f"{status['tokens_in']}in/{status['tokens_out']}out · {cost} · "
        f"{format_elapsed(status['elapsed_s'])}"
    )
    lines = [head]
    for a in status["agents"]:
        tool = f" tool={a['last_tool']}" if a["last_tool"] else ""
        lines.append(f"  {a['agent_id']:<12} {a['last_classification']}{tool} ({a['last_outcome']})")
    if status["branch"]:
        lines.append(f"  branch: {status['branch']}")
    return "\n".join(lines)
