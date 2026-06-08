"""Tests for the spec -> RunSpec bridge.

The headline test (test_runspec_consumable_by_real_coordinator) launches the
bridge's output through a REAL Coordinator with only the ClawTeam client /
corpus reader / improve runner mocked. This is deliberate: a pure-MagicMock
coordinator would accept any object shape and hide field/enum/signature drift
between the spec layer and Plan 5 — the exact failure mode this plan exists to
avoid.
"""
from __future__ import annotations

import tomllib
from unittest.mock import MagicMock

import pytest

from pi_harness.spec.decomposer import DecomposedTask
from pi_harness.spec.format import Spec
from pi_harness.spec.runspec import build_coordinator, spec_to_runspec
from pi_harness.topology.base import (
    AgentSpec,
    ModelTier,
    Role,
    RunSpec,
    SyncMode,
    TaskDef,
    TopologyMode,
)
from pi_harness.topology.coordinator import Coordinator


def _spec(**ov) -> Spec:
    d = dict(
        id="spec-cancel",
        title="Cancel button",
        goal="Users can cancel an in-flight upload",
        acceptance_criteria=["Clicking Cancel aborts within 200ms", "No partial file remains"],
        constraints=[],
        non_goals=["Resuming after cancel"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=1.0,
        status="decomposed",
    )
    d.update(ov)
    return Spec(**d)


def _tasks() -> list[DecomposedTask]:
    return [
        DecomposedTask(
            id="t-lead", name="Coordinate", description="lead the team",
            acceptance_criterion="", blocked_by=[], assigned_role="orchestrator",
        ),
        DecomposedTask(
            id="t-cancel", name="Cancel", description="wire cancel button",
            acceptance_criterion="Clicking Cancel aborts within 200ms",
            blocked_by=["t-lead"], assigned_role="builder",
        ),
        DecomposedTask(
            id="t-cleanup", name="Cleanup", description="delete partial file",
            acceptance_criterion="No partial file remains",
            blocked_by=["t-cancel"], assigned_role="builder",
        ),
    ]


def test_bridge_builds_real_runspec() -> None:
    rs = spec_to_runspec(_spec(), _tasks())
    assert isinstance(rs, RunSpec)
    assert rs.goal == "Users can cancel an in-flight upload"
    assert rs.mode is TopologyMode.SEQUENTIAL
    assert rs.sync_mode is SyncMode.PER_AGENT
    assert rs.executor == "pi"

    # One agent per ROLE (not per task): the two builder tasks collapse onto a
    # single builder agent so they share one ClawTeam worktree.
    assert [a.name for a in rs.agents] == ["orchestrator", "builder"]
    assert all(isinstance(a, AgentSpec) for a in rs.agents)
    lead = rs.agents[0]
    assert lead.role is Role.ORCHESTRATOR
    assert lead.model_tier is ModelTier.REASONING
    assert lead.task_prompt == "lead the team"  # sole orchestrator task → its description
    builder = rs.agents[1]
    assert builder.role is Role.BUILDER
    assert builder.model_tier is ModelTier.FAST
    # The builder owns both tasks; its standing prompt enumerates them in order.
    assert builder.task_prompt is not None
    assert "wire cancel button" in builder.task_prompt
    assert "delete partial file" in builder.task_prompt

    assert all(isinstance(t, TaskDef) for t in rs.tasks)
    by = {t.task_id: t for t in rs.tasks}
    assert by["t-cancel"].blocked_by == ["t-lead"]
    assert by["t-cancel"].agent_name == "builder"  # owned by the role agent, not a per-task agent
    assert by["t-cleanup"].agent_name == "builder"
    assert by["t-cancel"].goal == "wire cancel button"


def test_same_role_tasks_collapse_to_one_agent() -> None:
    """Dependent same-role tasks must share ONE agent so they share ONE ClawTeam
    worktree — otherwise a 'create file → use it → test it' chain fails because
    each task ran in an isolated worktree (the bug a local e2e run surfaced)."""
    rs = spec_to_runspec(_spec(), _tasks())
    builders = [a for a in rs.agents if a.role is Role.BUILDER]
    assert len(builders) == 1
    owners = {t.agent_name for t in rs.tasks if t.task_id in ("t-cancel", "t-cleanup")}
    assert owners == {builders[0].name}
    # Total agents == distinct roles, not number of tasks.
    assert len(rs.agents) == 2


def test_bridge_overrides_win_over_spec_fields() -> None:
    rs = spec_to_runspec(
        _spec(session_id="sess-spec", executor="pi", sync_profile=None),
        _tasks(),
        session_id="sess-override",
        executor="codex",
        sync_profile="pi-openai-fast",
    )
    assert rs.session_id == "sess-override"
    assert rs.executor == "codex"
    assert rs.sync_profile == "pi-openai-fast"


def test_bridge_falls_back_to_spec_fields() -> None:
    rs = spec_to_runspec(
        _spec(session_id="sess-spec", executor="codex", sync_profile="x", corpus_classifications=["tactical"])
    , _tasks())
    assert rs.session_id == "sess-spec"
    assert rs.executor == "codex"
    assert rs.sync_profile == "x"
    assert rs.corpus_classifications == ["tactical"]


def test_bridge_invalid_topology_raises() -> None:
    with pytest.raises(ValueError):
        spec_to_runspec(_spec(topology="bogus"), _tasks())


def test_bridge_invalid_sync_mode_raises() -> None:
    with pytest.raises(ValueError):
        spec_to_runspec(_spec(sync_mode="bogus"), _tasks())


def test_runspec_consumable_by_real_coordinator(tmp_path) -> None:
    rs = spec_to_runspec(_spec(), _tasks())

    client = MagicMock()
    reader = MagicMock()
    reader.prime.return_value = []
    improve = MagicMock()
    cfg = MagicMock()
    cfg.trajectory_db_path = tmp_path / "trajectory.db"
    cfg.reasoning_model = "gpt-5"
    cfg.fast_model = "gpt-5-mini"
    coord = Coordinator(
        config=cfg,
        clawteam_client=client,
        corpus_reader=reader,
        improve_runner=improve,
    )

    handle = coord.launch(rs)

    assert handle.topology is TopologyMode.SEQUENTIAL
    # Tasks seeded once each, in topological order.
    subjects = [c.kwargs["subject"] for c in client.create_task.call_args_list]
    assert subjects == ["t-lead", "t-cancel", "t-cleanup"]
    # blocked_by carried through verbatim.
    by_subject = {c.kwargs["subject"]: c.kwargs for c in client.create_task.call_args_list}
    assert by_subject["t-cancel"]["blocked_by"] == ["t-lead"]
    # The orchestrator task became the ClawTeam leader.
    install_toml = client.install_template.call_args.args[1]
    parsed = tomllib.loads(install_toml)
    assert parsed["template"]["leader"]["name"] == "orchestrator"
    assert parsed["template"]["leader"]["type"] == "orchestrator"
    worker_names = {a["name"] for a in parsed["template"]["agents"]}
    assert worker_names == {"builder"}


def test_build_coordinator_wires_real_components(tmp_path) -> None:
    """build_coordinator must hand the Coordinator a real ClawTeamClient,
    CorpusReader, and the improve runner module (whose run_for_completed_run
    signature matches Coordinator.on_completion's call)."""
    from pi_harness.clawteam import ClawTeamClient
    from pi_harness.corpus.reader import CorpusReader
    from pi_harness.improve import runner as improve_runner
    from pi_harness.topology.coordinator import Coordinator

    cfg = MagicMock()
    cfg.corpus_root = tmp_path / "corpus"
    coord = build_coordinator(cfg)

    assert isinstance(coord, Coordinator)
    assert isinstance(coord._clawteam_client, ClawTeamClient)
    assert isinstance(coord._corpus_reader, CorpusReader)
    assert coord._improve_runner is improve_runner
    assert hasattr(coord._improve_runner, "run_for_completed_run")
