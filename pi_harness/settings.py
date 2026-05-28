"""User-facing model selection persisted to ``~/.pi-harness/models.json``.

This is NOT pi's ``~/.pi/agent/models.json`` (which is pi's provider registry,
owned by pi). HarnessSettings is owned by the harness and records *which*
provider+model the user picked for each agent bucket via the Settings UI.

Two buckets mirror ``ROLE_PROFILE_MAP``:
    orchestrator  → applied to roles: orchestrator, reviewer, synthesizer
    builder       → applied to roles: builder, scout

The agent_wrapper reads these at run time (via ``--bucket reasoning|fast``)
and passes ``--provider``/``--model`` to pi.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

__all__ = [
    "BucketConfig",
    "HarnessSettings",
    "Provider",
    "load_settings",
    "save_settings",
    "settings_path",
]

Provider = Literal["api", "local"]
_VALID_PROVIDERS = {"api", "local"}

DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"  # Ollama default


@dataclass(frozen=True)
class BucketConfig:
    provider: Provider
    model: str

    def __post_init__(self) -> None:
        if self.provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"BucketConfig.provider must be one of {sorted(_VALID_PROVIDERS)}; "
                f"got {self.provider!r}"
            )


@dataclass(frozen=True)
class HarnessSettings:
    orchestrator: BucketConfig
    builder: BucketConfig
    local_base_url: str = DEFAULT_LOCAL_BASE_URL


def _home_dir() -> Path:
    raw = os.environ.get("PI_HARNESS_HOME")
    return Path(raw) if raw else Path.home() / ".pi-harness"


def settings_path() -> Path:
    return _home_dir() / "models.json"


def _default_settings() -> HarnessSettings:
    return HarnessSettings(
        orchestrator=BucketConfig(provider="api", model="gpt-5"),
        builder=BucketConfig(provider="api", model="gpt-5-mini"),
    )


def _bucket_from_dict(data: dict | None, default: BucketConfig) -> BucketConfig:
    if not isinstance(data, dict):
        return default
    provider = data.get("provider", default.provider)
    model = data.get("model", default.model)
    if provider not in _VALID_PROVIDERS:
        return default
    return BucketConfig(provider=provider, model=model)


def load_settings() -> HarnessSettings:
    """Load HarnessSettings from disk, falling back to defaults for any
    missing or invalid field. Never raises — the UI must always have settings
    to render."""
    path = settings_path()
    defaults = _default_settings()
    if not path.exists():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    return HarnessSettings(
        orchestrator=_bucket_from_dict(raw.get("orchestrator"), defaults.orchestrator),
        builder=_bucket_from_dict(raw.get("builder"), defaults.builder),
        local_base_url=str(raw.get("local_base_url", defaults.local_base_url)),
    )


def save_settings(settings: HarnessSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "orchestrator": {"provider": settings.orchestrator.provider, "model": settings.orchestrator.model},
        "builder": {"provider": settings.builder.provider, "model": settings.builder.model},
        "local_base_url": settings.local_base_url,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
