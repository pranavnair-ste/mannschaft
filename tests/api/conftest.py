"""Shared API test fixtures.

Seeds REAL temp stores (SQLite trajectory db + on-disk corpus/spec files) and
builds the real FastAPI app. No upstream pi_harness modules are mocked -- that
is deliberate: mocking is what hid the API drift the adapted plan exists to fix.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cfg(tmp_path: Path):
    """Real Config pointing at temp stores. Seeds nothing -- tests seed what they need."""
    corpus = tmp_path / "corpus"
    for sub in ("foundational", "tactical", "observational"):
        (corpus / sub).mkdir(parents=True)
    (corpus / "archived").mkdir(parents=True)
    from pi_harness.config import Config

    return Config(
        openai_api_key="test-key",
        reasoning_model="gpt-5",
        fast_model="gpt-5-mini",
        clawteam_state_dir=tmp_path / "clawteam",
        corpus_root=corpus,
        trajectory_db_path=tmp_path / "traj.db",
    )


@pytest.fixture
def client(cfg) -> TestClient:
    from pi_harness.api.server import DashboardConfig, create_app

    app = create_app(cfg, DashboardConfig())
    return TestClient(app)


@pytest.fixture
def seed_run(cfg):
    """Register a run + write events into the real temp db. Returns a callable."""
    from pi_harness.trajectory.runs import register_run
    from pi_harness.trajectory.schema import TrajectoryEvent
    from pi_harness.trajectory.store import write_event

    def _seed(run_id: str = "r-1", status: str = "succeeded", topology: str = "sequential") -> str:
        register_run(
            run_id=run_id,
            spec_id="spec-1",
            topology=topology,
            sync_mode="per_agent",
            session_id=None,
            goal="demo",
            team_name="team-1",
            started_at=datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc),
            run_spec_json="{}",
            status=status,
            db_path=cfg.trajectory_db_path,
        )
        write_event(
            TrajectoryEvent(
                run_id=run_id, agent_id="builder-1", step_id="s-1",
                ts=datetime(2026, 5, 28, 10, 0, 1, tzinfo=timezone.utc), model="gpt-5-mini",
                tool="edit_file", input={}, output={}, duration_ms=1200, tokens_in=400,
                tokens_out=200, outcome="success", classification="tool_call",
            ),
            db_path=cfg.trajectory_db_path,
        )
        write_event(
            TrajectoryEvent(
                run_id=run_id, agent_id="builder-1", step_id="s-1",
                ts=datetime(2026, 5, 28, 10, 0, 2, tzinfo=timezone.utc), model="",
                tool="edit_file", input={},
                output={"_guard_meta": {"guide": "AllowlistGuide", "allow": True, "reason": "ok"}},
                duration_ms=0, tokens_in=0, tokens_out=0, outcome="success",
                classification="guide_fired",
            ),
            db_path=cfg.trajectory_db_path,
        )
        return run_id

    return _seed
