"""Tests for the pi-harness CLI."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from pi_harness.spec.decomposer import DecomposedTask
from pi_harness.spec.format import Spec, serialize_spec

runner = CliRunner()


# --------------------------------------------------------------------------- #
# scaffold + fixtures
# --------------------------------------------------------------------------- #


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


def _canned_tasks():
    return [
        DecomposedTask(
            id="t-toggle", name="Toggle", description="add the toggle",
            acceptance_criterion="The toggle persists across 2 page reloads",
            blocked_by=[], assigned_role="builder",
        ),
        DecomposedTask(
            id="t-cookie", name="Cookie", description="write theme cookie",
            acceptance_criterion="The page writes a theme cookie on toggle",
            blocked_by=["t-toggle"], assigned_role="builder",
        ),
    ]


# --------------------------------------------------------------------------- #
# scaffold
# --------------------------------------------------------------------------- #


def test_app_imports():
    from pi_harness.cli import app
    assert app is not None


def test_help_runs_cleanly():
    from pi_harness.cli import app
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pi-harness" in result.stdout.lower()


def test_version_flag():
    from pi_harness.cli import app
    from pi_harness import __version__
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


# --------------------------------------------------------------------------- #
# launch
# --------------------------------------------------------------------------- #


def test_launch_calls_coordinator_with_decomposed_tasks(good_spec, monkeypatch):
    from pi_harness.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-abc")
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: _canned_tasks())

    result = runner.invoke(app, ["launch", str(good_spec), "--detach"])
    assert result.exit_code == 0, result.stdout
    assert "run-abc" in result.stdout
    fake_coord.launch.assert_called_once()
    # The bridge (real) built a RunSpec carrying the decomposed task DAG.
    run_spec = fake_coord.launch.call_args.args[0]
    assert [a.name for a in run_spec.agents] == ["t-toggle", "t-cookie"]
    by = {t.task_id: t for t in run_spec.tasks}
    assert by["t-cookie"].blocked_by == ["t-toggle"]


def test_launch_blocks_on_lint_errors(tmp_path, monkeypatch):
    from pi_harness.cli import app

    bad = Spec(
        id="bad", title="t", goal="g",
        acceptance_criteria=[], constraints=[], non_goals=[],
        created_at="2026-05-25T10:00:00Z", updated_at="2026-05-25T10:00:00Z",
        linter_score=None, status="draft",
    )
    bad_path = tmp_path / "bad.md"
    serialize_spec(bad, bad_path)

    fake_coord = MagicMock()
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)

    result = runner.invoke(app, ["launch", str(bad_path)])
    assert result.exit_code != 0
    fake_coord.launch.assert_not_called()


def test_launch_allow_warnings_bypasses_warnings(good_spec, monkeypatch):
    from pi_harness.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Inject a vague term so the spec lints with a warning (no error).
    text = good_spec.read_text().replace(
        "Let users toggle dark mode in settings",
        "Let users toggle a simple dark mode",
    )
    good_spec.write_text(text)

    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-warn")
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: _canned_tasks())

    # Without --allow-warnings: exits 2, no launch.
    r1 = runner.invoke(app, ["launch", str(good_spec), "--detach"])
    assert r1.exit_code == 2
    fake_coord.launch.assert_not_called()

    # With --allow-warnings: proceeds.
    r2 = runner.invoke(app, ["launch", str(good_spec), "--allow-warnings", "--detach"])
    assert r2.exit_code == 0, r2.stdout
    fake_coord.launch.assert_called_once()


def test_launch_session_flag_threads_into_runspec(good_spec, monkeypatch):
    from pi_harness.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-s")
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: _canned_tasks())

    result = runner.invoke(
        app, ["launch", str(good_spec), "--session", "sess-cli", "--executor", "codex", "--detach"]
    )
    assert result.exit_code == 0, result.stdout
    run_spec = fake_coord.launch.call_args.args[0]
    assert run_spec.session_id == "sess-cli"
    assert run_spec.executor == "codex"


# --------------------------------------------------------------------------- #
# lint / decompose
# --------------------------------------------------------------------------- #


def test_lint_clean_exits_zero(good_spec):
    from pi_harness.cli import app
    result = runner.invoke(app, ["lint", str(good_spec)])
    assert result.exit_code == 0
    assert "score" in result.stdout.lower()


def test_lint_errors_exit_one(tmp_path):
    from pi_harness.cli import app
    bad = Spec(
        id="bad", title="t", goal="g",
        acceptance_criteria=[], constraints=[], non_goals=[],
        created_at="2026-05-25T10:00:00Z", updated_at="2026-05-25T10:00:00Z",
        linter_score=None, status="draft",
    )
    p = tmp_path / "bad.md"
    serialize_spec(bad, p)
    result = runner.invoke(app, ["lint", str(p)])
    assert result.exit_code == 1


def test_decompose_emits_json_task_list(good_spec, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: _canned_tasks())

    result = runner.invoke(app, ["decompose", str(good_spec)])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert [t["id"] for t in payload] == ["t-toggle", "t-cookie"]


def test_decompose_refuses_imperfect_lint(tmp_path):
    from pi_harness.cli import app
    bad = Spec(
        id="warn", title="t", goal="g",
        acceptance_criteria=[], constraints=[], non_goals=[],
        created_at="2026-05-25T10:00:00Z", updated_at="2026-05-25T10:00:00Z",
        linter_score=None, status="draft",
    )
    p = tmp_path / "warn.md"
    serialize_spec(bad, p)
    result = runner.invoke(app, ["decompose", str(p)])
    assert result.exit_code != 0


# --------------------------------------------------------------------------- #
# spec management
# --------------------------------------------------------------------------- #


def test_spec_new_creates_parseable_file(tmp_path, monkeypatch):
    from pi_harness.cli import app
    from pi_harness.spec.format import parse_spec
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    result = runner.invoke(app, ["spec", "new", "my-new-spec", "--title", "Test feature"])
    assert result.exit_code == 0, result.stdout
    target = tmp_path / "specs" / "my-new-spec.md"
    assert target.exists()
    # Round-trips through the real parser (proves the scaffold is valid).
    spec = parse_spec(target)
    assert spec.id == "my-new-spec"
    assert spec.title == "Test feature"
    assert spec.status == "draft"
    assert spec.topology == "sequential"


def test_spec_new_refuses_existing(tmp_path, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    runner.invoke(app, ["spec", "new", "dup", "--title", "x"])
    result = runner.invoke(app, ["spec", "new", "dup", "--title", "x"])
    assert result.exit_code != 0


def test_spec_ls_lists_existing(tmp_path, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    runner.invoke(app, ["spec", "new", "aaa", "--title", "A"])
    runner.invoke(app, ["spec", "new", "bbb", "--title", "B"])
    result = runner.invoke(app, ["spec", "ls"])
    assert result.exit_code == 0
    assert "aaa" in result.stdout and "bbb" in result.stdout


def test_spec_show_prints_file(tmp_path, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    runner.invoke(app, ["spec", "new", "showme", "--title", "Show me"])
    result = runner.invoke(app, ["spec", "show", "showme"])
    assert result.exit_code == 0
    assert "Show me" in result.stdout


def test_spec_rm_force_deletes(tmp_path, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    runner.invoke(app, ["spec", "new", "doomed", "--title", "Doomed"])
    target = tmp_path / "specs" / "doomed.md"
    assert target.exists()
    result = runner.invoke(app, ["spec", "rm", "doomed", "--force"])
    assert result.exit_code == 0
    assert not target.exists()
