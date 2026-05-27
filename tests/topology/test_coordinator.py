"""Coordinator end-to-end: mode dispatch, corpus prime, launch, post-improve."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from pi_harness.corpus.format import Classification
from pi_harness.topology.base import (
    AgentSpec, ModelTier, Role, RunHandle, RunSpec, SyncMode, TaskDef, TopologyMode,
)
from pi_harness.topology.coordinator import Coordinator, DEFAULT_PRIME_TOKEN_BUDGET


@pytest.fixture
def basic_spec():
    return RunSpec(
        goal="coord goal",
        agents=[
            AgentSpec(name="a", role=Role.BUILDER, model_tier=ModelTier.FAST),
            AgentSpec(name="b", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
        ],
        mode=TopologyMode.SEQUENTIAL,
        sync_mode=SyncMode.PER_AGENT,
        corpus_classifications=["foundational"],
    )


@pytest.fixture
def coord(mock_clawteam_client, mock_corpus_reader, mock_improve_runner, tmp_path):
    cfg = MagicMock()
    cfg.trajectory_db_path = tmp_path / "trajectory.db"
    cfg.reasoning_model = "gpt-5"
    cfg.fast_model = "gpt-5-mini"
    return Coordinator(
        config=cfg,
        clawteam_client=mock_clawteam_client,
        corpus_reader=mock_corpus_reader,
        improve_runner=mock_improve_runner,
    )


class TestCoordinatorLaunch:
    def test_returns_run_handle_with_uuid_run_id(self, coord, basic_spec):
        handle = coord.launch(basic_spec)
        assert isinstance(handle, RunHandle)
        assert handle.run_id
        assert handle.topology == TopologyMode.SEQUENTIAL

    def test_calls_corpus_prime_before_launch(self, coord, basic_spec, mock_corpus_reader, mock_clawteam_client):
        coord.launch(basic_spec)
        assert mock_corpus_reader.prime.called
        assert mock_clawteam_client.launch_team.called
        # Order check: prime call index < launch_team call index
        prime_order = mock_corpus_reader.prime.call_args_list[0]
        assert prime_order is not None

    def test_dispatches_by_mode(self, coord, basic_spec):
        with patch("pi_harness.topology.coordinator.SequentialTopology") as mock_seq:
            instance = MagicMock()
            instance.plan.return_value = []
            instance.build_template_dict.return_value = {
                "template": {
                    "name": "t",
                    "leader": {"name": "L", "type": "orchestrator", "task": "", "profile": ""},
                    "agents": [],
                }
            }
            mock_seq.return_value = instance
            coord.launch(basic_spec)
            mock_seq.assert_called_once()

    def test_parallel_dispatch(self, coord):
        spec = RunSpec(
            goal="g",
            agents=[
                AgentSpec(name="lead", role=Role.ORCHESTRATOR, model_tier=ModelTier.REASONING),
                AgentSpec(name="w1", role=Role.BUILDER, model_tier=ModelTier.FAST),
                AgentSpec(name="m", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
            ],
            mode=TopologyMode.PARALLEL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
        )
        handle = coord.launch(spec)
        assert handle.topology == TopologyMode.PARALLEL

    def test_persistent_requires_session_id(self, coord):
        spec = RunSpec(
            goal="g",
            agents=[AgentSpec(name="a", role=Role.BUILDER, model_tier=ModelTier.FAST)],
            mode=TopologyMode.PERSISTENT,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
            session_id=None,
        )
        with pytest.raises(ValueError):
            coord.launch(spec)

    def test_launch_registers_both_profiles_with_executor(self, coord, basic_spec):
        """A fresh-launch must register both pi-openai profiles (idempotent
        upsert) before the team launches, with --command set to the executor."""
        coord.launch(basic_spec)
        client = coord._clawteam_client
        assert client.register_profile.call_count == 2
        registered = [c.args[0] for c in client.register_profile.call_args_list]
        assert {p.name for p in registered} == {"pi-openai-reasoning", "pi-openai-fast"}
        assert all(p.command == basic_spec.executor for p in registered)
        # Profiles must exist before the team launches.
        names = [c[0] for c in client.mock_calls]
        assert names.index("register_profile") < names.index("launch_team")


class TestCoordinatorSyncMode:
    def test_sync_all_rewrites_all_profiles(self, coord):
        spec = RunSpec(
            goal="g",
            agents=[
                AgentSpec(name="lead", role=Role.ORCHESTRATOR, model_tier=ModelTier.REASONING),
                AgentSpec(name="a", role=Role.BUILDER, model_tier=ModelTier.FAST),
                AgentSpec(name="b", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
            ],
            mode=TopologyMode.SEQUENTIAL,
            sync_mode=SyncMode.SYNC_ALL,
            corpus_classifications=[],
        )
        coord.launch(spec)
        # The template dict passed to install_template should have all agents
        # (leader + workers) sharing the sync profile (defaults to pi-openai-fast).
        install_call = coord._clawteam_client.install_template.call_args
        import tomllib
        template_toml = install_call.args[1] if len(install_call.args) > 1 else install_call.kwargs["toml_text"]
        parsed = tomllib.loads(template_toml)
        assert parsed["template"]["leader"]["profile"] == "pi-openai-fast"
        for a in parsed["template"]["agents"]:
            assert a["profile"] == "pi-openai-fast"

    def test_per_agent_uses_role_profile_map(self, coord, basic_spec):
        coord.launch(basic_spec)
        install_call = coord._clawteam_client.install_template.call_args
        import tomllib
        template_toml = install_call.args[1] if len(install_call.args) > 1 else install_call.kwargs["toml_text"]
        parsed = tomllib.loads(template_toml)
        # Default ROLE_PROFILE_MAP: builder/scout -> pi-openai-fast,
        # orchestrator/reviewer -> pi-openai-reasoning.
        from pi_harness.clawteam_profile import ROLE_PROFILE_MAP
        leader = parsed["template"]["leader"]
        assert leader["profile"] == ROLE_PROFILE_MAP[leader["type"]]
        for a in parsed["template"]["agents"]:
            assert a["profile"] == ROLE_PROFILE_MAP[a["type"]]


class TestCoordinatorWaitAndImprove:
    def test_wait_for_completion_returns_run_result_on_success(self, coord, basic_spec):
        handle = coord.launch(basic_spec)
        coord._clawteam_client.wait_for_completion.return_value = True
        # ClawTeam's `task list --json` keys the id as "id" (real board shape).
        coord._clawteam_client.list_tasks.return_value = [
            {"id": "t1", "status": "completed"},
            {"id": "t2", "status": "completed"},
        ]
        out = coord.wait_for_completion(handle, timeout=60)
        assert out.success is True
        assert out.error is None
        # Each task keeps its own id — must NOT collapse to a single "" key.
        assert out.terminal_statuses == {"t1": "completed", "t2": "completed"}

    def test_wait_for_completion_captures_timeout_as_error(self, coord, basic_spec):
        from pi_harness.clawteam import ClawTeamTimeout

        handle = coord.launch(basic_spec)
        coord._clawteam_client.wait_for_completion.side_effect = ClawTeamTimeout("nope")
        coord._clawteam_client.list_tasks.return_value = []
        out = coord.wait_for_completion(handle, timeout=60)
        assert out.success is False
        assert isinstance(out.error, ClawTeamTimeout)

    def test_wait_for_completion_captures_run_failure_as_error(self, coord, basic_spec):
        from pi_harness.clawteam import ClawTeamRunFailure

        handle = coord.launch(basic_spec)
        coord._clawteam_client.wait_for_completion.side_effect = ClawTeamRunFailure("boom")
        coord._clawteam_client.list_tasks.return_value = []
        out = coord.wait_for_completion(handle, timeout=60)
        assert out.success is False
        assert isinstance(out.error, ClawTeamRunFailure)

    def test_on_completion_calls_improve_runner_once_on_success(self, coord, basic_spec):
        handle = coord.launch(basic_spec)
        coord._clawteam_client.wait_for_completion.return_value = True
        coord._clawteam_client.list_tasks.return_value = []
        coord.wait_for_completion(handle, timeout=60)
        coord.on_completion(handle)
        assert coord._improve_runner.run_for_completed_run.call_count == 1
        # Fix 2: on_completion must use the real run_for_completed_run signature:
        # run_for_completed_run(run_id: str, config, *, session_id=...)
        coord._improve_runner.run_for_completed_run.assert_called_once_with(
            handle.run_id, coord._config, session_id=handle.session_id
        )

    def test_on_completion_skipped_on_failure(self, coord, basic_spec):
        from pi_harness.clawteam import ClawTeamTimeout

        handle = coord.launch(basic_spec)
        coord._clawteam_client.wait_for_completion.side_effect = ClawTeamTimeout("nope")
        coord._clawteam_client.list_tasks.return_value = []
        coord.wait_for_completion(handle, timeout=60)
        coord.on_completion(handle)
        assert coord._improve_runner.run_for_completed_run.call_count == 0


class TestCoordinatorTeardown:
    def test_teardown_kills_session_then_cleans_up(self, coord, basic_spec):
        handle = coord.launch(basic_spec)
        client = coord._clawteam_client
        coord.teardown(handle)
        client.kill_tmux_session.assert_called_once_with(handle.team_name)
        client.cleanup_team.assert_called_once_with(handle.team_name)
        names = [c[0] for c in client.mock_calls]
        assert names.index("kill_tmux_session") < names.index("cleanup_team")

    def test_on_completion_tears_down_on_success(self, coord, basic_spec):
        handle = coord.launch(basic_spec)
        client = coord._clawteam_client
        client.wait_for_completion.return_value = True
        client.list_tasks.return_value = []
        coord.wait_for_completion(handle, timeout=60)
        coord.on_completion(handle)
        client.kill_tmux_session.assert_called_once_with(handle.team_name)
        client.cleanup_team.assert_called_once_with(handle.team_name)

    def test_on_completion_no_teardown_on_failure(self, coord, basic_spec):
        from pi_harness.clawteam import ClawTeamTimeout

        handle = coord.launch(basic_spec)
        client = coord._clawteam_client
        client.wait_for_completion.side_effect = ClawTeamTimeout("nope")
        client.list_tasks.return_value = []
        coord.wait_for_completion(handle, timeout=60)
        coord.on_completion(handle)
        client.kill_tmux_session.assert_not_called()
        client.cleanup_team.assert_not_called()


class TestCoordinatorTemplateEmission:
    def test_installs_template_before_launch(self, coord, basic_spec):
        """Coordinator must register the template via install_template before
        calling launch_team (real ClawTeam requires the template to exist on
        disk first).

        Fix 3: Assert ordering is actually verified, not just that both were called.
        """
        coord.launch(basic_spec)
        assert coord._clawteam_client.install_template.called
        assert coord._clawteam_client.launch_team.called
        # Verify actual call order: install_template must precede launch_team.
        names = [c[0] for c in coord._clawteam_client.mock_calls]
        assert names.index("install_template") < names.index("launch_team"), (
            f"install_template must be called before launch_team; call order was: {names}"
        )

    def test_seeds_task_dag_via_create_task(self, coord, basic_spec):
        """For each TaskDef returned by topology.plan, Coordinator must call
        client.create_task with the right owner + blocked_by chain."""
        coord.launch(basic_spec)
        # SequentialTopology emits len(agents) tasks; basic_spec has 2 agents.
        assert coord._clawteam_client.create_task.call_count == 2


class TestCoordinatorPrimeCall:
    """Lock in the session-aware, typed prime() call introduced in Plan 3."""

    def test_prime_called_with_token_budget_and_session(
        self, coord, mock_corpus_reader
    ):
        """prime() must receive token_budget=DEFAULT_PRIME_TOKEN_BUDGET and the
        session_id from the spec."""
        spec = RunSpec(
            goal="g",
            agents=[
                AgentSpec(name="a", role=Role.BUILDER, model_tier=ModelTier.FAST),
                AgentSpec(name="b", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
            ],
            mode=TopologyMode.SEQUENTIAL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=["foundational"],
            session_id="sess-test",
        )
        coord.launch(spec)
        kwargs = mock_corpus_reader.prime.call_args.kwargs
        assert kwargs["token_budget"] == DEFAULT_PRIME_TOKEN_BUDGET
        assert kwargs["session_id"] == "sess-test"

    def test_empty_classifications_pass_none(self, coord, mock_corpus_reader):
        """An empty corpus_classifications list must be passed as None, not [],
        so the reader returns all tiers rather than filtering everything out."""
        spec = RunSpec(
            goal="g",
            agents=[
                AgentSpec(name="a", role=Role.BUILDER, model_tier=ModelTier.FAST),
                AgentSpec(name="b", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
            ],
            mode=TopologyMode.SEQUENTIAL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
        )
        coord.launch(spec)
        kwargs = mock_corpus_reader.prime.call_args.kwargs
        assert kwargs["classifications"] is None

    def test_classifications_converted_to_enums(self, coord, mock_corpus_reader):
        """String tier names in corpus_classifications must be converted to
        Classification enum instances before being passed to prime()."""
        spec = RunSpec(
            goal="g",
            agents=[
                AgentSpec(name="a", role=Role.BUILDER, model_tier=ModelTier.FAST),
                AgentSpec(name="b", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
            ],
            mode=TopologyMode.SEQUENTIAL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=["foundational"],
        )
        coord.launch(spec)
        kwargs = mock_corpus_reader.prime.call_args.kwargs
        assert kwargs["classifications"] == [Classification.FOUNDATIONAL]

    def test_run_handle_carries_session_id(self, coord):
        """RunHandle returned by launch must carry the session_id from RunSpec."""
        spec = RunSpec(
            goal="g",
            agents=[
                AgentSpec(name="a", role=Role.BUILDER, model_tier=ModelTier.FAST),
                AgentSpec(name="b", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
            ],
            mode=TopologyMode.SEQUENTIAL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
            session_id="sess-9",
        )
        handle = coord.launch(spec)
        assert handle.session_id == "sess-9"

    def test_run_handle_session_id_none_when_not_set(self, coord, basic_spec):
        """When spec.session_id is None, handle.session_id must also be None."""
        # basic_spec has no session_id set
        handle = coord.launch(basic_spec)
        assert handle.session_id is None


class TestCoordinatorExplicitTasks:
    """RunSpec.tasks lets a caller (Plan 7's decomposer) supply the ClawTeam task
    DAG verbatim instead of having the topology generate one-task-per-agent.

    These tests build REAL RunSpec/AgentSpec/TaskDef objects — only the ClawTeam
    client is a spy — so the explicit-DAG path is verified against the actual
    Coordinator contract, not a mock that would accept any shape.
    """

    def _spec(self, *, tasks, mode=TopologyMode.SEQUENTIAL, session_id=None):
        return RunSpec(
            goal="explicit goal",
            agents=[
                AgentSpec(name="t-scout", role=Role.SCOUT, model_tier=ModelTier.FAST),
                AgentSpec(name="t-build", role=Role.BUILDER, model_tier=ModelTier.FAST),
                AgentSpec(name="t-review", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
            ],
            mode=mode,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
            session_id=session_id,
            tasks=tasks,
        )

    def _subjects(self, coord):
        return [c.kwargs["subject"] for c in coord._clawteam_client.create_task.call_args_list]

    def test_explicit_tasks_bypass_topology_plan(self, coord):
        """The caller's task_ids reach create_task verbatim — not the
        seq-NNN-<agent> ids SequentialTopology.plan would synthesize."""
        tasks = [
            TaskDef(task_id="t-scout", agent_name="t-scout", goal="survey", blocked_by=[]),
            TaskDef(task_id="t-build", agent_name="t-build", goal="implement", blocked_by=["t-scout"]),
            TaskDef(task_id="t-review", agent_name="t-review", goal="review", blocked_by=["t-build"]),
        ]
        coord.launch(self._spec(tasks=tasks))
        subjects = self._subjects(coord)
        assert subjects == ["t-scout", "t-build", "t-review"]
        assert not any(s.startswith("seq-") for s in subjects)

    def test_explicit_tasks_created_in_topological_order(self, coord):
        """Tasks supplied out of dependency order must be created with every
        dependency preceding its dependent (create_task requires the blocker to
        exist first)."""
        # Listed dependent-first to force a reorder.
        tasks = [
            TaskDef(task_id="t-review", agent_name="t-review", goal="review", blocked_by=["t-build"]),
            TaskDef(task_id="t-build", agent_name="t-build", goal="implement", blocked_by=["t-scout"]),
            TaskDef(task_id="t-scout", agent_name="t-scout", goal="survey", blocked_by=[]),
        ]
        coord.launch(self._spec(tasks=tasks))
        subjects = self._subjects(coord)
        assert subjects.index("t-scout") < subjects.index("t-build") < subjects.index("t-review")

    def test_explicit_tasks_forward_blocked_by_to_create_task(self, coord):
        tasks = [
            TaskDef(task_id="t-scout", agent_name="t-scout", goal="survey", blocked_by=[]),
            TaskDef(task_id="t-build", agent_name="t-build", goal="implement", blocked_by=["t-scout"]),
        ]
        coord.launch(self._spec(tasks=tasks))
        by_subject = {
            c.kwargs["subject"]: c.kwargs
            for c in coord._clawteam_client.create_task.call_args_list
        }
        assert by_subject["t-scout"]["blocked_by"] is None  # empty → None
        assert by_subject["t-build"]["blocked_by"] == ["t-scout"]
        assert by_subject["t-build"]["owner"] == "t-build"
        assert by_subject["t-build"]["description"] == "implement"

    def test_explicit_tasks_unknown_agent_raises(self, coord):
        tasks = [
            TaskDef(task_id="t-x", agent_name="ghost", goal="g", blocked_by=[]),
        ]
        with pytest.raises(ValueError, match="unknown agent"):
            coord.launch(self._spec(tasks=tasks))

    def test_explicit_tasks_unknown_blocked_by_raises(self, coord):
        tasks = [
            TaskDef(task_id="t-build", agent_name="t-build", goal="g", blocked_by=["t-missing"]),
        ]
        with pytest.raises(ValueError, match="unknown task"):
            coord.launch(self._spec(tasks=tasks))

    def test_explicit_tasks_cycle_raises(self, coord):
        tasks = [
            TaskDef(task_id="t-scout", agent_name="t-scout", goal="g", blocked_by=["t-build"]),
            TaskDef(task_id="t-build", agent_name="t-build", goal="g", blocked_by=["t-scout"]),
        ]
        with pytest.raises(ValueError, match="cycle"):
            coord.launch(self._spec(tasks=tasks))

    def test_explicit_tasks_persistent_requires_session(self, coord):
        """The PERSISTENT session_id invariant holds even on the explicit-DAG
        path (which never calls PersistentTopology.plan)."""
        tasks = [TaskDef(task_id="t-build", agent_name="t-build", goal="g", blocked_by=[])]
        with pytest.raises(ValueError, match="session_id"):
            coord.launch(self._spec(tasks=tasks, mode=TopologyMode.PERSISTENT, session_id=None))

    def test_explicit_tasks_persistent_ok_with_session(self, coord):
        tasks = [TaskDef(task_id="t-build", agent_name="t-build", goal="g", blocked_by=[])]
        handle = coord.launch(
            self._spec(tasks=tasks, mode=TopologyMode.PERSISTENT, session_id="sess-x")
        )
        assert handle.session_id == "sess-x"
        assert self._subjects(coord) == ["t-build"]

    def test_empty_explicit_tasks_seeds_nothing(self, coord):
        """An explicit empty list is honored as 'no tasks' (distinct from None,
        which would fall back to topology.plan)."""
        coord.launch(self._spec(tasks=[]))
        assert coord._clawteam_client.create_task.call_count == 0


class TestCoordinatorRunRegistry:
    def test_launch_registers_run(self, coord, basic_spec):
        from pi_harness.trajectory.runs import get_run
        from pi_harness.topology.runspec_codec import runspec_from_json

        handle = coord.launch(basic_spec)
        row = get_run(handle.run_id, db_path=coord._config.trajectory_db_path)
        assert row is not None
        assert row["status"] == "running"
        assert row["topology"] == "sequential"
        assert row["team_name"] == handle.team_name
        assert row["run_spec_json"]  # non-empty serialized RunSpec
        restored = runspec_from_json(row["run_spec_json"])
        assert restored.goal == basic_spec.goal
        assert restored.mode == basic_spec.mode
        assert {a.name for a in restored.agents} == {"a", "b"}

    def test_wait_for_completion_marks_succeeded(self, coord, basic_spec):
        from pi_harness.trajectory.runs import get_run

        handle = coord.launch(basic_spec)
        coord._clawteam_client.wait_for_completion.return_value = True
        coord._clawteam_client.list_tasks.return_value = [{"id": "t1", "status": "completed"}]
        coord.wait_for_completion(handle, timeout=60)
        row = get_run(handle.run_id, db_path=coord._config.trajectory_db_path)
        assert row["status"] == "succeeded"
        assert row["ended_at"] is not None

    def test_wait_for_completion_marks_failed_on_timeout(self, coord, basic_spec):
        from pi_harness.clawteam import ClawTeamTimeout
        from pi_harness.trajectory.runs import get_run

        handle = coord.launch(basic_spec)
        coord._clawteam_client.wait_for_completion.side_effect = ClawTeamTimeout("nope")
        coord._clawteam_client.list_tasks.return_value = []
        coord.wait_for_completion(handle, timeout=60)
        row = get_run(handle.run_id, db_path=coord._config.trajectory_db_path)
        assert row["status"] == "failed"


class TestCoordinatorTrajectoryCapture:
    def test_launch_initializes_trajectory_db(self, coord, basic_spec):
        coord.launch(basic_spec)
        assert coord._config.trajectory_db_path.exists()

    def test_wait_for_completion_captures_task_transitions(self, coord, basic_spec):
        from pi_harness.trajectory.store import query_events

        handle = coord.launch(basic_spec)
        client = coord._clawteam_client

        def fake_wait(team_name, timeout, poll_interval=5.0, on_poll=None):
            on_poll([{"task_id": "t1", "owner": "a", "status": "pending"}])
            on_poll([{"task_id": "t1", "owner": "a", "status": "completed"}])
            return True

        client.wait_for_completion.side_effect = fake_wait
        client.list_tasks.return_value = [{"id": "t1", "status": "completed"}]

        result = coord.wait_for_completion(handle, timeout=60)
        assert result.success is True

        events = query_events(
            run_id=handle.run_id, db_path=coord._config.trajectory_db_path
        )
        statuses = [
            e.output["status"] for e in events if e.classification == "task_transition"
        ]
        assert "pending" in statuses
        assert "completed" in statuses
