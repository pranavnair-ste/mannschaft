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


def test_config_missing_key_ok_for_local(monkeypatch):
    """No OPENAI_API_KEY is fine — local is the sovereign default; the key is
    only required when an `api` bucket is actually selected (enforced in
    agent_wrapper, not here)."""
    from pi_harness.config import load_config

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    cfg = load_config(env_file=None)
    assert cfg.openai_api_key == ""


def test_config_loads_key_from_keystore(monkeypatch, tmp_path):
    """A key stored in the keystore file reaches Config.openai_api_key even
    with no repo .env and no env var set (so it reaches the launch env)."""
    from pi_harness.config import load_config

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ks = tmp_path / "secrets.env"
    ks.write_text("OPENAI_API_KEY=sk-fromkeystore\n")
    monkeypatch.setenv("PI_HARNESS_KEYSTORE_PATH", str(ks))

    cfg = load_config(env_file=None)
    assert cfg.openai_api_key == "sk-fromkeystore"


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


def test_obs_defaults_disabled(monkeypatch):
    from pi_harness.config import load_config

    for k in ("PI_HARNESS_OBS_ENABLED", "OBS_HOST", "OBS_PORT", "OBS_AUTH_TOKEN",
              "PI_HARNESS_OBS_FORK_DIR", "OBS_SERVER_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = load_config(env_file=None)
    assert cfg.obs_enabled is False
    assert cfg.obs_host == "127.0.0.1"
    assert cfg.obs_port == 43190
    assert cfg.obs_auth_token == ""
    assert cfg.obs_server_url == "http://127.0.0.1:43190"


def test_obs_fork_dir_default_is_app_owned(monkeypatch):
    """Default dashboard dir is the portable, app-owned ~/.pi-harness/obs-dashboard
    (D4) — not the author's ~/Desktop clone."""
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("PI_HARNESS_OBS_FORK_DIR", raising=False)
    cfg = load_config(env_file=None)
    home = Path(os.path.expanduser("~"))
    assert cfg.obs_fork_dir == (home / ".pi-harness" / "obs-dashboard").resolve(strict=False)


def test_obs_fork_ref_default_and_override(monkeypatch):
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("PI_HARNESS_OBS_FORK_REF", raising=False)
    assert load_config(env_file=None).obs_fork_ref == "v0.3.0"
    monkeypatch.setenv("PI_HARNESS_OBS_FORK_REF", "main")
    assert load_config(env_file=None).obs_fork_ref == "main"


def test_obs_server_url_composed_and_overridable(monkeypatch):
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OBS_SERVER_URL", raising=False)
    monkeypatch.setenv("OBS_HOST", "127.0.0.1")
    monkeypatch.setenv("OBS_PORT", "5000")
    assert load_config(env_file=None).obs_server_url == "http://127.0.0.1:5000"
    monkeypatch.setenv("OBS_SERVER_URL", "http://example:9/")
    assert load_config(env_file=None).obs_server_url == "http://example:9/"


def test_obs_enabled_requires_token(monkeypatch):
    from pi_harness.config import load_config, ConfigError

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PI_HARNESS_OBS_ENABLED", "1")
    monkeypatch.delenv("OBS_AUTH_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="OBS_AUTH_TOKEN"):
        load_config(env_file=None)


def test_obs_token_not_in_repr(monkeypatch):
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OBS_AUTH_TOKEN", "super-secret-xyz")
    assert "super-secret-xyz" not in repr(load_config(env_file=None))


def test_obs_port_invalid_raises(monkeypatch):
    from pi_harness.config import load_config, ConfigError

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OBS_PORT", "not-a-port")
    with pytest.raises(ConfigError, match="OBS_PORT"):
        load_config(env_file=None)
