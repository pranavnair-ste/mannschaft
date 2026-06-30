"""Tests for the `ms chat` and `ms status` CLI commands and the de-gated launch linter."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pi_harness.cli import app
from pi_harness.spec.format import Spec, serialize_spec

runner = CliRunner()


@pytest.fixture
def good_spec(tmp_path: Path) -> Path:
    """A spec file that lints cleanly (score 1.0)."""
    spec = Spec(
        id="cli-smoke",
        title="Dark mode toggle",
        goal="Let users toggle dark mode in settings",
        acceptance_criteria=[
            "The toggle persists across 2 page reloads",
            "The page writes a theme cookie on toggle",
        ],
        constraints=[],
        non_goals=["Theming third-party embeds"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=None,
        status="draft",
    )
    p = tmp_path / "cli-smoke.md"
    serialize_spec(spec, p)
    return p


def test_chat_invokes_launch_chat(monkeypatch):
    calls = {}
    monkeypatch.setattr("pi_harness.cli.launch_chat",
                        lambda **k: calls.update(k) or 0)
    res = runner.invoke(app, ["chat", "--provider", "openai", "--model", "gpt-5.4"])
    assert res.exit_code == 0
    assert calls["provider_override"] == "openai"
    assert calls["model_override"] == "gpt-5.4"


def test_chat_propagates_nonzero(monkeypatch):
    monkeypatch.setattr("pi_harness.cli.launch_chat", lambda **k: 1)
    res = runner.invoke(app, ["chat"])
    assert res.exit_code == 1


def test_status_not_found_exits_nonzero(monkeypatch):
    monkeypatch.setattr("pi_harness.cli.build_status", lambda run_id, db_path=None: None)
    res = runner.invoke(app, ["status", "run-missing"])
    assert res.exit_code == 1
    assert "not found" in res.stdout.lower()


def test_status_json(monkeypatch):
    fake = {"run_id": "run-x", "status": "running", "agents": [], "sovereign": True,
            "cost_usd": 0.0, "tokens_in": 1, "tokens_out": 2, "agent_count": 0,
            "elapsed_s": 5, "branch": None, "task_transitions": 0}
    monkeypatch.setattr("pi_harness.cli.build_status", lambda run_id, db_path=None: fake)
    res = runner.invoke(app, ["status", "run-x", "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["run_id"] == "run-x"


def test_launch_does_not_block_on_lint_warnings(good_spec, monkeypatch):
    """De-gate regression: launch no longer hard-exits on lint findings.

    The plan's fallback path: monkeypatch `_lint_advisory` to a no-op and assert
    launch still exits 0 (the point is the blocking lint gate is gone)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    advisory_calls = []
    monkeypatch.setattr("pi_harness.cli._lint_advisory", lambda spec: advisory_calls.append(spec))

    from unittest.mock import MagicMock

    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-abc", run_branch=None)
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: [])
    monkeypatch.setattr("pi_harness.cli.ensure_local_provider_from_settings", lambda *a, **k: None)

    res = runner.invoke(app, ["launch", str(good_spec), "--detach"])
    assert res.exit_code == 0, res.stdout
    assert advisory_calls, "launch must call _lint_advisory (advisory, not a gate)"
