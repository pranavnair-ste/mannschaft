from __future__ import annotations


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_lists_specs_route(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/specs" in paths


def test_openapi_lists_runs_route(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/runs" in paths


def test_cors_allows_frontend_origin(client):
    r = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
