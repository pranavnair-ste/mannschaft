"""Playwright fixture launcher: seeds an ISOLATED temp store, then runs the API.

Run via ``python -m pi_harness.api._fixtures`` (see ui/playwright.config.ts).
Uses a fresh temp dir so the e2e suite never touches the user's real
~/.pi-harness, and a no-op coordinator so the Branch button doesn't launch a
real ClawTeam team (no tmux, no credit).
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _seed(config) -> None:
    from pi_harness.topology.base import (
        AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
    )
    from pi_harness.topology.runspec_codec import runspec_to_json
    from pi_harness.trajectory.runs import register_run
    from pi_harness.trajectory.schema import TrajectoryEvent
    from pi_harness.trajectory.store import write_event

    spec = RunSpec(
        goal="fixture goal",
        agents=[
            AgentSpec(name="builder-1", role=Role.BUILDER, model_tier=ModelTier.FAST),
            AgentSpec(name="reviewer-1", role=Role.REVIEWER, model_tier=ModelTier.REASONING),
        ],
        mode=TopologyMode.SEQUENTIAL,
        sync_mode=SyncMode.PER_AGENT,
        corpus_classifications=[],
    )
    register_run(
        run_id="r-fixture-1", spec_id=None, topology="sequential", sync_mode="per_agent",
        session_id=None, goal="fixture goal", team_name="fixture-team",
        started_at=datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc),
        run_spec_json=runspec_to_json(spec), status="succeeded",
        db_path=config.trajectory_db_path,
    )
    write_event(
        TrajectoryEvent(
            run_id="r-fixture-1", agent_id="builder-1", step_id="s-1",
            ts=datetime(2026, 5, 28, 10, 0, 1, tzinfo=timezone.utc), model="gpt-5-mini",
            tool="edit_file", input={}, output={}, duration_ms=1200, tokens_in=400,
            tokens_out=200, outcome="success", classification="tool_call",
        ),
        db_path=config.trajectory_db_path,
    )
    write_event(
        TrajectoryEvent(
            run_id="r-fixture-1", agent_id="builder-1", step_id="s-1",
            ts=datetime(2026, 5, 28, 10, 0, 2, tzinfo=timezone.utc), model="",
            tool="edit_file", input={},
            output={"_guard_meta": {"guide": "AllowlistGuide", "allow": True, "reason": "ok"}},
            duration_ms=0, tokens_in=0, tokens_out=0, outcome="success",
            classification="guide_fired",
        ),
        db_path=config.trajectory_db_path,
    )


class _NoopClawTeam:
    def register_profile(self, *a, **k):
        return None

    def install_template(self, *a, **k):
        return None

    def launch_team(self, *a, **k):
        return None

    def create_task(self, *a, **k):
        return None


class _NoopReader:
    def prime(self, *a, **k):
        return []


def _fake_coordinator_factory(config):
    from pi_harness.topology.coordinator import Coordinator

    return Coordinator(
        config=config,
        clawteam_client=_NoopClawTeam(),
        corpus_reader=_NoopReader(),
        improve_runner=None,
    )


def main() -> None:
    import uvicorn

    from pi_harness.api.server import DashboardConfig, create_app
    from pi_harness.config import Config

    tmp = Path(tempfile.mkdtemp(prefix="pi-harness-e2e-"))
    corpus = tmp / "corpus"
    for sub in ("foundational", "tactical", "observational", "archived"):
        (corpus / sub).mkdir(parents=True)
    config = Config(
        openai_api_key="test", reasoning_model="gpt-5", fast_model="gpt-5-mini",
        clawteam_state_dir=tmp / "clawteam", corpus_root=corpus,
        trajectory_db_path=tmp / "traj.db",
        obs_enabled=False, obs_host="127.0.0.1", obs_port=43190,
        obs_auth_token="", obs_fork_dir=tmp / "obs-fork", obs_fork_ref="v0.3.0",
    )
    _seed(config)
    app = create_app(config, DashboardConfig())
    app.state.coordinator_factory = _fake_coordinator_factory
    port = int(os.environ.get("PI_HARNESS_API_PORT", "8800"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
