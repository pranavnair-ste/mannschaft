"""Serialize a RunSpec to/from JSON for the run registry.

The registry stores each run's RunSpec so branch (Phase 2) can reload it
verbatim and re-launch a child with overrides — no re-decompose, no LLM call.
``apply_overrides`` (added in Phase 2) mutates a reloaded spec for branching.
"""
from __future__ import annotations

import json
from dataclasses import replace

from pi_harness.topology.base import (
    AgentSpec,
    ModelTier,
    Role,
    RunSpec,
    SyncMode,
    TaskDef,
    TopologyMode,
)


def runspec_to_json(spec: RunSpec) -> str:
    return json.dumps(
        {
            "goal": spec.goal,
            "mode": spec.mode.value,
            "sync_mode": spec.sync_mode.value,
            "corpus_classifications": list(spec.corpus_classifications),
            "session_id": spec.session_id,
            "executor": spec.executor,
            "sync_profile": spec.sync_profile,
            "spec_id": spec.spec_id,
            "agents": [
                {
                    "name": a.name,
                    "role": a.role.value,
                    "model_tier": a.model_tier.value,
                    "tools": list(a.tools),
                    "expertise_classifications": list(a.expertise_classifications),
                    "task_prompt": a.task_prompt,
                }
                for a in spec.agents
            ],
            "tasks": None
            if spec.tasks is None
            else [
                {
                    "task_id": t.task_id,
                    "agent_name": t.agent_name,
                    "goal": t.goal,
                    "blocked_by": list(t.blocked_by),
                }
                for t in spec.tasks
            ],
        }
    )


def runspec_from_json(s: str) -> RunSpec:
    d = json.loads(s)
    agents = [
        AgentSpec(
            name=a["name"],
            role=Role(a["role"]),
            model_tier=ModelTier(a["model_tier"]),
            tools=a.get("tools", []),
            expertise_classifications=a.get("expertise_classifications", []),
            task_prompt=a.get("task_prompt"),
        )
        for a in d["agents"]
    ]
    tasks = (
        None
        if d.get("tasks") is None
        else [
            TaskDef(
                task_id=t["task_id"],
                agent_name=t["agent_name"],
                goal=t["goal"],
                blocked_by=t.get("blocked_by", []),
            )
            for t in d["tasks"]
        ]
    )
    return RunSpec(
        goal=d["goal"],
        agents=agents,
        mode=TopologyMode(d["mode"]),
        sync_mode=SyncMode(d["sync_mode"]),
        corpus_classifications=d.get("corpus_classifications", []),
        session_id=d.get("session_id"),
        executor=d.get("executor", "pi"),
        sync_profile=d.get("sync_profile"),
        tasks=tasks,
        spec_id=d.get("spec_id"),
    )


_SUPPORTED_OVERRIDES = frozenset({"goal", "topology", "sync_mode", "model_tier"})


def apply_overrides(spec: RunSpec, overrides: dict) -> RunSpec:
    """Return a copy of ``spec`` with branch overrides applied.

    Supported keys (Level-1 branch): ``goal`` (str), ``topology`` (str ->
    TopologyMode), ``sync_mode`` (str -> SyncMode), ``model_tier`` (str ->
    ModelTier, applied to every agent). Unknown keys raise ValueError.
    """
    new = spec
    for key, value in overrides.items():
        if key not in _SUPPORTED_OVERRIDES:
            raise ValueError(f"unsupported branch override: {key}")
        if key == "goal":
            new = replace(new, goal=str(value))
        elif key == "topology":
            new = replace(new, mode=TopologyMode(value))
        elif key == "sync_mode":
            new = replace(new, sync_mode=SyncMode(value))
        elif key == "model_tier":
            tier = ModelTier(value)
            new = replace(new, agents=[replace(a, model_tier=tier) for a in new.agents])
    return new
