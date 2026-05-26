"""End-to-end smoke test: launch a real ClawTeam team via Plan 1's client,
capture events into a fresh trajectory db, assert >=10 events land within 120s.

Marked `smoke` -- skipped in default CI; run with:
    OPENAI_API_KEY=sk-... uv run pytest tests/trajectory/test_capture_e2e.py -m smoke -v --timeout=240
"""
from __future__ import annotations

import asyncio
import os
import shutil
import textwrap
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pi_harness.trajectory.capture import capture_clawteam_transitions
from pi_harness.trajectory.store import init_db, query_events

pytestmark = [pytest.mark.smoke, pytest.mark.asyncio]


def _detect_executor() -> str:
    override = os.environ.get("PI_HARNESS_SMOKE_EXECUTOR", "").strip()
    aliases = {
        "pi-coding-agent": ["pi", "pi-coding-agent"],
        "pi": ["pi", "pi-coding-agent"],
        "codex": ["codex"],
    }
    candidates = aliases.get(override, [override]) if override else ["codex", "pi", "pi-coding-agent"]
    for cand in candidates:
        if cand and shutil.which(cand):
            return cand
    pytest.skip("No coding-agent CLI on PATH; install @openai/codex or @mariozechner/pi-coding-agent")


@pytest.mark.timeout(240)
async def test_clawteam_smoke_emits_at_least_10_events(tmp_path: Path):
    from pi_harness.clawteam import ClawTeamClient
    from pi_harness.clawteam_profile import build_profile_specs
    from pi_harness.config import load_config

    if not os.environ.get("OPENAI_API_KEY", "").startswith("sk-"):
        pytest.skip("OPENAI_API_KEY not set; smoke test skipped")
    if not shutil.which("clawteam") or not shutil.which("tmux"):
        pytest.skip("clawteam or tmux missing from PATH")

    executor = _detect_executor()

    # Sandbox ClawTeam state per-test so we don't disturb the user's ~/.clawteam.
    state_dir = tmp_path / "clawteam-state"
    os.environ["PI_HARNESS_CLAWTEAM_STATE_DIR"] = str(state_dir)
    cfg = load_config(env_file=None)
    client = ClawTeamClient(cfg)

    # Register profiles with the detected executor as the agent command.
    for spec in build_profile_specs(cfg):
        client.register_profile(replace(spec, command=executor))

    # Install the same minimal 2-agent template Plan 1's smoke uses.
    template_toml = textwrap.dedent(f"""
        [template]
        name = "pi-smoke"
        description = "2-agent smoke template (reused by trajectory smoke)."
        command = ["{executor}"]
        backend = "tmux"

        [template.leader]
        name = "leader"
        type = "orchestrator"
        task = '''Create one task assigned to builder titled "write-hello". Body: "Write hello.txt with HELLO, then mark completed." Then poll `clawteam task list {{team_name}}` every 15s. Exit when the builder task is completed.'''

        [[template.agents]]
        name = "builder"
        type = "builder"
        task = '''When you receive "write-hello", create hello.txt at the worktree root with HELLO, then mark the task completed.'''
    """).strip() + "\n"
    template_path = client.install_template("pi-smoke", template_toml)

    db_path = tmp_path / "smoke.db"
    init_db(db_path)
    run_id = f"smoke-{datetime.now(timezone.utc).isoformat()}"
    team_name = f"trajectory-smoke-{uuid.uuid4().hex[:8]}"

    try:
        client.launch_team(
            template="pi-smoke",
            team_name=team_name,
            goal="Write hello.txt with the word HELLO.",
        )
        poller = asyncio.create_task(
            capture_clawteam_transitions(
                run_id=run_id,
                team_name=team_name,
                db_path=db_path,
                poll_interval_s=2.0,
            )
        )

        # Wait up to 120s for the team to produce events.
        deadline = asyncio.get_event_loop().time() + 120.0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2.0)
            events = query_events(run_id=run_id, db_path=db_path)
            if len(events) >= 10:
                break

        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass
    finally:
        try:
            client.cleanup_team(team_name)
        except Exception:
            pass
        # Plan 1's install_template writes to ~/.clawteam/templates regardless of
        # data-dir; clean it up so we don't leak global state.
        try:
            template_path.unlink(missing_ok=True)
        except Exception:
            pass

    events = query_events(run_id=run_id, db_path=db_path)
    assert (
        len(events) >= 10
    ), f"smoke: expected >=10 events in 120s, got {len(events)}"
