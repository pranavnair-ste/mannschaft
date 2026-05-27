"""Coordinator: dispatch + lifecycle wrapper around topologies.

Selects the right Topology subclass by RunSpec.mode, primes corpus,
installs the ClawTeam template, launches the team, seeds the task DAG
via client.create_task, and schedules a post-completion improve run.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import tomli_w

from pi_harness.corpus.format import Classification
from pi_harness.clawteam import (
    ClawTeamClient,
    ClawTeamRunFailure,
    ClawTeamTimeout,
)
from pi_harness.clawteam_profile import PROFILE_NAME_FAST
from pi_harness.topology.base import (
    DEFAULT_PRIME_TOKEN_BUDGET,
    RunHandle,
    RunResult,
    RunSpec,
    SyncMode,
    TaskDef,
    Topology,
    TopologyMode,
)
from pi_harness.topology.nested import NestedTopology
from pi_harness.topology.parallel import ParallelTopology
from pi_harness.topology.persistent import PersistentTopology
from pi_harness.topology.sequential import SequentialTopology
from pi_harness.topology.synthesis import SynthesisTopology


def _get_topology_registry() -> dict[TopologyMode, type[Topology]]:
    """Return the topology registry, resolving class references at call time.

    Deferring the lookup to call time allows unit tests to patch the module-level
    names (e.g. ``pi_harness.topology.coordinator.SequentialTopology``) and have
    those patches take effect when Coordinator.launch() resolves the class.
    """
    return {
        TopologyMode.SEQUENTIAL: SequentialTopology,
        TopologyMode.PARALLEL: ParallelTopology,
        TopologyMode.SYNTHESIS: SynthesisTopology,
        TopologyMode.NESTED: NestedTopology,
        TopologyMode.PERSISTENT: PersistentTopology,
    }


class Coordinator:
    """Single entry-point for launching runs across all five topologies."""

    def __init__(
        self,
        config,
        clawteam_client: ClawTeamClient,
        corpus_reader,
        improve_runner,
    ) -> None:
        """Initialise the Coordinator.

        Args:
            config: A :class:`pi_harness.config.Config` instance. Forwarded
                to ``improve_runner.run_for_completed_run`` as the second
                positional argument.
            clawteam_client: A :class:`pi_harness.clawteam.ClawTeamClient`
                (or compatible mock).
            corpus_reader: An object exposing
                ``prime(token_budget, classifications, session_id)`` — typically
                :class:`pi_harness.corpus.reader.CorpusReader`.
            improve_runner: Object exposing
                ``run_for_completed_run(run_id: str, config, *, session_id=None)``
                — typically the ``pi_harness.improve.runner`` module itself.
        """
        self._config = config
        self._clawteam_client = clawteam_client
        self._corpus_reader = corpus_reader
        self._improve_runner = improve_runner
        self._last_result: dict[str, RunResult] = {}  # run_id -> result
        self._task_specs: dict[str, list] = {}        # run_id -> TaskDef list; reserved for downstream callers
        #   (e.g. dashboard / trajectory layers) to inspect the seeded DAG

    def launch(self, spec: RunSpec) -> RunHandle:
        registry = _get_topology_registry()
        topology_cls = registry.get(spec.mode)
        if topology_cls is None:
            raise ValueError(f"Unknown topology mode: {spec.mode}")
        topology = topology_cls()

        # 1. Pre-launch corpus prime (Plan 3).
        classifications = (
            [Classification(c) for c in spec.corpus_classifications]
            if spec.corpus_classifications
            else None
        )
        self._corpus_reader.prime(
            token_budget=DEFAULT_PRIME_TOKEN_BUDGET,
            classifications=classifications,
            session_id=spec.session_id,
        )

        # 2. Build task DAG (TaskDef list — separate from the template).
        #    An explicit caller-supplied DAG (e.g. Plan 7's decomposer) is used
        #    verbatim; otherwise the topology synthesizes one task per agent.
        if spec.tasks is not None:
            tasks = self._prepare_explicit_tasks(spec)
        else:
            tasks = topology.plan(spec)

        # 3. Build the template dict + apply sync_mode.
        template_dict = topology.build_template_dict(spec)
        self._apply_sync_mode(template_dict, spec)

        # 4. Emit run_id, derive template name + team name.
        run_id = f"run-{uuid.uuid4()}"
        template_name = f"topology-{spec.mode.value}-{run_id[-8:]}"
        team_name = f"team-{run_id[-8:]}"
        template_dict["template"]["name"] = template_name

        # 5. Register template + launch team via Plan 1.
        self._clawteam_client.install_template(
            template_name, tomli_w.dumps(template_dict)
        )
        self._clawteam_client.launch_team(
            template=template_name,
            team_name=team_name,
            goal=spec.goal,
        )

        # 6. Seed the task DAG. Order matters: a task referenced in `blocked_by`
        #    must exist before its dependent is created.
        for task in tasks:
            self._clawteam_client.create_task(
                team_name=team_name,
                subject=task.task_id,
                description=task.goal,
                owner=task.agent_name,
                blocked_by=task.blocked_by or None,
            )

        handle = RunHandle(
            run_id=run_id,
            team_name=team_name,
            started_at=datetime.now(timezone.utc),
            topology=spec.mode,
            session_id=spec.session_id,
        )
        self._task_specs[run_id] = tasks
        return handle

    def wait_for_completion(self, handle: RunHandle, timeout: float) -> RunResult:
        """Block on Plan 1's wait_for_completion, then summarize as RunResult."""
        error: Exception | None = None
        success = False
        try:
            success = self._clawteam_client.wait_for_completion(
                handle.team_name, timeout=timeout, poll_interval=5.0
            )
        except (ClawTeamTimeout, ClawTeamRunFailure) as exc:
            error = exc
            success = False

        # Snapshot terminal statuses for telemetry (best-effort).
        # ClawTeam's `task list --json` keys the task id as "id" (not
        # "task_id"); fall back to "task_id" only for non-ClawTeam stubs.
        try:
            board = self._clawteam_client.list_tasks(handle.team_name)
            terminal_statuses = {
                str(t.get("id", t.get("task_id", ""))): str(t.get("status", ""))
                for t in board
            }
        except Exception:
            terminal_statuses = {}

        result = RunResult(
            run_handle=handle,
            success=success,
            terminal_statuses=terminal_statuses,
            error=error,
        )
        self._last_result[handle.run_id] = result
        return result

    def on_completion(self, handle: RunHandle) -> None:
        """Called after wait_for_completion. Triggers Plan 4's improve run
        iff the run succeeded."""
        result = self._last_result.get(handle.run_id)
        if result is not None and result.success:
            self._improve_runner.run_for_completed_run(
                handle.run_id, self._config, session_id=handle.session_id
            )

    def _apply_sync_mode(self, template_dict: dict, spec: RunSpec) -> None:
        """In SYNC_ALL mode, force every agent (leader + workers) onto a
        single profile. PER_AGENT keeps the profiles set by build_template_dict."""
        if spec.sync_mode != SyncMode.SYNC_ALL:
            return
        sync_profile = spec.sync_profile or PROFILE_NAME_FAST
        template = template_dict.get("template", {})
        leader = template.get("leader")
        if leader is not None:
            leader["profile"] = sync_profile
        for agent in template.get("agents", []):
            agent["profile"] = sync_profile

    def _prepare_explicit_tasks(self, spec: RunSpec) -> list[TaskDef]:
        """Validate + topologically order a caller-supplied task DAG.

        Enforces the same invariants topology.plan() would: PERSISTENT runs
        still need a session_id, every task is owned by a declared agent, and
        every blocked_by edge references a real task in the same DAG. Returns
        the tasks ordered so each blocker precedes its dependents — create_task
        requires the blocker to exist before the dependent is created.
        """
        tasks = spec.tasks or []
        if spec.mode == TopologyMode.PERSISTENT and not spec.session_id:
            raise ValueError(
                "PERSISTENT mode requires RunSpec.session_id even when tasks "
                "are supplied explicitly"
            )
        agent_names = {a.name for a in spec.agents}
        seen: set[str] = set()
        for t in tasks:
            if t.task_id in seen:
                raise ValueError(
                    f"explicit RunSpec.tasks has duplicate task_id {t.task_id!r}"
                )
            seen.add(t.task_id)
            if t.agent_name not in agent_names:
                raise ValueError(
                    f"task {t.task_id!r} is owned by unknown agent "
                    f"{t.agent_name!r}; declared agents are {sorted(agent_names)}"
                )
        for t in tasks:
            for dep in t.blocked_by:
                if dep not in seen:
                    raise ValueError(
                        f"task {t.task_id!r} is blocked_by unknown task {dep!r}"
                    )
        return self._toposort(tasks)

    @staticmethod
    def _toposort(tasks: list[TaskDef]) -> list[TaskDef]:
        """Kahn's algorithm. Preserves input order among ready nodes for
        determinism; raises ValueError on a dependency cycle."""
        from collections import deque

        by_id = {t.task_id: t for t in tasks}
        indegree = {t.task_id: len(t.blocked_by) for t in tasks}
        dependents: dict[str, list[str]] = {t.task_id: [] for t in tasks}
        for t in tasks:
            for dep in t.blocked_by:
                dependents[dep].append(t.task_id)
        ready = deque(t.task_id for t in tasks if indegree[t.task_id] == 0)
        ordered: list[TaskDef] = []
        while ready:
            tid = ready.popleft()
            ordered.append(by_id[tid])
            for nxt in dependents[tid]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
        if len(ordered) != len(tasks):
            raise ValueError(
                "explicit RunSpec.tasks contains a dependency cycle"
            )
        return ordered
