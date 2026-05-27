"""Parallel topology: leader -> [workers] -> merge."""
from __future__ import annotations

from pi_harness.topology.base import RunSpec, TaskDef, Topology


class ParallelTopology(Topology):
    """Convention: first agent = leader, last agent = merger, middle = workers."""

    MIN_AGENTS = 3  # leader + at least 1 worker + merger

    def plan(self, spec: RunSpec, depth: int = 0) -> list[TaskDef]:
        if len(spec.agents) < self.MIN_AGENTS:
            raise ValueError(
                f"ParallelTopology requires at least {self.MIN_AGENTS} agents "
                f"(leader + worker(s) + merger); got {len(spec.agents)}"
            )
        leader = spec.agents[0]
        merger = spec.agents[-1]
        workers = spec.agents[1:-1]

        leader_task = TaskDef(
            task_id=f"par-leader-{leader.name}",
            agent_name=leader.name,
            goal=spec.goal,
            blocked_by=[],
        )
        worker_tasks = [
            TaskDef(
                task_id=f"par-worker-{i:03d}-{w.name}",
                agent_name=w.name,
                goal=spec.goal,
                blocked_by=[leader_task.task_id],
            )
            for i, w in enumerate(workers)
        ]
        merge_task = TaskDef(
            task_id=f"par-merge-{merger.name}",
            agent_name=merger.name,
            goal=spec.goal,
            blocked_by=[wt.task_id for wt in worker_tasks],
        )
        return [leader_task, *worker_tasks, merge_task]
