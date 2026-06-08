"""Shared pytest fixtures for the Pi-Agent Harness test suite."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip smoke-marked tests unless PI_HARNESS_RUN_SMOKE=1 is set.

    Smoke tests launch a REAL ClawTeam team — whose coding agents run git in
    the working directory — and spend OpenAI credit. The marker alone is not
    enough protection: a stray `pytest` (or `pytest -m smoke`) would run them
    just because an OPENAI_API_KEY happens to be present (e.g. from .env). This
    opt-in env var decouples "a key exists" from "launch real teams now".

    Combined with ``addopts = -m 'not smoke'`` in pyproject (which deselects
    smoke from the default run), running smoke requires BOTH an explicit
    ``-m smoke`` selection AND ``PI_HARNESS_RUN_SMOKE=1``.
    """
    if os.environ.get("PI_HARNESS_RUN_SMOKE") == "1":
        return
    skip_smoke = pytest.mark.skip(
        reason="smoke test: set PI_HARNESS_RUN_SMOKE=1 (and OPENAI_API_KEY) to run"
    )
    for item in items:
        if "smoke" in item.keywords:
            item.add_marker(skip_smoke)


@pytest.fixture(autouse=True)
def _guard_real_run_worktrees(request):
    """Global safety net: NO non-smoke test may shell out to real git through
    the coordinator's run-isolation path.

    ``Coordinator.launch()`` (default, non ``--in-place``) calls
    ``pi_harness.clawteam.git_workspace.create_run_worktree``, which runs
    ``git worktree add`` against the developer's REAL repo. Several tests build a
    real Coordinator (directly, or via ``branch()`` / the API) with a Mock or tmp
    config and call launch — without this guard each such test registered a
    ``run/<id>`` worktree + branch in the actual repository (hundreds leaked
    before this was caught). Patching the *coordinator's* reference to
    ``git_workspace`` makes the isolation path inert for the whole non-smoke
    suite, while leaving the real ``git_workspace`` module untouched so
    ``tests/clawteam/test_git_workspace.py`` still exercises it directly.

    Smoke tests (``@pytest.mark.smoke``) opt OUT: they launch a real ClawTeam
    team and rely on real worktree isolation to keep agent commits off your
    branch. Tests that assert on isolation re-patch locally — the inner patch
    wins inside its block and is restored to this mock on exit.
    """
    if request.node.get_closest_marker("smoke"):
        yield
        return
    with patch("pi_harness.topology.coordinator.git_workspace") as gw:
        gw.repo_root.return_value = Path("/tmp/fake-repo")
        yield gw


@pytest.fixture(autouse=True)
def _isolate_keystore(monkeypatch, tmp_path_factory):
    """Point the key store at a throwaway path so no test reads or writes the
    developer's real ~/.config/pi-harness/.env. ``config.load_config()`` loads
    the keystore with override=True, so without this an existing real key would
    clobber a test's fake OPENAI_API_KEY. Tests that exercise the keystore set
    PI_HARNESS_KEYSTORE_PATH themselves (their setenv runs later and wins)."""
    p = tmp_path_factory.mktemp("keystore") / ".env"  # dir exists, .env does not
    monkeypatch.setenv("PI_HARNESS_KEYSTORE_PATH", str(p))
    yield


@pytest.fixture
def tmp_corpus_root(tmp_path: Path) -> Path:
    """A temporary corpus root with all expected classification subdirs.

    Layout::

        <tmp_path>/corpus/
            foundational/
            tactical/
            observational/
            archived/
    """
    root = tmp_path / "corpus"
    root.mkdir()
    for sub in ("foundational", "tactical", "observational", "archived"):
        (root / sub).mkdir()
    return root
