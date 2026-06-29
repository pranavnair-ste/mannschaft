"""Auto-clone + pin the observability dashboard, and provision its auth token.

The dashboard is the repo ``pranavnair-ste/pi-agent-observability`` (a fork of
``disler/pi-agent-observability``). In prose and CLI output it is *the
observability dashboard* — never "the fork".

Two entry points:

* :func:`ensure_dashboard` — make a usable checkout exist at ``cfg.obs_fork_dir``.
  Missing dir → clone + checkout the pinned ref + best-effort ``bun install``.
  Existing dir → validate it is actually the dashboard and NEVER mutate its git
  state (only warn on a ref mismatch). This protects an author's dev clone (D6).
* :func:`ensure_obs_token` — return a persistent, non-weak ``OBS_AUTH_TOKEN``,
  generating and persisting one to the keystore on first use (D2).

Every subprocess call goes through :func:`_run`, which raises a typed
:class:`BootstrapError` carrying the captured stderr so ``doctor`` / ``up`` can
print actionable messages.
"""
from __future__ import annotations

import logging
import os
import secrets
import subprocess
from pathlib import Path

__all__ = ["BootstrapError", "ensure_dashboard", "ensure_obs_token", "DASHBOARD_REPO_URL"]

logger = logging.getLogger(__name__)

DASHBOARD_REPO_URL = "https://github.com/pranavnair-ste/pi-agent-observability"

# Relative to the dashboard checkout root — the Bun server entry. Its presence is
# how we recognise a directory as a real dashboard checkout.
_SERVER_ENTRY = Path("apps") / "observability" / "server.ts"


class BootstrapError(RuntimeError):
    """A bootstrap subprocess (git/bun) failed.

    Carries the captured stderr so callers can render an actionable message.
    """

    def __init__(self, message: str, *, stderr: str = "") -> None:
        self.stderr = stderr
        full = message if not stderr else f"{message}\n{stderr.strip()}"
        super().__init__(full)


def _run(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess, raising :class:`BootstrapError` (with captured stderr)
    on a non-zero exit or a missing executable."""
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise BootstrapError(f"command not found: {argv[0]!r}", stderr=str(exc)) from exc
    if proc.returncode != 0:
        raise BootstrapError(
            f"command failed ({proc.returncode}): {' '.join(argv)}",
            stderr=proc.stderr or "",
        )
    return proc


def ensure_dashboard(cfg) -> Path:
    """Ensure a usable observability-dashboard checkout exists at
    ``cfg.obs_fork_dir`` and return its path.

    Missing dir: ``git clone`` the dashboard, ``git checkout <obs_fork_ref>``,
    then a best-effort ``bun install`` (warn-don't-fail).

    Existing dir: assert it is a real dashboard checkout (``apps/observability/
    server.ts`` present) and NEVER run a state-mutating git command. If
    ``HEAD`` differs from the pinned ref, log a one-line warning only (re-pinning
    is opt-in via ``ms setup-obs --update``).

    Raises:
        BootstrapError: clone/checkout failed, or an existing dir is not a
            dashboard checkout.
    """
    fork_dir = Path(cfg.obs_fork_dir)
    ref = cfg.obs_fork_ref

    if not fork_dir.exists():
        _clone_and_pin(fork_dir, ref)
        return fork_dir

    # Existing dir — validate, never mutate.
    entry = fork_dir / _SERVER_ENTRY
    if not entry.exists():
        raise BootstrapError(
            f"{fork_dir} exists but is not an observability dashboard checkout "
            f"(missing {_SERVER_ENTRY}); remove it or point "
            f"PI_HARNESS_OBS_FORK_DIR elsewhere"
        )
    _warn_on_ref_drift(fork_dir, ref)
    return fork_dir


def _clone_and_pin(fork_dir: Path, ref: str) -> None:
    """Clone the dashboard into ``fork_dir`` and check out ``ref``; best-effort
    ``bun install``."""
    fork_dir.parent.mkdir(parents=True, exist_ok=True)
    logger.info("cloning observability dashboard into %s", fork_dir)
    _run(["git", "clone", DASHBOARD_REPO_URL, str(fork_dir)])
    _run(["git", "-C", str(fork_dir), "checkout", ref])

    entry = fork_dir / _SERVER_ENTRY
    if not entry.exists():
        raise BootstrapError(
            f"cloned {DASHBOARD_REPO_URL} at {ref} but {_SERVER_ENTRY} is missing"
        )

    # Best-effort dependency install — the server's only dep is @types/bun, so a
    # failed or no-op install must not abort boot. Warn, don't fail.
    try:
        _run(["bun", "install"], cwd=fork_dir)
    except BootstrapError as exc:
        logger.warning(
            "bun install in %s did not complete (%s); the dashboard server only "
            "needs @types/bun, so this is usually fine",
            fork_dir,
            exc.stderr.strip() or exc,
        )


def _warn_on_ref_drift(fork_dir: Path, ref: str) -> None:
    """If the checkout's HEAD doesn't resolve to the pinned ref, warn once.
    Best-effort: a failure to read git state is itself only a warning."""
    try:
        head = _run(["git", "-C", str(fork_dir), "rev-parse", "HEAD"]).stdout.strip()
        pinned = _run(["git", "-C", str(fork_dir), "rev-parse", ref]).stdout.strip()
    except BootstrapError:
        # Not a git repo, or the ref is unknown locally — don't block boot.
        return
    if head and pinned and head != pinned:
        logger.warning(
            "dashboard at %s is at %s, pinned ref is %s; run 'ms setup-obs "
            "--update' to re-pin",
            fork_dir,
            head[:12],
            ref,
        )
