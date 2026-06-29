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


def test_qwen_model_gets_thinking_control_fields(tmp_path: Path) -> None:
    """A Qwen local model must be registered with reasoning + qwen-chat-template
    compat, so `pi --thinking off` actually disables its reasoning trace
    (chat_template_kwargs.enable_thinking=false)."""
    from pi_harness.pi_models import ensure_pi_provider

    path = tmp_path / "models.json"
    ensure_pi_provider(
        name="harness-local", base_url="http://localhost:8080/v1",
        model_ids=["Qwen3.6-35B-A3B-MLX-4bit"], pi_models_path=path,
    )
    m = json.loads(path.read_text())["providers"]["harness-local"]["models"][0]
    assert m["reasoning"] is True
    assert m["compat"]["thinkingFormat"] == "qwen-chat-template"


def test_local_model_entry_has_generous_caps(tmp_path: Path) -> None:
    """A new local entry must allow whole-file writes; the old 4096 maxTokens
    cap made a coding agent hit stopReason=length mid-file and stall."""
    from pi_harness.pi_models import (
        ensure_pi_provider, _DEFAULT_MAX_TOKENS, _DEFAULT_CONTEXT_WINDOW,
    )

    assert _DEFAULT_MAX_TOKENS >= 16384
    path = tmp_path / "models.json"
    ensure_pi_provider(
        name="harness-local", base_url="http://localhost:8080/v1",
        model_ids=["Qwen3.6-35B-A3B-MLX-8bit"], pi_models_path=path,
    )
    m = json.loads(path.read_text())["providers"]["harness-local"]["models"][0]
    assert m["maxTokens"] == _DEFAULT_MAX_TOKENS
    assert m["contextWindow"] == _DEFAULT_CONTEXT_WINDOW


def test_existing_low_caps_raised_high_preserved(tmp_path: Path) -> None:
    """A stale 4096 cap is raised to the default; a larger custom value is kept."""
    from pi_harness.pi_models import ensure_pi_provider, _DEFAULT_MAX_TOKENS

    path = tmp_path / "models.json"
    path.write_text(json.dumps({"providers": {"harness-local": {
        "baseUrl": "http://localhost:8080/v1", "apiKey": "local",
        "api": "openai-completions",
        "models": [
            {"id": "Qwen3.6-35B-A3B-MLX-4bit", "name": "a", "maxTokens": 4096, "contextWindow": 32768},
            {"id": "big-model", "name": "b", "maxTokens": 99999, "contextWindow": 262144},
        ],
    }}}))
    ensure_pi_provider(
        name="harness-local", base_url="http://localhost:8080/v1",
        model_ids=["Qwen3.6-35B-A3B-MLX-4bit"], pi_models_path=path,
    )
    models = {m["id"]: m for m in json.loads(path.read_text())["providers"]["harness-local"]["models"]}
    assert models["Qwen3.6-35B-A3B-MLX-4bit"]["maxTokens"] == _DEFAULT_MAX_TOKENS  # raised
    assert models["big-model"]["maxTokens"] == 99999  # not lowered


def test_non_qwen_model_has_no_thinking_fields(tmp_path: Path) -> None:
    from pi_harness.pi_models import ensure_pi_provider

    path = tmp_path / "models.json"
    ensure_pi_provider(
        name="harness-local", base_url="http://localhost:8080/v1",
        model_ids=["gemma-4-26B-A4B-it-MLX-4bit"], pi_models_path=path,
    )
    m = json.loads(path.read_text())["providers"]["harness-local"]["models"][0]
    assert "reasoning" not in m
    assert "compat" not in m


def test_existing_qwen_entry_gets_thinking_fields_stamped(tmp_path: Path) -> None:
    """An entry written before thinking-control existed (no reasoning/compat)
    must be stamped on the next upsert."""
    from pi_harness.pi_models import ensure_pi_provider

    path = tmp_path / "models.json"
    path.write_text(json.dumps({"providers": {"harness-local": {
        "baseUrl": "http://localhost:8080/v1", "apiKey": "local",
        "api": "openai-completions",
        "models": [{"id": "Qwen3.6-35B-A3B-MLX-4bit", "name": "x"}],
    }}}))
    ensure_pi_provider(
        name="harness-local", base_url="http://localhost:8080/v1",
        model_ids=["Qwen3.6-35B-A3B-MLX-4bit"], pi_models_path=path,
    )
    m = json.loads(path.read_text())["providers"]["harness-local"]["models"][0]
    assert m["reasoning"] is True
    assert m["compat"]["thinkingFormat"] == "qwen-chat-template"
