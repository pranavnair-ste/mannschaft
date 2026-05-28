from __future__ import annotations

from datetime import datetime, timezone


def _write(cfg, run_id, agent, step, ts, classification="tool_call"):
    from pi_harness.trajectory.schema import TrajectoryEvent
    from pi_harness.trajectory.store import write_event

    write_event(
        TrajectoryEvent(
            run_id=run_id, agent_id=agent, step_id=step, ts=ts, model="gpt-5-mini",
            tool="edit", input={}, output={}, duration_ms=1, tokens_in=0, tokens_out=0,
            outcome="success", classification=classification,
        ),
        db_path=cfg.trajectory_db_path,
    )


def test_timeline_groups_events_by_agent(client, cfg, seed_run):
    seed_run("r-1")  # builder-1 with 2 events
    _write(cfg, "r-1", "reviewer-1", "s-9", datetime(2026, 5, 28, 10, 5, tzinfo=timezone.utc))
    r = client.get("/runs/r-1/timeline")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "r-1"
    agent_ids = [row["agent_id"] for row in body["agents"]]
    # builder-1's first event is earlier than reviewer-1's, so it comes first
    assert agent_ids == ["builder-1", "reviewer-1"]


def test_timeline_includes_firing_events(client, seed_run):
    seed_run("r-1")
    r = client.get("/runs/r-1/timeline")
    builder = next(row for row in r.json()["agents"] if row["agent_id"] == "builder-1")
    classifications = {e["classification"] for e in builder["events"]}
    assert "guide_fired" in classifications


def test_timeline_404_unknown(client):
    assert client.get("/runs/r-nope/timeline").status_code == 404
