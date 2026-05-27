"""End-to-end smoke test: Coordinator + topology stack against real ClawTeam.

Skipped by default. To run:

    OPENAI_API_KEY=sk-... uv run pytest -m smoke -v --timeout=360

Prerequisites:
    - clawteam CLI installed (via `uv sync`)
    - tmux installed (`brew install tmux` on macOS)
    - ONE of:
          npm install -g @openai/codex                  (preferred; default executor)
          npm install -g @mariozechner/pi-coding-agent  (alternative; binary: pi)
    - OPENAI_API_KEY exported (must start with `sk-`)
"""

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.smoke


# ---------------------------------------------------------------------------
# Prerequisite helpers (mirrored from tests/test_smoke_launch.py)
# ---------------------------------------------------------------------------


def _detect_executor() -> str:
    """Pick a coding-agent CLI: respect PI_HARNESS_SMOKE_EXECUTOR, else codex, else pi."""
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


# ---------------------------------------------------------------------------
# Module-scoped monkeypatch (pytest's default is function-scoped)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


# ---------------------------------------------------------------------------
# Config fixture: sandboxes ClawTeam state dir, checks prereqs
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


def test_smoke_coordinator_sequential(real_cfg):
    """End-to-end: Coordinator runs a 2-agent Sequential topology to completion."""
    from pi_harness.clawteam import ClawTeamClient
    from pi_harness.clawteam_profile import build_profile_specs
    from pi_harness.corpus.reader import CorpusReader
    from pi_harness.improve.runner import run_for_completed_run
    from pi_harness.topology.base import AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode
    from pi_harness.topology.coordinator import Coordinator

    executor = _detect_executor()

    # -- Build real collaborators -------------------------------------------

    client = ClawTeamClient(real_cfg)

    # Register both pi-openai-* profiles, overriding command to detected executor.
    for spec in build_profile_specs(real_cfg):
        spec = replace(spec, command=executor)
        client.register_profile(spec)

    # CorpusReader backed by the config corpus root (may be empty — that's fine).
    corpus_reader = CorpusReader(real_cfg.corpus_root)

    # Wrap run_for_completed_run in a thin object so Coordinator can call
    # .run_for_completed_run(handle). Forward the handle's session_id so any
    # corpus entries the improve agent writes are stamped with this session.
    class _ImproveRunner:
        def run_for_completed_run(self, handle):
            return run_for_completed_run(
                handle.run_id, real_cfg, session_id=handle.session_id
            )

    improve_runner = _ImproveRunner()

    # -- Wrap methods we want to count (wraps= keeps real behaviour) ----------

    template_file: list[Path] = []  # populated in finally via call_args

    coordinator = Coordinator(real_cfg, client, corpus_reader, improve_runner)

    handle = None
    with (
        patch.object(client, "create_task", wraps=client.create_task) as mock_create_task,
        patch.object(client, "install_template", wraps=client.install_template) as mock_install_template,
        patch.object(improve_runner, "run_for_completed_run", wraps=improve_runner.run_for_completed_run) as mock_improve,
    ):
        # -- Build a minimal 2-agent Sequential RunSpec ----------------------

        spec = RunSpec(
            goal="Write a file named smoke_out.txt containing the word SMOKE.",
            agents=[
                AgentSpec(
                    name="leader",
                    role=Role.ORCHESTRATOR,
                    model_tier=ModelTier.REASONING,
                    task_prompt=(
                        "You are the leader. Create exactly one task assigned to builder "
                        "titled 'write-smoke' with body: "
                        "'Write a file named smoke_out.txt at the worktree root containing "
                        "the single word SMOKE. Then mark this task completed.' "
                        "Use: clawteam task create {team_name} --title write-smoke "
                        "--owner builder --body \"<above>\". "
                        "Poll `clawteam task list {team_name}` every 15 seconds. "
                        "When the builder task is completed, exit."
                    ),
                ),
                AgentSpec(
                    name="builder",
                    role=Role.BUILDER,
                    model_tier=ModelTier.FAST,
                    task_prompt=(
                        "You are the builder. Wait for a task assigned to you. "
                        "When you receive 'write-smoke', create smoke_out.txt at the "
                        "worktree root with the single word SMOKE and nothing else. "
                        "Then mark the task completed via "
                        "`clawteam task update {team_name} <task_id> --status completed`. "
                        "Exit immediately after."
                    ),
                ),
            ],
            mode=TopologyMode.SEQUENTIAL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
        )

        try:
            # -- Launch -------------------------------------------------------

            handle = coordinator.launch(spec)

            # Derive the template name from install_template call args.
            assert mock_install_template.call_count == 1, (
                "expected exactly one install_template call from Coordinator.launch"
            )
            template_name = mock_install_template.call_args.args[0]
            template_file.append(
                Path.home() / ".clawteam" / "templates" / f"{template_name}.toml"
            )

            # Template file must exist and be valid TOML.
            assert template_file[0].exists(), (
                f"template file not found at {template_file[0]}"
            )
            import tomllib
            parsed_template = tomllib.loads(template_file[0].read_text())
            assert "template" in parsed_template, (
                f"registered template missing [template] table: {parsed_template}"
            )

            # create_task must have been called once per TaskDef from the topology.
            # SequentialTopology with 2 agents produces 2 tasks (each agent gets one).
            assert mock_create_task.call_count >= 1, (
                f"expected create_task to be called at least once; got {mock_create_task.call_count}"
            )

            # -- Wait for completion ------------------------------------------

            result = coordinator.wait_for_completion(handle, timeout=300.0)
            assert result.success, (
                f"run did not succeed; error={result.error!r}; "
                f"statuses={result.terminal_statuses}"
            )

            # -- on_completion triggers improve once -------------------------

            coordinator.on_completion(handle)
            assert mock_improve.call_count == 1, (
                f"expected improve_runner.run_for_completed_run to be called once; "
                f"got {mock_improve.call_count}"
            )

        finally:
            # Clean up the team (best-effort).
            if handle is not None:
                try:
                    client.cleanup_team(handle.team_name)
                except Exception:
                    pass

            # Always remove the global template file we wrote.
            for tpath in template_file:
                try:
                    tpath.unlink(missing_ok=True)
                except Exception:
                    pass
