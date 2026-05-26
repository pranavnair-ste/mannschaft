"""Synthesis topology: Parallel + synthesizer-role merger that votes/synthesizes."""
from __future__ import annotations

from pi_harness.topology.base import Role, RunSpec, TaskDef
from pi_harness.topology.parallel import ParallelTopology


class SynthesisTopology(ParallelTopology):
    """Same fan-out shape as Parallel, but enforces SYNTHESIZER role at merge
    and rewrites the merge task goal to a synthesis directive."""

    def plan(self, spec: RunSpec, depth: int = 0) -> list[TaskDef]:
        if not spec.agents or spec.agents[-1].role != Role.SYNTHESIZER:
            raise ValueError(
                "SynthesisTopology requires the final agent to have synthesizer role"
            )
        tasks = super().plan(spec, depth=depth)
        merge = tasks[-1]
        merge.goal = (
            f"Synthesize and vote across worker outputs to produce a single "
            f"answer for: {spec.goal}"
        )
        return tasks
