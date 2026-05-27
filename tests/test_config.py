"""Unit tests for pi_harness.config.Config."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_config_loads_required_openai_key(monkeypatch, tmp_path):
    """Config must read OPENAI_API_KEY from env."""
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-abc")
    monkeypatch.delenv("PI_HARNESS_REASONING_MODEL", raising=False)
    monkeypatch.delenv("PI_HARNESS_FAST_MODEL", raising=False)
    monkeypatch.delenv("PI_HARNESS_CLAWTEAM_STATE_DIR", raising=False)
    monkeypatch.delenv("PI_HARNESS_CORPUS_ROOT", raising=False)
    monkeypatch.delenv("PI_HARNESS_TRAJECTORY_DB_PATH", raising=False)

    cfg = load_config(env_file=None)

    assert cfg.openai_api_key == "sk-test-abc"


def test_config_applies_default_paths(monkeypatch):
    """Unset path env vars resolve to documented defaults under HOME."""
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.delenv("PI_HARNESS_CLAWTEAM_STATE_DIR", raising=False)
    monkeypatch.delenv("PI_HARNESS_CORPUS_ROOT", raising=False)
    monkeypatch.delenv("PI_HARNESS_TRAJECTORY_DB_PATH", raising=False)

    cfg = load_config(env_file=None)

    home = Path(os.path.expanduser("~"))
    assert cfg.clawteam_state_dir == (home / ".clawteam").resolve(strict=False)
    assert cfg.corpus_root == (home / ".pi-harness" / "corpus").resolve(strict=False)
    assert cfg.trajectory_db_path == (home / ".pi-harness" / "trajectory.db").resolve(strict=False)


def test_config_applies_default_models(monkeypatch):
    """Unset model env vars resolve to documented defaults."""
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.delenv("PI_HARNESS_REASONING_MODEL", raising=False)
    monkeypatch.delenv("PI_HARNESS_FAST_MODEL", raising=False)

    cfg = load_config(env_file=None)

    assert cfg.reasoning_model == "gpt-5"
    assert cfg.fast_model == "gpt-5-mini"


def test_config_overrides_via_env(monkeypatch, tmp_path):
    """All overridable fields honor env vars."""
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-override")
    monkeypatch.setenv("PI_HARNESS_REASONING_MODEL", "gpt-5-pro")
    monkeypatch.setenv("PI_HARNESS_FAST_MODEL", "gpt-5-nano")
    monkeypatch.setenv("PI_HARNESS_CLAWTEAM_STATE_DIR", str(tmp_path / "claw"))
    monkeypatch.setenv("PI_HARNESS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("PI_HARNESS_TRAJECTORY_DB_PATH", str(tmp_path / "traj.db"))

    cfg = load_config(env_file=None)

    assert cfg.reasoning_model == "gpt-5-pro"
    assert cfg.fast_model == "gpt-5-nano"
    assert cfg.clawteam_state_dir == (tmp_path / "claw").resolve(strict=False)
    assert cfg.corpus_root == (tmp_path / "corpus").resolve(strict=False)
    assert cfg.trajectory_db_path == (tmp_path / "traj.db").resolve(strict=False)


def test_config_missing_key_raises(monkeypatch):
    """No OPENAI_API_KEY in env (and no .env file) must raise."""
    from pi_harness.config import load_config, ConfigError

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        load_config(env_file=None)


def test_config_repr_masks_api_key(monkeypatch):
    """Config repr must NOT contain the API key — it leaks into tracebacks/logs
    otherwise (pytest prints fixture values, logging prints config, etc.)."""
    from pi_harness.config import load_config

    secret = "sk-proj-SUPERSECRETVALUE-do-not-leak"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    cfg = load_config(env_file=None)

    assert secret not in repr(cfg)
    assert secret not in str(cfg)
    # The value is still accessible programmatically.
    assert cfg.openai_api_key == secret


def test_config_is_frozen(monkeypatch):
    """Config dataclass must be immutable to prevent accidental mutation by callers."""
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    cfg = load_config(env_file=None)

    with pytest.raises(Exception):
        cfg.openai_api_key = "sk-other"  # type: ignore[misc]
