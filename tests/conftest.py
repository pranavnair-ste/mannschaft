"""Shared pytest fixtures for the Pi-Agent Harness test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


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
