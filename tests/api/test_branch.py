from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock


def _register_real_parent(cfg, run_id="parent-1"):
    """Register a parent run with a REAL serialized RunSpec so branch can reload it."""
    from pi_harness.topology.base import (
        AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
    )
    from pi_harness.topology.runspec_codec import runspec_to_json
    from pi_harness.trajectory.runs import register_run

    spec = RunSpec(
        goal="parent goal",
        agents=[
            AgentSpec(name="a", role=Role.BUILDER, model_tier=ModelTier.FAST),
            AgentSpec(name="b", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
        ],
        mode=TopologyMode.SEQUENTIAL,
        sync_mode=SyncMode.PER_AGENT,
        corpus_classifications=[],
    )
    register_run(
        run_id=run_id, spec_id="spec-1", topology="sequential", sync_mode="per_agent",
        session_id=None, goal="parent goal", team_name="pt",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        run_spec_json=runspec_to_json(spec), status="succeeded", db_path=cfg.trajectory_db_path,
    )
    return run_id


def _inject_fake_coordinator(client):
    """Override the coordinator factory with one whose ClawTeam boundary is faked.

    Branch logic + the run registry remain real; only the ClawTeam/tmux + corpus
    + improve boundaries are mocked (matching the topology test fixtures).
    """
    from pi_harness.topology.coordinator import Coordinator

    client.app.state.coordinator_factory = lambda cfg: Coordinator(
        config=cfg,
        clawteam_client=MagicMock(),
        corpus_reader=MagicMock(),
        improve_runner=MagicMock(),
    )


def test_branch_returns_child_with_lineage(client, cfg):
    _inject_fake_coordinator(client)
    parent = _register_real_parent(cfg)
    r = client.post(
        f"/runs/{parent}/branch",
        json={"step_id": "s-1", "overrides": {"model_tier": "reasoning"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["parent_run_id"] == parent
    assert body["branched_from_step"] == "s-1"
    assert body["run_id"] != parent

    # the child run is registered with lineage
    from pi_harness.trajectory.runs import get_run

    child = get_run(body["run_id"], db_path=cfg.trajectory_db_path)
    assert child["parent_run_id"] == parent
    assert child["overrides"] == {"model_tier": "reasoning"}


def test_branch_404_unknown_parent(client):
    _inject_fake_coordinator(client)
    r = client.post("/runs/ghost/branch", json={"step_id": "s-1"})
    assert r.status_code == 404


def test_branch_422_missing_step_id(client):
    r = client.post("/runs/whatever/branch", json={})
    assert r.status_code == 422
