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
