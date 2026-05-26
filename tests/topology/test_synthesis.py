"""SynthesisTopology: like Parallel, but merge agent must be SYNTHESIZER role."""
from __future__ import annotations

import pytest

from pi_harness.topology.base import (
    AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
)
from pi_harness.topology.synthesis import SynthesisTopology


def _spec(merger_role: Role, worker_count: int = 3) -> RunSpec:
    agents = [AgentSpec(name="q", role=Role.ORCHESTRATOR, model_tier=ModelTier.REASONING)]
    for i in range(worker_count):
        agents.append(AgentSpec(name=f"e{i}", role=Role.SCOUT, model_tier=ModelTier.FAST))
    agents.append(AgentSpec(name="syn", role=merger_role, model_tier=ModelTier.REASONING))
    return RunSpec(
        goal="synth goal",
        agents=agents,
        mode=TopologyMode.SYNTHESIS,
        sync_mode=SyncMode.PER_AGENT,
        corpus_classifications=[],
    )


class TestSynthesisPlan:
    def test_shape_matches_parallel(self):
        tasks = SynthesisTopology().plan(_spec(Role.SYNTHESIZER, 3))
        assert len(tasks) == 5
        merge = next(t for t in tasks if t.agent_name == "syn")
        worker_ids = {t.task_id for t in tasks if t.agent_name.startswith("e")}
        assert set(merge.blocked_by) == worker_ids

    def test_rejects_non_synthesizer_merger(self):
        with pytest.raises(ValueError, match="synthesizer role"):
            SynthesisTopology().plan(_spec(Role.REVIEWER, 3))

    def test_merge_task_goal_contains_synthesize_marker(self):
        tasks = SynthesisTopology().plan(_spec(Role.SYNTHESIZER, 3))
        merge = next(t for t in tasks if t.agent_name == "syn")
        assert "synthesize" in merge.goal.lower() or "vote" in merge.goal.lower()
