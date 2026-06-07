import pytest
from datetime import datetime, timezone

from pi_harness.observability import bridge
from pi_harness.trajectory import store, runs
from pi_harness.trajectory.schema import TrajectoryEvent


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    store.init_db(p)
    runs.register_run(run_id="r1", spec_id=None, topology="pipeline", sync_mode=None,
                      session_id=None, goal=None, team_name="team-a",
                      started_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
                      run_spec_json="{}", db_path=p)
    return p


def _msg(step):
    return TrajectoryEvent(run_id="r1", agent_id="a1", step_id=step,
                           ts=datetime(2026, 6, 7, tzinfo=timezone.utc), model="gpt", tool="",
                           input={}, output={"text": f"hi {step}"}, duration_ms=0,
                           tokens_in=1, tokens_out=1, outcome="success", classification="message")


def test_tail_once_ships_only_new(monkeypatch, db):
    posted = []
    monkeypatch.setattr(bridge, "post_events_with_retry",
                        lambda envs, url, token, **k: posted.extend(envs) or {"ingested": len(envs), "rejected": []})
    store.write_event(_msg("s1"), db_path=db)
    n1 = bridge.tail_once("r1", 0, url="http://x", token="t", db_path=db)
    assert n1 > 0 and len(posted) == n1
    first = list(posted)
    posted.clear()
    store.write_event(_msg("s2"), db_path=db)
    n2 = bridge.tail_once("r1", n1, url="http://x", token="t", db_path=db)
    assert n2 > n1
    # only the NEW tail shipped, and no event_id overlaps the first batch
    new_ids = {e["event_id"] for e in posted}
    assert new_ids.isdisjoint({e["event_id"] for e in first})
    assert len(posted) == n2 - n1


def test_follow_runs_stops_on_terminal(monkeypatch, db):
    posted = []
    monkeypatch.setattr(bridge, "post_events_with_retry",
                        lambda envs, url, token, **k: posted.extend(envs) or {"ingested": len(envs), "rejected": []})
    store.write_event(_msg("s1"), db_path=db)
    runs.mark_run_status("r1", "succeeded", db_path=db)
    polls = {"n": 0}

    def stop():
        polls["n"] += 1
        return polls["n"] >= 3

    bridge.follow_runs(url="http://x", token="t", db_path=db, poll_interval=0.0, sleep=lambda s: None, stop=stop)
    assert len(posted) > 0  # terminal run still drained once


def test_follow_runs_survives_a_failing_tail(monkeypatch, db):
    """A transient per-run failure (e.g. the fork not up yet at launch) must not
    kill the daemon — it logs and retries on the next poll, eventually shipping."""
    import urllib.error

    store.write_event(_msg("s1"), db_path=db)
    calls = {"n": 0}
    posted = []

    def flaky(envs, url, token, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("fork not up yet")
        posted.extend(envs)
        return {"ingested": len(envs), "rejected": []}

    monkeypatch.setattr(bridge, "post_events_with_retry", flaky)
    polls = {"n": 0}

    def stop():
        polls["n"] += 1
        return polls["n"] >= 3  # poll 1 raises (swallowed), poll 2 ships, poll 3 stops

    bridge.follow_runs(url="http://x", token="t", db_path=db, poll_interval=0.0, sleep=lambda s: None, stop=stop)
    assert calls["n"] >= 2 and len(posted) > 0  # survived the failure and shipped on retry
