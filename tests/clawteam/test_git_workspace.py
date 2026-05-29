"""Local git-worktree helpers for run isolation."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pi_harness.clawteam import git_workspace as gw


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(["init", "-q"], tmp_path)
    _git(["config", "user.email", "t@t.t"], tmp_path)
    _git(["config", "user.name", "t"], tmp_path)
    (tmp_path / "f.txt").write_text("hi\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-qm", "init"], tmp_path)
    return tmp_path


def test_repo_root_finds_toplevel(repo):
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert gw.repo_root(sub) == repo.resolve()


def test_create_run_worktree_makes_branch_off_head(repo):
    wt = repo / ".worktrees" / "run-1"
    gw.create_run_worktree(repo, branch="run/abc123", worktree_path=wt)
    assert wt.is_dir()
    # The new worktree is checked out on the new branch.
    out = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=wt, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == "run/abc123"


def test_remove_run_worktree_keeps_branch(repo):
    wt = repo / ".worktrees" / "run-1"
    gw.create_run_worktree(repo, branch="run/abc123", worktree_path=wt)
    gw.remove_run_worktree(repo, wt)
    assert not wt.exists()
    # Branch survives the worktree removal.
    branches = subprocess.run(
        ["git", "branch", "--list", "run/abc123"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    assert "run/abc123" in branches


def test_remove_missing_worktree_is_noop(repo):
    gw.remove_run_worktree(repo, repo / ".worktrees" / "nope")  # must not raise
