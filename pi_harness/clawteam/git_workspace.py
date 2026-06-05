"""Local git-worktree helpers the harness owns for run isolation.

These are plain `git` operations (NOT clawteam calls): create a dedicated
worktree on a fresh `run/<id>` branch off HEAD so a launched team works in
isolation from the user's checked-out branch, and remove the worktree on
teardown while keeping the branch (the consolidated work lives on it).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = ["repo_root", "create_run_worktree", "remove_run_worktree"]


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
    )


def repo_root(start: Path | str | None = None) -> Path:
    """Return the git repo top-level containing ``start`` (default: cwd)."""
    cwd = Path(start) if start is not None else Path.cwd()
    out = _git(["rev-parse", "--show-toplevel"], cwd).stdout.strip()
    return Path(out).resolve()


def create_run_worktree(repo: Path, *, branch: str, worktree_path: Path) -> None:
    """Create ``worktree_path`` as a new worktree on a new ``branch`` off HEAD."""
    worktree_path = Path(worktree_path)
    # Fail fast on a non-absolute path. A relative path would create the worktree
    # *inside* ``repo`` (the user's checked-out tree) and register it in the real
    # ``.git`` — the exact "don't trash my branch" hazard this isolation exists to
    # prevent. In practice this also catches a misconfigured ``clawteam_state_dir``
    # (e.g. a Mock leaking through in tests), which previously littered the repo
    # with hundreds of ``run/<id>`` worktrees/branches under ``MagicMock/...``.
    if not worktree_path.is_absolute():
        raise ValueError(
            f"run worktree path must be absolute, got {str(worktree_path)!r}; "
            "a relative path would create the worktree inside the repo being "
            "isolated. Check that config.clawteam_state_dir is a real absolute path."
        )
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "-b", branch, str(worktree_path), "HEAD"], repo)


def remove_run_worktree(repo: Path, worktree_path: Path) -> None:
    """Remove the worktree directory (keeps the branch). Missing → no-op."""
    if not Path(worktree_path).exists():
        return
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=str(repo), capture_output=True, text=True, check=False,
    )
