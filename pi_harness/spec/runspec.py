"""Bridge: a decomposed Spec -> Plan 5 RunSpec.

The single mapping point between the spec layer's DecomposedTask shape and the
topology layer's RunSpec / AgentSpec / TaskDef. The CLI's ``pi-harness launch``
and the editor's ``POST /specs/{id}/launch`` both go through here so they emit
identical runs from the same spec.

Model: one agent per decomposed task (agent name == task id). The task's
description becomes both the agent's ``task_prompt`` (its standing instruction
in the ClawTeam template) and the ClawTeam task goal. The decomposer's
``blocked_by`` chains are carried verbatim as the explicit ``TaskDef`` DAG,
which Coordinator.launch consumes via ``RunSpec.tasks`` instead of
synthesizing one-task-per-agent itself.
"""
from __future__ import annotations

from typing import Optional, Sequence

from pi_harness.spec.decomposer import DecomposedTask
from pi_harness.spec.format import Spec
from pi_harness.topology.base import (
    AgentSpec,
    ModelTier,
    Role,
    RunSpec,
    SyncMode,
    TaskDef,
    TopologyMode,
)

# Mirrors clawteam_profile.ROLE_PROFILE_MAP tiers: reasoning for the
# coordinating / judging roles, fast for the producing / gathering roles.
ROLE_TIER_MAP: dict[Role, ModelTier] = {
    Role.ORCHESTRATOR: ModelTier.REASONING,
    Role.REVIEWER: ModelTier.REASONING,
    Role.SYNTHESIZER: ModelTier.REASONING,
    Role.BUILDER: ModelTier.FAST,
    Role.SCOUT: ModelTier.FAST,
}


def spec_to_runspec(
    spec: Spec,
    tasks: Sequence[DecomposedTask],
    *,
    session_id: Optional[str] = None,
    executor: Optional[str] = None,
    sync_profile: Optional[str] = None,
) -> RunSpec:
    """Build a RunSpec from a spec + its decomposed tasks.

    Keyword overrides (session_id / executor / sync_profile) win over the
    spec's own run-shape fields — this is how the CLI surfaces ``--session``,
    ``--executor`` and ``--sync-profile``.
    """
    agents: list[AgentSpec] = []
    task_defs: list[TaskDef] = []
    for t in tasks:
        role = Role(t.assigned_role)
        agents.append(
            AgentSpec(
                name=t.id,
                role=role,
                model_tier=ROLE_TIER_MAP[role],
                task_prompt=t.description,
            )
        )
        task_defs.append(
            TaskDef(
                task_id=t.id,
                agent_name=t.id,
                goal=t.description,
                blocked_by=list(t.blocked_by),
            )
        )

    return RunSpec(
        goal=spec.goal,
        agents=agents,
        mode=TopologyMode(spec.topology),
        sync_mode=SyncMode(spec.sync_mode),
        corpus_classifications=list(spec.corpus_classifications),
        session_id=session_id if session_id is not None else spec.session_id,
        executor=executor if executor is not None else spec.executor,
        sync_profile=sync_profile if sync_profile is not None else spec.sync_profile,
        tasks=task_defs,
    )
