"""ClawTeamClient subprocess-argv tests for Phase 2 additions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from pi_harness.clawteam.client import ClawTeamClient


def _client():
    cfg = MagicMock()
    cfg.clawteam_state_dir = "/tmp/ctstate"
    cfg.openai_api_key = "sk-test"
    return ClawTeamClient(config=cfg)


def _argv(mock_run):
    return mock_run.call_args.args[0]


def test_launch_team_passes_workspace_and_repo():
    c = _client()
    with patch("pi_harness.clawteam.client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        c.launch_team(template="t", team_name="team-1", goal="g",
                      workspace=True, repo="/path/wt")
    argv = _argv(run)
    assert "--workspace" in argv
    assert argv[argv.index("--repo") + 1] == "/path/wt"


def test_launch_team_omits_workspace_by_default():
    c = _client()
    with patch("pi_harness.clawteam.client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        c.launch_team(template="t", team_name="team-1", goal="g")
    argv = _argv(run)
    assert "--workspace" not in argv
    assert "--repo" not in argv


def test_merge_workspace_argv_and_no_raise_on_conflict():
    c = _client()
    with patch("pi_harness.clawteam.client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="CONFLICT", stderr="")
        result = c.merge_workspace("team-1", "agent-a", repo="/path/wt", target="run/abc")
    argv = _argv(run)
    assert argv[-6:] == ["workspace", "merge", "team-1", "agent-a", "--repo", "/path/wt"] or \
        ("workspace" in argv and "merge" in argv and "team-1" in argv and "agent-a" in argv)
    assert argv[argv.index("--target") + 1] == "run/abc"
    # check=False: a conflict (rc=1) is returned, not raised.
    assert result.returncode == 1


def test_snapshot_team_argv():
    c = _client()
    with patch("pi_harness.clawteam.client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        c.snapshot_team("team-1", tag="failed-abc")
    argv = _argv(run)
    assert argv[argv.index("team") + 1] == "snapshot"
    assert "team-1" in argv
    assert argv[argv.index("--tag") + 1] == "failed-abc"
