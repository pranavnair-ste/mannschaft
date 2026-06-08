"""Environment-driven configuration for the Pi-Agent Harness.

All other modules (trajectory, corpus, topology, ...) import ``Config`` from
here and never re-read environment variables themselves.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

__all__ = ["Config", "ConfigError", "load_config"]


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


DEFAULT_REASONING_MODEL = "gpt-5"
DEFAULT_FAST_MODEL = "gpt-5-mini"
DEFAULT_CLAWTEAM_STATE_DIR = "~/.clawteam"
DEFAULT_CORPUS_ROOT = "~/.pi-harness/corpus"
DEFAULT_TRAJECTORY_DB_PATH = "~/.pi-harness/trajectory.db"
DEFAULT_OBS_FORK_DIR = "~/Desktop/Personal/pi-agent-observability"


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Frozen configuration snapshot.

    Attributes:
        openai_api_key: OpenAI API key (optional; required only when an 'api'
            provider bucket is selected).
        reasoning_model: Model assigned to orchestrator + reviewer roles.
        fast_model: Model assigned to builder + scout roles.
        clawteam_state_dir: Directory ClawTeam owns. The harness passes this to
            every ``clawteam`` invocation via ``--data-dir``; ClawTeam manages
            its contents.
        corpus_root: Root directory for the expertise corpus (Plan 3 owns it).
        trajectory_db_path: SQLite file path for the trajectory store (Plan 2).
        obs_enabled: Whether the observability layer is enabled.
        obs_host: Host the fork observability server binds to.
        obs_port: Port the fork observability server binds to.
        obs_auth_token: Bearer token for the fork observability server (secret).
        obs_fork_dir: Directory of the pi-agent observability fork checkout.
    """

    openai_api_key: str = field(repr=False)  # never echo the secret in reprs/tracebacks/logs
    reasoning_model: str
    fast_model: str
    clawteam_state_dir: Path
    corpus_root: Path
    trajectory_db_path: Path
    obs_enabled: bool
    obs_host: str
    obs_port: int
    obs_auth_token: str = field(repr=False)  # never echo the secret in reprs/tracebacks/logs
    obs_fork_dir: Path

    @property
    def obs_server_url(self) -> str:
        override = os.environ.get("OBS_SERVER_URL", "").strip()
        return override if override else f"http://{self.obs_host}:{self.obs_port}"


def _expand(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str)).resolve(strict=False)


def load_config(env_file: Optional[str | Path] = ".env") -> Config:
    """Load and validate configuration.

    Args:
        env_file: Optional path to a dotenv file. Pass ``None`` to skip loading
            (tests do this). If the file is missing it is silently ignored.

    Returns:
        A frozen :class:`Config`.

    Raises:
        ConfigError: If ``OBS_PORT`` is non-integer/out of range, or
            observability is enabled without ``OBS_AUTH_TOKEN``.
    """
    if env_file is not None:
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(env_path, override=False)

    # Sovereign default: the key is OPTIONAL. A local-provider run needs none.
    # Enforcement is deferred to the point of use — agent_wrapper raises a clear
    # ConfigError if an `api` bucket is selected without a key (see Phase 1).
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    obs_enabled = _bool_env(os.environ.get("PI_HARNESS_OBS_ENABLED", ""))
    obs_host = os.environ.get("OBS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port_raw = os.environ.get("OBS_PORT", "43190").strip()
    try:
        obs_port = int(port_raw)
    except ValueError as exc:
        raise ConfigError(f"OBS_PORT must be an integer, got {port_raw!r}") from exc
    if not (1 <= obs_port <= 65535):
        raise ConfigError(f"OBS_PORT out of range 1-65535: {obs_port}")
    obs_auth_token = os.environ.get("OBS_AUTH_TOKEN", "").strip()
    if obs_enabled and not obs_auth_token:
        raise ConfigError(
            "OBS_AUTH_TOKEN required when observability is enabled "
            "(PI_HARNESS_OBS_ENABLED is set)"
        )
    obs_fork_dir = _expand(os.environ.get("PI_HARNESS_OBS_FORK_DIR", DEFAULT_OBS_FORK_DIR))

    return Config(
        openai_api_key=api_key,
        reasoning_model=os.environ.get(
            "PI_HARNESS_REASONING_MODEL", DEFAULT_REASONING_MODEL
        ),
        fast_model=os.environ.get(
            "PI_HARNESS_FAST_MODEL", DEFAULT_FAST_MODEL
        ),
        clawteam_state_dir=_expand(
            os.environ.get("PI_HARNESS_CLAWTEAM_STATE_DIR", DEFAULT_CLAWTEAM_STATE_DIR)
        ),
        corpus_root=_expand(
            os.environ.get("PI_HARNESS_CORPUS_ROOT", DEFAULT_CORPUS_ROOT)
        ),
        trajectory_db_path=_expand(
            os.environ.get("PI_HARNESS_TRAJECTORY_DB_PATH", DEFAULT_TRAJECTORY_DB_PATH)
        ),
        obs_enabled=obs_enabled,
        obs_host=obs_host,
        obs_port=obs_port,
        obs_auth_token=obs_auth_token,
        obs_fork_dir=obs_fork_dir,
    )
