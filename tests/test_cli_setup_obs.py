"""Tests for `ms setup-obs` — one-shot clone + token + enable.

``ensure_dashboard`` is patched so no real git/bun ever runs; the keystore is
redirected to a temp file so the real one is never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values
from typer.testing import CliRunner

from pi_harness.cli import app
from pi_harness.observability import bootstrap

runner = CliRunner()


@pytest.fixture
def ks(tmp_path, monkeypatch):
    p = tmp_path / "keystore.env"
    monkeypatch.setenv("PI_HARNESS_KEYSTORE_PATH", str(p))
    return p


@pytest.fixture
def isolated_obs(tmp_path, monkeypatch, ks):
    """Patch ensure_dashboard to a no-op returning a dir; clean obs env."""
    for k in ("OBS_AUTH_TOKEN", "PI_HARNESS_OBS_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PI_HARNESS_OBS_FORK_DIR", str(tmp_path / "dash"))

    seen = {}

    def fake_ensure_dashboard(cfg):
        seen["called"] = True
        return Path(cfg.obs_fork_dir)

    monkeypatch.setattr(bootstrap, "ensure_dashboard", fake_ensure_dashboard)
    return seen


def test_setup_obs_clones_provisions_token_and_enables(isolated_obs, ks):
    res = runner.invoke(app, ["setup-obs"])
    assert res.exit_code == 0, res.stdout
    assert isolated_obs["called"] is True

    vals = dotenv_values(str(ks))
    tok = vals.get("OBS_AUTH_TOKEN")
    assert tok and len(tok) == 32
    assert vals.get("PI_HARNESS_OBS_ENABLED") == "1"
    assert oct(ks.stat().st_mode & 0o777) == "0o600"
    # Never echo the secret token to stdout.
    assert tok not in res.stdout


def test_setup_obs_idempotent_preserves_token(isolated_obs, ks):
    ks.write_text("OBS_AUTH_TOKEN=keepthistoken0123456789abcdef0123\n")
    res = runner.invoke(app, ["setup-obs"])
    assert res.exit_code == 0, res.stdout
    assert dotenv_values(str(ks)).get("OBS_AUTH_TOKEN") == "keepthistoken0123456789abcdef0123"


def test_setup_obs_update_repins_existing_dir(isolated_obs, tmp_path, monkeypatch):
    """--update is allowed to mutate git state on an existing checkout."""
    d = tmp_path / "dash" / "apps" / "observability"
    d.mkdir(parents=True)
    (d / "server.ts").write_text("x")

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    res = runner.invoke(app, ["setup-obs", "--update"])
    assert res.exit_code == 0, res.stdout
    # A re-pin must fetch + checkout the pinned ref.
    flat = [" ".join(c) for c in calls]
    assert any("fetch" in c for c in flat)
    assert any("checkout" in c and "v0.3.0" in c for c in flat)


def test_setup_obs_reports_bootstrap_error(isolated_obs, monkeypatch):
    def boom(cfg):
        raise bootstrap.BootstrapError("clone failed", stderr="fatal: no remote")

    monkeypatch.setattr(bootstrap, "ensure_dashboard", boom)
    res = runner.invoke(app, ["setup-obs"])
    assert res.exit_code != 0
    assert "no remote" in res.stdout or "no remote" in str(res.output)
