"""Tests for the dashboard bootstrap (auto-clone at pinned ref) + token provisioning.

All subprocess calls are mocked — these tests NEVER run real git/bun, and never
touch the user's real keystore or dashboard checkout.
"""
from __future__ import annotations

import stat

import pytest

from pi_harness.observability import bootstrap


def _cfg(tmp_path, ref="v0.3.0"):
    """Minimal duck-typed cfg with just the fields bootstrap reads."""
    return type(
        "C", (), {"obs_fork_dir": tmp_path / "dash", "obs_fork_ref": ref}
    )()


# --------------------------------------------------------------------------- #
# ensure_dashboard — missing dir clones + checks out
# --------------------------------------------------------------------------- #


def test_missing_dir_clones_and_checks_out(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        # The clone "creates" the server entry so the post-clone assert passes.
        if "clone" in cmd:
            d = tmp_path / "dash" / "apps" / "observability"
            d.mkdir(parents=True, exist_ok=True)
            (d / "server.ts").write_text("x")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    out = bootstrap.ensure_dashboard(_cfg(tmp_path))

    assert out == (tmp_path / "dash")
    assert any("clone" in c for c in calls)
    assert any("checkout" in c and "v0.3.0" in c for c in calls)
    # Clone URL is the dashboard repo, not the disler upstream.
    clone = next(c for c in calls if "clone" in c)
    assert "github.com/pranavnair-ste/pi-agent-observability" in " ".join(clone)


def test_missing_dir_bun_install_failure_is_best_effort(tmp_path, monkeypatch):
    """A failing/absent bun install must warn-don't-fail (the server's only dep
    is @types/bun)."""

    def fake_run(cmd, **kw):
        if "clone" in cmd:
            d = tmp_path / "dash" / "apps" / "observability"
            d.mkdir(parents=True, exist_ok=True)
            (d / "server.ts").write_text("x")

            class Ok:
                returncode = 0
                stdout = ""
                stderr = ""

            return Ok()
        if cmd and cmd[0] == "bun":
            raise FileNotFoundError("bun not found")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    # Must not raise despite bun missing.
    out = bootstrap.ensure_dashboard(_cfg(tmp_path))
    assert out == (tmp_path / "dash")


# --------------------------------------------------------------------------- #
# ensure_dashboard — existing dir never mutates git state
# --------------------------------------------------------------------------- #


def test_existing_dir_never_mutates_git(tmp_path, monkeypatch):
    d = tmp_path / "dash" / "apps" / "observability"
    d.mkdir(parents=True)
    (d / "server.ts").write_text("x")
    forbidden = {"clone", "checkout", "reset", "pull", "fetch", "merge"}

    def fake_run(cmd, **kw):
        assert not (forbidden & set(cmd)), f"must not mutate git state: {cmd}"

        class R:
            returncode = 0
            stdout = "abc123\n"
            stderr = ""

        return R()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    out = bootstrap.ensure_dashboard(_cfg(tmp_path))
    assert out == (tmp_path / "dash")


def test_existing_dir_warns_on_ref_mismatch(tmp_path, monkeypatch, caplog):
    d = tmp_path / "dash" / "apps" / "observability"
    d.mkdir(parents=True)
    (d / "server.ts").write_text("x")

    def fake_run(cmd, **kw):
        # `git rev-parse HEAD` resolves to one sha; `git rev-parse <ref>` to
        # another — i.e. the checkout has drifted off the pinned ref.
        sha = "headhead00000000" if cmd[-1] == "HEAD" else "refrefref0000000"

        class R:
            returncode = 0
            stdout = sha + "\n"
            stderr = ""

        return R()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    with caplog.at_level("WARNING"):
        bootstrap.ensure_dashboard(_cfg(tmp_path))
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "ms setup-obs --update" in msgs


def test_existing_dir_missing_server_entry_raises(tmp_path, monkeypatch):
    """An existing dir that isn't actually the dashboard is a hard error."""
    (tmp_path / "dash").mkdir(parents=True)

    def fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.ensure_dashboard(_cfg(tmp_path))


# --------------------------------------------------------------------------- #
# BootstrapError carries captured stderr
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# ensure_obs_token — persistent, idempotent, 0o600
# --------------------------------------------------------------------------- #


@pytest.fixture
def ks(tmp_path, monkeypatch):
    """Point the keystore at a temp file so tests never touch the real one."""
    p = tmp_path / "keystore.env"
    monkeypatch.setenv("PI_HARNESS_KEYSTORE_PATH", str(p))
    return p


def _token_cfg(token=""):
    return type("C", (), {"obs_auth_token": token})()


def test_ensure_obs_token_generates_and_persists_0o600(ks, monkeypatch):
    from dotenv import dotenv_values

    monkeypatch.delenv("OBS_AUTH_TOKEN", raising=False)
    tok = bootstrap.ensure_obs_token(_token_cfg())
    assert tok and len(tok) == 32  # secrets.token_hex(16)
    assert dotenv_values(str(ks)).get("OBS_AUTH_TOKEN") == tok
    assert oct(ks.stat().st_mode & 0o777) == "0o600"


def test_ensure_obs_token_idempotent_preserves_existing(ks, monkeypatch):
    from dotenv import dotenv_values

    monkeypatch.delenv("OBS_AUTH_TOKEN", raising=False)
    ks.write_text("OBS_AUTH_TOKEN=preexisting0123456789abcdef01234567\n")
    tok = bootstrap.ensure_obs_token(_token_cfg())
    assert tok == "preexisting0123456789abcdef01234567"
    # Not rewritten/duplicated.
    assert dotenv_values(str(ks)).get("OBS_AUTH_TOKEN") == tok


def test_ensure_obs_token_returns_cfg_token_when_set(ks, monkeypatch):
    """A non-weak token already on cfg (loaded from env/keystore) is reused,
    not regenerated."""
    monkeypatch.delenv("OBS_AUTH_TOKEN", raising=False)
    tok = bootstrap.ensure_obs_token(_token_cfg(token="already-a-strong-token-xyz"))
    assert tok == "already-a-strong-token-xyz"
    # Nothing written when the token already exists.
    assert not ks.exists()


def test_ensure_obs_token_replaces_weak_token(ks, monkeypatch):
    """A weak/dev placeholder token is treated as absent and replaced."""
    monkeypatch.delenv("OBS_AUTH_TOKEN", raising=False)
    tok = bootstrap.ensure_obs_token(_token_cfg(token="devtoken"))
    assert tok != "devtoken"
    assert len(tok) == 32


def test_set_obs_enabled_persists_flag(ks):
    from dotenv import dotenv_values

    bootstrap.set_obs_enabled(True)
    assert dotenv_values(str(ks)).get("PI_HARNESS_OBS_ENABLED") == "1"
    assert oct(ks.stat().st_mode & 0o777) == "0o600"


def test_bootstrap_error_carries_stderr(tmp_path, monkeypatch):
    def fake_run(cmd, **kw):
        if "clone" in cmd:
            class R:
                returncode = 128
                stdout = ""
                stderr = "fatal: could not read from remote repository"

            return R()

        class Ok:
            returncode = 0
            stdout = ""
            stderr = ""

        return Ok()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    with pytest.raises(bootstrap.BootstrapError) as ei:
        bootstrap.ensure_dashboard(_cfg(tmp_path))
    assert "could not read from remote repository" in str(ei.value)
