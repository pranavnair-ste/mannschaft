"""Topology layer base types and abstract class.

Provides the shared vocabulary used by all five named topologies and the
Coordinator. Downstream plans (6/7/8) import from here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pi_harness.improve.runner import ImproveResult


# metadata-tier priming budget; topology owns this per Decision §5
DEFAULT_PRIME_TOKEN_BUDGET = 4000


class TopologyMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    SYNTHESIS = "synthesis"
    NESTED = "nested"
    PERSISTENT = "persistent"


class Role(str, Enum):
    ORCHESTRATOR = "orchestrator"
    BUILDER = "builder"
    SCOUT = "scout"
    REVIEWER = "reviewer"
    SYNTHESIZER = "synthesizer"


class ModelTier(str, Enum):
    REASONING = "reasoning"
    FAST = "fast"


class SyncMode(str, Enum):
    SYNC_ALL = "sync_all"
    PER_AGENT = "per_agent"


@dataclass
class AgentSpec:
    """One agent's declaration inside a RunSpec."""
    name: str
    role: Role
    model_tier: ModelTier
    tools: list[str] = field(default_factory=list)
    expertise_classifications: list[str] = field(default_factory=list)
    task_prompt: str | None = None             # used as [[template.agents]].task; None → default


@dataclass
class RunSpec:
    """User-facing run declaration. Consumed by Coordinator.launch."""
    goal: str
    agents: list[AgentSpec]
    mode: TopologyMode
    sync_mode: SyncMode
    corpus_classifications: list[str]
    session_id: str | None = None              # required for PERSISTENT mode
    executor: str = "pi"                       # `pi` (pi-coding-agent) or `codex`; chosen by caller
    sync_profile: str | None = None            # overrides PROFILE_NAME_FAST when sync_mode = SYNC_ALL


@dataclass
class RunHandle:
    """Returned by Coordinator.launch. Threaded into trajectory capture +
    post-completion improve scheduling. session_id is propagated from RunSpec
    so the improve adapter can stamp corpus entries with the originating session."""
    run_id: str
    team_name: str
    started_at: datetime
    topology: TopologyMode
    session_id: str | None = None


@dataclass
class TaskDef:
    """One node in a ClawTeam task DAG. blocked_by lists task_ids that must
    complete before this task is unblocked."""
    task_id: str
    agent_name: str
    goal: str
    blocked_by: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    """Returned by Coordinator.wait_for_completion. Wraps Plan 1's
    ClawTeamClient.wait_for_completion (which returns bool / raises).
    terminal_statuses uses real ClawTeam values: pending|in_progress|
    completed|blocked (no `failed`/`cancelled` in v0.2.x)."""
    run_handle: RunHandle
    success: bool                              # True iff every task is "completed"
    terminal_statuses: dict[str, str]          # task_id -> status string
    error: Exception | None = None             # set when wait_for_completion raised


class Topology(ABC):
    """Abstract base. Every named topology subclasses this."""

    @abstractmethod
    def plan(self, spec: RunSpec, depth: int = 0) -> list[TaskDef]:
        """Build the task DAG. Returns a flat list of TaskDef whose blocked_by
        references form the dependency graph. depth is used by NestedTopology
        for recursion-limit checks."""
        ...

    def build_template_dict(self, spec: RunSpec) -> dict:
        """Build the ClawTeam template dict (leader + agents only, no tasks).

        Tasks are created at runtime by Coordinator via client.create_task;
        keeping them out of the template matches ClawTeam 0.2.x semantics.

        Subclasses may override for topology-specific tweaks (e.g. Nested
        appends agents from a child team).

        Raises:
            ValueError: If ``spec.agents`` is empty (no leader can be chosen).
        """
        if not spec.agents:
            raise ValueError("build_template_dict requires at least one agent")

        from pi_harness.clawteam_profile import ROLE_PROFILE_MAP

        # First agent (lowest task index) is the leader. Subclasses can
        # override _leader_index() if a different selection is desired.
        leader_idx = self._leader_index(spec)
        leader = spec.agents[leader_idx]
        workers = [a for i, a in enumerate(spec.agents) if i != leader_idx]

        return {
            "template": {
                "name": self._template_name(spec),
                "description": f"Topology={spec.mode.value} for goal: {spec.goal[:80]}",
                "command": [spec.executor],
                "backend": "tmux",
                "leader": {
                    "name": leader.name,
                    "type": leader.role.value,
                    "task": leader.task_prompt or self._default_leader_prompt(spec),
                    "profile": ROLE_PROFILE_MAP.get(leader.role.value, ""),
                },
                "agents": [
                    {
                        "name": a.name,
                        "type": a.role.value,
                        "task": a.task_prompt or self._default_worker_prompt(spec, a),
                        "profile": ROLE_PROFILE_MAP.get(a.role.value, ""),
                    }
                    for a in workers
                ],
            },
        }

    def _template_name(self, spec: RunSpec) -> str:
        """Deterministic template-name slug. Coordinator overrides with run_id."""
        return f"topology-{spec.mode.value}"

    def _leader_index(self, spec: RunSpec) -> int:
        """Pick which agent in spec.agents is the leader. Default: first orchestrator,
        else first agent."""
        for i, a in enumerate(spec.agents):
            if a.role == Role.ORCHESTRATOR:
                return i
        return 0

    def _default_leader_prompt(self, spec: RunSpec) -> str:
        return f"Lead the team toward this goal: {spec.goal}"

    def _default_worker_prompt(self, spec: RunSpec, agent: "AgentSpec") -> str:
        return f"Work on tasks assigned to you. Team goal: {spec.goal}"
