"""Tests for the pi models.json sidecar.

pi (the executor) keeps a provider+model registry at ~/.pi/agent/models.json.
When the user picks 'local' for a bucket in the Settings UI, the harness must
register a corresponding provider entry there so `pi --provider harness-local
--model X` succeeds. ``ensure_pi_provider`` is the idempotent upsert that
does it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_ensure_pi_provider_creates_file_when_missing(tmp_path: Path) -> None:
    from pi_harness.pi_models import ensure_pi_provider

    path = tmp_path / "models.json"
    ensure_pi_provider(
        name="harness-local",
        base_url="http://localhost:11434/v1",
        model_ids=["qwen2.5-coder:7b"],
        pi_models_path=path,
    )
    data = json.loads(path.read_text())
    assert "providers" in data
    assert "harness-local" in data["providers"]
    p = data["providers"]["harness-local"]
    assert p["baseUrl"] == "http://localhost:11434/v1"
    assert p["api"] == "openai-completions"
    assert any(m["id"] == "qwen2.5-coder:7b" for m in p["models"])


def test_ensure_pi_provider_preserves_other_providers(tmp_path: Path) -> None:
    from pi_harness.pi_models import ensure_pi_provider

    path = tmp_path / "models.json"
    path.write_text(json.dumps({
        "providers": {
            "openai": {
                "baseUrl": "https://api.openai.com/v1",
                "apiKey": "sk-existing-key",
                "api": "openai-completions",
                "models": [{"id": "gpt-5", "name": "GPT-5"}],
            },
        },
    }))

    ensure_pi_provider(
        name="harness-local",
        base_url="http://localhost:11434/v1",
        model_ids=["qwen3:30b"],
        pi_models_path=path,
    )

    data = json.loads(path.read_text())
    # New provider added.
    assert "harness-local" in data["providers"]
    # Old one untouched, including its api key.
    assert data["providers"]["openai"]["baseUrl"] == "https://api.openai.com/v1"
    assert data["providers"]["openai"]["apiKey"] == "sk-existing-key"
    assert data["providers"]["openai"]["models"][0]["id"] == "gpt-5"


def test_ensure_pi_provider_updates_base_url_when_changed(tmp_path: Path) -> None:
    from pi_harness.pi_models import ensure_pi_provider

    path = tmp_path / "models.json"
    ensure_pi_provider(
        name="harness-local",
        base_url="http://localhost:11434/v1",
        model_ids=["m1"],
        pi_models_path=path,
    )
    # User switches to LM Studio.
    ensure_pi_provider(
        name="harness-local",
        base_url="http://localhost:1234/v1",
        model_ids=["m1"],
        pi_models_path=path,
    )
    data = json.loads(path.read_text())
    assert data["providers"]["harness-local"]["baseUrl"] == "http://localhost:1234/v1"


def test_ensure_pi_provider_adds_new_models_without_duplicating(tmp_path: Path) -> None:
    from pi_harness.pi_models import ensure_pi_provider

    path = tmp_path / "models.json"
    ensure_pi_provider(
        name="harness-local",
        base_url="http://localhost:11434/v1",
        model_ids=["m1"],
        pi_models_path=path,
    )
    ensure_pi_provider(
        name="harness-local",
        base_url="http://localhost:11434/v1",
        model_ids=["m1", "m2"],
        pi_models_path=path,
    )
    data = json.loads(path.read_text())
    models = data["providers"]["harness-local"]["models"]
    ids = [m["id"] for m in models]
    assert ids == ["m1", "m2"]  # m1 wasn't duplicated, m2 was appended


def test_ensure_pi_provider_tolerates_garbled_existing_file(tmp_path: Path) -> None:
    """If pi's models.json is somehow malformed (hand-edit gone wrong, crash
    during write), the harness must not refuse to save — overwrite with a
    fresh file. Losing other providers is a worse outcome but the harness
    has no source of truth for them; document the trade-off in the body."""
    from pi_harness.pi_models import ensure_pi_provider

    path = tmp_path / "models.json"
    path.write_text("not-valid-json{{{")
    ensure_pi_provider(
        name="harness-local",
        base_url="http://localhost:11434/v1",
        model_ids=["m1"],
        pi_models_path=path,
    )
    data = json.loads(path.read_text())
    assert "harness-local" in data["providers"]


def test_ensure_local_provider_from_settings_registers_when_local(tmp_path: Path) -> None:
    from pi_harness.pi_models import ensure_local_provider_from_settings
    from pi_harness.settings import BucketConfig, HarnessSettings

    models_path = tmp_path / "models.json"
    settings = HarnessSettings(
        orchestrator=BucketConfig(provider="local", model="mlx-a"),
        builder=BucketConfig(provider="local", model="mlx-b"),
        local_base_url="http://localhost:8080/v1",
    )
    assert ensure_local_provider_from_settings(settings, pi_models_path=models_path) is True
    data = json.loads(models_path.read_text())
    prov = data["providers"]["harness-local"]
    assert prov["baseUrl"] == "http://localhost:8080/v1"
    assert {m["id"] for m in prov["models"]} == {"mlx-a", "mlx-b"}


def test_ensure_local_provider_from_settings_noop_when_all_api(tmp_path: Path) -> None:
    from pi_harness.pi_models import ensure_local_provider_from_settings
    from pi_harness.settings import BucketConfig, HarnessSettings

    models_path = tmp_path / "models.json"
    settings = HarnessSettings(
        orchestrator=BucketConfig(provider="api", model="gpt-5"),
        builder=BucketConfig(provider="api", model="gpt-5-mini"),
    )
    assert ensure_local_provider_from_settings(settings, pi_models_path=models_path) is False
    assert not models_path.exists()
