"""Shared pytest fixtures and Plan 2 stubs for the Pi-Agent Harness test suite.

Plan 3 runs in a worktree that does NOT contain Plan 2's ``pi_harness.trajectory``
module (Plan 2 is being implemented in parallel). The corpus reader's
``find_unreferenced(since_run=...)`` branch depends on Plan 2's
``TrajectoryEvent`` schema and ``query_events`` callable. We stub a minimal
shim here so the corpus code (which imports ``TrajectoryEvent`` only lazily and
accepts ``query_events`` via constructor injection) can be exercised end-to-end
without the real Plan 2 module on disk.

The stub is registered into ``sys.modules`` *before* test collection so that
any ``from pi_harness.trajectory.schema import TrajectoryEvent`` style import
inside ``pi_harness.corpus`` resolves cleanly. The actual Plan 2 modules will
replace this stub once they land on main.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Plan 2 stub: pi_harness.trajectory.schema.TrajectoryEvent
#              pi_harness.trajectory.store.query_events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StubTrajectoryEvent:
    """Stand-in for Plan 2's TrajectoryEvent.

    Only fields the curator's pruning logic touches are stubbed:
    ``run_id``, ``corpus_refs``, ``corpus_cited``.
    """

    run_id: str
    corpus_refs: List[str] = field(default_factory=list)
    corpus_cited: List[str] = field(default_factory=list)


def _stub_query_events(
    run_id: Optional[str] = None,
    since_ts: Optional[object] = None,
    limit: Optional[int] = None,
) -> List[_StubTrajectoryEvent]:
    """Default no-op query. Tests inject their own callable; this is a safe fallback."""
    return []


def _install_trajectory_stub() -> None:
    """Install a minimal ``pi_harness.trajectory`` package into ``sys.modules``."""
    pkg_name = "pi_harness.trajectory"
    if pkg_name in sys.modules:
        return

    trajectory_pkg = types.ModuleType(pkg_name)
    trajectory_pkg.__path__ = []  # mark as package

    schema_mod = types.ModuleType(f"{pkg_name}.schema")
    schema_mod.TrajectoryEvent = _StubTrajectoryEvent  # type: ignore[attr-defined]

    store_mod = types.ModuleType(f"{pkg_name}.store")
    store_mod.query_events = _stub_query_events  # type: ignore[attr-defined]

    trajectory_pkg.schema = schema_mod  # type: ignore[attr-defined]
    trajectory_pkg.store = store_mod  # type: ignore[attr-defined]

    sys.modules[pkg_name] = trajectory_pkg
    sys.modules[f"{pkg_name}.schema"] = schema_mod
    sys.modules[f"{pkg_name}.store"] = store_mod


_install_trajectory_stub()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_corpus_root(tmp_path: Path) -> Path:
    """A temporary corpus root with all expected classification subdirs.

    Layout::

        <tmp_path>/corpus/
            foundational/
            tactical/
            observational/
            archived/

    Tests inject this via ``pi_harness.config.Config(corpus_root=...)`` or
    direct constructor injection.
    """
    root = tmp_path / "corpus"
    root.mkdir()
    for sub in ("foundational", "tactical", "observational", "archived"):
        (root / sub).mkdir()
    return root


@pytest.fixture
def stub_query_events() -> Callable[..., List[_StubTrajectoryEvent]]:
    """Returns a fresh default ``query_events`` callable.

    Tests that need to control trajectory data can either pass their own
    callable to ``CorpusReader(..., query_events=...)`` or monkeypatch this.
    """
    return _stub_query_events


# Re-export the stub event type so tests can construct synthetic trajectory rows
# without importing from the stubbed module path directly.
StubTrajectoryEvent = _StubTrajectoryEvent
