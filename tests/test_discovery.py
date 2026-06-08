"""Tests for model discovery (local OpenAI-compatible + OpenAI cloud)."""
from __future__ import annotations

import httpx
import pytest


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=httpx.Request("GET", "http://x"), response=None)


def test_openai_filters_to_chat_models(monkeypatch):
    from pi_harness import discovery

    payload = {"data": [
        {"id": "gpt-5"},
        {"id": "text-embedding-3-large"},
        {"id": "o3"},
        {"id": "whisper-1"},
        {"id": "dall-e-3"},
        {"id": "gpt-4o-audio-preview"},
    ]}
    monkeypatch.setattr(discovery.httpx, "get", lambda *a, **k: _Resp(payload))
    out = discovery.list_models("openai", api_key="sk-x")
    assert out["models"] == ["gpt-5", "o3"]
    assert not out.get("error")


def test_openai_error_does_not_raise_or_leak_key(monkeypatch):
    from pi_harness import discovery

    def boom(*a, **k):
        raise httpx.HTTPError("401 unauthorized for sk-secret")

    monkeypatch.setattr(discovery.httpx, "get", boom)
    out = discovery.list_models("openai", api_key="sk-secret")
    assert out["models"] == []
    assert "sk-secret" not in out.get("error", "")


def test_local_ssrf_target_blocked_without_fetch(monkeypatch):
    from pi_harness import discovery

    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return _Resp({"data": []})

    monkeypatch.setattr(discovery.httpx, "get", spy)
    out = discovery.list_models("local", base_url="http://169.254.169.254/v1")
    assert out["models"] == []
    assert out.get("error")
    assert called["n"] == 0  # link-local refused before any fetch


def test_local_lists_models(monkeypatch):
    from pi_harness import discovery

    monkeypatch.setattr(
        discovery.httpx, "get",
        lambda *a, **k: _Resp({"data": [{"id": "mlx-a"}, {"id": "mlx-b"}]}),
    )
    out = discovery.list_models("local", base_url="http://localhost:8080/v1")
    assert out["models"] == ["mlx-a", "mlx-b"]
