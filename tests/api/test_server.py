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


def test_cors_allows_loopback_ip_origin_by_default(client):
    """`localhost` and `127.0.0.1` are the same machine, but browsers treat
    them as distinct origins. The default allowlist must accept both so a user
    browsing the dashboard at either name reaches the backend."""
    r = client.get("/healthz", headers={"Origin": "http://127.0.0.1:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"


def test_cors_env_var_parses_comma_separated_origins(monkeypatch):
    """PI_HARNESS_FRONTEND_ORIGIN accepts a comma-separated list so deployments
    can register multiple origins (staging + prod, or localhost + a tunnel)
    without needing a new env var."""
    monkeypatch.setenv(
        "PI_HARNESS_FRONTEND_ORIGIN",
        "https://a.example.com, https://b.example.com",
    )
    from pi_harness.api.server import load_dashboard_config

    dash = load_dashboard_config()
    assert "https://a.example.com" in dash.frontend_origins
    assert "https://b.example.com" in dash.frontend_origins
