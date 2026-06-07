"""Deep-link endpoint: GET /observability/link.

Builds a runtime-resolved tokenized deep-link into the fork observability UI
from app.state.config (obs_server_url / obs_auth_token / obs_enabled).
"""
from __future__ import annotations


def test_observability_link(client):  # `client` from tests/api/conftest.py
    r = client.get("/observability/link", params={"run_id": "run-xyz"})
    assert r.status_code == 200
    body = r.json()
    assert body["base"].startswith("http")
    assert "pool=run-xyz" in body["url"]
    assert "#view=race" in body["url"]
