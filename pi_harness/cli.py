"""ms command-line entry point (aka ``pi-harness``, the legacy alias).

The canonical headless surface. Every subcommand is a thin shim over the same
in-process modules the FastAPI editor uses — no duplicated business logic.

  ms launch <spec>      lint -> decompose -> spec_to_runspec -> Coordinator.launch
  ms lint <spec>        pure linter; exits 0/1/2 by severity
  ms decompose <spec>   print JSON task list; gated on lint score 1.0
  ms spec new|ls|show|rm|edit   manage ~/.pi-harness/specs/*.md
  ms serve              boot the dashboard backend (spec router + runs + corpus + guards + ws)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from pi_harness import __version__
from pi_harness.spec.format import parse_spec_file, spec_path, spec_storage_dir
from pi_harness.spec.runspec import build_coordinator, spec_to_runspec

app = typer.Typer(
    name="ms",
    help="mannschaft (ms) — spec-driven multi-agent run launcher.",
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
        help="Show the ms version and exit.",
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
    # Sovereign default: register the local provider in pi's models.json from
    # the saved settings so a run uses the local MLX endpoint without first
    # touching the Settings UI (no-op when all buckets are `api`).
    from pi_harness.pi_models import ensure_local_provider_from_settings
    ensure_local_provider_from_settings()
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
        typer.echo(f"  detached — stop it with: ms stop {handle.run_id}")
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
    run: Optional[str] = typer.Option(None, "--run", help="run_id to backfill/replay into the observability fork (required unless --follow)."),
    url: Optional[str] = typer.Option(None, "--url", help="Fork base URL (default OBS_SERVER_URL or http://127.0.0.1:43190)."),
    token: Optional[str] = typer.Option(None, "--token", help="Bearer token (default OBS_AUTH_TOKEN)."),
    db: Optional[Path] = typer.Option(None, "--db", help="Trajectory DB to read (default: configured trajectory_db_path)."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream events live to the fork until runs finish (Ctrl-C to stop)."),
) -> None:
    """Translate a run's trajectory rows and POST them to the pi-observability fork."""
    import urllib.error

    from pi_harness.config import load_config
    from pi_harness.observability import bridge

    cfg = load_config()
    db_path = db or cfg.trajectory_db_path
    target = url or cfg.obs_server_url
    auth = token or cfg.obs_auth_token

    if follow:
        typer.echo(f"following all runs -> {target} (Ctrl-C to stop)")
        bridge.follow_runs(url=target, token=auth, db_path=db_path)
        return

    if not run:
        typer.echo("error: --run is required unless --follow is given", err=True)
        raise typer.Exit(code=1)

    try:
        result = bridge.backfill_run(run, url=target, token=auth, db_path=db_path)
    except urllib.error.URLError as exc:
        typer.echo(f"error: could not reach observability fork at {target}: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"bridged {result.sent} events for {run} "
        f"({result.ingested} ingested, {result.rejected} already present)"
    )


# --------------------------------------------------------------------------- #
# up / doctor — the one-command observability launcher + preflight
# --------------------------------------------------------------------------- #


def _fork_server_entry(fork_dir: Path) -> list[str]:
    """Resolve the Bun argv that boots the fork's observability server.

    The fork has no root ``package.json`` start script; its justfile runs
    ``cd apps/observability && bun server.ts``, so the entry relative to the
    fork root is ``apps/observability/server.ts``. We run it explicitly via
    ``bun run <entry>`` from the fork root (the documented default).
    """
    return ["bun", "run", "apps/observability/server.ts"]


@app.command()
def up(
    no_ui: bool = typer.Option(
        False, "--no-ui", help="Skip the Next.js dashboard UI process."
    ),
    ready_timeout: float = typer.Option(
        30.0, "--ready-timeout", help="Seconds to wait for health checks before tailing."
    ),
) -> None:
    """Boot the full observability stack: the fork's Bun server, the live bridge
    tailer, the FastAPI dashboard, and (unless --no-ui) the Next.js UI.

    Blocks until a child exits or Ctrl-C. All children are torn down on exit.
    """
    from urllib.parse import quote

    from pi_harness.config import load_config
    from pi_harness.observability.supervisor import Proc, Supervisor

    cfg = load_config()

    fork_env = {
        **os.environ,
        "OBS_AUTH_TOKEN": cfg.obs_auth_token,
        "OBS_PORT": str(cfg.obs_port),
        "OBS_HOST": cfg.obs_host,
        "OBS_DEV": "1" if not cfg.obs_auth_token else "",
    }
    procs = [
        Proc(
            "fork",
            _fork_server_entry(cfg.obs_fork_dir),
            cwd=cfg.obs_fork_dir,
            env=fork_env,
            health_url=f"{cfg.obs_server_url}/health",
        ),
        Proc(
            "bridge",
            [sys.executable, "-m", "pi_harness.cli", "observe", "--follow"],
            env=dict(os.environ),
        ),
        Proc(
            "api",
            [sys.executable, "-m", "pi_harness.api.server"],
            env=dict(os.environ),
            health_url="http://127.0.0.1:8800/healthz",
        ),
    ]
    if not no_ui:
        procs.append(
            Proc(
                "ui",
                ["npm", "run", "dev"],
                cwd=Path("ui"),
                env=dict(os.environ),
                health_url="http://127.0.0.1:3000",
            )
        )

    base = cfg.obs_server_url.rstrip("/")
    frag = "#view=race&pool=<run_id>&hide_after=never&show_hidden=1"
    link = (
        f"{base}/?token={quote(cfg.obs_auth_token)}{frag}"
        if cfg.obs_auth_token
        else f"{base}/{frag}"
    )
    typer.echo(f"observability fork UI: {base}/")
    typer.echo(f"run deep-link template: {link}")
    typer.echo("starting processes: " + ", ".join(p.name for p in procs))

    raise typer.Exit(Supervisor(procs).run(ready_timeout=ready_timeout))


@app.command()
def doctor() -> None:
    """Preflight the observability stack: bun, the fork checkout, npm, the UI
    deps, free ports, and the auth token. Exits non-zero if a hard check fails."""
    import shutil
    import socket
    from urllib.parse import quote

    from pi_harness.config import load_config

    cfg = load_config()
    ok = True

    def check(label: str, passed: bool, *, hard: bool = True) -> None:
        nonlocal ok
        mark = "✓" if passed else "✗"
        typer.echo(f"  {mark} {label}")
        if not passed and hard:
            ok = False

    def port_free(port: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    typer.echo("observability preflight:")

    check("bun on PATH", shutil.which("bun") is not None)
    entry = cfg.obs_fork_dir / "apps" / "observability" / "server.ts"
    check(f"fork checkout at {cfg.obs_fork_dir}", cfg.obs_fork_dir.exists())
    check(f"fork server entry {entry}", entry.exists())

    check("npm on PATH", shutil.which("npm") is not None)
    check("ui/node_modules present", (Path("ui") / "node_modules").exists())

    check(f"port 8800 free (api)", port_free(8800))
    check(f"port 3000 free (ui)", port_free(3000))
    check(f"port {cfg.obs_port} free (fork)", port_free(cfg.obs_port))

    check(
        "OBS_AUTH_TOKEN set (required when obs enabled)",
        (not cfg.obs_enabled) or bool(cfg.obs_auth_token),
    )

    base = cfg.obs_server_url.rstrip("/")
    frag = "#view=race&pool=<run_id>&hide_after=never&show_hidden=1"
    link = (
        f"{base}/?token={quote(cfg.obs_auth_token)}{frag}"
        if cfg.obs_auth_token
        else f"{base}/{frag}"
    )
    typer.echo(f"  deep-link template: {link}")

    if not ok:
        raise typer.Exit(1)


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
# model & provider management
# --------------------------------------------------------------------------- #

models_app = typer.Typer(help="Discover and manage LLM providers & models.")
app.add_typer(models_app, name="models")

_BUCKETS = ("orchestrator", "builder")


def _active_run_or_none(cfg) -> Optional[str]:
    """Idle-gate source of truth — the same query the /settings/run-active route
    uses, so CLI and GUI never disagree."""
    from pi_harness.trajectory.runs import query_run_summaries

    rows = query_run_summaries(status="running", limit=1, db_path=cfg.trajectory_db_path)
    return rows[0].run_id if rows else None


@models_app.command("set")
def models_set(
    bucket: str = typer.Option(..., "--bucket", help="orchestrator | builder"),
    provider: str = typer.Option(..., "--provider", help="local | api"),
    model: str = typer.Option(..., "--model", help="Model id to assign."),
) -> None:
    """Assign a model to a bucket. Blocked while a run is building."""
    from dataclasses import replace as dc_replace

    from pi_harness.config import load_config
    from pi_harness.settings import BucketConfig, load_settings, save_settings

    if bucket not in _BUCKETS:
        typer.echo(f"error: --bucket must be one of {_BUCKETS}", err=True)
        raise typer.Exit(code=2)
    if provider not in ("local", "api"):
        typer.echo("error: --provider must be 'local' or 'api'", err=True)
        raise typer.Exit(code=2)

    cfg = load_config()
    active = _active_run_or_none(cfg)
    if active:
        typer.echo(
            f"error: run {active} is active; stop it (`ms stop {active}`) before switching models",
            err=True,
        )
        raise typer.Exit(code=1)

    settings = dc_replace(load_settings(), **{bucket: BucketConfig(provider=provider, model=model)})
    save_settings(settings)
    if provider == "local":
        # Mirror the PUT /settings/models side-effect: register the local
        # provider in pi's models.json so the picker isn't a lie.
        from pi_harness.pi_models import ensure_local_provider_from_settings

        ensure_local_provider_from_settings(settings)
    typer.echo(f"{bucket} → {provider}:{model}")


@models_app.command("key")
def models_key(
    provider: str = typer.Option("openai", "--provider", help="Provider to set a key for."),
) -> None:
    """Securely store an API key (hidden prompt); validated via discovery."""
    import getpass

    from pi_harness import discovery, keystore

    if provider not in keystore.PROVIDER_ENV:
        typer.echo(f"error: unknown provider {provider!r}", err=True)
        raise typer.Exit(code=2)
    value = getpass.getpass(f"{provider} API key: ")
    if not value.strip():
        typer.echo("error: empty key", err=True)
        raise typer.Exit(code=1)
    result = discovery.list_models(provider, api_key=value)
    if result.get("error") or not result.get("models"):
        typer.echo("error: invalid or unauthorized key", err=True)
        raise typer.Exit(code=1)
    keystore.set_key(provider, value)
    typer.echo(
        f"stored {provider} key {keystore.mask(value)} "
        f"({len(result['models'])} models available)"
    )


@models_app.command("list")
def models_list() -> None:
    """Show current bucket selection + available models (local always; cloud if
    a key is stored)."""
    from pi_harness import discovery, keystore
    from pi_harness.settings import load_settings

    s = load_settings()
    typer.echo(f"orchestrator: {s.orchestrator.provider}:{s.orchestrator.model}")
    typer.echo(f"builder:      {s.builder.provider}:{s.builder.model}")

    local = discovery.list_models("local", base_url=s.local_base_url)
    typer.echo(f"\nlocal @ {s.local_base_url}:")
    if local.get("error"):
        typer.echo(f"  ({local['error']})")
    for m in local.get("models", []):
        typer.echo(f"  {m}")

    if keystore.has_key("openai"):
        cloud = discovery.list_models("openai", api_key=keystore.get_key("openai"))
        typer.echo("\nopenai (cloud):")
        if cloud.get("error"):
            typer.echo(f"  ({cloud['error']})")
        for m in cloud.get("models", []):
            typer.echo(f"  {m}")
    else:
        typer.echo("\nopenai (cloud): no key stored — run `ms models key`")


@app.command()
def setup() -> None:
    """Interactive first-run setup: pick a provider, connect, assign models."""
    from pi_harness import discovery, keystore
    from pi_harness.settings import BucketConfig, HarnessSettings, load_settings, save_settings

    s = load_settings()
    provider = typer.prompt("Provider [local/api]", default="local").strip()
    if provider not in ("local", "api"):
        typer.echo("error: provider must be 'local' or 'api'", err=True)
        raise typer.Exit(code=2)

    base_url = s.local_base_url
    if provider == "api":
        if not keystore.has_key("openai"):
            models_key(provider="openai")  # hidden prompt + validate + store
        avail = discovery.list_models("openai", api_key=keystore.get_key("openai"))
    else:
        base_url = typer.prompt("Local server base URL", default=s.local_base_url).strip()
        avail = discovery.list_models("local", base_url=base_url)

    models = avail.get("models", [])
    if models:
        typer.echo("Available models:")
        for m in models:
            typer.echo(f"  - {m}")
    default_model = models[0] if models else ""
    orch = typer.prompt("Model for orchestrator bucket", default=default_model).strip()
    bld = typer.prompt("Model for builder bucket", default=orch).strip()

    settings = HarnessSettings(
        orchestrator=BucketConfig(provider=provider, model=orch),
        builder=BucketConfig(provider=provider, model=bld),
        local_base_url=base_url,
    )
    save_settings(settings)
    if provider == "local":
        from pi_harness.pi_models import ensure_local_provider_from_settings

        ensure_local_provider_from_settings(settings)
    typer.echo(f"saved: orchestrator={provider}:{orch}  builder={provider}:{bld}")


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
