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
import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Iterable

from pi_harness.trajectory.agent_capture import PiEventParser
from pi_harness.trajectory.store import init_db, write_event


def _build_argv(executor: str, prompt_args: list[str]) -> list[str]:
    if executor == "pi":
        # Flags verified against pi 0.73.1 (see CAPTURE_FORMAT.md).
        return [
            "pi",
            "--print",
            "--mode",
            "json",
            "--no-session",
            "--no-context-files",
            "--no-extensions",
            "--no-skills",
            *prompt_args,
        ]
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
    for line in lines:
        for event in parser.feed(line):
            try:
                write_event(event, db_path=db_path)
                count += 1
            except Exception:  # noqa: BLE001 -- capture must never break the run
                pass
        if tee_to is not None:
            tee_to.write(line if line.endswith("\n") else line + "\n")
            tee_to.flush()
    return count


def run(
    *,
    executor: str,
    run_id: str,
    agent_id: str,
    db_path: Path | str | None,
    prompt_args: list[str],
    tee_stdout: bool = True,
) -> int:
    """Spawn the executor, capture its stream, return its exit code."""
    argv = _build_argv(executor, prompt_args)
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
    finally:
        return proc.wait()


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
        "prompt", nargs=argparse.REMAINDER,
        help="prompt + extra args passed to the executor (precede with --)",
    )
    args = ap.parse_args(argv)
    if not args.run_id:
        ap.error("--run-id is required (or set PI_HARNESS_RUN_ID)")
    if not args.agent_id:
        ap.error("--agent-id is required (or set CLAWTEAM_AGENT_NAME)")

    db_path = args.db_path
    if db_path is None:
        from pi_harness.config import load_config
        db_path = load_config(env_file=None).trajectory_db_path

    prompt_args = args.prompt
    if prompt_args and prompt_args[0] == "--":
        prompt_args = prompt_args[1:]

    return run(
        executor=args.executor,
        run_id=args.run_id,
        agent_id=args.agent_id,
        db_path=db_path,
        prompt_args=prompt_args,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
