"""Tests for the HarnessSettings data model + persistence.

HarnessSettings is the user's UI-driven selection of provider+model for each
agent bucket (orchestrator vs builder). Persisted at
~/.pi-harness/models.json — distinct from pi's own ~/.pi/agent/models.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    return tmp_path


def test_load_settings_returns_defaults_when_file_missing(home: Path) -> None:
    from pi_harness.settings import load_settings

    s = load_settings()
    assert s.orchestrator.provider == "api"
    assert s.orchestrator.model == "gpt-5"
    assert s.builder.provider == "api"
    assert s.builder.model == "gpt-5-mini"
    assert s.local_base_url == "http://localhost:11434/v1"


def test_save_then_load_roundtrips(home: Path) -> None:
    from pi_harness.settings import BucketConfig, HarnessSettings, load_settings, save_settings

    settings = HarnessSettings(
        orchestrator=BucketConfig(provider="local", model="qwen2.5-coder:7b"),
        builder=BucketConfig(provider="api", model="gpt-5-mini"),
        local_base_url="http://localhost:11434/v1",
    )
    save_settings(settings)
    loaded = load_settings()
    assert loaded == settings


def test_save_creates_parent_directory(home: Path) -> None:
    """The ~/.pi-harness/ dir may not exist when the user opens settings for
    the first time. save_settings must create it (mkdir parents=True)."""
    from pi_harness.settings import BucketConfig, HarnessSettings, save_settings, settings_path

    # Pre-condition: parent dir doesn't exist yet.
    assert not settings_path().parent.exists() or len(list(settings_path().parent.iterdir())) == 0

    settings = HarnessSettings(
        orchestrator=BucketConfig(provider="api", model="gpt-5"),
        builder=BucketConfig(provider="api", model="gpt-5-mini"),
    )
    save_settings(settings)
    assert settings_path().exists()


def test_load_settings_tolerates_partial_file(home: Path) -> None:
    """A hand-edited or future-version file should not crash the harness;
    unknown keys are dropped and missing keys use defaults."""
    from pi_harness.settings import load_settings, settings_path

    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps({
        "orchestrator": {"provider": "local", "model": "qwen3:30b"},
        "future_field_we_dont_know_about": True,
    }))

    s = load_settings()
    assert s.orchestrator.provider == "local"
    assert s.orchestrator.model == "qwen3:30b"
    # Builder fell back to default since the file omitted it.
    assert s.builder.provider == "api"
    assert s.builder.model == "gpt-5-mini"


def test_invalid_provider_raises(home: Path) -> None:
    from pi_harness.settings import BucketConfig

    with pytest.raises(ValueError):
        BucketConfig(provider="bogus", model="x")  # type: ignore[arg-type]
