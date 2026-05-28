from __future__ import annotations


def test_list_runs_returns_summaries(client, seed_run):
    seed_run("r-1", status="succeeded")
    r = client.get("/runs")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    row = body[0]
    assert row["run_id"] == "r-1"
    assert row["agent_count"] == 1
    assert row["total_cost_usd"] > 0  # 400 in / 200 out @ gpt-5-mini
    assert row["topology"] == "sequential"


def test_list_runs_filter_by_status(client, seed_run):
    seed_run("r-1", status="succeeded")
    seed_run("r-2", status="running")
    r = client.get("/runs", params={"status": "running"})
    assert r.status_code == 200
    assert [row["run_id"] for row in r.json()] == ["r-2"]


def test_list_runs_limit(client, seed_run):
    seed_run("r-1")
    seed_run("r-2")
    r = client.get("/runs", params={"limit": 1})
    assert len(r.json()) == 1


def test_get_run_detail_returns_summary_and_events(client, seed_run):
    seed_run("r-1")
    r = client.get("/runs/r-1")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["run_id"] == "r-1"
    assert len(body["events"]) == 2
    classifications = {e["classification"] for e in body["events"]}
    assert classifications == {"tool_call", "guide_fired"}


def test_get_run_detail_404_unknown(client):
    r = client.get("/runs/r-nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "run not found"}
