"""Shared pytest fixtures for the Pi-Agent Harness test suite."""

from __future__ import annotations

import os
from pathlib import Path

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
