"""Tests for the /settings/models API: GET, PUT, and local-model discovery.

Integration tests against the real dashboard app (no mocks for the harness
internals — mocking is what hides API drift). External HTTP for the
discovery endpoint is monkeypatched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def settings_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    return tmp_path


def test_get_settings_returns_defaults_on_fresh_install(client, settings_home):
    r = client.get("/settings/models")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["orchestrator"] == {"provider": "api", "model": "gpt-5"}
    assert body["builder"] == {"provider": "api", "model": "gpt-5-mini"}
    assert body["local_base_url"] == "http://localhost:11434/v1"


def test_put_settings_persists_and_returns_current(client, settings_home):
    r = client.put("/settings/models", json={
        "orchestrator": {"provider": "local", "model": "qwen3:30b"},
        "builder": {"provider": "api", "model": "gpt-5-mini"},
        "local_base_url": "http://localhost:11434/v1",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["orchestrator"]["model"] == "qwen3:30b"

    # GET reflects the saved state.
    r2 = client.get("/settings/models")
    assert r2.json()["orchestrator"]["model"] == "qwen3:30b"


def test_put_settings_with_local_registers_pi_provider(client, settings_home, tmp_path, monkeypatch):
    """PUT must side-effect pi's models.json so a subsequent
    ``pi --provider harness-local --model <id>`` actually works. Without
    this, the picker is a lie — pi will refuse the provider name."""
    fake_pi_models = tmp_path / "pi-agent" / "models.json"
    monkeypatch.setattr(
        "pi_harness.pi_models.DEFAULT_PI_MODELS_PATH",
        lambda: fake_pi_models,
    )

    client.put("/settings/models", json={
        "orchestrator": {"provider": "local", "model": "qwen3:30b"},
        "builder": {"provider": "local", "model": "qwen2.5-coder:7b"},
        "local_base_url": "http://localhost:11434/v1",
    })

    assert fake_pi_models.exists()
    data = json.loads(fake_pi_models.read_text())
    assert "harness-local" in data["providers"]
    p = data["providers"]["harness-local"]
    assert p["baseUrl"] == "http://localhost:11434/v1"
    ids = {m["id"] for m in p["models"]}
    assert {"qwen3:30b", "qwen2.5-coder:7b"} <= ids


def test_put_settings_api_only_does_not_touch_pi_models(client, settings_home, tmp_path, monkeypatch):
    """If both buckets are 'api', the harness has no business writing to
    pi's models.json. Leave it untouched."""
    fake_pi_models = tmp_path / "pi-agent" / "models.json"
    monkeypatch.setattr(
        "pi_harness.pi_models.DEFAULT_PI_MODELS_PATH",
        lambda: fake_pi_models,
    )

    client.put("/settings/models", json={
        "orchestrator": {"provider": "api", "model": "gpt-5"},
        "builder": {"provider": "api", "model": "gpt-5-mini"},
        "local_base_url": "http://localhost:11434/v1",
    })

    assert not fake_pi_models.exists()


def test_put_settings_rejects_invalid_provider(client, settings_home):
    r = client.put("/settings/models", json={
        "orchestrator": {"provider": "bogus", "model": "x"},
        "builder": {"provider": "api", "model": "gpt-5-mini"},
        "local_base_url": "http://localhost:11434/v1",
    })
    assert r.status_code == 422 or r.status_code == 400


def test_local_models_discovers_models_from_local_server(client, monkeypatch):
    """The /local-models endpoint queries the user's local OpenAI-compatible
    server's /v1/models and returns the list. Mocked here so the test is
    hermetic."""
    import httpx

    captured: dict = {}

    def fake_get(url, *args, **kwargs):
        captured["url"] = url

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                # Ollama-style /v1/models response: OpenAI list shape.
                return {
                    "object": "list",
                    "data": [
                        {"id": "qwen2.5-coder:7b", "object": "model"},
                        {"id": "llama3.3:70b", "object": "model"},
                    ],
                }

        return _Resp()

    monkeypatch.setattr(httpx, "get", fake_get)

    r = client.get("/settings/models/local-models?base_url=http://localhost:11434/v1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert captured["url"].rstrip("/").endswith("/v1/models")
    assert "qwen2.5-coder:7b" in body["models"]
    assert "llama3.3:70b" in body["models"]


def test_local_models_returns_empty_when_server_unreachable(client, monkeypatch):
    """The user might click Discover before starting their local server.
    Surface that as an empty list + a hint, not a 500."""
    import httpx

    def fake_get(url, *args, **kwargs):
        raise httpx.ConnectError("not running")

    monkeypatch.setattr(httpx, "get", fake_get)

    r = client.get("/settings/models/local-models?base_url=http://localhost:11434/v1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["models"] == []
    assert "error" in body  # Some user-facing message.


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254/v1",  # cloud metadata (link-local)
        "http://8.8.8.8/v1",          # public / global
        "ftp://localhost/v1",         # wrong scheme
        "http://[::ffff:169.254.169.254]/v1",  # IPv4-mapped metadata (must unwrap)
        "http://[::ffff:8.8.8.8]/v1",          # IPv4-mapped public (must unwrap)
    ],
)
def test_local_models_rejects_ssrf_targets(client, bad_url):
    """Discover must refuse non-loopback/private targets (SSRF), audit #6.
    (IP literals + bad scheme — no real DNS lookups.)"""
    r = client.get("/settings/models/local-models", params={"base_url": bad_url})
    assert r.status_code == 400, r.text


def test_put_settings_local_rejects_ssrf_url(client, settings_home):
    """A local provider with an SSRF-able base_url is rejected and NOT persisted
    (audit #23)."""
    r = client.put("/settings/models", json={
        "orchestrator": {"provider": "local", "model": "m"},
        "builder": {"provider": "api", "model": "gpt-5-mini"},
        "local_base_url": "http://169.254.169.254/v1",
    })
    assert r.status_code == 400, r.text
