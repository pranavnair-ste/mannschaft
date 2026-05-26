"""Tests for topology base types and abstract class."""
from __future__ import annotations

import pytest
from datetime import datetime

from pi_harness.topology.base import (
    AgentSpec,
    ModelTier,
    Role,
    RunHandle,
    RunSpec,
    SyncMode,
    TopologyMode,
    Topology,
    TaskDef,
)


class TestEnums:
    def test_topology_mode_has_five_values(self):
        assert {m.value for m in TopologyMode} == {
            "sequential", "parallel", "synthesis", "nested", "persistent"
        }

    def test_role_has_five_values(self):
        assert {r.value for r in Role} == {
            "orchestrator", "builder", "scout", "reviewer", "synthesizer"
        }

    def test_model_tier_has_two_values(self):
        assert {t.value for t in ModelTier} == {"reasoning", "fast"}

    def test_sync_mode_has_two_values(self):
        assert {s.value for s in SyncMode} == {"sync_all", "per_agent"}


class TestAgentSpec:
    def test_defaults(self):
        spec = AgentSpec(name="alice", role=Role.BUILDER, model_tier=ModelTier.FAST)
        assert spec.tools == []
        assert spec.expertise_classifications == []

    def test_with_tools(self):
        spec = AgentSpec(
            name="bob",
            role=Role.REVIEWER,
            model_tier=ModelTier.REASONING,
            tools=["bash", "edit"],
            expertise_classifications=["foundational"],
        )
        assert spec.tools == ["bash", "edit"]
        assert spec.expertise_classifications == ["foundational"]


class TestRunSpec:
    def test_minimal(self):
        agents = [AgentSpec(name="a", role=Role.BUILDER, model_tier=ModelTier.FAST)]
        spec = RunSpec(
            goal="ship feature X",
            agents=agents,
            mode=TopologyMode.SEQUENTIAL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=["foundational"],
        )
        assert spec.goal == "ship feature X"
        assert spec.session_id is None

    def test_with_session_id(self):
        spec = RunSpec(
            goal="g",
            agents=[],
            mode=TopologyMode.PERSISTENT,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
            session_id="session-42",
        )
        assert spec.session_id == "session-42"


class TestRunHandle:
    def test_required_fields(self):
        now = datetime(2026, 5, 25, 12, 0, 0)
        handle = RunHandle(
            run_id="run-001",
            team_name="team-001",
            started_at=now,
            topology=TopologyMode.SEQUENTIAL,
        )
        assert handle.run_id == "run-001"
        assert handle.started_at == now


class TestTaskDef:
    def test_blocked_by_defaults_empty(self):
        t = TaskDef(task_id="t1", agent_name="alice", goal="do X")
        assert t.blocked_by == []

    def test_blocked_by_list(self):
        t = TaskDef(task_id="t2", agent_name="bob", goal="do Y", blocked_by=["t1"])
        assert t.blocked_by == ["t1"]


class TestTopologyAbstract:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Topology()

    def test_subclass_must_implement_plan(self):
        class Broken(Topology):
            pass
        with pytest.raises(TypeError):
            Broken()
