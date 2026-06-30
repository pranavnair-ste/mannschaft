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
    assert "mannschaft" in result.stdout.lower()


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
    # The bridge (real) built a RunSpec carrying the decomposed task DAG. Both
    # tasks are builder-role, so they collapse onto ONE builder agent (one
    # worktree); the task DAG itself is carried verbatim.
    run_spec = fake_coord.launch.call_args.args[0]
    assert [a.name for a in run_spec.agents] == ["builder"]
    by = {t.task_id: t for t in run_spec.tasks}
    assert by["t-cookie"].blocked_by == ["t-toggle"]
    assert by["t-toggle"].agent_name == "builder"
    assert by["t-cookie"].agent_name == "builder"


def test_launch_non_detach_waits_and_finalizes(good_spec, monkeypatch):
    """Exercise the wait/finalize path the --detach tests skip (audit #18)."""
    from pi_harness.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-abc", run_branch=None)
    fake_coord.wait_for_completion.return_value = MagicMock(
        success=True, terminal_statuses={"t1": "completed"}
    )
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: _canned_tasks())

    result = runner.invoke(app, ["launch", str(good_spec)])  # no --detach
    assert result.exit_code == 0, result.stdout
    fake_coord.wait_for_completion.assert_called_once()
    fake_coord.on_completion.assert_called_once()
    assert "task=t1 status=completed" in result.stdout


def test_launch_tears_down_when_wait_raises(good_spec, monkeypatch):
    """Ctrl-C / unexpected error during the wait must tear the team down so it
    can't keep burning credit, and must not be silently swallowed (audit #4)."""
    from pi_harness.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-abc", run_branch=None)
    fake_coord.wait_for_completion.side_effect = RuntimeError("boom")
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: _canned_tasks())

    result = runner.invoke(app, ["launch", str(good_spec)])
    assert result.exit_code != 0
    fake_coord.teardown.assert_called_once_with(fake_coord.launch.return_value)


def test_stop_command_stops_run(monkeypatch):
    """`stop <run-id>` tears down a (detached) run via the coordinator (audit #5)."""
    from pi_harness.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_coord = MagicMock()
    fake_coord.stop.return_value = True
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)

    result = runner.invoke(app, ["stop", "run-xyz"])
    assert result.exit_code == 0, result.stdout
    fake_coord.stop.assert_called_once_with("run-xyz")
    assert "stopped run-xyz" in result.stdout


def test_stop_command_unknown_run_exits_nonzero(monkeypatch):
    from pi_harness.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_coord = MagicMock()
    fake_coord.stop.return_value = False
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)

    result = runner.invoke(app, ["stop", "ghost"])
    assert result.exit_code == 1


def test_launch_lint_is_advisory_not_a_gate(tmp_path, monkeypatch):
    """De-gate: the launch-time linter is advisory only. A spec the linter would
    flag still launches (spec quality now comes from the interactive shape-spec
    skill); `ms lint` keeps its severity-based exit codes for explicit checks."""
    from pi_harness.cli import app

    bad = Spec(
        id="bad", title="t", goal="g",
        acceptance_criteria=[], constraints=[], non_goals=[],
        created_at="2026-05-25T10:00:00Z", updated_at="2026-05-25T10:00:00Z",
        linter_score=None, status="draft",
    )
    bad_path = tmp_path / "bad.md"
    serialize_spec(bad, bad_path)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-bad", run_branch=None)
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: _canned_tasks())

    result = runner.invoke(app, ["launch", str(bad_path), "--detach"])
    assert result.exit_code == 0, result.stdout
    # Findings surfaced as advice, but the launch proceeded.
    assert "advisory" in result.stdout.lower()
    fake_coord.launch.assert_called_once()


def test_launch_warnings_no_longer_block_and_allow_warnings_is_a_noop(good_spec, monkeypatch):
    """De-gate: a warning-only spec launches with OR without --allow-warnings.

    The blocking lint gate is gone; --allow-warnings is kept as a harmless
    no-op for backward-compat."""
    from pi_harness.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Inject a vague term so the spec lints with a warning (no error).
    text = good_spec.read_text().replace(
        "Let users toggle dark mode in settings",
        "Let users toggle a simple dark mode",
    )
    good_spec.write_text(text)

    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-warn", run_branch=None)
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: _canned_tasks())

    # Without --allow-warnings: still proceeds (no blocking gate).
    r1 = runner.invoke(app, ["launch", str(good_spec), "--detach"])
    assert r1.exit_code == 0, r1.stdout
    assert fake_coord.launch.call_count == 1

    # With --allow-warnings: same outcome — the flag is a no-op now.
    r2 = runner.invoke(app, ["launch", str(good_spec), "--allow-warnings", "--detach"])
    assert r2.exit_code == 0, r2.stdout
    assert fake_coord.launch.call_count == 2


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


def test_spec_subcommands_reject_path_traversal(tmp_path, monkeypatch):
    """A traversing spec_id must be rejected, not used to read/write/delete
    files outside the specs dir (audit #17)."""
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    # Plant a file outside the specs dir that a traversal would target.
    secret = tmp_path / "secret.md"
    secret.write_text("top secret\n")
    for cmd in (
        ["spec", "rm", "../secret", "--force"],
        ["spec", "show", "../secret"],
        ["spec", "new", "../secret", "--title", "pwn", "--force"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 2, (cmd, result.stdout)
    # The outside file is untouched (not deleted, not overwritten).
    assert secret.exists() and secret.read_text() == "top secret\n"


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


# --------------------------------------------------------------------------- #
# serve
# --------------------------------------------------------------------------- #


def test_serve_boots_the_dashboard_app(monkeypatch):
    """`pi-harness serve` must boot the unified dashboard app, which mounts
    /runs, /corpus, /guards, /ws and the spec router — not just the spec
    editor's /specs routes."""
    import uvicorn

    from pi_harness.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    captured: dict = {}

    def fake_run(application, host, port, reload):
        captured["app"] = application
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(uvicorn, "run", fake_run)

    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.stdout

    served = captured["app"]
    paths = {r.path for r in served.routes if hasattr(r, "path")}
    assert "/healthz" in paths, paths
    assert "/runs" in paths, paths
    assert "/specs" in paths, paths


# --------------------------------------------------------------------------- #
# ms models / ms setup
# --------------------------------------------------------------------------- #


def _seed_running(db_path, run_id="run-busy"):
    from datetime import datetime, timezone

    from pi_harness.trajectory.runs import register_run

    register_run(
        run_id=run_id, spec_id="s", topology="sequential", sync_mode="per_agent",
        session_id=None, goal="g", team_name="t",
        started_at=datetime(2026, 6, 8, tzinfo=timezone.utc), run_spec_json="{}",
        status="running", db_path=db_path,
    )


def test_models_set_blocked_when_run_active(monkeypatch, tmp_path):
    from pi_harness.cli import app

    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path / "home"))
    db = tmp_path / "traj.db"
    monkeypatch.setenv("PI_HARNESS_TRAJECTORY_DB_PATH", str(db))
    _seed_running(db)

    res = runner.invoke(app, ["models", "set", "--bucket", "orchestrator", "--provider", "api", "--model", "gpt-5"])
    assert res.exit_code == 1, res.output
    assert "active" in res.output.lower()


def test_models_set_succeeds_when_idle(monkeypatch, tmp_path):
    from pi_harness.cli import app
    from pi_harness.settings import load_settings

    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PI_HARNESS_TRAJECTORY_DB_PATH", str(tmp_path / "traj.db"))

    res = runner.invoke(app, ["models", "set", "--bucket", "builder", "--provider", "api", "--model", "gpt-5-mini"])
    assert res.exit_code == 0, res.output
    s = load_settings()
    assert s.builder.provider == "api"
    assert s.builder.model == "gpt-5-mini"


def test_models_set_local_registers_pi_provider(monkeypatch, tmp_path):
    import pi_harness.pi_models as pm
    from pi_harness.cli import app

    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PI_HARNESS_TRAJECTORY_DB_PATH", str(tmp_path / "traj.db"))
    calls = []
    monkeypatch.setattr(pm, "ensure_local_provider_from_settings", lambda *a, **k: calls.append(1) or True)

    res = runner.invoke(app, ["models", "set", "--bucket", "orchestrator", "--provider", "local", "--model", "mlx-z"])
    assert res.exit_code == 0, res.output
    assert calls == [1]  # local provider registration was triggered


def test_models_key_stores_without_echo(monkeypatch, tmp_path):
    import getpass

    import pi_harness.discovery as discovery
    from pi_harness import keystore
    from pi_harness.cli import app

    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PI_HARNESS_KEYSTORE_PATH", str(tmp_path / "secrets.env"))
    monkeypatch.setattr(getpass, "getpass", lambda *a, **k: "sk-CLIKEY5678")
    monkeypatch.setattr(discovery, "list_models", lambda *a, **k: {"models": ["gpt-5"]})

    res = runner.invoke(app, ["models", "key", "--provider", "openai"])
    assert res.exit_code == 0, res.output
    assert "sk-CLIKEY5678" not in res.output  # raw key never echoed
    assert keystore.get_key("openai") == "sk-CLIKEY5678"
