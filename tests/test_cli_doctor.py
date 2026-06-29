"""Tests for run-from-anywhere + loud boot (Task 2.3).

Supervisor.run / wait_ready are patched so no real process is spawned and no
real health check is made.
"""
from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

from pi_harness import cli
from pi_harness.cli import app, repo_root
from pi_harness.observability import supervisor as sup

runner = CliRunner()


def test_repo_root_anchors_on_package_and_has_ui():
    root = repo_root()
    assert root == Path(cli.__file__).resolve().parents[1]
    # The UI the `up`/`doctor` commands target lives here regardless of cwd.
    assert (root / "ui").is_dir()


def test_doctor_node_modules_check_is_cwd_independent(monkeypatch, tmp_path):
    """Running doctor from an unrelated cwd still finds ui/node_modules via
    repo_root() (the bug was a relative Path('ui'))."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.chdir(tmp_path)  # nowhere near the repo
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code in (0, 1)
    # The line reflects repo_root()'s ui/, not a (now-missing) relative ui/.
    expected = (repo_root() / "ui" / "node_modules").exists()
    line = next(l for l in res.stdout.splitlines() if "node_modules" in l)
    assert ("✓" in line) == expected


def test_up_ui_cwd_is_repo_root_ui(monkeypatch):
    """The UI proc is launched with cwd=<repo_root>/ui, not a relative 'ui'."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}

    def fake_run(self, **k):
        captured["procs"] = {p.name: p for p in self.procs}
        return 0

    monkeypatch.setattr(sup.Supervisor, "run", fake_run)
    res = runner.invoke(app, ["up"])
    assert res.exit_code == 0
    ui = captured["procs"]["ui"]
    assert ui.cwd == repo_root() / "ui"
    assert ui.cwd.is_absolute()


def test_up_reports_ready_and_not_ready(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def fake_run(self, *, ready_timeout, strict, on_ready):
        on_ready({"fork": True, "api": False})
        return 0

    monkeypatch.setattr(sup.Supervisor, "run", fake_run)
    res = runner.invoke(app, ["up", "--no-ui"])
    assert res.exit_code == 0
    out = res.output
    assert "ready: fork" in out
    assert "NOT READY: api" in out


def test_up_strict_exits_nonzero_on_not_ready(monkeypatch):
    """--strict makes a not-ready health-checked proc a non-zero exit; default
    stays non-aborting."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    # Use the real Supervisor.run but stub spawn + wait_ready so nothing real runs.
    monkeypatch.setattr(sup.subprocess, "Popen", lambda argv, **k: _FakeChild())
    monkeypatch.setattr(
        sup.Supervisor, "wait_ready",
        lambda self, **k: {"fork": False, "api": True},
    )
    monkeypatch.setattr(sup.Supervisor, "teardown", lambda self: None)

    res = runner.invoke(app, ["up", "--no-ui", "--strict"])
    assert res.exit_code == 2  # strict abort on the not-ready 'fork'


def test_up_default_does_not_abort_on_not_ready(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(sup.subprocess, "Popen", lambda argv, **k: _FakeChild())
    monkeypatch.setattr(
        sup.Supervisor, "wait_ready",
        lambda self, **k: {"fork": False, "api": True},
    )
    monkeypatch.setattr(sup.Supervisor, "teardown", lambda self: None)
    # poll_once returns a dead proc immediately so run() returns 1 (not the
    # strict-abort path) — proving default boot tailed past the not-ready proc.
    monkeypatch.setattr(sup.Supervisor, "poll_once", lambda self: self.procs[0])

    res = runner.invoke(app, ["up", "--no-ui"])
    assert res.exit_code == 1  # tailed, then a child exited — not the strict 2


class _FakeChild:
    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass

    def kill(self):
        pass
