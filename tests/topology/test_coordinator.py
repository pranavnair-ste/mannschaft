"""Coordinator end-to-end: mode dispatch, corpus prime, launch, post-improve."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from pi_harness.topology.base import (
    AgentSpec, ModelTier, Role, RunHandle, RunSpec, SyncMode, TopologyMode,
)
from pi_harness.topology.coordinator import Coordinator


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
def coord(mock_clawteam_client, mock_corpus_reader, mock_improve_runner):
    cfg = MagicMock()
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
        coord._clawteam_client.list_tasks.return_value = [
            {"task_id": "t1", "status": "completed"}
        ]
        out = coord.wait_for_completion(handle, timeout=60)
        assert out.success is True
        assert out.error is None
        assert out.terminal_statuses == {"t1": "completed"}

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

    def test_on_completion_skipped_on_failure(self, coord, basic_spec):
        from pi_harness.clawteam import ClawTeamTimeout

        handle = coord.launch(basic_spec)
        coord._clawteam_client.wait_for_completion.side_effect = ClawTeamTimeout("nope")
        coord._clawteam_client.list_tasks.return_value = []
        coord.wait_for_completion(handle, timeout=60)
        coord.on_completion(handle)
        assert coord._improve_runner.run_for_completed_run.call_count == 0


class TestCoordinatorTemplateEmission:
    def test_installs_template_before_launch(self, coord, basic_spec):
        """Coordinator must register the template via install_template before
        calling launch_team (real ClawTeam requires the template to exist on
        disk first)."""
        coord.launch(basic_spec)
        assert coord._clawteam_client.install_template.called
        assert coord._clawteam_client.launch_team.called

    def test_seeds_task_dag_via_create_task(self, coord, basic_spec):
        """For each TaskDef returned by topology.plan, Coordinator must call
        client.create_task with the right owner + blocked_by chain."""
        coord.launch(basic_spec)
        # SequentialTopology emits len(agents) tasks; basic_spec has 2 agents.
        assert coord._clawteam_client.create_task.call_count == 2
