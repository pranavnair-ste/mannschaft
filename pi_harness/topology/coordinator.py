"""Coordinator: dispatch + lifecycle wrapper around topologies.

Selects the right Topology subclass by RunSpec.mode, primes corpus,
installs the ClawTeam template, launches the team, seeds the task DAG
via client.create_task, and schedules a post-completion improve run.
"""
from __future__ import annotations

import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone

import tomli_w

from pathlib import Path

from pi_harness.clawteam import git_workspace

from pi_harness.corpus.format import Classification
from pi_harness.clawteam import (
    ClawTeamCLIError,
    ClawTeamClient,
    ClawTeamRunFailure,
    ClawTeamTimeout,
)
from pi_harness.clawteam_profile import PROFILE_NAME_FAST, build_profile_specs
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

    def launch(self, spec: RunSpec, *, in_place: bool = False, keep_alive: bool = False) -> RunHandle:
        # Ensure the trajectory store exists before any capture write.
        from pi_harness.trajectory.store import init_db
        init_db(self._config.trajectory_db_path)

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

        # Route every agent's command through the pi_harness wrapper so its
        # NDJSON event stream lands in the trajectory store. ClawTeam's launch
        # uses the template's top-level ``command`` unless a top-level
        # ``--profile`` is passed; we set BOTH (template AND profile.command)
        # as defense-in-depth. agent_id is picked up from CLAWTEAM_AGENT_NAME
        # (set by ClawTeam in each pane).
        import shlex

        wrapper_argv = [
            sys.executable,
            "-m",
            "pi_harness.agent_wrapper",
            "--executor",
            spec.executor,
            "--run-id",
            run_id,
        ]
        template_dict["template"]["command"] = list(wrapper_argv)
        wrapper_cmd_str = " ".join(shlex.quote(p) for p in wrapper_argv)

        # Per-agent commands carry the agent's bucket so agent_wrapper can pick
        # the right HarnessSettings entry (orchestrator vs builder) for
        # --provider/--model on pi. Without this, every pi pane uses pi's
        # built-in settings.json defaults regardless of the UI selection.
        from pi_harness.clawteam_profile import bucket_for_role

        leader_block = template_dict["template"]["leader"]
        leader_block["command"] = list(wrapper_argv) + ["--bucket", bucket_for_role(leader_block["type"])]
        for agent_block in template_dict["template"]["agents"]:
            agent_block["command"] = list(wrapper_argv) + ["--bucket", bucket_for_role(agent_block["type"])]

        # 4b. Register the profiles the template references (idempotent upsert).
        for pspec in build_profile_specs(self._config):
            self._clawteam_client.register_profile(
                replace(pspec, command=wrapper_cmd_str)
            )

        # 4c. Isolation (default): create a run/<id> worktree off HEAD and point
        #     ClawTeam at it so per-agent worktrees fork off run/<id>; the user's
        #     checked-out branch is never touched. --in-place opts out.
        run_branch: str | None = None
        workspace_repo: str | None = None
        if not in_place:
            repo = git_workspace.repo_root()
            run_branch = f"run/{run_id[-8:]}"
            wt_path = Path(self._config.clawteam_state_dir) / "run-worktrees" / run_id
            git_workspace.create_run_worktree(repo, branch=run_branch, worktree_path=wt_path)
            workspace_repo = str(wt_path)

        # Capture agent names (leader + workers) for later consolidation.
        agent_names = [leader_block["name"]] + [
            a["name"] for a in template_dict["template"]["agents"]
        ]

        # Build the handle + register the run BEFORE the fragile install/launch/
        # seed steps. If any of those raise, a half-launched run would otherwise
        # orphan a live, credit-burning team and leak the run worktree; with the
        # handle already in hand we can finalize the run and tear it down (except).
        handle = RunHandle(
            run_id=run_id,
            team_name=team_name,
            started_at=datetime.now(timezone.utc),
            topology=spec.mode,
            session_id=spec.session_id,
            run_branch=run_branch,
            workspace_repo=workspace_repo,
            agent_names=agent_names,
            keep_alive=keep_alive,
        )
        self._task_specs[run_id] = tasks

        from pi_harness.topology.runspec_codec import runspec_to_json
        from pi_harness.trajectory.runs import mark_run_status, register_run

        try:
            # Register the run so the dashboard can list it with real status /
            # topology / lineage, and so branch can reload this RunSpec verbatim.
            register_run(
                run_id=run_id,
                spec_id=spec.spec_id,
                topology=spec.mode.value,
                sync_mode=spec.sync_mode.value,
                session_id=spec.session_id,
                goal=spec.goal,
                team_name=team_name,
                started_at=handle.started_at,
                run_spec_json=runspec_to_json(spec),
                status="running",
                db_path=self._config.trajectory_db_path,
            )

            # 5. Register template + launch team via Plan 1.
            self._clawteam_client.install_template(
                template_name, tomli_w.dumps(template_dict)
            )
            self._clawteam_client.launch_team(
                template=template_name,
                team_name=team_name,
                goal=spec.goal,
                workspace=workspace_repo is not None,
                repo=workspace_repo,
            )

            # 6. Seed the task DAG. Order matters: a task referenced in
            #    `blocked_by` must exist before its dependent is created.
            for task in tasks:
                self._clawteam_client.create_task(
                    team_name=team_name,
                    subject=task.task_id,
                    description=task.goal,
                    owner=task.agent_name,
                    blocked_by=task.blocked_by or None,
                )
        except Exception:
            # Half-launched run: stop any credit burn and remove the run worktree
            # (best-effort; the original error is re-raised for the caller).
            try:
                mark_run_status(
                    run_id,
                    "failed",
                    ended_at=datetime.now(timezone.utc),
                    db_path=self._config.trajectory_db_path,
                )
            except Exception:  # noqa: BLE001 — finalize is best-effort
                pass
            try:
                self.teardown(handle)
            except Exception:  # noqa: BLE001 — teardown is best-effort
                pass
            raise
        return handle

    def branch(
        self,
        parent_run_id: str,
        step_id: str,
        overrides: dict | None = None,
    ) -> RunHandle:
        """Level-1 branch: reload the parent's RunSpec, apply overrides, launch a
        child tagged with lineage.

        This is NOT mid-run replay — it re-runs the work from the parent's spec
        with a tweak (model_tier/topology/sync_mode/goal). The parent run must
        have been registered with a stored RunSpec.
        """
        from pi_harness.topology.runspec_codec import (
            apply_overrides,
            runspec_from_json,
            runspec_to_json,
        )
        from pi_harness.trajectory.runs import get_run, register_run

        parent = get_run(parent_run_id, db_path=self._config.trajectory_db_path)
        if parent is None:
            raise ValueError(f"unknown parent run {parent_run_id!r}")
        if not parent.get("run_spec_json"):
            raise ValueError("cannot branch: parent has no stored RunSpec")

        spec = runspec_from_json(parent["run_spec_json"])
        if overrides:
            spec = apply_overrides(spec, overrides)

        handle = self.launch(spec)  # registers the child as running

        # Re-register to stamp lineage onto the freshly-created child row.
        register_run(
            run_id=handle.run_id,
            spec_id=spec.spec_id,
            topology=spec.mode.value,
            sync_mode=spec.sync_mode.value,
            session_id=spec.session_id,
            goal=spec.goal,
            team_name=handle.team_name,
            started_at=handle.started_at,
            run_spec_json=runspec_to_json(spec),
            status="running",
            parent_run_id=parent_run_id,
            branch_from_step=step_id,
            overrides=overrides or {},
            db_path=self._config.trajectory_db_path,
        )
        return handle

    def wait_for_completion(self, handle: RunHandle, timeout: float) -> RunResult:
        """Block on Plan 1's wait_for_completion, capturing task transitions into
        the trajectory store as they happen, then summarize as RunResult."""
        from pi_harness.trajectory.capture import diff_task_states
        from pi_harness.trajectory.store import write_event

        capture_state: dict[str, str] = {}

        def _capture(tasks) -> None:
            events = diff_task_states(
                capture_state, tasks, run_id=handle.run_id,
                now=datetime.now(timezone.utc),
            )
            for ev in events:
                try:
                    write_event(ev, db_path=self._config.trajectory_db_path)
                except Exception:  # noqa: BLE001 — capture must never break the wait
                    pass

        error: Exception | None = None
        success = False
        try:
            success = self._clawteam_client.wait_for_completion(
                handle.team_name, timeout=timeout, poll_interval=5.0, on_poll=_capture
            )
        except (ClawTeamTimeout, ClawTeamRunFailure, ClawTeamCLIError) as exc:
            # A transient clawteam CLI failure during polling (raised by
            # list_tasks -> _run(check=True)) must be captured as a run failure,
            # not allowed to escape — otherwise the run is never finalized and the
            # team is left live (credit burn).
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

        # Reflect terminal status in the run registry for the dashboard.
        from pi_harness.trajectory.runs import mark_run_status

        mark_run_status(
            handle.run_id,
            "succeeded" if success else "failed",
            ended_at=datetime.now(timezone.utc),
            db_path=self._config.trajectory_db_path,
        )
        return result

    def on_completion(self, handle: RunHandle) -> None:
        """Always finalize the run safely.

        Success: run the improve loop, consolidate agent branches into the run
        branch, then tear the team down.
        Failure/timeout: snapshot the team for debugging, then tear it down —
        unless ``handle.keep_alive`` is set, in which case it is left live.
        """
        result = self._last_result.get(handle.run_id)
        success = bool(result is not None and result.success)
        if success:
            # Consolidate FIRST (merge agent branches into the run branch) so the
            # work is preserved even if the improve loop later fails, then run
            # improve, then ALWAYS tear down — a raise from improve OR consolidate
            # must never leave a live, credit-burning team or a leaked worktree.
            try:
                conflicts = self.consolidate(handle)
                if conflicts:
                    print(
                        f"warning: run {handle.run_id}: agents {conflicts} did not "
                        f"merge cleanly into {handle.run_branch}; resolve manually "
                        "before merging the run branch.",
                        file=sys.stderr,
                    )
                self._improve_runner.run_for_completed_run(
                    handle.run_id, self._config, session_id=handle.session_id
                )
            finally:
                self.teardown(handle)
            return
        # Failure / timeout: preserve full state for debugging, then stop the
        # credit burn (snapshot first so it survives teardown).
        self._clawteam_client.snapshot_team(
            handle.team_name, tag=f"failed-{handle.run_id[-8:]}"
        )
        if not handle.keep_alive:
            self.teardown(handle)

    def teardown(self, handle: RunHandle) -> None:
        """Stop the run's agents and delete its team data, then remove the run
        worktree (the run/<id> branch is kept — that's where the work lives).

        Kills the tmux session first (so agents stop immediately and stop burning
        credit), then removes the team record, then the worktree. Safe to call
        repeatedly.
        """
        self._clawteam_client.kill_tmux_session(handle.team_name)
        self._clawteam_client.cleanup_team(handle.team_name)
        if handle.workspace_repo:
            try:
                git_workspace.remove_run_worktree(
                    git_workspace.repo_root(), Path(handle.workspace_repo)
                )
            except Exception:  # noqa: BLE001 — teardown must never raise
                pass

    def consolidate(self, handle: RunHandle) -> list[str]:
        """Merge each agent's branch into the run branch (default target).

        Runs in launch order (leader first). A conflicting merge is recorded and
        skipped — never force-resolved. Returns the list of agent names whose
        merge conflicted. No-op (returns []) for in-place runs (no run_branch).
        """
        if handle.run_branch is None:
            return []
        conflicts: list[str] = []
        for agent_name in handle.agent_names:
            result = self._clawteam_client.merge_workspace(
                handle.team_name, agent_name,
                repo=handle.workspace_repo, target=handle.run_branch,
            )
            if getattr(result, "returncode", 0) != 0:
                conflicts.append(agent_name)
        return conflicts

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
