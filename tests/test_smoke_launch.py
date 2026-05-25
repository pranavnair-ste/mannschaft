"""Smoke test: launch a real 2-agent ClawTeam with a coding-agent CLI.

Skipped by default. To run:

    OPENAI_API_KEY=sk-... uv run pytest -m smoke -v --timeout=360

Prerequisites:
    - clawteam CLI installed (via `uv sync`)
    - tmux installed (`brew install tmux` on macOS)
    - ONE of:
          npm install -g @openai/codex                  (preferred; default executor)
          npm install -g @mariozechner/pi-coding-agent  (alternative)
    - OPENAI_API_KEY exported (must start with `sk-`)
"""

from __future__ import annotations

import os
import shutil
import textwrap
import time
import uuid
from dataclasses import replace

import pytest

pytestmark = pytest.mark.smoke


def _detect_executor() -> str:
    """Pick a coding-agent CLI: respect PI_HARNESS_SMOKE_EXECUTOR, else codex, else pi.

    Note on names: ``@mariozechner/pi-coding-agent`` installs a binary called ``pi``
    (not ``pi-coding-agent``). The override accepts either form for ergonomics.
    """
    aliases = {
        "pi-coding-agent": ["pi", "pi-coding-agent"],
        "pi": ["pi", "pi-coding-agent"],
        "codex": ["codex"],
    }
    override = os.environ.get("PI_HARNESS_SMOKE_EXECUTOR", "").strip()
    if override:
        candidates = aliases.get(override, [override])
    else:
        candidates = ["codex", "pi", "pi-coding-agent"]
    for cand in candidates:
        if cand and shutil.which(cand):
            return cand
    pytest.skip(
        "No coding-agent CLI found on PATH. Install one:\n"
        "  npm install -g @openai/codex                  (binary: codex)\n"
        "  npm install -g @mariozechner/pi-coding-agent  (binary: pi)"
    )


def _which_or_skip(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        pytest.skip(f"required binary {binary!r} not on PATH")
    return path


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch (pytest's default is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def real_cfg(tmp_path_factory, monkeypatch_module):
    """A Config that points at a sandboxed ClawTeam state dir."""
    from pi_harness.config import load_config

    if not os.environ.get("OPENAI_API_KEY", "").startswith("sk-"):
        pytest.skip("OPENAI_API_KEY not set (or not sk-*); smoke test skipped")

    _which_or_skip("clawteam")
    _which_or_skip("tmux")

    state_dir = tmp_path_factory.mktemp("clawteam-state")
    monkeypatch_module.setenv("PI_HARNESS_CLAWTEAM_STATE_DIR", str(state_dir))
    return load_config(env_file=None)


def test_smoke_launch_completes(real_cfg):
    """End-to-end: register profiles, install template, launch, wait, cleanup."""
    from pi_harness.clawteam import ClawTeamClient
    from pi_harness.clawteam_profile import build_profile_specs

    executor = _detect_executor()
    client = ClawTeamClient(real_cfg)

    # 1. Register both profiles, overriding `command` to the detected executor.
    for spec in build_profile_specs(real_cfg):
        spec = replace(spec, command=executor)
        client.register_profile(spec)

    # 2. Install a tiny 2-agent template.
    template_toml = textwrap.dedent(f"""
        [template]
        name = "pi-smoke"
        description = "Two-agent smoke template for pi-harness foundation tests."
        command = ["{executor}"]
        backend = "tmux"

        [template.leader]
        name = "leader"
        type = "orchestrator"
        task = '''You are the leader. Create exactly one task assigned to builder titled "write-hello" with this body:
        "Write a file named hello.txt at the worktree root containing the single word HELLO. Then mark this task completed."
        Use: clawteam task create {{team_name}} --title write-hello --owner builder --body "<above>"
        Then poll `clawteam task list {{team_name}}` every 15 seconds. When the builder task is completed, exit.
        Do not create any other tasks. Do not modify any files yourself.'''

        [[template.agents]]
        name = "builder"
        type = "builder"
        task = '''You are the builder. Wait for a task assigned to you. When you receive "write-hello", create hello.txt at the
        worktree root with the single word HELLO and nothing else. Then mark the task completed via
        `clawteam task update {{team_name}} <task_id> --status completed`. Exit immediately after.'''
    """).strip() + "\n"

    template_path = client.install_template("pi-smoke", template_toml)
    assert template_path.exists()

    # 3. Launch a team.
    team_name = f"pi-smoke-{uuid.uuid4().hex[:8]}"
    try:
        client.launch_team(
            template="pi-smoke",
            team_name=team_name,
            goal="Write hello.txt with the word HELLO.",
        )

        # 4. Wait for completion (5 minute cap; typical run < 2 min).
        start = time.monotonic()
        client.wait_for_completion(team_name, timeout=300.0, poll_interval=5.0)
        elapsed = time.monotonic() - start
        assert elapsed < 300.0

        # 5. Verify the board.
        tasks = client.list_tasks(team_name)
        assert tasks, "expected at least one task on the board"
        assert all(t.get("status") == "completed" for t in tasks), (
            f"not all tasks completed cleanly: {tasks}"
        )

        # 6. Verify ClawTeam state dir for this team exists.
        team_state_dir = real_cfg.clawteam_state_dir / "teams" / team_name
        assert team_state_dir.exists(), (
            f"expected ClawTeam team state at {team_state_dir}"
        )
    finally:
        try:
            client.cleanup_team(team_name)
        except Exception:
            pass
        # Always clean up the global template file we wrote (~/.clawteam/templates/pi-smoke.toml).
        try:
            template_path.unlink(missing_ok=True)
        except Exception:
            pass
