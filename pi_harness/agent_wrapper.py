"""Wrap a pi/codex agent run, capturing its NDJSON event stream into the
trajectory store.

OBSERVATIONAL ONLY (v1). pi runs its own tools internally (``--tools``
allowlist + builtin executors); there is no RPC tool-delegation interface for
us to inject denials into. So the wrapper records events as they happen
(``tool_call`` / ``tool_result`` / ``message`` with cost) but cannot block a
tool pre-call. ``guards/runner.py``'s ``intercept_tool_call`` design assumed
RPC delegation -- that is a future agent type, not pi 0.73.1.

CRITICAL pi gotcha: pi 0.73.1 hangs in ``--print`` mode when stdin is a
non-TTY that isn't closed (e.g. a unix-socket stdin from a tmux pane or test
harness). We spawn with ``stdin=DEVNULL`` -- see CAPTURE_FORMAT.md §6.

Usage (subprocess from ClawTeam template, future Task 6.4):
    python -m pi_harness.agent_wrapper \\
        --executor pi --run-id <uuid> --agent-id <name> -- <prompt>
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Iterable

from pi_harness.settings import load_settings
from pi_harness.trajectory.agent_capture import PiEventParser
from pi_harness.trajectory.store import init_db, write_event

log = logging.getLogger(__name__)


LOCAL_PROVIDER_NAME = "harness-local"


def _resolve_provider_model(bucket: str) -> tuple[str, str]:
    """Translate a bucket name into a (pi provider, pi model) pair.

    Buckets line up with ROLE_PROFILE_MAP / ModelTier:
        "reasoning" → orchestrator-bucket (orchestrator/reviewer/synthesizer roles)
        "fast"      → builder-bucket (builder/scout roles)

    The pi provider is either "openai" (built into pi) or LOCAL_PROVIDER_NAME
    (registered by the settings API into ~/.pi/agent/models.json when the
    user picks Local). The model string is whatever the user saved.
    """
    settings = load_settings()
    if bucket == "reasoning":
        cfg = settings.orchestrator
    elif bucket == "fast":
        cfg = settings.builder
    else:
        raise ValueError(f"unknown bucket {bucket!r}; expected 'reasoning' or 'fast'")

    if cfg.provider == "api":
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            from pi_harness.config import ConfigError
            raise ConfigError(
                f"bucket {bucket!r} selects the 'api' provider but OPENAI_API_KEY "
                "is unset. Set it, or switch the bucket to 'local' (the sovereign "
                "default)."
            )
        return ("openai", cfg.model)
    if cfg.provider == "local":
        return (LOCAL_PROVIDER_NAME, cfg.model)
    raise ValueError(f"unknown provider {cfg.provider!r} on bucket {bucket!r}")


def _build_argv(
    executor: str,
    prompt_args: list[str],
    *,
    provider: str | None = None,
    model: str | None = None,
    disable_thinking: bool = False,
) -> list[str]:
    if executor == "pi":
        # Flags verified against pi 0.73.1 (see CAPTURE_FORMAT.md).
        argv = [
            "pi",
            "--print",
            "--mode",
            "json",
            "--no-session",
            "--no-context-files",
            "--no-extensions",
            "--no-skills",
        ]
        if provider is not None:
            argv.extend(["--provider", provider])
        if model is not None:
            argv.extend(["--model", model])
        if disable_thinking:
            # Local Qwen thinking models default to thinking ON at the server,
            # which makes every agent turn slow + verbose. `--thinking off` maps
            # (via the qwen-chat-template compat we stamp into pi's registry) to
            # chat_template_kwargs.enable_thinking=false. Gated on the harness
            # setting local_disable_thinking (default True) for local buckets.
            argv.extend(["--thinking", "off"])
        # pi 0.73.1 has NO end-of-options ("--") support: passing it crashes
        # with `Error: Unknown option: --` (verified 2026-06-06). The prompt is
        # appended as positional `[messages...]`, preserving pi's @file and
        # multi-message semantics (`pi @file.md "msg1" "msg2"`).
        # KNOWN LIMITATION (was audit #27): a prompt literally beginning with
        # '-' is still parsed as a flag. pi offers no argv-level guard, and
        # routing through stdin would collapse @file/multi-message into one blob
        # — so we accept this edge (agent prompts don't start with '-'). The old
        # `--` "guard" never worked; it just crashed pi on every non-empty prompt.
        argv.extend(prompt_args)
        return argv
    if executor == "codex":
        # codex 0.134.0 CLI flags are not yet verified; pass through verbatim
        # until a codex-mode capture spike confirms the shape.
        return ["codex", *prompt_args]
    raise ValueError(f"unknown executor {executor!r}")


def consume_stream(
    lines: Iterable[str],
    *,
    run_id: str,
    agent_id: str,
    db_path: Path | str | None,
    tee_to: IO[str] | None = None,
) -> int:
    """Consume a line stream of pi NDJSON, write parsed events to the db.

    ``tee_to`` optionally mirrors each line (so ClawTeam's tmux pane shows the
    agent's output). Returns the count of events written.
    """
    if db_path is not None:
        init_db(db_path)  # idempotent; ensures the events table exists
    parser = PiEventParser(run_id=run_id, agent_id=agent_id)
    count = 0
    dropped = 0
    for line in lines:
        for event in parser.feed(line):
            try:
                write_event(event, db_path=db_path)
                count += 1
            except Exception:  # noqa: BLE001 -- capture must never break the run
                # Don't crash the agent on a write failure, but never drop the
                # event silently either: a lost write is a hole in the audit
                # trail and must be visible in logs (audit #9).
                dropped += 1
                log.warning(
                    "trajectory write_event failed; event dropped from the audit "
                    "trail (%d dropped so far)", dropped,
                    exc_info=dropped == 1,
                )
        if tee_to is not None:
            tee_to.write(line if line.endswith("\n") else line + "\n")
            tee_to.flush()
    if dropped:
        log.warning("consume_stream: %d trajectory event(s) dropped due to write failures", dropped)
    return count


def run(
    *,
    executor: str,
    run_id: str,
    agent_id: str,
    db_path: Path | str | None,
    prompt_args: list[str],
    tee_stdout: bool = True,
    bucket: str | None = None,
) -> int:
    """Spawn the executor, capture its stream, return its exit code.

    When ``bucket`` is set (``reasoning`` or ``fast``), HarnessSettings is
    consulted to choose pi's --provider/--model. When None, pi falls back to
    its own settings.json defaults — current legacy behavior.
    """
    provider: str | None = None
    model: str | None = None
    disable_thinking = False
    if bucket is not None and executor == "pi":
        provider, model = _resolve_provider_model(bucket)
        # Disable thinking for a LOCAL bucket by default (harness setting), so a
        # local thinking model (Qwen3.6) doesn't burn a slow reasoning trace on
        # every agent turn. The api/cloud path is untouched.
        if provider == LOCAL_PROVIDER_NAME and load_settings().local_disable_thinking:
            disable_thinking = True
    elif bucket is not None:
        # provider/model routing is only wired for pi; warn so the operator
        # knows their model selection is NOT applied (audit #28).
        log.warning(
            "--bucket=%r is ignored for executor %r; provider/model selection is "
            "only wired for pi, so the agent uses %s's own defaults.",
            bucket, executor, executor,
        )
    argv = _build_argv(
        executor, prompt_args, provider=provider, model=model,
        disable_thinking=disable_thinking,
    )
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,  # critical: pi hangs without this
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    tee = sys.stdout if tee_stdout else None
    try:
        consume_stream(
            proc.stdout, run_id=run_id, agent_id=agent_id, db_path=db_path, tee_to=tee,
        )
    except BaseException:
        # A failure in capture (or Ctrl-C) must not orphan the child executor —
        # it would keep running and burning credit. Kill it, then let the error
        # surface instead of being swallowed by a `return` in finally (#10/#26/#35).
        proc.kill()
        raise
    finally:
        rc = proc.wait()
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Wrap pi/codex and capture its NDJSON events into the trajectory store.",
    )
    ap.add_argument("--executor", required=True, choices=["pi", "codex"])
    ap.add_argument(
        "--run-id",
        default=os.environ.get("PI_HARNESS_RUN_ID"),
        help="defaults to $PI_HARNESS_RUN_ID (set by Coordinator at template install time)",
    )
    ap.add_argument(
        "--agent-id",
        default=os.environ.get("CLAWTEAM_AGENT_NAME"),
        help="defaults to $CLAWTEAM_AGENT_NAME (set by ClawTeam in the agent's pane)",
    )
    ap.add_argument(
        "--db-path",
        default=None,
        help="trajectory db path; defaults to Config.trajectory_db_path",
    )
    ap.add_argument(
        "-p", "--prompt",
        help="The agent prompt (ClawTeam's adapter passes this via -p)",
    )
    ap.add_argument(
        "--bucket",
        choices=["reasoning", "fast"],
        default=None,
        help=(
            "Agent's bucket; selects which HarnessSettings entry "
            "(orchestrator/builder) drives --provider/--model on pi. "
            "Stamped by Coordinator per-agent based on ROLE_PROFILE_MAP."
        ),
    )
    # Anything else (unknown flags, trailing positionals) is forwarded to the
    # executor verbatim so callers can pass executor-specific flags.
    args, extras = ap.parse_known_args(argv)
    if not args.run_id:
        ap.error("--run-id is required (or set PI_HARNESS_RUN_ID)")
    if not args.agent_id:
        ap.error("--agent-id is required (or set CLAWTEAM_AGENT_NAME)")

    db_path = args.db_path
    if db_path is None:
        from pi_harness.config import load_config
        db_path = load_config(env_file=None).trajectory_db_path

    # Strip a leading "--" separator (direct-CLI users may use it).
    if extras and extras[0] == "--":
        extras = extras[1:]
    prompt_args = list(extras)
    if args.prompt is not None:
        prompt_args.append(args.prompt)

    return run(
        executor=args.executor,
        run_id=args.run_id,
        agent_id=args.agent_id,
        db_path=db_path,
        prompt_args=prompt_args,
        bucket=args.bucket,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
