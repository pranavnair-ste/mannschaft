"""ParallelTopology: 1 leader + N workers + 1 merge."""
from __future__ import annotations

import pytest

from pi_harness.topology.base import (
    AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
)
from pi_harness.topology.parallel import ParallelTopology


def _spec(worker_count: int) -> RunSpec:
    agents = [AgentSpec(name="leader", role=Role.ORCHESTRATOR, model_tier=ModelTier.REASONING)]
    for i in range(worker_count):
        agents.append(AgentSpec(name=f"w{i}", role=Role.BUILDER, model_tier=ModelTier.FAST))
    agents.append(AgentSpec(name="merger", role=Role.REVIEWER, model_tier=ModelTier.REASONING))
    return RunSpec(
        goal="parallel goal",
        agents=agents,
        mode=TopologyMode.PARALLEL,
        sync_mode=SyncMode.PER_AGENT,
        corpus_classifications=[],
    )


class TestParallelPlan:
    def test_three_workers_total_five_tasks(self):
        tasks = ParallelTopology().plan(_spec(3))
        assert len(tasks) == 5  # leader + 3 workers + merge

    def test_leader_is_first_and_unblocked(self):
        tasks = ParallelTopology().plan(_spec(3))
        assert tasks[0].agent_name == "leader"
        assert tasks[0].blocked_by == []

    def test_workers_blocked_only_by_leader(self):
        tasks = ParallelTopology().plan(_spec(3))
        leader_id = tasks[0].task_id
        worker_tasks = [t for t in tasks if t.agent_name.startswith("w")]
        assert len(worker_tasks) == 3
        for w in worker_tasks:
            assert w.blocked_by == [leader_id]

    def test_merge_blocked_by_all_workers(self):
        tasks = ParallelTopology().plan(_spec(3))
        worker_ids = {t.task_id for t in tasks if t.agent_name.startswith("w")}
        merge_task = next(t for t in tasks if t.agent_name == "merger")
        assert set(merge_task.blocked_by) == worker_ids

    def test_requires_at_least_three_agents(self):
        spec = RunSpec(
            goal="g",
            agents=[AgentSpec(name="solo", role=Role.BUILDER, model_tier=ModelTier.FAST)],
            mode=TopologyMode.PARALLEL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
        )
        with pytest.raises(ValueError, match="at least 3 agents"):
            ParallelTopology().plan(spec)
