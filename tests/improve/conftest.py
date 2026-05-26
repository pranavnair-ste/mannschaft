"""Shared fixtures for tests/improve/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_trajectory() -> list[dict]:
    return json.loads((FIXTURE_DIR / "sample_trajectory.json").read_text())


@pytest.fixture
def sample_corpus_index() -> list[dict]:
    return json.loads((FIXTURE_DIR / "sample_corpus_index.json").read_text())


@pytest.fixture
def sample_git_diff() -> str:
    return (FIXTURE_DIR / "sample_git_diff.txt").read_text()


@pytest.fixture
def sample_agent_response() -> str:
    return (FIXTURE_DIR / "sample_agent_response.json").read_text()
