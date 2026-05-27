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


@dataclass(frozen=True)
class Config:
    """Frozen configuration snapshot.

    Attributes:
        openai_api_key: OpenAI API key (required).
        reasoning_model: Model assigned to orchestrator + reviewer roles.
        fast_model: Model assigned to builder + scout roles.
        clawteam_state_dir: Directory ClawTeam owns. The harness passes this to
            every ``clawteam`` invocation via ``--data-dir``; ClawTeam manages
            its contents.
        corpus_root: Root directory for the expertise corpus (Plan 3 owns it).
        trajectory_db_path: SQLite file path for the trajectory store (Plan 2).
    """

    openai_api_key: str = field(repr=False)  # never echo the secret in reprs/tracebacks/logs
    reasoning_model: str
    fast_model: str
    clawteam_state_dir: Path
    corpus_root: Path
    trajectory_db_path: Path


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
        ConfigError: If ``OPENAI_API_KEY`` is unset.
    """
    if env_file is not None:
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(env_path, override=False)

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "OPENAI_API_KEY is required. Set it in the environment or in a .env file."
        )

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
    )
