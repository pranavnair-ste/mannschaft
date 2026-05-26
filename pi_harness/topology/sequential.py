"""Sequential topology: A -> B -> C -> ... -> N."""
from __future__ import annotations

from pi_harness.topology.base import RunSpec, TaskDef, Topology


class SequentialTopology(Topology):
    """Linear chain. Each agent blocked by the previous one."""

    def plan(self, spec: RunSpec, depth: int = 0) -> list[TaskDef]:
        if not spec.agents:
            raise ValueError("SequentialTopology requires at least one agent")
        tasks: list[TaskDef] = []
        for i, agent in enumerate(spec.agents):
            task_id = f"seq-{i:03d}-{agent.name}"
            blocked = [tasks[i - 1].task_id] if i > 0 else []
            tasks.append(TaskDef(
                task_id=task_id,
                agent_name=agent.name,
                goal=spec.goal,
                blocked_by=blocked,
            ))
        return tasks
