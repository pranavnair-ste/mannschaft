"""Shared fixtures for topology tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_clawteam_client():
    client = MagicMock()
    client.launch_team.return_value = MagicMock(
        run_id="run-test-0001",
        team_name="test-team",
    )
    return client


@pytest.fixture
def mock_corpus_reader():
    reader = MagicMock()
    reader.prime.return_value = []
    return reader


@pytest.fixture
def mock_improve_runner():
    runner = MagicMock()
    runner.run_for_completed_run.return_value = MagicMock(success=True)
    return runner
