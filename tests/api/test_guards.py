from __future__ import annotations

from datetime import datetime, timezone


def _seed_sensor_fires(cfg, n=20, *, sensor="JudgeAgentSensor", criterion="is the code correct", allow=True):
    from pi_harness.trajectory.schema import TrajectoryEvent
    from pi_harness.trajectory.store import init_db, write_event

    init_db(cfg.trajectory_db_path)
    for i in range(n):
        write_event(
            TrajectoryEvent(
                run_id="r-1", agent_id="reviewer-1", step_id=f"s-{i}",
                ts=datetime(2026, 5, 28, 10, i % 60, tzinfo=timezone.utc), model="",
                tool="judge", input={},
                output={
                    "_guard_meta": {
                        "sensor": sensor,
                        "sensor_kind": "inferential_sensor",
                        "allow": allow,
                        "reason": "looks correct",
                        "guard_metadata": {"criterion": criterion},
                    }
                },
                duration_ms=0, tokens_in=0, tokens_out=0, outcome="success",
                classification="sensor_fired",
            ),
            db_path=cfg.trajectory_db_path,
        )


def test_promotion_candidates_returns_suggested_list(client, cfg):
    _seed_sensor_fires(cfg, n=25)
    r = client.get("/guards/promotion-candidates")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    cand = body[0]
    assert cand["sensor_name"] == "JudgeAgentSensor"
    assert cand["fires"] == 25
    assert cand["allow_fraction"] == 1.0
    assert "suggested_stub_code" in cand


def test_promotion_candidates_empty_when_below_threshold(client, cfg):
    _seed_sensor_fires(cfg, n=5)  # below default min_fires=20
    r = client.get("/guards/promotion-candidates")
    assert r.status_code == 200
    assert r.json() == []
