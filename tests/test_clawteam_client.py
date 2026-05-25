"""Unit tests for pi_harness.clawteam.client.ClawTeamClient.

All subprocess calls are mocked. The real-CLI integration lives in
tests/test_smoke_launch.py.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-client-test")
    monkeypatch.setenv("PI_HARNESS_CLAWTEAM_STATE_DIR", str(tmp_path / "claw"))
    return load_config(env_file=None)


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.stdout = stdout
    cp.stderr = stderr
    cp.returncode = returncode
    return cp


def test_launch_team_invokes_clawteam_launch(cfg):
    from pi_harness.clawteam.client import ClawTeamClient

    client = ClawTeamClient(cfg)
    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed(stdout="launched")
        client.launch_team(
            template="hello-team",
            team_name="my-team",
            goal="ship it",
            profile="pi-openai-fast",
        )

    assert mock_run.called
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "clawteam"
    assert "--data-dir" in cmd
    assert "launch" in cmd
    launch_idx = cmd.index("launch")
    assert cmd[launch_idx + 1] == "hello-team"
    assert "--team" in cmd and "my-team" in cmd
    assert "--goal" in cmd and "ship it" in cmd
    assert "--profile" in cmd and "pi-openai-fast" in cmd


def test_launch_team_without_profile_omits_flag(cfg):
    from pi_harness.clawteam.client import ClawTeamClient

    client = ClawTeamClient(cfg)
    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed()
        client.launch_team(
            template="hello-team", team_name="my-team", goal="x"
        )

    cmd = mock_run.call_args.args[0]
    assert "--profile" not in cmd


def test_launch_team_raises_on_nonzero_exit(cfg):
    from pi_harness.clawteam.client import ClawTeamClient, ClawTeamCLIError

    client = ClawTeamClient(cfg)
    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed(stderr="boom", returncode=2)

        with pytest.raises(ClawTeamCLIError, match="boom"):
            client.launch_team(template="x", team_name="y", goal="z")


def test_list_tasks_parses_json(cfg):
    from pi_harness.clawteam.client import ClawTeamClient

    payload = [
        {"task_id": "t1", "title": "build", "status": "completed"},
        {"task_id": "t2", "title": "test", "status": "in_progress"},
    ]
    client = ClawTeamClient(cfg)
    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed(stdout=json.dumps(payload))
        tasks = client.list_tasks("my-team")

    assert tasks == payload
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "clawteam"
    assert "--json" in cmd
    task_idx = cmd.index("task")
    assert cmd[task_idx:task_idx + 3] == ["task", "list", "my-team"]


def test_peek_inbox_parses_json(cfg):
    from pi_harness.clawteam.client import ClawTeamClient

    payload = [{"from": "leader", "to": "builder", "body": "hi"}]
    client = ClawTeamClient(cfg)
    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed(stdout=json.dumps(payload))
        messages = client.peek_inbox("my-team", agent="builder", limit=5)

    assert messages == payload
    cmd = mock_run.call_args.args[0]
    assert "--json" in cmd
    inbox_idx = cmd.index("inbox")
    assert cmd[inbox_idx:inbox_idx + 3] == ["inbox", "peek", "my-team"]
    assert "--agent" in cmd and "builder" in cmd
    assert "--limit" in cmd and "5" in cmd


def test_register_profile_invokes_profile_set(cfg):
    from pi_harness.clawteam.client import ClawTeamClient
    from pi_harness.clawteam_profile import build_profile_specs

    client = ClawTeamClient(cfg)
    specs = build_profile_specs(cfg)
    reasoning = next(s for s in specs if s.name == "pi-openai-reasoning")

    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed()
        client.register_profile(reasoning)

    cmd = mock_run.call_args.args[0]
    assert "profile" in cmd and "set" in cmd
    assert "pi-openai-reasoning" in cmd
    assert "--model" in cmd and "gpt-5" in cmd
    assert "--api-key-env" in cmd and "OPENAI_API_KEY" in cmd


def test_install_template_writes_file_under_user_templates_dir(cfg, tmp_path, monkeypatch):
    """install_template writes to the global user-templates dir without shelling out.

    ClawTeam 0.2.x only loads user templates from a fixed path
    (``~/.clawteam/templates``). The test redirects HOME to a tmp dir so
    nothing pollutes the real filesystem.
    """
    from pathlib import Path

    from pi_harness.clawteam.client import ClawTeamClient

    # Redirect ~/.clawteam/templates to a sandbox by overriding USER_TEMPLATES_DIR.
    sandbox = tmp_path / "fake-home" / ".clawteam" / "templates"
    monkeypatch.setattr(
        "pi_harness.clawteam.client.ClawTeamClient.USER_TEMPLATES_DIR", sandbox
    )

    client = ClawTeamClient(cfg)
    toml_text = '[template]\nname = "pi-smoke"\n'

    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        target = client.install_template("pi-smoke", toml_text)

    assert not mock_run.called, "install_template must not shell out"
    assert target == sandbox / "pi-smoke.toml"
    assert target.exists()
    assert target.read_text() == toml_text


def test_create_task_minimum_args(cfg):
    from pi_harness.clawteam.client import ClawTeamClient

    client = ClawTeamClient(cfg)
    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed(stdout="ok")
        client.create_task("my-team", "write hello")

    cmd = mock_run.call_args.args[0]
    create_idx = cmd.index("create")
    assert cmd[create_idx - 1] == "task"
    assert cmd[create_idx + 1] == "my-team"
    assert cmd[create_idx + 2] == "write hello"
    assert "--description" not in cmd
    assert "--owner" not in cmd
    assert "--blocked-by" not in cmd


def test_create_task_passes_all_optional_args(cfg):
    from pi_harness.clawteam.client import ClawTeamClient

    client = ClawTeamClient(cfg)
    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed(stdout="ok")
        client.create_task(
            "my-team",
            "build feature",
            description="describe it",
            owner="builder",
            priority="high",
            blocks=["t-down"],
            blocked_by=["t-up-1", "t-up-2"],
        )

    cmd = mock_run.call_args.args[0]
    assert "--description" in cmd and "describe it" in cmd
    assert "--owner" in cmd and "builder" in cmd
    assert "--priority" in cmd and "high" in cmd
    assert "--blocks" in cmd and "t-down" in cmd
    assert "--blocked-by" in cmd and "t-up-1,t-up-2" in cmd


def test_cleanup_team_invokes_team_cleanup_force(cfg):
    from pi_harness.clawteam.client import ClawTeamClient

    client = ClawTeamClient(cfg)
    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed(stdout="ok")
        client.cleanup_team("my-team")

    cmd = mock_run.call_args.args[0]
    cleanup_idx = cmd.index("cleanup")
    assert cmd[cleanup_idx - 1] == "team"
    assert cmd[cleanup_idx + 1] == "my-team"
    assert "--force" in cmd


def test_wait_for_completion_returns_when_all_done(cfg):
    from pi_harness.clawteam.client import ClawTeamClient

    done = [
        {"task_id": "t1", "status": "completed"},
        {"task_id": "t2", "status": "completed"},
    ]
    client = ClawTeamClient(cfg)
    with patch.object(ClawTeamClient, "list_tasks", return_value=done):
        result = client.wait_for_completion("my-team", timeout=2.0, poll_interval=0.01)

    assert result is True


def test_wait_for_completion_times_out(cfg):
    from pi_harness.clawteam.client import ClawTeamClient, ClawTeamTimeout

    pending = [{"task_id": "t1", "status": "in_progress"}]
    client = ClawTeamClient(cfg)
    with patch.object(ClawTeamClient, "list_tasks", return_value=pending):
        with pytest.raises(ClawTeamTimeout):
            client.wait_for_completion("my-team", timeout=0.05, poll_interval=0.01)


def test_wait_for_completion_fails_when_status_in_failure_set(cfg, monkeypatch):
    """wait_for_completion raises ClawTeamRunFailure if a task's status is in FAILURE_STATUSES.

    Real ClawTeam 0.2.x has no `failed` status (only pending/in_progress/completed/blocked),
    so FAILURE_STATUSES is empty in production. This test patches it to simulate a future
    ClawTeam version that adds a failure status. The mechanism stays in the wrapper so
    callers remain forward-compatible.
    """
    from pi_harness.clawteam import client as client_mod
    from pi_harness.clawteam.client import ClawTeamClient, ClawTeamRunFailure

    monkeypatch.setattr(client_mod, "FAILURE_STATUSES", frozenset({"failed"}))

    mixed = [
        {"task_id": "t1", "status": "completed"},
        {"task_id": "t2", "status": "failed"},
    ]
    client = ClawTeamClient(cfg)
    with patch.object(ClawTeamClient, "list_tasks", return_value=mixed):
        with pytest.raises(ClawTeamRunFailure, match="t2"):
            client.wait_for_completion("my-team", timeout=1.0, poll_interval=0.01)


def test_client_passes_data_dir_top_level(cfg):
    """Every invocation must pass --data-dir before the subcommand."""
    from pi_harness.clawteam.client import ClawTeamClient

    client = ClawTeamClient(cfg)
    with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
        mock_run.return_value = _completed(stdout="[]")
        client.list_tasks("my-team")

    cmd = mock_run.call_args.args[0]
    data_idx = cmd.index("--data-dir")
    task_idx = cmd.index("task")
    assert data_idx < task_idx
    assert cmd[data_idx + 1] == str(cfg.clawteam_state_dir)


def test_client_reexport_from_subpackage(cfg):
    """pi_harness.clawteam re-exports ClawTeamClient for ergonomic import."""
    from pi_harness.clawteam import ClawTeamClient as Reexport
    from pi_harness.clawteam.client import ClawTeamClient

    assert Reexport is ClawTeamClient
