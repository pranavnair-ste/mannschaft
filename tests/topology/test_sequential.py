"""SequentialTopology produces a linear --blocked-by chain."""
from __future__ import annotations

import pytest

from pi_harness.topology.base import (
    AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
)
from pi_harness.topology.sequential import SequentialTopology


def _spec(n: int) -> RunSpec:
    return RunSpec(
        goal="seq goal",
        agents=[
            AgentSpec(name=f"a{i}", role=Role.BUILDER, model_tier=ModelTier.FAST)
            for i in range(n)
        ],
        mode=TopologyMode.SEQUENTIAL,
        sync_mode=SyncMode.PER_AGENT,
        corpus_classifications=[],
    )


class TestSequentialPlan:
    def test_three_agents_two_edges(self):
        tasks = SequentialTopology().plan(_spec(3))
        assert len(tasks) == 3
        assert tasks[0].blocked_by == []
        assert tasks[1].blocked_by == [tasks[0].task_id]
        assert tasks[2].blocked_by == [tasks[1].task_id]

    def test_n_agents_n_minus_1_edges(self):
        tasks = SequentialTopology().plan(_spec(5))
        edge_count = sum(len(t.blocked_by) for t in tasks)
        assert edge_count == 4

    def test_single_agent_no_edges(self):
        tasks = SequentialTopology().plan(_spec(1))
        assert len(tasks) == 1
        assert tasks[0].blocked_by == []

    def test_empty_agents_raises(self):
        with pytest.raises(ValueError, match="at least one agent"):
            SequentialTopology().plan(_spec(0))

    def test_task_agent_names_match_spec(self):
        tasks = SequentialTopology().plan(_spec(3))
        assert [t.agent_name for t in tasks] == ["a0", "a1", "a2"]
