"""chmod-600 store for provider API keys.

Single secret home: ``~/.config/pi-harness/.env`` (override via
``PI_HARNESS_KEYSTORE_PATH``). ``config.load_config()`` loads this file with
``override=True`` so stored keys reach the launch environment (and thus
``Config.openai_api_key`` → ``ClawTeamClient._env()`` → the pi subprocess).

NEVER log a key value. ``mask()`` is the only sanctioned renderer.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values, set_key as _dotenv_set_key

__all__ = ["keystore_path", "set_key", "get_key", "has_key", "mask", "PROVIDER_ENV"]

# provider name → the environment variable the rest of the system reads.
PROVIDER_ENV = {"openai": "OPENAI_API_KEY"}


def keystore_path() -> Path:
    raw = os.environ.get("PI_HARNESS_KEYSTORE_PATH")
    if raw:
        return Path(raw)
    return Path.home() / ".config" / "pi-harness" / ".env"


def _env_var(provider: str) -> str:
    try:
        return PROVIDER_ENV[provider]
    except KeyError:
        raise ValueError(
            f"unknown provider {provider!r}; known: {sorted(PROVIDER_ENV)}"
        ) from None


def set_key(provider: str, value: str) -> None:
    """Persist ``value`` for ``provider``, preserving any other lines in the
    file, and (re)apply 0o600 to the file."""
    var = _env_var(provider)
    path = keystore_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    os.chmod(path, 0o600)
    # set_key preserves other keys; it may rewrite the file with umask perms,
    # so re-apply 0o600 afterwards.
    _dotenv_set_key(str(path), var, value)
    os.chmod(path, 0o600)


def get_key(provider: str) -> Optional[str]:
    var = _env_var(provider)
    path = keystore_path()
    if not path.exists():
        return None
    return dotenv_values(str(path)).get(var)


def has_key(provider: str) -> bool:
    return bool(get_key(provider))


def mask(value: str) -> str:
    """Render a key for display without revealing it. Never returns the full
    value."""
    if not value:
        return ""
    if len(value) <= 8:
        return "…" + value[-2:]
    return f"{value[:3]}…{value[-4:]}"
