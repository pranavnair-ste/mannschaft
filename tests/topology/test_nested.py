"""NestedTopology: coordinator spawns a child team."""
from __future__ import annotations

import pytest

from pi_harness.topology.base import (
    AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
)
from pi_harness.topology.nested import NestedTopology


def _spec() -> RunSpec:
    return RunSpec(
        goal="nested goal",
        agents=[
            AgentSpec(name="coord", role=Role.ORCHESTRATOR, model_tier=ModelTier.REASONING),
            AgentSpec(name="sub1", role=Role.BUILDER, model_tier=ModelTier.FAST),
            AgentSpec(name="sub2", role=Role.BUILDER, model_tier=ModelTier.FAST),
        ],
        mode=TopologyMode.NESTED,
        sync_mode=SyncMode.PER_AGENT,
        corpus_classifications=[],
    )


class TestNestedPlan:
    def test_coordinator_task_exists_and_unblocked(self):
        tasks = NestedTopology().plan(_spec())
        coord = next(t for t in tasks if t.agent_name == "coord")
        assert coord.blocked_by == []

    def test_subagents_blocked_by_coordinator(self):
        tasks = NestedTopology().plan(_spec())
        coord_id = next(t.task_id for t in tasks if t.agent_name == "coord")
        for t in tasks:
            if t.agent_name != "coord":
                assert coord_id in t.blocked_by

    def test_depth_default_max_two(self):
        top = NestedTopology()
        assert top.max_depth == 2

    def test_depth_zero_succeeds(self):
        tasks = NestedTopology().plan(_spec(), depth=0)
        assert len(tasks) == 3

    def test_depth_at_max_succeeds(self):
        tasks = NestedTopology(max_depth=2).plan(_spec(), depth=2)
        assert len(tasks) == 3

    def test_depth_exceeds_raises(self):
        with pytest.raises(RecursionError, match="max depth"):
            NestedTopology(max_depth=2).plan(_spec(), depth=3)

    def test_custom_max_depth(self):
        top = NestedTopology(max_depth=5)
        assert top.max_depth == 5
        top.plan(_spec(), depth=4)  # should not raise

    def test_child_team_name_includes_parent(self):
        top = NestedTopology()
        tasks = top.plan(_spec(), depth=0)
        # Child-team metadata is attached to the template dict under
        # `[template.metadata.child]` (ClawTeam ignores unknown keys in
        # `template.metadata`; the Coordinator reads it before launch).
        dct = top.build_template_dict(_spec())
        assert "metadata" in dct["template"]
        assert dct["template"]["metadata"]["child"]["parent_template"] == dct["template"]["name"]
