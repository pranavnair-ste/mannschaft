# pi_harness/session.py
"""Launcher for the sovereign interactive session (`ms chat`).

Runs `pi` UNGAGGED — interactive, session-saving, skills- and context-aware —
on the local model by default, so the user gets "a Claude Code, but local".
The batch path (agent_wrapper) deliberately disables all of that; here we
deliberately enable it. Logic lives here (testable); cli.py stays a thin shim.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import httpx

from pi_harness.agent_wrapper import LOCAL_PROVIDER_NAME, _resolve_provider_model
from pi_harness.pi_models import ensure_local_provider_from_settings
from pi_harness.settings import load_settings
from pi_harness.skills_setup import repo_skills_dir, retire_raw_clawteam_skill

CHAT_SYSTEM_PROMPT = (
    "You are the mannschaft sovereign coding session: a hands-on local-model "
    "coding agent. Work directly with your read/bash/edit/write tools in the "
    "user's repo. For work that is large enough to benefit from a parallel "
    "agentic team, do NOT just grind alone — offer to dispatch a team via the "
    "`pi-harness` skill, but ALWAYS confirm with the user first. When a team is "
    "running, surface its observability-fork deep-link and use `ms status "
    "<run_id>` to report progress. Never shell out to raw `clawteam`; the "
    "mannschaft pipeline (`ms launch`) is the only sanctioned path."
)


def resolve_session_model(
    settings=None,
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> tuple[str, str]:
    """Return (pi_provider, model) for the session.

    Defaults to the orchestrator (reasoning) bucket — the most capable
    configured model — and is overridable per invocation.
    """
    if provider_override and model_override:
        return (provider_override, model_override)
    return _resolve_provider_model("reasoning")


def local_server_reachable(base_url: str, *, timeout: float = 2.0) -> bool:
    """True if the local OpenAI-compatible server answers at all.

    Any HTTP response (even 404) means the socket is up; only a transport-level
    failure counts as unreachable.
    """
    url = base_url.rstrip("/") + "/models"
    try:
        httpx.get(url, timeout=timeout)
        return True
    except httpx.RequestError:
        return False


def build_chat_argv(
    *,
    provider: str,
    model: str,
    session_dir: Path,
    skills_dir: Path,
    disable_thinking: bool,
    system_prompt: str = CHAT_SYSTEM_PROMPT,
) -> list[str]:
    """Compose the interactive pi argv. The inverse of agent_wrapper._build_argv:
    we OMIT every batch gag-flag so pi runs its interactive REPL."""
    argv = [
        "pi",
        "--provider", provider,
        "--model", model,
        "--session-dir", str(session_dir),
        "--skill", str(skills_dir),
        "--append-system-prompt", system_prompt,
    ]
    if disable_thinking:
        argv.extend(["--thinking", "off"])
    return argv


def launch_chat(
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
    spawn=subprocess.run,
) -> int:
    """Resolve config, preflight, retire the stale clawteam skill, and hand the
    terminal to interactive pi. Returns an exit code (does not raise on a
    user-facing failure)."""
    settings = load_settings()
    provider, model = resolve_session_model(
        settings=settings,
        provider_override=provider_override,
        model_override=model_override,
    )

    if provider == LOCAL_PROVIDER_NAME:
        ensure_local_provider_from_settings(settings)
        if not local_server_reachable(settings.local_base_url):
            print(
                f"error: no local model server reachable at {settings.local_base_url}\n"
                f"  start one first, e.g.:\n"
                f"    mlx_lm.server --model {model} --port 8080\n"
                f"  or point a bucket at the API with `ms models set`."
            )
            return 1

    retire_raw_clawteam_skill()

    home = _home_dir()
    session_dir = home / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)

    argv = build_chat_argv(
        provider=provider,
        model=model,
        session_dir=session_dir,
        skills_dir=repo_skills_dir(),
        disable_thinking=(provider == LOCAL_PROVIDER_NAME and settings.local_disable_thinking),
    )
    result = spawn(argv)
    return getattr(result, "returncode", 0) or 0


def _home_dir() -> Path:
    import os

    raw = os.environ.get("PI_HARNESS_HOME")
    return Path(raw) if raw else Path.home() / ".pi-harness"
