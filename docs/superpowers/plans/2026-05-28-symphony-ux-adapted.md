# Symphony UX (Adapted) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the full Symphony UX dashboard — a FastAPI backend + Next.js frontend that lists runs (with real status/cost/topology/lineage), inspects per-agent timelines with guide/sensor markers, branches runs, watches corpus health, edits/launches specs, and reviews guard promotions — wired against the **real** Plan 2/3/5/6/7 APIs, plus the upstream additions those features require.

**Why this supersedes `2026-05-25-symphony-ux.md`:** the original was written against imagined upstream APIs that don't match what shipped (`query_runs` returns dicts not `RunSummary`; no `subscribe`; `Coordinator.launch(RunSpec)->RunHandle` with no `branch_from`; `suggest_promotions->PromotionSuggestion`; `spec.editor` is a FastAPI *app* not a router; no `Curator.restore_archived`). Executing it verbatim (its `conftest` monkeypatches fictional symbols with `raising=False`) would pass tests against fabricated stubs while the backend can't wire to the harness. See memory `project_symphony_ux_v1.md`.

**Architecture:** Five new/extended backend layers feed one FastAPI app, which a Next.js App Router frontend consumes via a typed client. Tests seed **real** temp SQLite/corpus/spec stores — NO mocks of upstream modules (mocking is what hid the drift). Layers:
1. **Run registry + cost** (`pi_harness/trajectory/runs.py`, `cost.py`) — persists run metadata at launch/completion; derives cost from event tokens × a model price table. Source of real status/topology/timestamps/lineage.
2. **Level-1 branch** (`Coordinator.branch`) — reloads the parent run's serialized RunSpec, applies overrides, launches a child tagged with lineage. NOT mid-run replay.
3. **Corpus restore** (`Curator.restore_archived`) — moves an archived entry back to its classification dir + git-commits.
4. **FastAPI backend** (`pi_harness/api/`) — runs/timeline/branch/corpus/guards routes + WebSocket tailer; mounts the spec router (refactored out of Plan 7's app).
5. **Next.js frontend** (`ui/`) — adapted from the original plan's components with corrected DTO shapes and real branch/cost/gauges.
6. **Live-capture wrapper** (separate, spike-first, credit-required) — makes real runs emit tool/token/firing events so cost + timeline fill in.

**Tech Stack:**
- Backend: Python 3.10+, `fastapi[standard]`, `uvicorn`, `websockets`, `pydantic` v2, `pytest`, `pytest-asyncio`, `httpx`. Existing: `aiosqlite`, `tomli_w`, `GitPython`.
- Frontend: Node 20+, `pnpm`, Next.js 14 (App Router), React 18, TS strict, TailwindCSS, `@tanstack/react-query`, `lucide-react`, `openapi-typescript` (dev), `@playwright/test`.

---

## Conventions (apply to every task)

- **TDD, backend.** Every function/route gets a failing test first. Run `uv run pytest <file> -v` after each task.
- **NEVER run the full suite without `-m "not smoke"`.** Smoke tests launch a real ClawTeam team that git-commits to your branch and spends credit (memory `feedback_smoke_test_hazard.md`). All commands below pin specific files or add `-m "not smoke"`.
- **No mocks of upstream `pi_harness` modules.** Seed real temp stores: `write_event(...)` into a tmp SQLite, real corpus files via `corpus.format.serialize_entry`, real spec files via `spec.format.serialize_spec`. Mocking is what hid the API drift.
- **Type hints + pydantic models** on every route — never bare `dict`. `from __future__ import annotations` at module top.
- **TypeScript strict.** No `any` without `// @ts-expect-error <reason>`.
- **Conventional commits**, one per completed task: `feat(trajectory|api|ui|topology|corpus):`, `test(...)`, `chore(...)`.
- **Absolute paths** in shell commands, rooted at `/Users/pranavnair/Desktop/Personal/mannschaft`.
- **Frontend commands from `ui/`** only: `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm <cmd>`.

---

## Verified upstream surface (read before starting — these are REAL signatures)

- `pi_harness.config`: `load_config(env_file=".env") -> Config`; frozen `Config(openai_api_key, reasoning_model, fast_model, clawteam_state_dir: Path, corpus_root: Path, trajectory_db_path: Path)`. No `api_*`/`frontend_origin`.
- `pi_harness.trajectory.store`: `init_db(db_path=None)`, `write_event(event, *, db_path=None)`, `query_events(*, run_id=None, agent_id=None, since: datetime|None=None, limit=None, db_path=None) -> list[TrajectoryEvent]`, `query_runs(*, limit=None, db_path=None) -> list[dict{run_id, latest_ts, event_count, agent_ids}]`.
- `pi_harness.trajectory.schema.TrajectoryEvent`: `run_id, agent_id, step_id, ts(datetime, tz-aware), model, tool, input: Mapping, output: Mapping, duration_ms, tokens_in, tokens_out, outcome∈{success,error,blocked,timeout}, classification∈{tool_call,tool_result,message,task_transition,guide_fired,sensor_fired}, corpus_refs, corpus_cited`. `from_row`/`to_row` for SQLite.
- `pi_harness.topology.base`: `RunSpec(goal, agents: list[AgentSpec], mode: TopologyMode, sync_mode: SyncMode, corpus_classifications: list[str], session_id=None, executor="pi", sync_profile=None, tasks: list[TaskDef]|None=None)`; `RunHandle(run_id, team_name, started_at, topology: TopologyMode, session_id=None)`; `RunResult(run_handle, success: bool, terminal_statuses: dict, error=None)`; `AgentSpec(name, role: Role, model_tier: ModelTier, tools, expertise_classifications, task_prompt=None)`; enums `TopologyMode`, `Role`, `ModelTier`, `SyncMode`.
- `pi_harness.topology.coordinator.Coordinator(config, clawteam_client, corpus_reader, improve_runner)`; `.launch(spec: RunSpec) -> RunHandle`; `.wait_for_completion(handle, timeout) -> RunResult`; `.on_completion(handle)`; `.teardown(handle)`.
- `pi_harness.spec.runspec`: `spec_to_runspec(spec, tasks, *, session_id=None, executor=None, sync_profile=None) -> RunSpec`; `build_coordinator(config) -> Coordinator`.
- `pi_harness.spec.editor`: module-level `app: FastAPI` with routes `GET/POST /specs`, `GET/PUT /specs/{id}`, `POST /specs/{id}/lint|decompose|launch`. Response models: `SpecList{specs: list[Spec]}`, `Spec`, `LintResult`, `DecomposeResponse{tasks: list[DecomposedTask]}`, `LaunchResponse{run_id}`.
- `pi_harness.guards.promote.suggest_promotions(min_fires=20, low_variance_threshold=0.1, *, db_path=None) -> list[PromotionSuggestion{sensor_name, sensor_criterion, fires, allow_fraction, suggested_stub_code, suggested_kind, evidence: dict}]`.
- `pi_harness.corpus.reader.CorpusReader(root: Path)`: `prime(...)`, `expand(entry_id)`, `find_by_classification(cls) -> list[CorpusEntry]`, `find_unreferenced(...)`.
- `pi_harness.corpus.format`: `RecordType(Enum)`, `Classification(Enum)`, `CorpusEntry` (frozen dataclass), `serialize_entry(entry)->str`, `parse_entry(path)->CorpusEntry`, `count_tokens(text)->int`.
- `pi_harness.corpus.prune`: `prune_by_counter(entry)->list[PruneAction]`, `prune_by_contradiction(entry)->list[PruneAction]`, `prune_by_staleness(...)`, `prune_by_budget(...)`, `prune_by_dedup(...)`. (Return LISTS, not bools.)
- `pi_harness.corpus.curator.Curator(config, archive_grace_days=...)`: `apply_candidates(...)`; private helpers `_find_archived_entry_path(root, entry_id)`, `_classification_dir(root, cls)`, `_archive_dir(root, cls)`, `_ensure_git()`, `_commit_pass(...)`. NO `restore_archived` yet (Phase 3 adds it).

> Exact field names of `CorpusEntry`, `DecomposedTask`, `Spec`, `LintResult`, and the `_archive_dir` layout MUST be read from source when their task begins — do not assume.

---

## Phase 1 — Run registry + cost (`pi_harness/trajectory/`)

Gives the run list real `status`, `topology`, `started_at`, `ended_at`, lineage, and cost. Persisted in the SAME SQLite db as events, in a new `runs` table.

### Task 1.1: Model price table + `event_cost`

**Files:**
- Create: `pi_harness/trajectory/cost.py`
- Test: `tests/trajectory/test_cost.py`

- [ ] **Step 1: Write failing test** `tests/trajectory/test_cost.py`:

```python
from __future__ import annotations
import pytest
from pi_harness.trajectory.cost import event_cost, run_cost, MODEL_PRICES

def test_known_model_cost():
    # price is USD per 1M tokens; gpt-5-mini present in table
    pin, pout = MODEL_PRICES["gpt-5-mini"]
    assert event_cost("gpt-5-mini", 1_000_000, 0) == pytest.approx(pin)
    assert event_cost("gpt-5-mini", 0, 1_000_000) == pytest.approx(pout)

def test_unknown_model_costs_zero():
    assert event_cost("totally-unknown", 1000, 1000) == 0.0

def test_empty_model_costs_zero():
    # task_transition events carry model="" and zero tokens
    assert event_cost("", 0, 0) == 0.0

def test_run_cost_sums_events():
    events = [
        {"model": "gpt-5-mini", "tokens_in": 1_000_000, "tokens_out": 0},
        {"model": "gpt-5", "tokens_in": 0, "tokens_out": 1_000_000},
    ]
    expected = MODEL_PRICES["gpt-5-mini"][0] + MODEL_PRICES["gpt-5"][1]
    assert run_cost(events) == pytest.approx(expected)
```

- [ ] **Step 2: Run, expect fail.** `uv run pytest tests/trajectory/test_cost.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement** `pi_harness/trajectory/cost.py`:

```python
"""Token→USD cost derivation for trajectory events.

Cost has no fuel until the live-capture wrapper (Phase 6) records real token
counts; task_transition events carry model="" and zero tokens, so they cost 0.
Prices are USD per 1,000,000 tokens (input, output). EXAMPLE values — confirm
real OpenAI pricing before trusting cost figures (see Unresolved decisions).
Override at runtime via PI_HARNESS_MODEL_PRICES (JSON: {"model": [in, out]}).
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping

# EXAMPLE prices (USD / 1M tokens). Update with confirmed values.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
}


def _prices() -> dict[str, tuple[float, float]]:
    raw = os.environ.get("PI_HARNESS_MODEL_PRICES")
    if not raw:
        return MODEL_PRICES
    try:
        parsed = json.loads(raw)
        return {k: (float(v[0]), float(v[1])) for k, v in parsed.items()}
    except (ValueError, TypeError, KeyError, IndexError):
        return MODEL_PRICES


def event_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    prices = _prices()
    if model not in prices:
        return 0.0
    pin, pout = prices[model]
    return (tokens_in / 1_000_000) * pin + (tokens_out / 1_000_000) * pout


def run_cost(events: list[Mapping[str, Any]]) -> float:
    return sum(
        event_cost(str(e.get("model", "")), int(e.get("tokens_in", 0)), int(e.get("tokens_out", 0)))
        for e in events
    )
```

- [ ] **Step 4: Run, expect pass.** `uv run pytest tests/trajectory/test_cost.py -v`
- [ ] **Step 5: Commit.** `git add pi_harness/trajectory/cost.py tests/trajectory/test_cost.py && git commit -m "feat(trajectory): model price table + event/run cost derivation"`

### Task 1.2: `RunSummary` dataclass + `runs` table DDL

**Files:**
- Create: `pi_harness/trajectory/runs.py`
- Test: `tests/trajectory/test_runs.py`

- [ ] **Step 1: Write failing test** (`tests/trajectory/test_runs.py`) — schema + register/get round-trip:

```python
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest
from pi_harness.trajectory.runs import (
    init_runs_table, register_run, mark_run_status, get_run, RunSummary,
)

@pytest.fixture
def db(tmp_path: Path) -> Path:
    p = tmp_path / "traj.db"
    init_runs_table(p)
    return p

def test_register_and_get(db: Path):
    started = datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc)
    register_run(
        run_id="run-1", spec_id="spec-x", topology="sequential",
        sync_mode="per_agent", session_id=None, goal="ship it",
        team_name="team-1", started_at=started, run_spec_json="{}", db_path=db,
    )
    row = get_run("run-1", db_path=db)
    assert row is not None
    assert row["status"] == "running"
    assert row["topology"] == "sequential"
    assert row["spec_id"] == "spec-x"
    assert row["parent_run_id"] is None

def test_mark_status(db: Path):
    register_run(run_id="run-2", spec_id=None, topology="parallel", sync_mode="per_agent",
                 session_id=None, goal="g", team_name="t",
                 started_at=datetime(2026,5,28,tzinfo=timezone.utc), run_spec_json="{}", db_path=db)
    ended = datetime(2026, 5, 28, 11, 0, tzinfo=timezone.utc)
    mark_run_status("run-2", "succeeded", ended_at=ended, db_path=db)
    row = get_run("run-2", db_path=db)
    assert row["status"] == "succeeded"
    assert row["ended_at"] == ended.isoformat()

def test_branch_lineage_columns(db: Path):
    register_run(run_id="child", spec_id="spec-x", topology="sequential", sync_mode="per_agent",
                 session_id=None, goal="g", team_name="t",
                 started_at=datetime(2026,5,28,tzinfo=timezone.utc), run_spec_json="{}",
                 parent_run_id="run-1", branch_from_step="s-3",
                 overrides={"topology": "parallel"}, db_path=db)
    row = get_run("child", db_path=db)
    assert row["parent_run_id"] == "run-1"
    assert row["branch_from_step"] == "s-3"
    assert row["overrides"]["topology"] == "parallel"
```

- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** `pi_harness/trajectory/runs.py` (table coexists with `trajectory_events`; reuses store's `_connect`):

```python
"""Run registry: one row per run, persisted alongside trajectory_events.

Coordinator.launch inserts a row (status="running"); wait_for_completion
updates it (succeeded/failed). The dashboard reads run summaries by joining
this table with aggregated event token counts (cost derived via cost.run_cost).
Stores the serialized RunSpec so branch (Phase 2) can reload it verbatim.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pi_harness.trajectory.store import _connect, _resolve_db_path
from pi_harness.trajectory.cost import event_cost

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    spec_id TEXT,
    parent_run_id TEXT,
    branch_from_step TEXT,
    overrides TEXT,
    goal TEXT,
    topology TEXT,
    sync_mode TEXT,
    session_id TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    team_name TEXT,
    run_spec_json TEXT
)
"""


@dataclass
class RunSummary:
    run_id: str
    status: str
    topology: str | None
    started_at: datetime | None
    ended_at: datetime | None
    agent_count: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    event_count: int
    parent_run_id: str | None
    branch_from_step: str | None
    goal: str | None
    spec_id: str | None


def init_runs_table(db_path: Path | str | None = None) -> Path:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        conn.execute(_CREATE_RUNS)
        conn.commit()
    return path


def register_run(
    *, run_id: str, spec_id: str | None, topology: str | None, sync_mode: str | None,
    session_id: str | None, goal: str | None, team_name: str | None,
    started_at: datetime, run_spec_json: str, parent_run_id: str | None = None,
    branch_from_step: str | None = None, overrides: dict[str, Any] | None = None,
    status: str = "running", db_path: Path | str | None = None,
) -> None:
    path = _resolve_db_path(db_path)
    init_runs_table(path)
    with _connect(path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, spec_id, parent_run_id, branch_from_step, overrides, goal,
                topology, sync_mode, session_id, status, started_at, ended_at,
                team_name, run_spec_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, spec_id, parent_run_id, branch_from_step,
             json.dumps(overrides) if overrides is not None else None,
             goal, topology, sync_mode, session_id, status,
             started_at.isoformat(), None, team_name, run_spec_json),
        )
        conn.commit()


def mark_run_status(
    run_id: str, status: str, *, ended_at: datetime | None = None,
    db_path: Path | str | None = None,
) -> None:
    path = _resolve_db_path(db_path)
    with _connect(path) as conn:
        conn.execute(
            "UPDATE runs SET status = ?, ended_at = ? WHERE run_id = ?",
            (status, ended_at.isoformat() if ended_at else None, run_id),
        )
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("overrides"):
        d["overrides"] = json.loads(d["overrides"])
    return d


def get_run(run_id: str, *, db_path: Path | str | None = None) -> dict[str, Any] | None:
    path = _resolve_db_path(db_path)
    with _connect(path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return _row_to_dict(row) if row else None
```

- [ ] **Step 4: Run, expect pass.** `uv run pytest tests/trajectory/test_runs.py -v`
- [ ] **Step 5: Commit.** `git add pi_harness/trajectory/runs.py tests/trajectory/test_runs.py && git commit -m "feat(trajectory): runs registry table (register/mark/get) + RunSummary"`

### Task 1.3: `query_run_summaries` (join runs + event aggregates + cost)

**Files:** Modify `pi_harness/trajectory/runs.py`; Test `tests/trajectory/test_runs.py`.

- [ ] **Step 1: Add failing test** to `tests/trajectory/test_runs.py`:

```python
def test_query_run_summaries_joins_events_and_cost(db: Path):
    from datetime import datetime, timezone
    from pi_harness.trajectory.store import write_event
    from pi_harness.trajectory.schema import TrajectoryEvent
    from pi_harness.trajectory.runs import query_run_summaries
    register_run(run_id="run-1", spec_id="s", topology="sequential", sync_mode="per_agent",
                 session_id=None, goal="g", team_name="t",
                 started_at=datetime(2026,5,28,tzinfo=timezone.utc), run_spec_json="{}", db_path=db)
    for i, agent in enumerate(["a", "b"]):
        write_event(TrajectoryEvent(
            run_id="run-1", agent_id=agent, step_id=f"s-{i}",
            ts=datetime(2026,5,28,0,i,tzinfo=timezone.utc), model="gpt-5-mini",
            tool="edit", input={}, output={}, duration_ms=1, tokens_in=1_000_000,
            tokens_out=0, outcome="success", classification="tool_call"), db_path=db)
    summaries = query_run_summaries(db_path=db)
    assert len(summaries) == 1
    s = summaries[0]
    assert s.run_id == "run-1"
    assert s.agent_count == 2
    assert s.total_tokens_in == 2_000_000
    assert s.total_cost_usd == pytest.approx(0.5)  # 2M in * 0.25/1M

def test_query_run_summaries_status_filter(db: Path):
    from datetime import datetime, timezone
    from pi_harness.trajectory.runs import query_run_summaries
    register_run(run_id="r-run", spec_id=None, topology="x", sync_mode="per_agent", session_id=None,
                 goal="g", team_name="t", started_at=datetime(2026,5,28,tzinfo=timezone.utc),
                 run_spec_json="{}", status="running", db_path=db)
    register_run(run_id="r-done", spec_id=None, topology="x", sync_mode="per_agent", session_id=None,
                 goal="g", team_name="t", started_at=datetime(2026,5,28,tzinfo=timezone.utc),
                 run_spec_json="{}", status="succeeded", db_path=db)
    running = query_run_summaries(status="running", db_path=db)
    assert {s.run_id for s in running} == {"r-run"}
```

- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** `query_run_summaries` in `runs.py` (aggregate events per run, derive cost):

```python
def query_run_summaries(
    *, status: str | None = None, limit: int | None = None,
    db_path: Path | str | None = None,
) -> list[RunSummary]:
    path = _resolve_db_path(db_path)
    clauses, params = [], []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
    with _connect(path) as conn:
        run_rows = conn.execute(
            f"SELECT * FROM runs {where} ORDER BY started_at DESC {limit_clause}", params
        ).fetchall()
        out: list[RunSummary] = []
        for r in run_rows:
            agg = conn.execute(
                """SELECT COUNT(*) AS n, COUNT(DISTINCT agent_id) AS agents,
                          COALESCE(SUM(tokens_in),0) AS tin,
                          COALESCE(SUM(tokens_out),0) AS tout
                   FROM trajectory_events WHERE run_id = ?""",
                (r["run_id"],),
            ).fetchone()
            ev_rows = conn.execute(
                "SELECT model, tokens_in, tokens_out FROM trajectory_events WHERE run_id = ?",
                (r["run_id"],),
            ).fetchall()
            cost = sum(event_cost(e["model"], e["tokens_in"], e["tokens_out"]) for e in ev_rows)
            out.append(RunSummary(
                run_id=r["run_id"], status=r["status"], topology=r["topology"],
                started_at=datetime.fromisoformat(r["started_at"]) if r["started_at"] else None,
                ended_at=datetime.fromisoformat(r["ended_at"]) if r["ended_at"] else None,
                agent_count=int(agg["agents"]), total_tokens_in=int(agg["tin"]),
                total_tokens_out=int(agg["tout"]), total_cost_usd=cost,
                event_count=int(agg["n"]), parent_run_id=r["parent_run_id"],
                branch_from_step=r["branch_from_step"], goal=r["goal"], spec_id=r["spec_id"],
            ))
    return out
```

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit.** `git commit -am "feat(trajectory): query_run_summaries joins event aggregates + cost"`

### Task 1.4: Wire registry into Coordinator + RunSpec.spec_id

**Files:** Modify `pi_harness/topology/base.py` (add `spec_id` to RunSpec), `pi_harness/topology/coordinator.py` (register on launch, mark on completion), `pi_harness/spec/runspec.py` (thread spec.id + serialize). Test `tests/topology/test_coordinator.py` (extend, no smoke).

- [ ] **Step 1:** Read `tests/topology/test_coordinator.py` and `tests/topology/conftest.py` to learn the existing fake `clawteam_client`/`corpus_reader`/`improve_runner` fixtures. Reuse them — do not invent new mocks.
- [ ] **Step 2: Add `spec_id` to RunSpec** in `base.py` (after `tasks`): `spec_id: str | None = None  # originating spec for run-registry linkage / branch`.
- [ ] **Step 3: Write failing test** `tests/topology/test_coordinator.py::test_launch_registers_run`: build a RunSpec, call `coord.launch(spec)` with a `config.trajectory_db_path` pointing at `tmp_path`, then assert `get_run(handle.run_id, db_path=cfg.trajectory_db_path)` returns a row with `status=="running"`, `topology==spec.mode.value`, and a non-empty `run_spec_json`.
- [ ] **Step 4: Run, expect fail.**
- [ ] **Step 5: Implement** in `coordinator.py`:
  - Add a RunSpec serializer. Create `pi_harness/topology/runspec_codec.py` with `runspec_to_json(spec: RunSpec) -> str` and `runspec_from_json(s: str) -> RunSpec` (dataclasses → dict with enum `.value`, agents/tasks as lists; reverse rebuilds enums). Full code:

```python
from __future__ import annotations
import json
from pi_harness.topology.base import (
    AgentSpec, ModelTier, Role, RunSpec, SyncMode, TaskDef, TopologyMode,
)

def runspec_to_json(spec: RunSpec) -> str:
    return json.dumps({
        "goal": spec.goal, "mode": spec.mode.value, "sync_mode": spec.sync_mode.value,
        "corpus_classifications": list(spec.corpus_classifications),
        "session_id": spec.session_id, "executor": spec.executor,
        "sync_profile": spec.sync_profile, "spec_id": spec.spec_id,
        "agents": [{"name": a.name, "role": a.role.value, "model_tier": a.model_tier.value,
                    "tools": list(a.tools), "expertise_classifications": list(a.expertise_classifications),
                    "task_prompt": a.task_prompt} for a in spec.agents],
        "tasks": None if spec.tasks is None else [
            {"task_id": t.task_id, "agent_name": t.agent_name, "goal": t.goal,
             "blocked_by": list(t.blocked_by)} for t in spec.tasks],
    })

def runspec_from_json(s: str) -> RunSpec:
    d = json.loads(s)
    agents = [AgentSpec(name=a["name"], role=Role(a["role"]), model_tier=ModelTier(a["model_tier"]),
                        tools=a.get("tools", []), expertise_classifications=a.get("expertise_classifications", []),
                        task_prompt=a.get("task_prompt")) for a in d["agents"]]
    tasks = None if d.get("tasks") is None else [
        TaskDef(task_id=t["task_id"], agent_name=t["agent_name"], goal=t["goal"],
                blocked_by=t.get("blocked_by", [])) for t in d["tasks"]]
    return RunSpec(goal=d["goal"], agents=agents, mode=TopologyMode(d["mode"]),
                   sync_mode=SyncMode(d["sync_mode"]), corpus_classifications=d.get("corpus_classifications", []),
                   session_id=d.get("session_id"), executor=d.get("executor", "pi"),
                   sync_profile=d.get("sync_profile"), tasks=tasks, spec_id=d.get("spec_id"))
```
  - In `Coordinator.launch`, just before `return handle`, register:

```python
from pi_harness.trajectory.runs import register_run
from pi_harness.topology.runspec_codec import runspec_to_json
register_run(
    run_id=run_id, spec_id=spec.spec_id, topology=spec.mode.value,
    sync_mode=spec.sync_mode.value, session_id=spec.session_id, goal=spec.goal,
    team_name=team_name, started_at=handle.started_at,
    run_spec_json=runspec_to_json(spec), status="running",
    db_path=self._config.trajectory_db_path,
)
```
  - In `Coordinator.wait_for_completion`, after computing `result`, before returning:

```python
from pi_harness.trajectory.runs import mark_run_status
mark_run_status(handle.run_id, "succeeded" if success else "failed",
                ended_at=datetime.now(timezone.utc), db_path=self._config.trajectory_db_path)
```
  - In `spec_to_runspec` (`runspec.py`), pass `spec_id=spec.id` into the returned `RunSpec(...)`.

- [ ] **Step 6: Run** `uv run pytest tests/topology/test_coordinator.py tests/spec/test_runspec.py -v -m "not smoke"` → pass.
- [ ] **Step 7: Commit.** `git commit -am "feat(topology): register runs + completion status; RunSpec.spec_id + codec"`

---

## Phase 2 — Level-1 branch (`Coordinator.branch`)

Fork the parent's serialized RunSpec, apply overrides, launch a child tagged with lineage. NOT mid-run replay (see memory `project_symphony_ux_v1.md`).

### Task 2.1: `apply_overrides` to a RunSpec

**Files:** Modify `pi_harness/topology/runspec_codec.py`; Test `tests/topology/test_runspec_codec.py`.

- [ ] **Step 1: Write failing tests** (`tests/topology/test_runspec_codec.py`): round-trip `runspec_to_json`/`from_json` equality; `apply_overrides` for `goal`, `topology` (→ TopologyMode), `sync_mode`, and `model_tier` (sets every agent's `model_tier`). Unknown keys raise `ValueError`.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** `apply_overrides(spec: RunSpec, overrides: dict) -> RunSpec` using `dataclasses.replace`; supported keys: `goal: str`, `topology: str`, `sync_mode: str`, `model_tier: str` (replace each agent's `model_tier`). Raise `ValueError(f"unsupported branch override: {key}")` for anything else.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit.** `git commit -am "feat(topology): apply_overrides for branch (goal/topology/sync_mode/model_tier)"`

### Task 2.2: `Coordinator.branch`

**Files:** Modify `pi_harness/topology/coordinator.py`; Test `tests/topology/test_coordinator.py`.

- [ ] **Step 1: Write failing test** `test_branch_launches_child_with_lineage`: register a parent run (status succeeded) with a real `run_spec_json` (use `runspec_to_json` on a built RunSpec); call `coord.branch(parent_run_id, step_id="s-2", overrides={"model_tier": "reasoning"})`; assert it returns a `RunHandle`, that `get_run(child.run_id)` has `parent_run_id==parent`, `branch_from_step=="s-2"`, `overrides=={"model_tier":"reasoning"}`, and that the fake clawteam_client saw a launch. (Reuse coordinator test fixtures; no smoke.)
- [ ] **Step 2: Add test** `test_branch_unknown_parent_raises` (KeyError/ValueError) and `test_branch_parent_without_runspec_raises` (registered run with empty run_spec_json → ValueError "cannot branch: parent has no stored RunSpec").
- [ ] **Step 3: Run, expect fail.**
- [ ] **Step 4: Implement** `Coordinator.branch`:

```python
def branch(self, parent_run_id: str, step_id: str, overrides: dict | None = None) -> RunHandle:
    from pi_harness.trajectory.runs import get_run, register_run
    from pi_harness.topology.runspec_codec import runspec_from_json, runspec_to_json, apply_overrides
    parent = get_run(parent_run_id, db_path=self._config.trajectory_db_path)
    if parent is None:
        raise ValueError(f"unknown parent run {parent_run_id!r}")
    if not parent.get("run_spec_json"):
        raise ValueError("cannot branch: parent has no stored RunSpec")
    spec = runspec_from_json(parent["run_spec_json"])
    if overrides:
        spec = apply_overrides(spec, overrides)
    handle = self.launch(spec)  # launch() already registers the child as running
    # annotate lineage on the freshly-registered child row
    register_run(
        run_id=handle.run_id, spec_id=spec.spec_id, topology=spec.mode.value,
        sync_mode=spec.sync_mode.value, session_id=spec.session_id, goal=spec.goal,
        team_name=handle.team_name, started_at=handle.started_at,
        run_spec_json=runspec_to_json(spec), status="running",
        parent_run_id=parent_run_id, branch_from_step=step_id, overrides=overrides or {},
        db_path=self._config.trajectory_db_path,
    )
    return handle
```

- [ ] **Step 5: Run** `uv run pytest tests/topology/test_coordinator.py -v -m "not smoke"` → pass.
- [ ] **Step 6: Commit.** `git commit -am "feat(topology): Coordinator.branch (Level-1 fork + lineage)"`

---

## Phase 3 — Corpus restore (`Curator.restore_archived`)

### Task 3.1: `restore_archived`

**Files:** Modify `pi_harness/corpus/curator.py`; Test `tests/corpus/test_curator.py`.

- [ ] **Step 1:** Read `curator.py` lines 114–143 + `_find_archived_entry_path`/`_classification_dir`/`_archive_dir`/`_commit_pass` to learn the exact archive layout and git-commit helper signatures.
- [ ] **Step 2: Write failing test** in `tests/corpus/test_curator.py`: seed a real archived entry (serialize a `CorpusEntry` into the archive dir via the layout learned in Step 1); construct `Curator(config)` with `config.corpus_root=tmp`; call `curator.restore_archived(entry_id)`; assert the returned `CorpusEntry.id == entry_id`, the file now lives in the active classification dir, and the archive copy is gone. Add `test_restore_unknown_raises` → `FileNotFoundError`.
- [ ] **Step 3: Run, expect fail.**
- [ ] **Step 4: Implement** `restore_archived(self, entry_id: str) -> CorpusEntry`: locate via `_find_archived_entry_path`; if None → `raise FileNotFoundError(entry_id)`; `parse_entry`; compute active dir via `_classification_dir(root, entry.classification)`; move the file (`shutil.move`); commit via the existing commit helper; return the parsed entry. Match the real helper signatures from Step 1.
- [ ] **Step 5: Run** `uv run pytest tests/corpus/test_curator.py -v -m "not smoke"` → pass.
- [ ] **Step 6: Commit.** `git commit -am "feat(corpus): Curator.restore_archived (un-archive + git commit)"`

---

## Phase 4 — FastAPI backend (`pi_harness/api/`)

All routes tested via `fastapi.testclient.TestClient` against a real temp SQLite db + real temp corpus/spec dirs. **No upstream mocks.**

### Task 4.0: Bootstrap

- [ ] **Step 1:** `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/routes /Users/pranavnair/Desktop/Personal/mannschaft/tests/api && touch pi_harness/api/__init__.py pi_harness/api/routes/__init__.py tests/api/__init__.py`
- [ ] **Step 2:** `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv add 'fastapi[standard]' uvicorn websockets && uv add --dev pytest-asyncio` (pydantic, httpx, pytest already present — verify with `uv run python -c "import fastapi, httpx, pydantic"`).
- [ ] **Step 3: Write** `tests/api/conftest.py` with a real-store fixture (NOT the original plan's mock-based one):

```python
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def cfg(tmp_path: Path, monkeypatch):
    """Real Config pointing at temp stores. Seeds nothing — tests seed what they need."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    corpus = tmp_path / "corpus"
    for sub in ("foundational", "tactical", "observational"):
        (corpus / sub).mkdir(parents=True)
    (corpus / "archived").mkdir(parents=True)
    from pi_harness.config import Config
    return Config(
        openai_api_key="test-key", reasoning_model="gpt-5", fast_model="gpt-5-mini",
        clawteam_state_dir=tmp_path / "clawteam", corpus_root=corpus,
        trajectory_db_path=tmp_path / "traj.db",
    )

@pytest.fixture
def client(cfg) -> TestClient:
    from pi_harness.api.server import create_app, DashboardConfig
    app = create_app(cfg, DashboardConfig())
    return TestClient(app)

@pytest.fixture
def seed_run(cfg):
    """Helper: register a run + write events into the real temp db."""
    from pi_harness.trajectory.store import write_event
    from pi_harness.trajectory.schema import TrajectoryEvent
    from pi_harness.trajectory.runs import register_run
    def _seed(run_id="r-1", status="succeeded", topology="sequential"):
        register_run(run_id=run_id, spec_id="spec-1", topology=topology, sync_mode="per_agent",
                     session_id=None, goal="demo", team_name="team-1",
                     started_at=datetime(2026,5,28,10,0,tzinfo=timezone.utc),
                     run_spec_json="{}", status=status, db_path=cfg.trajectory_db_path)
        write_event(TrajectoryEvent(run_id=run_id, agent_id="builder-1", step_id="s-1",
            ts=datetime(2026,5,28,10,0,1,tzinfo=timezone.utc), model="gpt-5-mini", tool="edit_file",
            input={}, output={}, duration_ms=1200, tokens_in=400, tokens_out=200,
            outcome="success", classification="tool_call"), db_path=cfg.trajectory_db_path)
        write_event(TrajectoryEvent(run_id=run_id, agent_id="builder-1", step_id="s-1",
            ts=datetime(2026,5,28,10,0,2,tzinfo=timezone.utc), model="", tool="edit_file",
            input={}, output={"_guard_meta": {"guide": "AllowlistGuide", "allow": True, "reason": "ok"}},
            duration_ms=0, tokens_in=0, tokens_out=0, outcome="success",
            classification="guide_fired"), db_path=cfg.trajectory_db_path)
        return run_id
    return _seed
```

- [ ] **Step 4: Run** `uv run pytest --collect-only tests/api -q` → collects (0 tests).
- [ ] **Step 5: Commit.** `git add pi_harness/api tests/api pyproject.toml uv.lock && git commit -m "chore(api): bootstrap FastAPI package + real-store test fixtures"`

### Task 4.1: Refactor spec editor to expose a router; app factory + health + CORS

**Files:** Modify `pi_harness/spec/editor.py` (extract `router`); Create `pi_harness/api/server.py`, `pi_harness/api/__main__.py`; Test `tests/api/test_server.py`, `tests/spec/test_editor.py` (must still pass).

- [ ] **Step 1: Write failing test** `tests/api/test_server.py`: `GET /healthz`→200 `{"status":"ok"}`; `GET /openapi.json` paths include `/specs` and `/runs`; `OPTIONS /runs` with `Origin: http://localhost:3000` returns matching `access-control-allow-origin`.
- [ ] **Step 2: Refactor** `pi_harness/spec/editor.py`: add `from fastapi import APIRouter`, create `router = APIRouter()`, change every `@app.<verb>` decorator to `@router.<verb>`, then after the routes add `app = FastAPI(title="Pi-Harness Spec Editor", version="0.1.0"); app.include_router(router)`. The standalone `main()` keeps working. Run `uv run pytest tests/spec/test_editor.py -v -m "not smoke"` to confirm no regression.
- [ ] **Step 3: Implement** `pi_harness/api/server.py` (real `Config`; `DashboardConfig` from env; mount the spec router; CORS) and `pi_harness/api/__main__.py`:

```python
# server.py
from __future__ import annotations
import os
from dataclasses import dataclass
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pi_harness.config import Config, load_config
from pi_harness.spec.editor import router as spec_router

@dataclass(frozen=True)
class DashboardConfig:
    api_host: str = "127.0.0.1"
    api_port: int = 8800
    frontend_origin: str = "http://localhost:3000"

def load_dashboard_config() -> DashboardConfig:
    return DashboardConfig(
        api_host=os.environ.get("PI_HARNESS_API_HOST", "127.0.0.1"),
        api_port=int(os.environ.get("PI_HARNESS_API_PORT", "8800")),
        frontend_origin=os.environ.get("PI_HARNESS_FRONTEND_ORIGIN", "http://localhost:3000"),
    )

def create_app(config: Config, dash: DashboardConfig | None = None) -> FastAPI:
    dash = dash or load_dashboard_config()
    app = FastAPI(title="Pi-Agent Harness API", version="0.1.0")
    app.state.config = config
    app.state.dashboard_config = dash
    app.add_middleware(CORSMiddleware, allow_origins=[dash.frontend_origin],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}
    app.include_router(spec_router)  # routes already prefixed with /specs
    # runs/corpus/guards/ws routers added in later tasks
    return app

def main() -> None:
    import uvicorn
    cfg = load_config()
    dash = load_dashboard_config()
    uvicorn.run(create_app(cfg, dash), host=dash.api_host, port=dash.api_port, reload=False)

if __name__ == "__main__":
    main()
```
Note: the `/runs` openapi assertion in Step 1 will fail until Task 4.2 — mark it `@pytest.mark.xfail(reason="runs router added in 4.2")` now, remove the marker in 4.2.

- [ ] **Step 4: Run** `uv run pytest tests/api/test_server.py tests/spec/test_editor.py -v -m "not smoke"`.
- [ ] **Step 5: Commit.** `git commit -am "feat(api): app factory, healthz, CORS; extract spec router from editor app"`

### Task 4.2: `GET /runs`, `GET /runs/{id}` (real registry)

**Files:** Create `pi_harness/api/models.py`, `pi_harness/api/routes/runs.py`; Modify `server.py`; Test `tests/api/test_runs.py`.

- [ ] **Step 1: Define DTOs** in `models.py` matching the REAL `RunSummary` + `TrajectoryEvent` (note: NO `guide_firings`/`sensor_firings` on the event; `classification`/`outcome` are open `str`; `input`/`output` are `dict`):

```python
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

class RunSummaryDTO(BaseModel):
    run_id: str
    status: str
    topology: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    agent_count: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    event_count: int
    parent_run_id: str | None = None
    branch_from_step: str | None = None
    goal: str | None = None
    spec_id: str | None = None

class TrajectoryEventDTO(BaseModel):
    run_id: str
    agent_id: str
    step_id: str
    ts: datetime
    model: str
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int
    tokens_in: int
    tokens_out: int
    outcome: str
    classification: str
    corpus_refs: list[str] = Field(default_factory=list)
    corpus_cited: list[str] = Field(default_factory=list)

class RunDetailDTO(BaseModel):
    summary: RunSummaryDTO
    events: list[TrajectoryEventDTO]
```

- [ ] **Step 2: Write failing tests** `tests/api/test_runs.py` using `client` + `seed_run`: `GET /runs`→200 list incl. seeded run with `total_cost_usd>0`; `GET /runs?status=running` filters; `GET /runs/{id}` returns summary+events (2 events incl. the guide_fired one); `GET /runs/r-nope`→404 `{"detail":"run not found"}`.
- [ ] **Step 3: Run, expect fail.**
- [ ] **Step 4: Implement** `routes/runs.py` (reads `request.app.state.config.trajectory_db_path`; converts dataclass→DTO via `RunSummaryDTO(**vars(s))` and `TrajectoryEventDTO(**vars(e))`):

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query, Request
from pi_harness.api.models import RunSummaryDTO, RunDetailDTO, TrajectoryEventDTO
from pi_harness.trajectory.runs import query_run_summaries, get_run
from pi_harness.trajectory.store import query_events

router = APIRouter(tags=["runs"])

def _db(request: Request):
    return request.app.state.config.trajectory_db_path

@router.get("/runs", response_model=list[RunSummaryDTO])
def list_runs(request: Request, status: str | None = Query(None), limit: int | None = Query(None, ge=1, le=500)):
    return [RunSummaryDTO(**vars(s)) for s in query_run_summaries(status=status, limit=limit, db_path=_db(request))]

@router.get("/runs/{run_id}", response_model=RunDetailDTO)
def get_run_detail(request: Request, run_id: str):
    summaries = query_run_summaries(db_path=_db(request))
    match = next((s for s in summaries if s.run_id == run_id), None)
    if match is None:
        raise HTTPException(404, "run not found")
    events = query_events(run_id=run_id, db_path=_db(request))
    return RunDetailDTO(summary=RunSummaryDTO(**vars(match)),
                        events=[TrajectoryEventDTO(**vars(e)) for e in events])
```
Wire `app.include_router(runs_router)` in `server.py`; remove the xfail from Task 4.1.

- [ ] **Step 5: Run** `uv run pytest tests/api/test_runs.py tests/api/test_server.py -v` → pass.
- [ ] **Step 6: Commit.** `git commit -am "feat(api): GET /runs and /runs/{id} from real run registry"`

### Task 4.3: `GET /runs/{id}/timeline` (grouped per agent, firing markers)

**Files:** Modify `models.py`, `routes/runs.py`; Test `tests/api/test_timeline.py`.

- [ ] **Step 1: Add DTOs** `AgentTimelineRowDTO{agent_id, events: list[TrajectoryEventDTO]}`, `TimelineDTO{run_id, agents: list[AgentTimelineRowDTO]}`.
- [ ] **Step 2: Write failing tests**: `GET /runs/{id}/timeline` groups by agent in first-event-ts order; the builder-1 row includes the `guide_fired` event (UI keys icons off `classification`); 404 on unknown run.
- [ ] **Step 3: Run, expect fail.**
- [ ] **Step 4: Implement** `get_timeline`: 404 if run absent; `query_events(run_id)`; group into an `OrderedDict[agent_id]` over `sorted(events, key=ts)`; return `TimelineDTO`.
- [ ] **Step 5: Run → pass. Commit.** `git commit -am "feat(api): GET /runs/{id}/timeline grouped per agent"`

### Task 4.4: `POST /runs/{id}/branch` (real Coordinator.branch)

**Files:** Modify `models.py`, `routes/runs.py`; Test `tests/api/test_branch.py`.

- [ ] **Step 1: Add DTOs** `BranchRequest{step_id: str, overrides: dict[str, Any] = {}}`, `BranchResponse{run_id, parent_run_id, branched_from_step}`.
- [ ] **Step 2: Write failing tests**: seed a parent run whose `run_spec_json` is a real serialized RunSpec; `POST /runs/{parent}/branch {"step_id":"s-1","overrides":{"model_tier":"reasoning"}}`→200 with child run_id; 404 unknown parent; 422 missing step_id. Build the Coordinator with a **fake clawteam_client** that records launches but does NOT spawn tmux — inject it via a `app.state` hook (see Step 4). This is the one place we use a fake, because branch calls `Coordinator.launch` which would otherwise hit ClawTeam; the fake matches the REAL `ClawTeamClient` method surface (`register_profile, install_template, launch_team, create_task, wait_for_completion, kill_tmux_session, cleanup_team, list_tasks`).
- [ ] **Step 3: Run, expect fail.**
- [ ] **Step 4: Implement**: add `app.state.coordinator_factory` (defaults to `build_coordinator`; tests override with one that injects the fake client). Route:

```python
@router.post("/runs/{run_id}/branch", response_model=BranchResponse)
def branch_run(request: Request, run_id: str, body: BranchRequest):
    if get_run(run_id, db_path=_db(request)) is None:
        raise HTTPException(404, "run not found")
    coord = request.app.state.coordinator_factory(request.app.state.config)
    try:
        handle = coord.branch(run_id, body.step_id, body.overrides)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return BranchResponse(run_id=handle.run_id, parent_run_id=run_id, branched_from_step=body.step_id)
```
Set `app.state.coordinator_factory = build_coordinator` in `create_app`.

- [ ] **Step 5: Run → pass. Commit.** `git commit -am "feat(api): POST /runs/{id}/branch wires Coordinator.branch"`

### Task 4.5: Corpus routes (`/corpus/health`, `/corpus/entries`, restore)

**Files:** Create `pi_harness/api/routes/corpus.py`; Modify `models.py`, `server.py`; Test `tests/api/test_corpus.py`.

- [ ] **Step 1:** Read `corpus/format.py` `CorpusEntry` fields + `corpus/reader.py` `find_by_classification`/`find_unreferenced` signatures + `prune.py` function signatures. Define DTOs from the REAL fields.
- [ ] **Step 2: Write failing tests** seeding real corpus files via `serialize_entry`: `/corpus/health` returns token gauge + classification counts + `prune_candidates` (counts where `len(prune_by_X(e))>0`); `/corpus/entries?classification=tactical` filters; `/corpus/entries?archived=true` lists archived; `POST /corpus/entries/{id}/restore` moves an archived entry back (uses Phase 3); 404 on unknown.
- [ ] **Step 3: Run, expect fail.**
- [ ] **Step 4: Implement** `routes/corpus.py` using real `CorpusReader`, `prune_by_*` (count via `len(...)>0`), and `Curator(cfg).restore_archived`. Soft cap from `PI_HARNESS_CORPUS_SOFT_CAP` env (default 50_000).
- [ ] **Step 5: Run → pass. Commit.** `git commit -am "feat(api): corpus health/entries/restore routes"`

### Task 4.6: `GET /guards/promotion-candidates` (real PromotionSuggestion)

**Files:** Create `pi_harness/api/routes/guards.py`; Modify `models.py`, `server.py`; Test `tests/api/test_guards.py`.

- [ ] **Step 1: Add DTO** `PromotionCandidateDTO{sensor_name, sensor_criterion, fires: int, allow_fraction: float, suggested_kind: str, suggested_stub_code: str, evidence: dict[str, Any]}` (mirrors REAL `PromotionSuggestion`).
- [ ] **Step 2: Write failing test**: seed ≥20 `sensor_fired` events with `_guard_meta{sensor_kind:"inferential_sensor", sensor:"JudgeAgentSensor", allow:true, guard_metadata:{criterion:"..."}}` in the real temp db so `suggest_promotions(min_fires=20)` returns one candidate; `GET /guards/promotion-candidates`→200 with that candidate. (Pass `db_path` through — see Step 4.)
- [ ] **Step 3: Run, expect fail.**
- [ ] **Step 4: Implement**: `suggest_promotions` reads `db_path=request.app.state.config.trajectory_db_path`. Route maps each `PromotionSuggestion` (a dataclass) → DTO via `PromotionCandidateDTO(**vars(s))`.
- [ ] **Step 5: Run → pass. Commit.** `git commit -am "feat(api): GET /guards/promotion-candidates from real suggest_promotions"`

### Task 4.7: WebSocket `/ws/runs/{id}` (poll-and-push tailer)

No `subscribe` exists upstream, so the WS tails the db: query events since the last seen ts, push new ones, sleep, repeat. Works for task-transition events now and lights up further when capture (Phase 6) lands.

**Files:** Create `pi_harness/api/routes/ws.py`; Modify `server.py`; Test `tests/api/test_websocket.py`.

- [ ] **Step 1: Write failing tests**: seed a run + 2 events; `client.websocket_connect("/ws/runs/{id}")` receives 2 JSON messages parsing as `TrajectoryEventDTO`; connecting to unknown run closes with code 4404. Use a short poll interval via `app.state.ws_poll_interval = 0.05` in the fixture and cap the tailer to "drain existing then one poll" so the sync TestClient test terminates (see Step 3).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** `routes/ws.py`: validate run via `get_run`; `await ws.accept()`; loop `query_events(run_id, since=last_ts)`, send each new event as `TrajectoryEventDTO(**vars(e)).model_dump(mode="json")`, advance `last_ts`, `await asyncio.sleep(app.state.ws_poll_interval)`; break on `WebSocketDisconnect`. To keep the synchronous test bounded, stop after a poll yields zero new events AND at least one drain happened (document this "drain-then-idle-closes" behavior; the browser client reconnects via refetch). Wire into `server.py`.
- [ ] **Step 4: Run → pass. Commit.** `git commit -am "feat(api): WebSocket /ws/runs/{id} poll-and-push tailer"`

### Task 4.8: Reliability gauges (derived) `GET /runs/{id}/reliability`

**Files:** Create `pi_harness/api/reliability.py`; Modify `routes/runs.py`, `models.py`; Test `tests/api/test_reliability.py`.

- [ ] **Step 1: Write failing test** for `compute_reliability(events) -> dict`: define concrete heuristics over events — `safety` = pass-fraction of guide_fired+sensor_fired (allow=True in `_guard_meta`); `robustness` = 1 − error-fraction (outcome=="error"); `predictability` = fraction of tool calls that had a matching tool_result; `consistency` = 1 − (distinct tools / total tool calls) capped to [0,1]. Empty events → all `None`. Assert known inputs map to known scores.
- [ ] **Step 2: Run, expect fail. Step 3: Implement** `reliability.py`; add `GET /runs/{id}/reliability` returning `ReliabilityDTO{consistency, robustness, predictability, safety}` (each `float|None`).
- [ ] **Step 4: Run → pass. Commit.** `git commit -am "feat(api): derived reliability gauges route"`

### Task 4.9: Backend acceptance sweep

- [ ] **Step 1:** `uv run pytest tests/api tests/trajectory tests/topology tests/corpus tests/spec -v -m "not smoke"` → all pass.
- [ ] **Step 2:** Smoke-launch: `uv run python -m pi_harness.api &` then `curl -sf http://127.0.0.1:8800/healthz && curl -sf http://127.0.0.1:8800/openapi.json | head -c 200`; `kill %1`.
- [ ] **Step 3: Commit** any fixups. `git commit -am "test(api): backend acceptance sweep" --allow-empty`

---

## Phase 5 — Next.js frontend (`ui/`)

Reuse the **original** plan's frontend scaffolding and components (`docs/superpowers/plans/2026-05-25-symphony-ux.md`, Tasks 8–16) VERBATIM where unchanged, applying the corrections below. Each task: apply changes, run `cd ui && pnpm typecheck`, commit.

### Task 5.1: Scaffold (original Tasks 8.1–8.10 unchanged)
- [ ] Create `ui/package.json`, `tsconfig.json`, `next.config.js`, `tailwind.config.ts`, `postcss.config.js`, `app/globals.css`, `.gitignore` exactly as original Task 8; `cd ui && pnpm install`; commit `chore(ui): Next.js 14 + Tailwind + pnpm scaffold`.

### Task 5.2: Typed client + providers (original Task 9, CORRECTED)
- [ ] Generate types: backend running (`uv run python -m pi_harness.api`), then `cd ui && pnpm gen:api`.
- [ ] Write `ui/lib/api.ts` as original Task 9.2 BUT correct the types/endpoints to the real shapes:
  - `RunSummary` = `components["schemas"]["RunSummaryDTO"]` (new fields: `event_count, parent_run_id, branch_from_step, goal, spec_id`; `status`/`topology` are strings).
  - **Specs (Plan 7 real shapes):** `listSpecs()` returns `{ specs: Spec[] }` → expose `listSpecs: () => json<{specs: Spec[]}>("/specs").then(r => r.specs)`. `getSpec` returns a `Spec` (fields `id, title, goal, acceptance_criteria, constraints, non_goals, topology, sync_mode, status, linter_score, ...`) — there is NO `{body, frontmatter}`. `saveSpec` PUTs an `UpdateSpecBody` (partial Spec fields), not `{body}`. `lintSpec` returns `LintResult` (`score, errors, warnings`), not `{violations}`. `decomposeSpec` returns `{tasks: DecomposedTask[]}`. `launchSpec(id)` POSTs `/specs/{id}/launch` (no body) → `{run_id}`.
  - `branchRun(runId, {step_id, overrides})` → `BranchResponse`.
  - Add `reliability: (id) => json<ReliabilityDTO>(\`/runs/${id}/reliability\`)`.
- [ ] Write `ui/lib/query-client.tsx` and `ui/lib/use-live-run.ts` exactly as original Task 9.3–9.4.
- [ ] `pnpm typecheck`; commit `feat(ui): typed client (corrected to real DTOs) + providers + live hook`.

### Task 5.3: Layout + left rail (original Task 10 unchanged)
- [ ] `ui/components/LeftRail.tsx`, `ui/app/layout.tsx`, `ui/app/memory/page.tsx`, `ui/app/subagents/page.tsx` as original Task 10; commit.

### Task 5.4: Run list (original Task 11, minor)
- [ ] `ui/app/page.tsx` as original Task 11 — works unchanged (`run_id, status, topology, agent_count, total_cost_usd` all exist). Commit.

### Task 5.5: Run detail + timeline (original Task 12, CORRECTED)
- [ ] `GuardIcon.tsx`, `CostPanel.tsx` unchanged. `ReliabilityGauges.tsx`: wire to real scores from `api.reliability(runId)` instead of `{}`.
- [ ] `RunTimeline.tsx`: the event has NO `guide_firings`/`sensor_firings` arrays. Instead render icons by `classification`: a `guide_fired` event → `<GuardIcon kind="guide" .../>`, `sensor_fired` → sensor icon; read pass/fail from `event.output["_guard_meta"].allow`. Keep the Branch button but call `api.branchRun(runId, {step_id: ev.step_id, overrides: {}})` and only show it on non-firing tool events. Inspector pane unchanged.
- [ ] `ui/app/runs/[runId]/page.tsx` as original Task 12.5 but also fetch `api.reliability` and pass real scores. `pnpm typecheck`; commit.

### Task 5.6: Corpus page (original Task 13, minor)
- [ ] `CorpusHealthGauge.tsx` + `ui/app/corpus/page.tsx` as original Task 13 — DTO field names already match Phase-4 corpus DTOs (verify `prune_candidates` keys + `recently_archived`/`stale_entries`). Commit.

### Task 5.7: Specs page (original Task 14, CORRECTED for real Spec shape)
- [ ] `SpecEditor.tsx`: the editor edits structured `Spec` fields, not a raw `body` textarea. Replace the single `body` textarea with fields for `goal` + `acceptance_criteria` (textarea, newline-split) + `constraints` + `non_goals`; on save call `api.saveSpec(id, {goal, acceptance_criteria, ...})`. Lint shows `LintResult.score` + `errors`/`warnings` lists (not `violations`). Decompose shows `DecomposedTask[]`. Launch unchanged.
- [ ] `ui/app/specs/page.tsx`: `specs.data` is now `Spec[]` (from `listSpecs()` unwrapping `.specs`); list by `s.title`; `getSpec` returns a `Spec`. `pnpm typecheck`; commit.

### Task 5.8: Guards page (original Task 15, CORRECTED)
- [ ] `ui/app/guards/page.tsx`: candidate fields are `sensor_name, sensor_criterion, fires, allow_fraction, suggested_kind, suggested_stub_code, evidence`. Render `sensor_name` + `sensor_criterion`, `fired {fires}×`, `allow {Math.round(allow_fraction*100)}%`, and a `<pre>` of `suggested_stub_code`. `pnpm typecheck`; commit.

### Task 5.9: Playwright smoke (original Task 16, CORRECTED fixtures)
- [ ] Replace the original `_fixtures.py` monkeypatch with a real seeder: a `PI_HARNESS_FIXTURE_MODE=1` block in `create_app` that registers one run + writes a handful of events (tool_call + guide_fired) into `config.trajectory_db_path`, and writes one real spec file. NO monkeypatching of `query_runs`/`subscribe`.
- [ ] `playwright.config.ts` as original Task 16.2 with `env: { PI_HARNESS_FIXTURE_MODE: "1", OPENAI_API_KEY: "test" }` on the backend webServer.
- [ ] `tests/ui/smoke.spec.ts`: landing lists the fixture run; run detail shows timeline + a guide icon; branch POST returns 200 (or 409 if no stored RunSpec — assert `[200,409].includes(status)` and document); corpus gauge renders %; specs page header renders. `pnpm exec playwright install chromium && pnpm exec playwright test`; commit.

---

## Phase 6 — Live trajectory capture wrapper (SEPARATE concern — spike first, needs credit)

> This phase makes REAL runs emit tool/token/firing events so cost + timeline fill in. It runs live `pi`/`codex` agents (spends credit) and depends on their NDJSON stdout format, which is UNVERIFIED (the `guards/runner.py` docstring format is an assumption). **Do Task 6.1 before writing any parser.** Consider splitting into its own plan file once the spike confirms the format.

### Task 6.1: Stdout format verification spike (CREDIT)
- [ ] **Step 1:** With `PI_HARNESS_RUN_SMOKE=1` and a real API key, run one trivial `pi` task (and `codex` if used) capturing raw stdout to a file: e.g. drive `clawteam launch` for a one-task team, OR run the executor binary directly on a hello-world prompt with stdout redirected. Save samples under `docs/captures/pi-stdout-sample.ndjson` (gitignored if large).
- [ ] **Step 2:** Document the REAL event schema (tool_call / tool_result / message / token-usage lines) in `pi_harness/trajectory/CAPTURE_FORMAT.md`. Compare against `guards/runner.py`'s assumed `{"type":"tool_call","id","name","input"}` / `{"type":"tool_result","id","output","exit_code"}`. Note where token counts + model appear (needed for cost).
- [ ] **Step 3: STOP and report** the real format to Pranav before building the parser. Adjust Tasks 6.2–6.4 to match. (Building a parser against the assumed format is the exact mock-mismatch trap — don't.)

### Task 6.2: NDJSON → TrajectoryEvent parser (TDD against the REAL samples)
- [ ] Write `pi_harness/trajectory/agent_capture.py`: `parse_line(line: str) -> ActionIntent | ActionResult | None` and `events_from_stream(...)`, tested against the saved sample lines (golden file). Map model + token usage onto `TrajectoryEvent.model/tokens_in/tokens_out` so cost has fuel. Commit.

### Task 6.3: Wrapper subprocess + GuardRunner wiring
- [ ] Write `pi_harness/agent_wrapper.py` (`python -m pi_harness.agent_wrapper --executor pi --run-id ... --agent-id ...`): execs the real executor, tees stdout to the pane AND to the capture sink; routes each tool_call through `GuardRunner.intercept_tool_call` (deny → synthetic error to stdin) and each tool_result through `intercept_tool_result`; writes tool_call/tool_result events via `write_event`. Tests: feed it the sample stream over a pipe; assert events + firings land in a temp db. Commit.
- [ ] Make ClawTeam launch the wrapper: in `Topology.build_template_dict`, set template `command` to `[python, "-m", "pi_harness.agent_wrapper", "--executor", spec.executor]` (the wrapper resolves run_id/agent_id from `$CLAWTEAM_TEAM_NAME` + a team→run map in the registry). Unit-test the template dict; do NOT launch live here.

### Task 6.4: Live end-to-end validation (CREDIT, opt-in)
- [ ] Behind `PI_HARNESS_RUN_SMOKE=1`: launch a tiny real run, wait, then assert the dashboard `/runs/{id}` shows tool events with non-zero tokens and `total_cost_usd > 0`, and any guide/sensor firings appear in the timeline. Document results. Commit.

---

## Unresolved decisions (confirm with Pranav)

1. **Model prices.** `cost.py`'s `MODEL_PRICES` are EXAMPLE values. Confirm real OpenAI per-1M-token input/output prices for `gpt-5` / `gpt-5-mini` (or set `PI_HARNESS_MODEL_PRICES` JSON in `.env`). Until then cost figures are indicative.
2. **Reliability heuristics.** The four-dimension formulas in Task 4.8 are a first pass derived from event stats (no upstream scores exist). Confirm the definitions or refine after seeing real data.
3. **`pi`/`codex` stdout format.** UNVERIFIED until Task 6.1. The whole capture parser depends on it — spike before building.
4. **Branch override surface.** Level-1 supports `goal`/`topology`/`sync_mode`/`model_tier`. A per-agent model override or tool-allowlist override can be added if needed.
5. **WS semantics.** The tailer is poll-and-push with a "drain-then-idle-closes" rule so the sync test terminates; the browser reconnects via TanStack refetch. If you want a persistent socket, add server-side keepalive + client backoff (original Unresolved #8).
6. **Auth.** Localhost-only, no auth (original Unresolved #5). Add an API-key middleware before exposing beyond localhost.

---

## Self-review checklist (run before execution)
- Spec coverage: every Symphony pillar maps to a task — run list (4.2), timeline+icons (4.3/5.5), branch (2.2/4.4/5.5), corpus health+restore (4.5/5.6), specs (5.7), promotions (4.6/5.8), cost (1.1/1.3/5.5), reliability (4.8/5.5), live data (Phase 6).
- No upstream mocks in fixtures (real temp stores) — guards against the drift that motivated this rewrite.
- Type consistency: `RunSummary` fields identical in `runs.py` (1.2) ↔ `RunSummaryDTO` (4.2) ↔ `ui/lib/api.ts` (5.2).
- Smoke safety: every multi-file pytest invocation pins files or adds `-m "not smoke"`.
