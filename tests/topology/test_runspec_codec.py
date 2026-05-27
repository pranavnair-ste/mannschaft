from __future__ import annotations

import pytest

from pi_harness.topology.base import (
    AgentSpec,
    ModelTier,
    Role,
    RunSpec,
    SyncMode,
    TaskDef,
    TopologyMode,
)
from pi_harness.topology.runspec_codec import (
    apply_overrides,
    runspec_from_json,
    runspec_to_json,
)


def _spec(**kw) -> RunSpec:
    base = dict(
        goal="ship the thing",
        agents=[
            AgentSpec(name="lead", role=Role.ORCHESTRATOR, model_tier=ModelTier.REASONING),
            AgentSpec(name="b", role=Role.BUILDER, model_tier=ModelTier.FAST, tools=["edit"]),
        ],
        mode=TopologyMode.SEQUENTIAL,
        sync_mode=SyncMode.PER_AGENT,
        corpus_classifications=["foundational"],
        session_id="sess-1",
        executor="pi",
        sync_profile=None,
        tasks=[TaskDef(task_id="t1", agent_name="b", goal="do it", blocked_by=[])],
        spec_id="spec-abc",
    )
    base.update(kw)
    return RunSpec(**base)


def test_roundtrip_preserves_everything():
    spec = _spec()
    restored = runspec_from_json(runspec_to_json(spec))
    assert restored == spec


def test_roundtrip_with_none_tasks():
    spec = _spec(tasks=None)
    restored = runspec_from_json(runspec_to_json(spec))
    assert restored.tasks is None
    assert restored == spec


def test_override_goal():
    out = apply_overrides(_spec(), {"goal": "new goal"})
    assert out.goal == "new goal"


def test_override_topology():
    out = apply_overrides(_spec(), {"topology": "parallel"})
    assert out.mode == TopologyMode.PARALLEL


def test_override_sync_mode():
    out = apply_overrides(_spec(), {"sync_mode": "sync_all"})
    assert out.sync_mode == SyncMode.SYNC_ALL


def test_override_model_tier_applies_to_all_agents():
    out = apply_overrides(_spec(), {"model_tier": "reasoning"})
    assert all(a.model_tier == ModelTier.REASONING for a in out.agents)


def test_override_unknown_key_raises():
    with pytest.raises(ValueError, match="unsupported branch override"):
        apply_overrides(_spec(), {"nonsense": 1})


def test_override_does_not_mutate_original():
    spec = _spec()
    apply_overrides(spec, {"goal": "x", "model_tier": "fast"})
    assert spec.goal == "ship the thing"
    assert spec.agents[0].model_tier == ModelTier.REASONING
