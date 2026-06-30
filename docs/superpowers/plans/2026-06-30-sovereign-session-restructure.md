# Sovereign Session Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an interactive sovereign `pi` session (`ms chat`) the front door — a Claude-Code-style local-model coding agent — and expose the existing team pipeline as a skill it can summon in the background with observability surfaced in-chat.

**Architecture:** Add three small, testable modules (`session.py`, `skills_setup.py`, `status.py`); wire two thin CLI commands (`ms chat`, `ms status`) and demote the launch-time linter gate to advisory; author three pi `SKILL.md` files (dispatch, shape-spec, choose-team-models). Everything else (coordinator/decomposer/ClawTeam/trajectory/improve, `ms launch --detach`, the fork dashboard, `ms models *`, `HarnessSettings`) is reused unchanged.

**Tech Stack:** Python ≥3.11, Typer (CLI), `pi` v0.73.1 (the agent runtime), httpx, pytest + `typer.testing.CliRunner`, SQLite trajectory store, OpenAI-compatible local model server (`mlx_lm.server`).

## Global Constraints

- Python floor: `requires-python = ">=3.11"`.
- Console entry points stay: `ms = "pi_harness.cli:app"`, `pi-harness = "pi_harness.cli:app"`.
- All tests run under the existing default `addopts = "-ra --strict-markers -m 'not smoke'"`. Never write or run smoke tests here (they launch a real ClawTeam team that commits to the branch).
- `PI_HARNESS_HOME` (default `~/.pi-harness`) is the harness home; pi's own home is `~/.pi/agent`. Keep them distinct.
- Local provider name is `LOCAL_PROVIDER_NAME = "harness-local"` (from `pi_harness/agent_wrapper.py`). Local default model: `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit` at `http://localhost:8080/v1`.
- The session and skills must route teams through `ms launch` (the mannschaft pipeline) — NEVER raw `clawteam`.
- Reversible, idempotent, non-destructive when touching user-global state (`~/.pi/agent/skills/`): move aside, never hard-delete.
- New modules hold the logic; CLI commands stay thin wrappers (keeps `cli.py` reviewable and the logic unit-testable without the TUI).

---

### Task 1: `pi_harness/session.py` — the `ms chat` launcher core

**Files:**
- Create: `pi_harness/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `pi_harness.agent_wrapper._resolve_provider_model(bucket: str) -> tuple[str, str]`, `pi_harness.agent_wrapper.LOCAL_PROVIDER_NAME`, `pi_harness.settings.load_settings()`, `pi_harness.pi_models.ensure_local_provider_from_settings(settings=None)`, `pi_harness.skills_setup.retire_raw_clawteam_skill()` and `repo_skills_dir()` (Task 2).
- Produces:
  - `CHAT_SYSTEM_PROMPT: str`
  - `resolve_session_model(settings=None, *, provider_override: str | None = None, model_override: str | None = None) -> tuple[str, str]` → `(pi_provider, model)`
  - `local_server_reachable(base_url: str, *, timeout: float = 2.0) -> bool`
  - `build_chat_argv(*, provider: str, model: str, session_dir: Path, skills_dir: Path, disable_thinking: bool, system_prompt: str = CHAT_SYSTEM_PROMPT) -> list[str]`
  - `launch_chat(*, provider_override: str | None = None, model_override: str | None = None, spawn=subprocess.run) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_session.py
from __future__ import annotations

from pathlib import Path

import pytest


def test_build_chat_argv_is_interactive_and_ungagged():
    from pi_harness.session import build_chat_argv

    argv = build_chat_argv(
        provider="harness-local",
        model="qwen",
        session_dir=Path("/h/sessions"),
        skills_dir=Path("/repo/skills"),
        disable_thinking=True,
    )
    # interactive: NONE of the batch gag-flags are present
    for gag in ("--print", "-p", "--no-session", "--no-skills",
                "--no-context-files", "--no-extensions", "--mode"):
        assert gag not in argv, f"{gag} must not be in an interactive chat argv"
    # the pieces we DO want
    assert argv[0] == "pi"
    assert argv[argv.index("--provider") + 1] == "harness-local"
    assert argv[argv.index("--model") + 1] == "qwen"
    assert argv[argv.index("--session-dir") + 1] == "/h/sessions"
    assert argv[argv.index("--skill") + 1] == "/repo/skills"
    assert "--thinking" in argv and argv[argv.index("--thinking") + 1] == "off"
    assert "--append-system-prompt" in argv


def test_build_chat_argv_no_thinking_flag_when_not_disabled():
    from pi_harness.session import build_chat_argv

    argv = build_chat_argv(
        provider="openai", model="gpt-5.4",
        session_dir=Path("/h/s"), skills_dir=Path("/r/skills"),
        disable_thinking=False,
    )
    assert "--thinking" not in argv


def test_resolve_session_model_defaults_to_orchestrator_bucket(monkeypatch):
    from pi_harness import session
    monkeypatch.setattr(
        "pi_harness.session._resolve_provider_model",
        lambda bucket: ("harness-local", "qwen") if bucket == "reasoning" else ("x", "y"),
    )
    assert session.resolve_session_model() == ("harness-local", "qwen")


def test_resolve_session_model_honors_overrides():
    from pi_harness import session
    assert session.resolve_session_model(
        provider_override="openai", model_override="gpt-5.4"
    ) == ("openai", "gpt-5.4")


def test_local_server_reachable_true_on_response(monkeypatch):
    from pi_harness import session

    class _Resp:  # any response means the socket answered
        status_code = 200

    monkeypatch.setattr(session.httpx, "get", lambda *a, **k: _Resp())
    assert session.local_server_reachable("http://localhost:8080/v1") is True


def test_local_server_reachable_false_on_connect_error(monkeypatch):
    from pi_harness import session

    def _boom(*a, **k):
        raise session.httpx.RequestError("nope")

    monkeypatch.setattr(session.httpx, "get", _boom)
    assert session.local_server_reachable("http://localhost:8080/v1") is False


def test_launch_chat_local_unreachable_exits_nonzero(monkeypatch, capsys):
    from pi_harness import session

    monkeypatch.setattr(session, "resolve_session_model", lambda **k: ("harness-local", "qwen"))
    monkeypatch.setattr(session, "ensure_local_provider_from_settings", lambda *a, **k: None)
    monkeypatch.setattr(session, "local_server_reachable", lambda *a, **k: False)
    spawned = []
    rc = session.launch_chat(spawn=lambda argv, **k: spawned.append(argv))
    assert rc != 0
    assert spawned == []  # never spawned pi
    assert "mlx_lm.server" in capsys.readouterr().out


def test_launch_chat_local_reachable_spawns_pi(monkeypatch, tmp_path):
    from pi_harness import session

    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    monkeypatch.setattr(session, "resolve_session_model", lambda **k: ("harness-local", "qwen"))
    monkeypatch.setattr(session, "ensure_local_provider_from_settings", lambda *a, **k: None)
    monkeypatch.setattr(session, "local_server_reachable", lambda *a, **k: True)
    monkeypatch.setattr(session, "retire_raw_clawteam_skill", lambda **k: None)

    captured = {}

    class _Done:
        returncode = 0

    def _spawn(argv, **k):
        captured["argv"] = argv
        return _Done()

    rc = session.launch_chat(spawn=_spawn)
    assert rc == 0
    assert captured["argv"][0] == "pi"
    assert "--provider" in captured["argv"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_session.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pi_harness.session'`.

- [ ] **Step 3: Implement `pi_harness/session.py`**

```python
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
        settings,
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
```

> Note: simplify the `home =` line to `home = _home_dir()` — the inlined guard above is a typo to avoid; the implementer should write `home = _home_dir()`.

> Note: in `launch_chat`, write `home = _home_dir()` exactly as shown — no guard expression.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_session.py -q`
Expected: PASS (all session tests green).

- [ ] **Step 5: (no commit here — see "Execution" note; commits are batched by the integrator)**

---

### Task 2: `pi_harness/skills_setup.py` — locate repo skills + reversibly retire the raw clawteam skill

**Files:**
- Create: `pi_harness/skills_setup.py`
- Test: `tests/test_skills_setup.py`

**Interfaces:**
- Produces:
  - `repo_skills_dir() -> Path` → the repo's `skills/` directory.
  - `raw_clawteam_skill_dir() -> Path` → `~/.pi/agent/skills/clawteam` (function so tests monkeypatch HOME).
  - `retire_raw_clawteam_skill(*, skills_root: Path | None = None) -> Path | None` → moves the stale skill aside (returns the backup path), or `None` if there was nothing to do. Idempotent, non-destructive, prints one log line on action.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_skills_setup.py
from __future__ import annotations

from pathlib import Path


def test_repo_skills_dir_points_at_repo_skills():
    from pi_harness.skills_setup import repo_skills_dir
    d = repo_skills_dir()
    assert d.name == "skills"
    assert (d / "pi-harness").exists()  # the dispatch skill lives here


def test_retire_noop_when_absent(tmp_path, capsys):
    from pi_harness.skills_setup import retire_raw_clawteam_skill
    root = tmp_path / "skills"
    root.mkdir()
    assert retire_raw_clawteam_skill(skills_root=root) is None
    assert "clawteam" not in capsys.readouterr().out


def test_retire_moves_aside_reversibly(tmp_path, capsys):
    from pi_harness.skills_setup import retire_raw_clawteam_skill
    root = tmp_path / "skills"
    (root / "clawteam").mkdir(parents=True)
    (root / "clawteam" / "SKILL.md").write_text("raw clawteam skill")

    backup = retire_raw_clawteam_skill(skills_root=root)

    assert backup is not None
    assert not (root / "clawteam").exists()           # original gone
    assert backup.exists()                             # content preserved
    assert (backup / "SKILL.md").read_text() == "raw clawteam skill"
    assert "clawteam" in capsys.readouterr().out        # logged


def test_retire_is_idempotent_with_suffix(tmp_path):
    from pi_harness.skills_setup import retire_raw_clawteam_skill
    root = tmp_path / "skills"
    # first disable
    (root / "clawteam").mkdir(parents=True)
    first = retire_raw_clawteam_skill(skills_root=root)
    assert first.name == "clawteam.disabled"
    # skill reinstalled, disable again -> new non-clobbering backup
    (root / "clawteam").mkdir()
    second = retire_raw_clawteam_skill(skills_root=root)
    assert second is not None and second != first and second.exists()
    assert first.exists()  # earlier backup untouched
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_skills_setup.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pi_harness.skills_setup'`.

- [ ] **Step 3: Implement `pi_harness/skills_setup.py`**

```python
# pi_harness/skills_setup.py
"""Skill provisioning for the sovereign session.

The session must route teams through the mannschaft pipeline, not the raw
`clawteam` CLI. A stale pi skill at ~/.pi/agent/skills/clawteam teaches the
value-stripped shortcut, so we reversibly move it aside on `ms chat` first-run.
"""
from __future__ import annotations

from pathlib import Path


def repo_skills_dir() -> Path:
    """The repo's skills/ directory (sibling of the pi_harness package)."""
    return Path(__file__).resolve().parents[1] / "skills"


def raw_clawteam_skill_dir() -> Path:
    return Path.home() / ".pi" / "agent" / "skills" / "clawteam"


def retire_raw_clawteam_skill(*, skills_root: Path | None = None) -> Path | None:
    """Move the stale raw-clawteam pi skill aside. Idempotent, non-destructive.

    Returns the backup path if something was moved, else None.
    """
    root = skills_root if skills_root is not None else raw_clawteam_skill_dir().parent
    target = root / "clawteam"
    if not target.exists():
        return None

    backup = root / "clawteam.disabled"
    if backup.exists():
        n = 1
        while (root / f"clawteam.disabled.{n}").exists():
            n += 1
        backup = root / f"clawteam.disabled.{n}"

    target.rename(backup)
    print(
        f"note: disabled the raw-clawteam pi skill (moved {target} -> {backup}); "
        f"restore with `mv {backup} {target}` if you want it back."
    )
    return backup
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_skills_setup.py -q`
Expected: PASS.

---

### Task 3: `pi_harness/status.py` — agent-consumable run status

**Files:**
- Create: `pi_harness/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: `pi_harness.trajectory.runs.get_run_summary(run_id, *, db_path=None) -> RunSummary | None`, `get_run(run_id, *, db_path=None) -> dict | None`, `pi_harness.trajectory.store.query_events(*, run_id=None, db_path=None) -> list[TrajectoryEvent]`.
- Produces:
  - `build_status(run_id: str, *, db_path=None) -> dict | None` — structured status; `None` if the run doesn't exist.
  - `render_status_human(status: dict) -> str`
  - `format_elapsed(seconds: float | None) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_status.py
from __future__ import annotations

from datetime import datetime, timezone


def _seed(db_path):
    from pi_harness.trajectory.runs import register_run, mark_run_status
    from pi_harness.trajectory.store import append_event
    from pi_harness.trajectory.schema import TrajectoryEvent

    # register_run / append_event / mark_* are the existing write APIs; if a
    # name differs, use the writer the other trajectory tests use.
    register_run(run_id="run-x", topology="sequential", db_path=db_path,
                 goal="g", spec_id="s")
    ev = TrajectoryEvent(
        run_id="run-x", agent_id="builder", step_id="1",
        ts=datetime(2026, 6, 30, tzinfo=timezone.utc), model="qwen",
        tool="edit", input={}, output={}, duration_ms=10,
        tokens_in=5, tokens_out=7, outcome="success",
        classification="tool_result",
    )
    append_event(ev, db_path=db_path)


def test_build_status_none_for_missing_run(tmp_path):
    from pi_harness.status import build_status
    assert build_status("nope", db_path=tmp_path / "t.db") is None


def test_build_status_reports_core_fields(tmp_path):
    from pi_harness.status import build_status
    db = tmp_path / "t.db"
    _seed(db)
    st = build_status("run-x", db_path=db)
    assert st["run_id"] == "run-x"
    assert "status" in st
    assert st["tokens_out"] >= 7
    assert any(a["agent_id"] == "builder" for a in st["agents"])


def test_render_status_human_is_one_block(tmp_path):
    from pi_harness.status import build_status, render_status_human
    db = tmp_path / "t.db"
    _seed(db)
    out = render_status_human(build_status("run-x", db_path=db))
    assert "run-x" in out
    assert "builder" in out
```

> Implementer: confirm the exact writer names by reading `pi_harness/trajectory/runs.py` and `store.py` (and how existing `tests/trajectory/test_runs.py` seeds data). Mirror that seeding; the assertions above only depend on the read side.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_status.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pi_harness.status'`.

- [ ] **Step 3: Implement `pi_harness/status.py`**

```python
# pi_harness/status.py
"""Concise, agent-consumable status for a single run.

Reads the trajectory store (never a live ClawTeam team, which may be torn down)
so `ms status <run_id>` works during and after a run. The dispatch skill reads
the --json form to narrate team progress in the chat.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pi_harness.trajectory.runs import get_run, get_run_summary
from pi_harness.trajectory.store import query_events


def format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def build_status(run_id: str, *, db_path: Any = None) -> dict | None:
    summary = get_run_summary(run_id, db_path=db_path)
    if summary is None:
        return None
    row = get_run(run_id, db_path=db_path) or {}
    branch = row.get("run_branch") or row.get("branch")

    events = query_events(run_id=run_id, db_path=db_path)
    last_by_agent: dict[str, Any] = {}
    task_transitions = 0
    for e in events:  # ordered ts asc -> last write wins
        last_by_agent[e.agent_id] = e
        if e.classification == "task_transition":
            task_transitions += 1

    if summary.wall_clock_s is not None:
        elapsed = summary.wall_clock_s
    elif summary.started_at is not None:
        end = summary.ended_at or datetime.now(timezone.utc)
        elapsed = (end - summary.started_at).total_seconds()
    else:
        elapsed = None

    return {
        "run_id": run_id,
        "status": summary.status,
        "agent_count": summary.agent_count or len(last_by_agent),
        "tokens_in": summary.total_tokens_in,
        "tokens_out": summary.total_tokens_out,
        "cost_usd": summary.total_cost_usd,
        "sovereign": summary.sovereign,
        "elapsed_s": elapsed,
        "branch": branch,
        "task_transitions": task_transitions,
        "agents": [
            {
                "agent_id": aid,
                "last_classification": e.classification,
                "last_tool": e.tool or None,
                "last_outcome": e.outcome,
                "last_ts": e.ts.isoformat() if e.ts else None,
            }
            for aid, e in sorted(last_by_agent.items())
        ],
    }


def render_status_human(status: dict) -> str:
    cost = "$0.00 (sovereign)" if status["sovereign"] else f"${status['cost_usd']:.4f}"
    head = (
        f"{status['run_id']} · status={status['status']} · "
        f"{status['agent_count']} agents · "
        f"{status['tokens_in']}in/{status['tokens_out']}out · {cost} · "
        f"{format_elapsed(status['elapsed_s'])}"
    )
    lines = [head]
    for a in status["agents"]:
        tool = f" tool={a['last_tool']}" if a["last_tool"] else ""
        lines.append(f"  {a['agent_id']:<12} {a['last_classification']}{tool} ({a['last_outcome']})")
    if status["branch"]:
        lines.append(f"  branch: {status['branch']}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_status.py -q`
Expected: PASS.

---

### Task 4: Wire `ms chat` + `ms status` and de-gate the launch linter (single `cli.py` change)

> All `cli.py` edits live in ONE task to avoid concurrent edits to the same file. Depends on Tasks 1–3.

**Files:**
- Modify: `pi_harness/cli.py` (add `chat` and `status` commands; swap `_lint_or_die` for advisory in `launch`)
- Test: `tests/test_cli_chat_status.py`

**Interfaces:**
- Consumes: `pi_harness.session.launch_chat(...)`, `pi_harness.status.build_status(...)`, `render_status_human(...)`, `pi_harness.config.load_config()` (for `trajectory_db_path`).
- Produces: CLI commands `ms chat [--provider X --model Y]`, `ms status <run_id> [--json]`, and a `_lint_advisory(spec)` helper used by `launch`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_chat_status.py
from __future__ import annotations

import json

from typer.testing import CliRunner

from pi_harness.cli import app

runner = CliRunner()


def test_chat_invokes_launch_chat(monkeypatch):
    calls = {}
    monkeypatch.setattr("pi_harness.cli.launch_chat",
                        lambda **k: calls.update(k) or 0)
    res = runner.invoke(app, ["chat", "--provider", "openai", "--model", "gpt-5.4"])
    assert res.exit_code == 0
    assert calls["provider_override"] == "openai"
    assert calls["model_override"] == "gpt-5.4"


def test_chat_propagates_nonzero(monkeypatch):
    monkeypatch.setattr("pi_harness.cli.launch_chat", lambda **k: 1)
    res = runner.invoke(app, ["chat"])
    assert res.exit_code == 1


def test_status_not_found_exits_nonzero(monkeypatch):
    monkeypatch.setattr("pi_harness.cli.build_status", lambda run_id, db_path=None: None)
    res = runner.invoke(app, ["status", "run-missing"])
    assert res.exit_code == 1
    assert "not found" in res.stdout.lower()


def test_status_json(monkeypatch):
    fake = {"run_id": "run-x", "status": "running", "agents": [], "sovereign": True,
            "cost_usd": 0.0, "tokens_in": 1, "tokens_out": 2, "agent_count": 0,
            "elapsed_s": 5, "branch": None, "task_transitions": 0}
    monkeypatch.setattr("pi_harness.cli.build_status", lambda run_id, db_path=None: fake)
    res = runner.invoke(app, ["status", "run-x", "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["run_id"] == "run-x"


def test_launch_does_not_block_on_lint_warnings(good_spec_with_warning, monkeypatch):
    """De-gate regression: a warning-only spec must launch, not Exit(2)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_coord = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    fake_coord.launch.return_value = type("H", (), {"run_id": "run-abc", "run_branch": None})()
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die", lambda spec, cfg: [])
    monkeypatch.setattr("pi_harness.cli.ensure_local_provider_from_settings", lambda *a, **k: None)
    res = runner.invoke(app, ["launch", str(good_spec_with_warning), "--detach"])
    assert res.exit_code == 0, res.stdout
```

> Implementer: add a `good_spec_with_warning` fixture (a spec that the linter flags as warning-only, not error) to this test module or `tests/conftest.py`, modeled on the existing `good_spec` fixture in `tests/test_cli.py`. If producing a guaranteed-warning spec is fragile, instead monkeypatch `pi_harness.cli._lint_advisory` to a no-op and assert it was called (the point is launch no longer hard-exits on lint).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli_chat_status.py -q`
Expected: FAIL — `chat`/`status` commands don't exist; `cli` has no `launch_chat`/`build_status` names.

- [ ] **Step 3: Implement the `cli.py` changes**

Add near the other command imports/definitions:

```python
# in pi_harness/cli.py — module-level imports used by the new commands
from pi_harness.session import launch_chat
from pi_harness.status import build_status, render_status_human


@app.command()
def chat(
    provider: Optional[str] = typer.Option(None, "--provider", help="Override the session provider (local | api)."),
    model: Optional[str] = typer.Option(None, "--model", help="Override the session model id."),
) -> None:
    """Start the sovereign interactive coding session (local model by default).

    Ungags `pi`: interactive, session-saving, skills + context aware. For
    team-sized work it offers to dispatch the agentic-team pipeline."""
    rc = launch_chat(provider_override=provider, model_override=model)
    if rc != 0:
        raise typer.Exit(code=rc)


@app.command()
def status(
    run_id: str = typer.Argument(..., help="The run_id to report on."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Concise status for a run (for in-chat narration or quick checks)."""
    from pi_harness.config import load_config

    cfg = load_config()
    st = build_status(run_id, db_path=cfg.trajectory_db_path)
    if st is None:
        typer.echo(f"run {run_id} not found", err=False)
        raise typer.Exit(code=1)
    if as_json:
        import json

        typer.echo(json.dumps(st, indent=2))
    else:
        typer.echo(render_status_human(st))
```

De-gate the linter in `launch`. Add the advisory helper and replace the gate call:

```python
def _lint_advisory(spec) -> None:
    """Run the linter and print findings as SUGGESTIONS. Never blocks a launch
    (the blocking gate is gone — spec quality now comes from the interactive
    shape-spec skill). `ms lint` still exits by severity for explicit checks."""
    from pi_harness.spec.linter import Linter

    result = Linter().lint(spec)
    issues = list(result.errors) + list(result.warnings)
    if issues:
        typer.echo("spec suggestions (advisory — launching anyway):")
        for v in issues:
            typer.echo(f"  [{v.rule_name}] {v.message} ({v.location})")
```

In the `launch` body, change:

```python
    spec = _load_spec_or_die(spec_path)
    _lint_or_die(spec, allow_warnings=allow_warnings)
```

to:

```python
    spec = _load_spec_or_die(spec_path)
    _lint_advisory(spec)
```

Leave `_lint_or_die` defined (the standalone `ms lint` command keeps its severity-based exit codes); only the `launch` path stops calling it. The `--allow-warnings` option on `launch` becomes a harmless no-op; keep it for backward-compat.

- [ ] **Step 4: Run the targeted + adjacent tests**

Run: `pytest tests/test_cli_chat_status.py tests/test_cli.py -q`
Expected: PASS (new commands work; existing launch tests still green — they pass `--detach` and monkeypatch the coordinator).

---

### Task 5: Rewrite `skills/pi-harness/SKILL.md` — the background dispatch + observe skill

**Files:**
- Modify (full rewrite): `skills/pi-harness/SKILL.md`

**Interfaces:** prose skill for the pi session. References commands: `ms launch <spec> --detach`, `ms status <run_id>`, `ms up`, `ms stop <run_id>`, the `choose-team-models` skill.

- [ ] **Step 1: Replace the file with the new dispatch skill**

```markdown
---
name: pi-harness
description: >
  Use when work is large enough to benefit from a parallel agentic team — the
  user asks to "build/implement X with a team", "spin up agents", "run the
  harness", or the current task clearly exceeds efficient solo work. Dispatches
  the mannschaft team pipeline IN THE BACKGROUND via `ms launch --detach`, after
  confirming with the user, and surfaces live observability in the chat. Never
  shells out to raw clawteam.
version: 1.0.0
---

# pi-harness — dispatch an agentic team (background + observable)

You are the sovereign session. This skill lets you summon the mannschaft
multi-agent pipeline as a power tool. The team runs in the background so the
chat stays live and you can report progress.

## When to use
- The user explicitly asks for a team / the harness, OR
- You judge the work is team-sized (multi-file feature, parallelizable scope).

## Protocol

1. **Have a spec.** If the user has a spec file or `~/.pi-harness/specs/<id>.md`,
   use it. If not, use the `shape-spec` skill first to build one interactively.

2. **CONFIRM before dispatching.** Always ask, e.g.: "This is team-sized — spin
   up an agentic team to build it in the background? [y/n]". Do not launch
   without a yes.

3. **Pick models.** Unless the user says "use my defaults", run the
   `choose-team-models` skill so they can set orchestrator/builder per dispatch
   (recommend API reasoning + local builder for reliable decomposition).

4. **Launch in the background** with Bash:
   `ms launch <spec-path> --detach`
   Capture the printed `run_id` (and the `isolated on branch:` line if shown).

5. **Surface observability.** Tell the user the run_id and the fork dashboard
   deep-link `<dashboard>/runs/<run_id>`. If the dashboard isn't running, tell
   them to start it: `ms up`. Say they can ask "status" anytime.

6. **Report progress on demand / on a cadence** with Bash:
   `ms status <run_id> --json`
   Summarize it in plain language (tasks done, current agent activity, tokens,
   cost, elapsed). Keep working with the user in the meantime.

7. **On completion** (`ms status` shows a terminal state): report success/failure
   and the run branch; offer to diff/review/merge. On failure, surface the
   branch for inspection; `ms stop <run_id>` cleans up a stuck run.

## Do NOT
- Do not launch without explicit confirmation.
- Do not block the session waiting for the team (always `--detach`).
- Do not shell out to `clawteam` directly — `ms launch` is the only path.
- Do not re-run `ms decompose` before `ms launch` (launch decomposes once).
```

- [ ] **Step 2: Validate frontmatter + referenced commands exist**

Run: `python -c "import re,sys; t=open('skills/pi-harness/SKILL.md').read(); assert t.startswith('---'); assert 'name: pi-harness' in t and 'ms launch' in t and 'ms status' in t; print('ok')"`
Expected: `ok`.

---

### Task 6: `skills/shape-spec/SKILL.md` — interactive spec shaping (replaces the linter gate)

**Files:**
- Create: `skills/shape-spec/SKILL.md`

- [ ] **Step 1: Create the file**

```markdown
---
name: shape-spec
description: >
  Use when the user wants to define WHAT to build before building it — "let's
  plan a feature", "write a spec/PRD", "I want to build X but it's fuzzy", or as
  the on-ramp before dispatching an agentic team. Interactively accretes goal,
  constraints, non-goals, and acceptance criteria through dialogue, writes a
  harness spec, and hands off to model selection + team dispatch. Linting is
  advisory here, never a gate.
version: 1.0.0
---

# shape-spec — turn a fuzzy idea into a launchable spec

Replace rigid spec-writing + a blocking linter with a short collaborative
conversation. The output is a spec the mannschaft pipeline can decompose.

## Protocol

1. **Understand the idea.** Ask focused questions ONE at a time to pin down:
   - **Goal** — one or two sentences: what should exist when done.
   - **Acceptance criteria** — concrete, checkable statements ("`POST /todos`
     returns 201 with a generated id").
   - **Constraints** — language/runtime/libraries/scope limits.
   - **Non-goals** — explicitly out of scope.
   Don't over-ask; stop when the four are clear.

2. **Write the spec.** Scaffold and fill it via Bash:
   `ms spec new <id> --title "<title>"`
   then edit `~/.pi-harness/specs/<id>.md` to fill goal / acceptance_criteria /
   constraints / non_goals (use your edit tool).

3. **Advisory lint (not a gate).** Run `ms lint ~/.pi-harness/specs/<id>.md --json`
   and weave any findings into the conversation as SUGGESTIONS. Offer to tighten
   the spec, but never refuse to proceed.

4. **Hand off.** Ask if they want to build it now. If yes, run `choose-team-models`,
   then the `pi-harness` dispatch skill with the spec path. If they'd rather you
   build it solo, just do the work hands-on.

## Do NOT
- Do not block on lint findings — they are advice.
- Do not invent acceptance criteria the user didn't agree to.
```

- [ ] **Step 2: Validate**

Run: `python -c "t=open('skills/shape-spec/SKILL.md').read(); assert 'name: shape-spec' in t and 'ms spec new' in t and 'ms lint' in t; print('ok')"`
Expected: `ok`.

---

### Task 7: `skills/choose-team-models/SKILL.md` — guided per-dispatch model roster

**Files:**
- Create: `skills/choose-team-models/SKILL.md`

- [ ] **Step 1: Create the file**

```markdown
---
name: choose-team-models
description: >
  Use right before dispatching an agentic team (after shape-spec, or when the
  pi-harness skill offers it) to choose which model is orchestrator and which is
  builder for this run. Surfaces the sovereign-vs-mixed trade-off and the
  single-local-server constraint, then applies the choice with `ms models set`.
version: 1.0.0
---

# choose-team-models — pick orchestrator & builder before a team runs

## Protocol

1. **Show the current roster + options** with Bash:
   `ms models list`
   This prints the current orchestrator/builder buckets, the available local
   models (at the configured base_url), and cloud models if a key is stored.

2. **Recommend, then ask.** Explain the trade-off:
   - **Sovereign (default):** orchestrator + builder both local — $0, offline,
     fully private. Caveat: a fully-local autonomous team on a ~30B model may
     struggle to converge on complex decompositions.
   - **Mixed (most reliable):** orchestrator = an API model (e.g. gpt-5.x) for
     dependable decomposition + review; builder = local for sovereign,
     cost-free code generation. This is the proven config.
   Ask the user which orchestrator model and which builder model they want.

3. **Encode the single-local-server constraint.** `mlx_lm.server` serves ONE
   model. So "orchestrator = local model A AND builder = local model B (a
   DIFFERENT local model)" is NOT servable from one local server. Allow only:
   same local model for both buckets, OR a mixed API/local split. Warn and
   re-ask if they pick two different local models.

4. **Apply (sticky)** with Bash, once per bucket:
   `ms models set --bucket orchestrator --provider <local|api> --model <id>`
   `ms models set --bucket builder --provider <local|api> --model <id>`
   These persist as the new defaults. (If a key is needed for `api`, point them
   to `ms models key`.)

5. **Hand off** to the `pi-harness` dispatch skill to launch the team.

## Do NOT
- Do not set two DIFFERENT local models across buckets (unservable).
- Do not change models while a run is active (`ms models set` will refuse).
```

- [ ] **Step 2: Validate**

Run: `python -c "t=open('skills/choose-team-models/SKILL.md').read(); assert 'name: choose-team-models' in t and 'ms models set' in t and 'ms models list' in t; print('ok')"`
Expected: `ok`.

---

### Task 8: v1 user manual + expansion-decisions note

**Files:**
- Create: `docs/demo/SOVEREIGN_SESSION_v1.md` (how to use v1)
- Create: `docs/superpowers/EXPANSION-DECISIONS.md` (record of deferred/expansion decisions)

- [ ] **Step 1: Write the user manual** covering: prerequisites (start `mlx_lm.server`), `ms chat` to start the session, what the session can do solo, how to shape a spec (`shape-spec`), how to pick models (`choose-team-models`), how a team gets dispatched + observed (`ms status`, `ms up`, dashboard deep-link), `ms stop`, and the sovereign-vs-mixed model guidance. Use real commands verbatim.

- [ ] **Step 2: Write the expansion-decisions note** capturing: Phase 4 (live-streaming pi extension), per-run model overrides (vs sticky), auto-boot/health-managed dashboard, `ms` bare-invocation aliasing — each with the decision and rationale, copied/condensed from the spec's "Deferred enhancements".

- [ ] **Step 3: Validate both files exist and are non-empty**

Run: `test -s docs/demo/SOVEREIGN_SESSION_v1.md && test -s docs/superpowers/EXPANSION-DECISIONS.md && echo ok`
Expected: `ok`.

---

### Task 9: Full-suite verification

- [ ] **Step 1: Run the whole suite (smoke excluded by addopts)**

Run: `pytest -q`
Expected: all green (previously 712 passed; new tests add to that). Fix any regressions before finishing.

- [ ] **Step 2: Sanity-check the CLI surface loads**

Run: `python -c "from pi_harness.cli import app; import typer; print('cli ok')"` and `ms --help` (confirm `chat` and `status` appear).
Expected: `chat` and `status` listed in help.

---

## Execution note (commits)

Because this plan is executed by parallel agents sharing one working tree, **agents do not run `git commit`** — they write files and run only their own task's tests. The orchestrator commits in logical chunks after the full suite is green (Task 9), e.g.: (1) modules + tests, (2) cli wiring + de-gate, (3) skills, (4) docs.

## Self-review notes

- **Spec coverage:** P1 `ms chat` → Task 1+4; clawteam retirement (D5) → Task 2 (+ called from Task 1); P2 `ms status` → Task 3+4; dispatch skill → Task 5; P3 shape-spec → Task 6; choose-team-models (D10) → Task 7; de-gate linter (D6) → Task 4; user manual + expansion note → Task 8; reuse of `ms launch --detach`/fork dashboard/`ms models *` → referenced in skills, no code change. Phase 4 explicitly deferred (not implemented).
- **Type consistency:** `launch_chat(*, provider_override, model_override, spawn)`, `build_status(run_id, *, db_path) -> dict | None`, `retire_raw_clawteam_skill(*, skills_root) -> Path | None`, `resolve_session_model(...) -> tuple[str,str]` are used identically in their tests and in `cli.py`.
- **Known soft spots flagged for implementers:** (a) `home = _home_dir()` in `launch_chat` (ignore the inlined typo in the draft); (b) confirm trajectory writer names when seeding `tests/test_status.py`; (c) the `good_spec_with_warning` fixture or the monkeypatch fallback in Task 4.
