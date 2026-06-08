"""Bridge: a decomposed Spec -> Plan 5 RunSpec.

The single mapping point between the spec layer's DecomposedTask shape and the
topology layer's RunSpec / AgentSpec / TaskDef. The CLI's ``ms launch``
and the editor's ``POST /specs/{id}/launch`` both go through here so they emit
identical runs from the same spec.

Model: **one agent per role** (agent name == role, e.g. ``builder``). Every
decomposed task of that role is owned by the single role agent and seeded onto
the ClawTeam board, so they all run in that agent's ONE worktree. The agent's
``task_prompt`` is its standing instruction (the spec goal + its tasks, in
order); each task's description stays the per-task ClawTeam goal. The
decomposer's ``blocked_by`` chains are carried verbatim as the explicit
``TaskDef`` DAG, which Coordinator.launch consumes via ``RunSpec.tasks``.

Why per-role, not per-task: one-agent-per-task gave every task its own isolated
ClawTeam worktree (artifacts only merge at run end), so a ``create file → use
file → test it`` chain failed — a later task couldn't see an earlier task's
files. Per-role keeps a role's whole sequence in one worktree, which also stays
correct when the decomposer omits a ``blocked_by`` edge between related tasks.
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


def _role_task_prompt(spec: Spec, role_tasks: Sequence[DecomposedTask]) -> str:
    """Standing instruction for a role agent. One task → its description
    verbatim (the board carries the same goal). Multiple tasks → the spec goal
    plus the tasks numbered in order, so the agent sees its whole plan and knows
    they share one working directory."""
    if len(role_tasks) == 1:
        return role_tasks[0].description
    steps = "\n".join(f"{i}. {t.description}" for i, t in enumerate(role_tasks, 1))
    return (
        f"{spec.goal}\n\nComplete these steps in order, in a single working "
        f"directory (do not assume another agent created files for you):\n{steps}"
    )


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
    # Group tasks by role, preserving first-appearance order (so the leader
    # selection — first orchestrator, else first agent — stays deterministic).
    roles_in_order: list[Role] = []
    tasks_by_role: dict[Role, list[DecomposedTask]] = {}
    for t in tasks:
        role = Role(t.assigned_role)
        if role not in tasks_by_role:
            tasks_by_role[role] = []
            roles_in_order.append(role)
        tasks_by_role[role].append(t)

    agents: list[AgentSpec] = [
        AgentSpec(
            name=role.value,
            role=role,
            model_tier=ROLE_TIER_MAP[role],
            task_prompt=_role_task_prompt(spec, tasks_by_role[role]),
        )
        for role in roles_in_order
    ]
    task_defs: list[TaskDef] = [
        TaskDef(
            task_id=t.id,
            agent_name=Role(t.assigned_role).value,
            goal=t.description,
            blocked_by=list(t.blocked_by),
        )
        for t in tasks
    ]

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
        spec_id=spec.id,
    )


def build_coordinator(config):
    """Wire a real Plan 5 Coordinator with the real Plan 3 corpus reader and the
    Plan 4 improve runner module.

    The CLI's ``ms launch`` and the editor's ``/launch`` route share
    this so a launched run primes the corpus and schedules improve identically.
    The improve *module* itself is passed as ``improve_runner`` — its
    module-level ``run_for_completed_run(run_id, config, *, session_id=...)``
    matches what Coordinator.on_completion calls.
    """
    from pi_harness.clawteam import ClawTeamClient
    from pi_harness.corpus.reader import CorpusReader
    from pi_harness.improve import runner as improve_runner
    from pi_harness.topology.coordinator import Coordinator

    return Coordinator(
        config=config,
        clawteam_client=ClawTeamClient(config),
        corpus_reader=CorpusReader(config.corpus_root),
        improve_runner=improve_runner,
    )
