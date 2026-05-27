"""Nested topology: coordinator spawns a recursive child team."""
from __future__ import annotations

from pi_harness.topology.base import RunSpec, TaskDef, Topology


class NestedTopology(Topology):
    """First agent is the coordinator; all others are subagents inside a child
    team. The coordinator unblocks the child-team launch; subagent tasks
    within the child are blocked by the coordinator's completion (modeled as
    --blocked-by here for the DAG; ClawTeam handles the actual sub-team
    spawn from the coordinator's tmux session)."""

    def __init__(self, max_depth: int = 2) -> None:
        self.max_depth = max_depth

    def plan(self, spec: RunSpec, depth: int = 0) -> list[TaskDef]:
        if depth > self.max_depth:
            raise RecursionError(
                f"NestedTopology exceeded max depth {self.max_depth} (current={depth})"
            )
        if not spec.agents:
            raise ValueError("NestedTopology requires at least one coordinator agent")

        coord_agent = spec.agents[0]
        sub_agents = spec.agents[1:]

        coord_task = TaskDef(
            task_id=f"nest-coord-{coord_agent.name}",
            agent_name=coord_agent.name,
            goal=spec.goal,
            blocked_by=[],
        )
        sub_tasks = [
            TaskDef(
                task_id=f"nest-sub-{i:03d}-{a.name}",
                agent_name=a.name,
                goal=spec.goal,
                blocked_by=[coord_task.task_id],
            )
            for i, a in enumerate(sub_agents)
        ]
        return [coord_task, *sub_tasks]

    def build_template_dict(self, spec: RunSpec) -> dict:
        dct = super().build_template_dict(spec)
        parent_name = dct["template"]["name"]
        dct["template"].setdefault("metadata", {})["child"] = {
            "parent_template": parent_name,
            "name": f"child_of_{parent_name}",
        }
        return dct
