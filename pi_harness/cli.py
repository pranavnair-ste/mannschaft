"""pi-harness command-line entry point.

The canonical headless surface. Every subcommand is a thin shim over the same
in-process modules the FastAPI editor uses — no duplicated business logic.

  pi-harness launch <spec>      lint -> decompose -> spec_to_runspec -> Coordinator.launch
  pi-harness lint <spec>        pure linter; exits 0/1/2 by severity
  pi-harness decompose <spec>   print JSON task list; gated on lint score 1.0
  pi-harness spec new|ls|show|rm|edit   manage ~/.pi-harness/specs/*.md
  pi-harness serve              boot the dashboard backend (spec router + runs + corpus + guards + ws)
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from pi_harness import __version__
from pi_harness.spec.format import parse_spec_file, spec_path, spec_storage_dir
from pi_harness.spec.runspec import build_coordinator, spec_to_runspec

app = typer.Typer(
    name="pi-harness",
    help="Pi-Agent Harness — spec-driven multi-agent run launcher.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", "-V",
        callback=_version_callback, is_eager=True,
        help="Show the pi-harness version and exit.",
    ),
) -> None:
    """Root callback — owns --version so all subcommands inherit it."""


# --------------------------------------------------------------------------- #
# shared helpers (lazy imports keep `--help` fast)
# --------------------------------------------------------------------------- #


def _load_spec_or_die(spec_path: Path):
    if not spec_path.exists():
        typer.echo(f"error: spec file not found: {spec_path}", err=True)
        raise typer.Exit(code=2)
    return parse_spec_file(spec_path)


def _lint_or_die(spec, *, allow_warnings: bool):
    """Run the linter; exit non-zero on errors (always) or warnings (unless
    allow_warnings). Returns the LintResult on success."""
    from pi_harness.spec.linter import Linter

    result = Linter().lint(spec)
    if result.errors:
        typer.echo("error: spec has lint errors:", err=True)
        for v in result.errors:
            typer.echo(f"  [{v.rule_name}] {v.message} ({v.location})", err=True)
        raise typer.Exit(code=1)
    if result.warnings and not allow_warnings:
        typer.echo("error: spec has lint warnings (use --allow-warnings to proceed):", err=True)
        for v in result.warnings:
            typer.echo(f"  [{v.rule_name}] {v.message} ({v.location})", err=True)
        raise typer.Exit(code=2)
    return result


def _decompose_or_die(spec, cfg):
    from pi_harness.spec.decomposer import Decomposer

    return Decomposer(cfg).decompose(spec)


def _make_coordinator(cfg):
    """Real Plan 5 Coordinator wired with the real corpus reader + improve
    runner. Thin wrapper over build_coordinator so tests have a stable
    monkeypatch point."""
    return build_coordinator(cfg)


# --------------------------------------------------------------------------- #
# launch
# --------------------------------------------------------------------------- #


@app.command()
def launch(
    spec_path: Path = typer.Argument(..., help="Path to a spec .md file."),
    allow_warnings: bool = typer.Option(False, "--allow-warnings", help="Don't block on lint warnings."),
    detach: bool = typer.Option(False, "--detach", "-d", help="Return run_id and exit; don't wait."),
    timeout: float = typer.Option(1800.0, "--timeout", help="wait_for_completion timeout (seconds)."),
    session: Optional[str] = typer.Option(
        None, "--session",
        help="Bind the run to a session_id (required for persistent topology; "
        "primes + appends corpus scoped to this session). Overrides the spec's session_id.",
    ),
    executor: Optional[str] = typer.Option(
        None, "--executor", help="Coding-agent executor: 'pi' or 'codex'. Overrides the spec."
    ),
    sync_profile: Optional[str] = typer.Option(
        None, "--sync-profile", help="ClawTeam profile to force when sync_mode is sync_all."
    ),
    in_place: bool = typer.Option(
        False, "--in-place",
        help="Run in the current checkout instead of an isolated run/<id> branch "
        "(NOT recommended: agents commit to your working branch).",
    ),
    keep_alive: bool = typer.Option(
        False, "--keep-alive",
        help="On failure, leave the team running for inspection instead of "
        "snapshotting and tearing it down.",
    ),
    api_url: Optional[str] = typer.Option(
        None, "--api-url",
        help="If set, POST to <url>/specs/<id>/launch instead of launching in-process.",
    ),
) -> None:
    """Launch a Pi-Agent Harness run from a spec file."""
    from pi_harness.config import load_config

    spec = _load_spec_or_die(spec_path)
    _lint_or_die(spec, allow_warnings=allow_warnings)

    if api_url:
        import httpx

        r = httpx.post(f"{api_url.rstrip('/')}/specs/{spec.id}/launch", timeout=30.0)
        r.raise_for_status()
        typer.echo(r.json().get("run_id", ""))
        return

    cfg = load_config()
    tasks = _decompose_or_die(spec, cfg)
    run_spec = spec_to_runspec(
        spec, tasks, session_id=session, executor=executor, sync_profile=sync_profile
    )
    coord = _make_coordinator(cfg)
    handle = coord.launch(run_spec, in_place=in_place, keep_alive=keep_alive)
    typer.echo(handle.run_id)
    if handle.run_branch:
        typer.echo(f"  isolated on branch: {handle.run_branch}")

    if detach:
        typer.echo(f"  detached — stop it with: pi-harness stop {handle.run_id}")
        return

    try:
        result = coord.wait_for_completion(handle, timeout=timeout)
        coord.on_completion(handle)
    except BaseException:
        # Ctrl-C or any failure during the wait/finalize must not leave a live
        # team burning credit or a leaked worktree (audit #4). Best-effort
        # teardown, then re-raise so the original error/interrupt surfaces.
        try:
            coord.teardown(handle)
        except Exception:
            pass
        raise
    for task_id, status in sorted(result.terminal_statuses.items()):
        typer.echo(f"  task={task_id} status={status}")
    if result.success and handle.run_branch:
        typer.echo(f"work is on branch {handle.run_branch} — diff and merge when ready")
    if not result.success:
        typer.echo("run did not complete successfully", err=True)
        raise typer.Exit(code=1)


@app.command()
def stop(
    run_id: str = typer.Argument(..., help="Run id to stop (printed by `launch`)."),
) -> None:
    """Stop a run: kill its agents (halting credit burn) and clean up its team
    and run worktree. Use this for a --detach'd run, or to recover after Ctrl-C."""
    from pi_harness.config import load_config

    cfg = load_config()
    coord = _make_coordinator(cfg)
    if not coord.stop(run_id):
        typer.echo(f"error: unknown run {run_id!r}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"stopped {run_id}")


@app.command()
def observe(
    run: str = typer.Option(..., "--run", help="run_id to backfill/replay into the observability fork."),
    url: Optional[str] = typer.Option(None, "--url", help="Fork base URL (default OBS_SERVER_URL or http://127.0.0.1:43190)."),
    token: Optional[str] = typer.Option(None, "--token", help="Bearer token (default OBS_AUTH_TOKEN or devtoken)."),
    db: Optional[Path] = typer.Option(None, "--db", help="Trajectory DB to read (default: configured trajectory_db_path)."),
) -> None:
    """Translate a run's trajectory rows and POST them to the pi-observability fork."""
    import urllib.error

    from pi_harness.config import load_config
    from pi_harness.observability import bridge

    db_path = db or load_config().trajectory_db_path
    target = url or bridge.DEFAULT_URL
    try:
        result = bridge.backfill_run(run, url=target, token=token or bridge.DEFAULT_TOKEN, db_path=db_path)
    except urllib.error.URLError as exc:
        typer.echo(f"error: could not reach observability fork at {target}: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"bridged {result.sent} events for {run} "
        f"({result.ingested} ingested, {result.rejected} already present)"
    )


# --------------------------------------------------------------------------- #
# lint / decompose
# --------------------------------------------------------------------------- #


@app.command()
def lint(
    spec_path: Path = typer.Argument(..., help="Path to a spec .md file."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of pretty text."),
) -> None:
    """Lint a spec file. Exit code: 0 clean, 1 errors, 2 warnings."""
    from pi_harness.spec.linter import Linter

    spec = _load_spec_or_die(spec_path)
    result = Linter().lint(spec)

    if json_output:
        typer.echo(json.dumps({
            "score": result.score,
            "violations": [
                {"rule": v.rule_name, "severity": v.severity,
                 "message": v.message, "location": v.location}
                for v in result.violations
            ],
        }))
    else:
        typer.echo(f"score: {result.score:.2f}")
        for v in result.violations:
            typer.echo(f"  [{v.severity}] {v.rule_name}: {v.message} ({v.location})")

    if result.errors:
        raise typer.Exit(code=1)
    if result.warnings:
        raise typer.Exit(code=2)


@app.command()
def decompose(
    spec_path: Path = typer.Argument(..., help="Path to a spec .md file."),
) -> None:
    """Decompose a clean spec into ClawTeam-ready tasks. Refuses if lint < 1.0."""
    from pi_harness.config import load_config
    from pi_harness.spec.linter import Linter

    spec = _load_spec_or_die(spec_path)
    lint_result = Linter().lint(spec)
    if lint_result.score < 1.0:
        typer.echo(
            f"error: lint score is {lint_result.score:.2f}; decomposer requires 1.0",
            err=True,
        )
        raise typer.Exit(code=1)

    cfg = load_config()
    tasks = _decompose_or_die(spec, cfg)
    typer.echo(json.dumps([t.model_dump() for t in tasks], indent=2))


# --------------------------------------------------------------------------- #
# spec management
# --------------------------------------------------------------------------- #

spec_app = typer.Typer(help="Manage spec files under ~/.pi-harness/specs/.")
app.add_typer(spec_app, name="spec")

_SCAFFOLD_PATH = Path(__file__).parent / "spec" / "scaffold.md"


def _specs_dir() -> Path:
    d = spec_storage_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _spec_path_or_die(spec_id: str) -> Path:
    """Validated spec path (rejects path-traversal / unsafe ids) or clean exit."""
    try:
        return spec_path(spec_id)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@spec_app.command("new")
def spec_new(
    spec_id: str = typer.Argument(..., help="Slug (e.g. dark-mode-toggle)."),
    title: str = typer.Option(..., "--title", "-t", help="Human-readable title."),
    force: bool = typer.Option(False, "--force", help="Overwrite if exists."),
) -> None:
    """Scaffold a new spec at ~/.pi-harness/specs/<id>.md."""
    target = _spec_path_or_die(spec_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        typer.echo(f"error: {target} already exists (pass --force to overwrite)", err=True)
        raise typer.Exit(code=1)
    body = (
        _SCAFFOLD_PATH.read_text(encoding="utf-8")
        .replace("__SPEC_ID__", spec_id)
        .replace("__TITLE__", title)
        .replace("__CREATED_AT__", _now_iso())
    )
    target.write_text(body, encoding="utf-8")
    typer.echo(str(target))


@spec_app.command("ls")
def spec_ls() -> None:
    """List spec ids."""
    for f in sorted(_specs_dir().glob("*.md")):
        typer.echo(f.stem)


@spec_app.command("show")
def spec_show(spec_id: str) -> None:
    """Print a spec file."""
    target = _spec_path_or_die(spec_id)
    if not target.exists():
        typer.echo(f"error: {target} not found", err=True)
        raise typer.Exit(code=1)
    typer.echo(target.read_text(encoding="utf-8"))


@spec_app.command("rm")
def spec_rm(
    spec_id: str,
    force: bool = typer.Option(False, "--force", help="Skip confirmation."),
) -> None:
    """Delete a spec file."""
    target = _spec_path_or_die(spec_id)
    if not target.exists():
        typer.echo(f"error: {target} not found", err=True)
        raise typer.Exit(code=1)
    if not force and not typer.confirm(f"Delete {target}?", default=False):
        typer.echo("aborted")
        raise typer.Exit(code=0)
    target.unlink()
    typer.echo(f"removed {target}")


@spec_app.command("edit")
def spec_edit(spec_id: str) -> None:
    """Open the spec in $EDITOR (falls back to vi)."""
    target = _spec_path_or_die(spec_id)
    if not target.exists():
        typer.echo(f"error: {target} not found", err=True)
        raise typer.Exit(code=1)
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(target)], check=False)


# --------------------------------------------------------------------------- #
# serve
# --------------------------------------------------------------------------- #


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8800, "--port", help="Bind port (8080 is ClawTeam's board)."),
) -> None:
    """Boot the FastAPI dashboard backend (mounts spec router + runs + corpus
    + guards + ws on a single port)."""
    import uvicorn

    from pi_harness.api.server import create_app, load_dashboard_config
    from pi_harness.config import load_config

    fastapi_app = create_app(load_config(), load_dashboard_config())
    uvicorn.run(fastapi_app, host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    app()
