# Symphony UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a FastAPI backend that exposes trajectory/corpus/spec/guard queries plus a Next.js + TypeScript dashboard (the Symphony UX surface from `HARNESS_ARCHITECTURE.md` §5) that lets the user list runs, inspect per-agent timelines with Guide/Sensor inline icons, branch+replay at checkpoints, watch corpus health, edit specs, and approve guard promotions.

**Architecture:** A single-process Python FastAPI app (`pi_harness/api/server.py`) is the only backend surface — it mounts Plan 7's `spec.editor` router and adds run/corpus/guard/WebSocket routes. The Next.js 14 App Router frontend in `ui/` calls it via a typed TanStack Query client (`ui/lib/api.ts`) generated from the FastAPI OpenAPI schema, and subscribes to live event streams over native WebSocket. Server components render the run list; the run-detail timeline is client-side for live updates. No design system is locked in — TailwindCSS only, hand-rolled minimal components for Pranav to restyle later.

**Tech Stack:**
- Backend: Python 3.10+, `fastapi[standard]`, `uvicorn`, `websockets`, `pydantic` v2, `pytest`, `httpx` (TestClient), `pytest-asyncio`.
- Frontend: Node 20+, `pnpm`, Next.js 14 (App Router), React 18, TypeScript strict, TailwindCSS, `@tanstack/react-query`, `lucide-react`, `openapi-typescript` (dev), native WebSocket.
- E2E: `@playwright/test`.

---

## Dependencies — read these from prior plans

You depend on five upstream plans. Skim their public surface before starting; if any is unimplemented when you begin a task, **stub it locally** in `tests/api/conftest.py` rather than blocking.

- **Plan 1 — Config.** `pi_harness.config.Config` (a frozen `@dataclass`) loaded via `from pi_harness.config import load_config; cfg = load_config()` — there is NO `Config.from_env()` classmethod. Provides `corpus_root: Path`, `trajectory_db_path: Path` (note: `_path` suffix), `clawteam_state_dir: Path`, `openai_api_key`, `reasoning_model`, `fast_model`. The dashboard-only knobs (`api_port`, `api_host`, `frontend_origin`) are NOT on Config — this plan reads them from env directly via `os.environ.get("PI_HARNESS_API_PORT", "8800")`, etc., or defines its own `DashboardConfig` dataclass in `pi_harness/api/config.py`.
- **Plan 2 — Trajectory store.**
  - `pi_harness.trajectory.store.query_runs(limit: int | None = None, status: str | None = None) -> list[RunSummary]`
  - `pi_harness.trajectory.store.query_events(run_id: str, since_ts: str | None = None, limit: int | None = None) -> list[TrajectoryEvent]`
  - `pi_harness.trajectory.schema.RunSummary` fields: `run_id, status, started_at, ended_at, agent_count, total_tokens_in, total_tokens_out, total_cost_usd, topology`.
  - `pi_harness.trajectory.schema.TrajectoryEvent` fields: `run_id, agent_id, step_id, ts, model, tool, input, output, duration_ms, tokens_in, tokens_out, outcome, classification, corpus_refs, corpus_cited, guide_firings: list[GuideFiring], sensor_firings: list[SensorFiring]`. `GuideFiring` and `SensorFiring` each have `name: str, status: Literal["pass","fail","warn"], detail: str`.
  - Plan 2 also exposes a live event bus: `pi_harness.trajectory.store.subscribe(run_id: str) -> AsyncIterator[TrajectoryEvent]` — yields events as agents emit them.
- **Plan 3 — Corpus.**
  - `pi_harness.corpus.reader.CorpusReader(root: Path)` with `find_by_classification`, `find_unreferenced`, `prime`, `expand`.
  - `pi_harness.corpus.prune.prune_by_budget / prune_by_counter / prune_by_contradiction / prune_by_staleness / prune_by_dedup` — used in **introspection only** (don't trigger writes from the API).
  - Plan 3's `Curator.restore_archived(entry_id: str) -> CorpusEntry` (the only write call this plan makes; defer if Plan 3 doesn't expose it yet — stub in conftest).
- **Plan 5 — Coordinator.** `pi_harness.topology.coordinator.Coordinator.launch(spec_id: str, topology: str, sync_mode: str, *, branch_from: BranchSeed | None = None) -> str` returns the new `run_id`. `BranchSeed = {parent_run_id, step_id, overrides: dict[str, Any]}`.
- **Plan 6 — Promote-to-Guide.** `pi_harness.guards.promote.suggest_promotions() -> list[PromotionCandidate]` where `PromotionCandidate = {check_id, name, fire_count, last_fired_at, sample_violations: list[dict]}`.
- **Plan 7 — Spec editor router.** `pi_harness.spec.editor.router: APIRouter` (mounted at `/specs`). Provides `GET /specs`, `GET /specs/{id}`, `PUT /specs/{id}`, `POST /specs/{id}/lint`, `POST /specs/{id}/decompose`, `POST /specs/{id}/launch`. The frontend `app/specs/page.tsx` calls these.

You provide downstream: nothing — this plan is the leaf.

---

## Conventions (apply to every task)

- **TDD on the backend.** Every FastAPI route gets a `httpx.AsyncClient` (or `TestClient`) test BEFORE the route is implemented. Run `uv run pytest tests/api/<file>.py -v` after each task.
- **TDD on the frontend is best-effort.** Playwright smoke + isolated component tests where they catch real issues. Don't chase coverage; chase wiring.
- **Type hints everywhere (Python).** All FastAPI route signatures use pydantic models for request and response — never bare `dict`. `from __future__ import annotations` at module top.
- **TypeScript strict.** `tsconfig.json` has `"strict": true`. No `any` except where a typed third-party shim is missing — annotate with `// @ts-expect-error <reason>` if unavoidable.
- **Conventional commits:** prefix `feat(api):`, `feat(ui):`, `test(api):`, `test(ui):`, `chore(ui):`, `chore(api):`. One commit per completed task (checkbox group).
- **No placeholders.** If a value is missing, stop and add it to `## Unresolved decisions` rather than emitting `# TODO` or `// TODO`.
- **No new design system.** No shadcn, no Radix, no Material. Tailwind utility classes and minimal hand-rolled components. Pranav restyles later — keep markup semantic and class lists small.
- **Run dirs / paths absolute in commands.** Every shell command in this plan uses absolute paths starting `/Users/pranavnair/Desktop/Personal/mannschaft`.
- **Always run frontend commands from `ui/`.** `cd ui && pnpm <cmd>` is the only form. The backend runs from repo root via `uv`.

---

## Task 0 — Project bootstrap

- [ ] **0.1** Confirm `pi_harness/` package exists at repo root with `__init__.py` (created by an upstream plan). If not, create it.
  - Run: `ls /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/__init__.py`
  - Expected: file exists. If not: `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness && touch /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/__init__.py`.
- [ ] **0.2** Create the API package skeleton.
  - Run: `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api /Users/pranavnair/Desktop/Personal/mannschaft/tests/api && touch /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/__init__.py /Users/pranavnair/Desktop/Personal/mannschaft/tests/api/__init__.py`
  - Expected: both `__init__.py` files exist and are empty.
- [ ] **0.3** Add backend dependencies via `uv`.
  - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv add 'fastapi[standard]' uvicorn websockets pydantic && uv add --dev pytest pytest-asyncio httpx`
  - Expected: `pyproject.toml` gains `fastapi`, `uvicorn`, `websockets`, `pydantic`; dev deps gain `pytest-asyncio`, `httpx`.
- [ ] **0.4** Confirm Node 20+ and pnpm are available.
  - Run: `node --version && pnpm --version`
  - Expected: `v20.*` (or higher) and any pnpm 8+. If pnpm is missing: `npm install -g pnpm`.
- [ ] **0.5** Initialise the `ui/` directory.
  - Run: `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/ui/app /Users/pranavnair/Desktop/Personal/mannschaft/ui/components /Users/pranavnair/Desktop/Personal/mannschaft/ui/lib /Users/pranavnair/Desktop/Personal/mannschaft/ui/public`
  - Expected: directories exist.
- [ ] **0.6** Create `tests/api/conftest.py` with shared fixtures.
  - File: `/Users/pranavnair/Desktop/Personal/mannschaft/tests/api/conftest.py`
  - Contents:
    ```python
    from __future__ import annotations
    from datetime import datetime, timezone
    from pathlib import Path
    from typing import Any
    import pytest
    from fastapi.testclient import TestClient

    @pytest.fixture
    def fixture_now() -> datetime:
        return datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def tmp_state(tmp_path: Path) -> dict[str, Path]:
        (tmp_path / "corpus").mkdir()
        for sub in ("foundational", "tactical", "observational", "archived"):
            (tmp_path / "corpus" / sub).mkdir()
        return {
            "corpus_root": tmp_path / "corpus",
            "trajectory_db": tmp_path / "trajectory.sqlite",
        }

    @pytest.fixture
    def fake_runs() -> list[dict[str, Any]]:
        return [
            {
                "run_id": "r-001", "status": "succeeded",
                "started_at": "2026-05-25T10:00:00Z", "ended_at": "2026-05-25T10:05:00Z",
                "agent_count": 3, "total_tokens_in": 1200, "total_tokens_out": 800,
                "total_cost_usd": 0.045, "topology": "sequential",
            },
            {
                "run_id": "r-002", "status": "running",
                "started_at": "2026-05-25T11:00:00Z", "ended_at": None,
                "agent_count": 5, "total_tokens_in": 5000, "total_tokens_out": 2000,
                "total_cost_usd": 0.18, "topology": "synthesis",
            },
        ]

    @pytest.fixture
    def fake_events() -> list[dict[str, Any]]:
        return [
            {
                "run_id": "r-001", "agent_id": "builder-1", "step_id": "s-1",
                "ts": "2026-05-25T10:00:01Z", "model": "openai-fast", "tool": "edit_file",
                "input": "...", "output": "...", "duration_ms": 1200,
                "tokens_in": 400, "tokens_out": 200, "outcome": "ok",
                "classification": "computational",
                "corpus_refs": ["pattern-abc123"], "corpus_cited": ["pattern-abc123"],
                "guide_firings": [
                    {"name": "allowlist-edit", "status": "pass", "detail": "ok"},
                ],
                "sensor_firings": [],
            },
            {
                "run_id": "r-001", "agent_id": "reviewer-1", "step_id": "s-2",
                "ts": "2026-05-25T10:00:30Z", "model": "openai-reasoning", "tool": "judge",
                "input": "...", "output": "...", "duration_ms": 4000,
                "tokens_in": 800, "tokens_out": 600, "outcome": "ok",
                "classification": "inferential",
                "corpus_refs": [], "corpus_cited": [],
                "guide_firings": [],
                "sensor_firings": [
                    {"name": "lint-judge", "status": "pass", "detail": "clean"},
                ],
            },
        ]

    @pytest.fixture
    def app_client(monkeypatch, tmp_state, fake_runs, fake_events):
        """TestClient wired against in-memory stubs for every upstream plan."""
        # Stub Plan 2
        import pi_harness.trajectory.store as store_mod  # may not exist yet
        monkeypatch.setattr(store_mod, "query_runs", lambda **kw: [
            store_mod.RunSummary(**r) for r in fake_runs
        ], raising=False)
        monkeypatch.setattr(store_mod, "query_events", lambda run_id, **kw: [
            store_mod.TrajectoryEvent(**e) for e in fake_events if e["run_id"] == run_id
        ], raising=False)
        # Stub Plan 5 (Coordinator.launch returns a fixed id)
        import pi_harness.topology.coordinator as coord_mod
        class _StubCoord:
            def launch(self, **kw): return "r-branch-001"
        monkeypatch.setattr(coord_mod, "Coordinator", _StubCoord, raising=False)
        # Stub Plan 6
        import pi_harness.guards.promote as promote_mod
        monkeypatch.setattr(promote_mod, "suggest_promotions",
            lambda: [{"check_id": "c1", "name": "schema-check", "fire_count": 8,
                      "last_fired_at": "2026-05-25T11:00:00Z", "sample_violations": []}],
            raising=False)
        # Build app
        from pi_harness.api.server import create_app
        from pi_harness.config import Config
        cfg = Config(
            corpus_root=tmp_state["corpus_root"],
            trajectory_db=tmp_state["trajectory_db"],
            api_port=8800, api_host="127.0.0.1",
            frontend_origin="http://localhost:3000",
        )
        app = create_app(cfg)
        return TestClient(app)
    ```
  - Run: `uv run pytest --collect-only tests/api -q`
  - Expected: collection succeeds (zero tests yet).
- [ ] **0.7** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add pi_harness/api tests/api ui pyproject.toml uv.lock && git commit -m "chore(api): bootstrap FastAPI package, ui scaffold dir, dev deps"`

---

## Task 1 — `pi_harness/api/server.py` — app factory + health check

- [ ] **1.1** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/api/test_server.py`:
  - `test_health_returns_200`: `GET /healthz` returns `{"status": "ok"}` and HTTP 200.
  - `test_openapi_served_at_docs`: `GET /docs` returns HTTP 200 (HTML).
  - `test_openapi_json_lists_runs_route`: `GET /openapi.json` JSON contains `paths["/runs"]` (will fail until Task 2; xfail-skip with reason for now or comment-out and re-enable in Task 2).
  - `test_cors_headers_present_for_frontend_origin`: `OPTIONS /runs` with `Origin: http://localhost:3000` returns `access-control-allow-origin: http://localhost:3000`.
  - `test_create_app_mounts_specs_router`: assert `/specs` exists in `app.routes` (router from Plan 7).
  - Run: `uv run pytest tests/api/test_server.py -v` → fails (module not yet implemented).
- [ ] **1.2** Implement `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/server.py`:
  ```python
  from __future__ import annotations

  import os
  from dataclasses import dataclass

  from fastapi import FastAPI
  from fastapi.middleware.cors import CORSMiddleware

  from pi_harness.config import Config, load_config

  # Plan 7 router import; if it doesn't exist yet, fall back to an empty APIRouter.
  try:
      from pi_harness.spec.editor import router as spec_router
  except ImportError:  # pragma: no cover - bootstrap only
      from fastapi import APIRouter
      spec_router = APIRouter()


  @dataclass(frozen=True)
  class DashboardConfig:
      """Dashboard-specific config — kept out of Plan 1's harness Config so the
      core library doesn't carry FastAPI/UI concerns. Loaded from env in
      ``load_dashboard_config``."""
      api_host: str = "127.0.0.1"
      api_port: int = 8800
      frontend_origin: str = "http://localhost:3000"


  def load_dashboard_config() -> DashboardConfig:
      return DashboardConfig(
          api_host=os.environ.get("PI_HARNESS_API_HOST", "127.0.0.1"),
          api_port=int(os.environ.get("PI_HARNESS_API_PORT", "8800")),
          frontend_origin=os.environ.get(
              "PI_HARNESS_FRONTEND_ORIGIN", "http://localhost:3000"
          ),
      )


  def create_app(config: Config, dash: DashboardConfig | None = None) -> FastAPI:
      dash = dash or load_dashboard_config()
      app = FastAPI(
          title="Pi-Agent Harness API",
          version="0.1.0",
          description="Trajectory, corpus, spec, and guard surfaces for the Symphony dashboard.",
      )
      app.state.config = config
      app.state.dashboard_config = dash
      app.add_middleware(
          CORSMiddleware,
          allow_origins=[dash.frontend_origin],
          allow_credentials=True,
          allow_methods=["*"],
          allow_headers=["*"],
      )

      @app.get("/healthz")
      def healthz() -> dict[str, str]:
          return {"status": "ok"}

      app.include_router(spec_router, prefix="/specs", tags=["specs"])
      return app


  def main() -> None:
      """Entrypoint for ``python -m pi_harness.api.server``."""
      import uvicorn

      config = load_config()
      dash = load_dashboard_config()
      app = create_app(config, dash)
      uvicorn.run(app, host=dash.api_host, port=dash.api_port, reload=False)


  if __name__ == "__main__":  # python -m pi_harness.api.server
      main()
  ```
  - Note: we pass a pre-built `app` to uvicorn (no `factory=True`) because `create_app` requires a `Config` argument. The Plan 1 `Config` is loaded once at startup; the dashboard knobs live on `DashboardConfig` and are read from env vars (`PI_HARNESS_API_HOST`, `PI_HARNESS_API_PORT`, `PI_HARNESS_FRONTEND_ORIGIN`).
- [ ] **1.3** Implement the `__main__.py` entrypoint at `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/__main__.py`:
  ```python
  from pi_harness.api.server import main
  if __name__ == "__main__":
      main()
  ```
- [ ] **1.4** Run tests.
  - Run: `uv run pytest tests/api/test_server.py -v`
  - Expected: 4/5 pass; `test_openapi_json_lists_runs_route` still xfail until Task 2.
- [ ] **1.5** Smoke-launch.
  - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run python -m pi_harness.api server --port 8800` in one terminal, `curl http://127.0.0.1:8800/healthz` in another.
  - Expected: `{"status":"ok"}`. Confirm `http://127.0.0.1:8800/docs` renders Swagger UI in a browser. Kill the server with Ctrl-C.
- [ ] **1.6** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add pi_harness/api tests/api && git commit -m "feat(api): app factory, healthz, CORS, mount specs router"`

---

## Task 2 — `GET /runs` and `GET /runs/{run_id}`

- [ ] **2.1** Define pydantic response models in `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/models.py`:
  ```python
  from __future__ import annotations
  from datetime import datetime
  from typing import Any, Literal
  from pydantic import BaseModel, Field

  class GuideFiringDTO(BaseModel):
      name: str
      status: Literal["pass", "fail", "warn"]
      detail: str

  class SensorFiringDTO(GuideFiringDTO):
      pass

  class TrajectoryEventDTO(BaseModel):
      run_id: str
      agent_id: str
      step_id: str
      ts: datetime
      model: str
      tool: str
      input: str
      output: str
      duration_ms: int
      tokens_in: int
      tokens_out: int
      outcome: str
      classification: Literal["computational", "inferential"]
      corpus_refs: list[str] = Field(default_factory=list)
      corpus_cited: list[str] = Field(default_factory=list)
      guide_firings: list[GuideFiringDTO] = Field(default_factory=list)
      sensor_firings: list[SensorFiringDTO] = Field(default_factory=list)

  class RunSummaryDTO(BaseModel):
      run_id: str
      status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
      started_at: datetime
      ended_at: datetime | None = None
      agent_count: int
      total_tokens_in: int
      total_tokens_out: int
      total_cost_usd: float
      topology: Literal["sequential", "parallel", "synthesis", "nested", "persistent"]

  class RunDetailDTO(BaseModel):
      summary: RunSummaryDTO
      events: list[TrajectoryEventDTO]
  ```
- [ ] **2.2** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/api/test_runs.py`:
  - `test_list_runs_returns_summaries`: `GET /runs` returns 200 and a list of two summaries (from `fake_runs`); assert keys match `RunSummaryDTO` fields.
  - `test_list_runs_filter_by_status`: `GET /runs?status=running` returns one run with `run_id == "r-002"`.
  - `test_list_runs_limit`: `GET /runs?limit=1` returns one item.
  - `test_get_run_detail_returns_summary_and_events`: `GET /runs/r-001` returns the summary plus 2 events from `fake_events`.
  - `test_get_run_detail_404_unknown_run`: `GET /runs/r-nope` returns 404 with body `{"detail": "run not found"}`.
  - Run: `uv run pytest tests/api/test_runs.py -v` → fail.
- [ ] **2.3** Create `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/routes/__init__.py` (empty) and `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/routes/runs.py`:
  ```python
  from __future__ import annotations
  from fastapi import APIRouter, HTTPException, Query
  from pi_harness.api.models import RunDetailDTO, RunSummaryDTO, TrajectoryEventDTO
  from pi_harness.trajectory.store import query_runs, query_events

  router = APIRouter()

  @router.get("/runs", response_model=list[RunSummaryDTO])
  def list_runs(
      status: str | None = Query(default=None),
      limit: int | None = Query(default=None, ge=1, le=500),
  ) -> list[RunSummaryDTO]:
      summaries = query_runs(status=status, limit=limit)
      return [RunSummaryDTO.model_validate(s, from_attributes=True) for s in summaries]

  @router.get("/runs/{run_id}", response_model=RunDetailDTO)
  def get_run(run_id: str) -> RunDetailDTO:
      all_runs = query_runs()
      match = next((r for r in all_runs if r.run_id == run_id), None)
      if match is None:
          raise HTTPException(status_code=404, detail="run not found")
      events = query_events(run_id=run_id)
      return RunDetailDTO(
          summary=RunSummaryDTO.model_validate(match, from_attributes=True),
          events=[TrajectoryEventDTO.model_validate(e, from_attributes=True) for e in events],
      )
  ```
- [ ] **2.4** Wire the router into `create_app`. Edit `pi_harness/api/server.py`:
  ```python
  from pi_harness.api.routes.runs import router as runs_router
  # … inside create_app, after the specs router include:
  app.include_router(runs_router, tags=["runs"])
  ```
- [ ] **2.5** Run tests.
  - Run: `uv run pytest tests/api/test_runs.py tests/api/test_server.py -v`
  - Expected: all pass. Un-xfail the openapi test from Task 1.
- [ ] **2.6** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add pi_harness/api tests/api && git commit -m "feat(api): GET /runs and /runs/{run_id} with pydantic DTOs"`

---

## Task 3 — `GET /runs/{run_id}/timeline` (grouped per-agent)

- [ ] **3.1** Add to `pi_harness/api/models.py`:
  ```python
  class AgentTimelineRowDTO(BaseModel):
      agent_id: str
      events: list[TrajectoryEventDTO]

  class TimelineDTO(BaseModel):
      run_id: str
      agents: list[AgentTimelineRowDTO]
  ```
- [ ] **3.2** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/api/test_timeline.py`:
  - `test_timeline_groups_events_by_agent`: `GET /runs/r-001/timeline` returns 200 with `agents` of length 2 (builder-1, reviewer-1) in order of first-event timestamp.
  - `test_timeline_includes_guide_and_sensor_firings_inline`: assert the builder-1 row's events[0] has `guide_firings` with one entry named `allowlist-edit`; reviewer-1 row's events[0] has `sensor_firings` with one entry named `lint-judge`.
  - `test_timeline_404_unknown_run`: `GET /runs/r-nope/timeline` returns 404.
  - Run: `uv run pytest tests/api/test_timeline.py -v` → fail.
- [ ] **3.3** Append to `pi_harness/api/routes/runs.py`:
  ```python
  from collections import OrderedDict
  from pi_harness.api.models import TimelineDTO, AgentTimelineRowDTO

  @router.get("/runs/{run_id}/timeline", response_model=TimelineDTO)
  def get_timeline(run_id: str) -> TimelineDTO:
      all_runs = query_runs()
      if not any(r.run_id == run_id for r in all_runs):
          raise HTTPException(status_code=404, detail="run not found")
      events = query_events(run_id=run_id)
      grouped: OrderedDict[str, list[TrajectoryEventDTO]] = OrderedDict()
      for e in sorted(events, key=lambda ev: ev.ts):
          dto = TrajectoryEventDTO.model_validate(e, from_attributes=True)
          grouped.setdefault(e.agent_id, []).append(dto)
      return TimelineDTO(
          run_id=run_id,
          agents=[AgentTimelineRowDTO(agent_id=a, events=evs) for a, evs in grouped.items()],
      )
  ```
- [ ] **3.4** Run: `uv run pytest tests/api/test_timeline.py -v` → expected: pass.
- [ ] **3.5** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add pi_harness/api tests/api && git commit -m "feat(api): GET /runs/{run_id}/timeline grouped per-agent"`

---

## Task 4 — `POST /runs/{run_id}/branch`

- [ ] **4.1** Add to `pi_harness/api/models.py`:
  ```python
  class BranchRequest(BaseModel):
      step_id: str
      overrides: dict[str, Any] = Field(default_factory=dict)
      topology: Literal["sequential", "parallel", "synthesis", "nested", "persistent"] | None = None
      sync_mode: Literal["sync_all", "separate"] | None = None

  class BranchResponse(BaseModel):
      run_id: str
      parent_run_id: str
      branched_from_step: str
  ```
- [ ] **4.2** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/api/test_branch.py`:
  - `test_branch_calls_coordinator_with_branch_seed`: POST `/runs/r-001/branch` with `{"step_id": "s-1", "overrides": {"model": "openai-reasoning"}}` returns 200, body `{"run_id": "r-branch-001", "parent_run_id": "r-001", "branched_from_step": "s-1"}`. Use the `_StubCoord` from the fixture.
  - `test_branch_404_unknown_parent`: POST `/runs/r-nope/branch` with valid body returns 404.
  - `test_branch_422_invalid_topology`: POST with `topology="invalid"` returns 422 from pydantic.
  - `test_branch_422_missing_step_id`: POST `{}` returns 422.
  - Run: `uv run pytest tests/api/test_branch.py -v` → fail.
- [ ] **4.3** Append to `pi_harness/api/routes/runs.py`:
  ```python
  from pi_harness.api.models import BranchRequest, BranchResponse
  from pi_harness.topology.coordinator import Coordinator

  @router.post("/runs/{run_id}/branch", response_model=BranchResponse)
  def branch_run(run_id: str, body: BranchRequest) -> BranchResponse:
      all_runs = query_runs()
      parent = next((r for r in all_runs if r.run_id == run_id), None)
      if parent is None:
          raise HTTPException(status_code=404, detail="run not found")
      coord = Coordinator()
      new_run_id = coord.launch(
          spec_id="",  # branch reuses parent's spec — Plan 5 resolves from parent_run_id
          topology=body.topology or parent.topology,
          sync_mode=body.sync_mode or "separate",
          branch_from={
              "parent_run_id": run_id,
              "step_id": body.step_id,
              "overrides": body.overrides,
          },
      )
      return BranchResponse(
          run_id=new_run_id,
          parent_run_id=run_id,
          branched_from_step=body.step_id,
      )
  ```
- [ ] **4.4** Run: `uv run pytest tests/api/test_branch.py -v` → expected: pass.
- [ ] **4.5** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add pi_harness/api tests/api && git commit -m "feat(api): POST /runs/{run_id}/branch wires Coordinator.launch"`

---

## Task 5 — Corpus routes (`/corpus/health`, `/corpus/entries`, restore)

- [ ] **5.1** Add to `pi_harness/api/models.py`:
  ```python
  class CorpusEntryDTO(BaseModel):
      id: str
      record_type: Literal["convention", "pattern", "failure", "decision", "reference", "guide"]
      classification: Literal["foundational", "tactical", "observational"]
      helpful_count: int
      harmful_count: int
      contradiction_count: int
      created_at: datetime
      last_updated_at: datetime
      last_referenced_run_id: str | None
      size_tokens: int
      archived: bool = False
      body_preview: str  # first 80 chars

  class CorpusHealthDTO(BaseModel):
      total_active_tokens: int
      soft_cap_tokens: int
      pct_of_cap: float  # 0..1+
      foundational_count: int
      tactical_count: int
      observational_count: int
      archived_count: int
      prune_candidates: dict[str, int]  # {"counter": N, "contradiction": M, "staleness": K, "dedup": J, "budget": Q}
      stale_entries: list[CorpusEntryDTO]
      recently_archived: list[CorpusEntryDTO]

  class CorpusEntryFilter(BaseModel):
      classification: Literal["foundational", "tactical", "observational"] | None = None
      record_type: Literal["convention", "pattern", "failure", "decision", "reference", "guide"] | None = None
      archived: bool | None = None
  ```
- [ ] **5.2** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/api/test_corpus.py`:
  - Build a tiny corpus on disk in the fixture (3 entries summing to e.g. 10k tokens, soft cap 50k). Use `pi_harness.corpus.format.serialize_entry` + `writer.curator_context` for setup.
  - `test_corpus_health_returns_token_gauge`: `GET /corpus/health` returns 200; `pct_of_cap == approx(0.2)`; counts are correct.
  - `test_corpus_health_lists_prune_candidates_grouped_by_trigger`: seed one entry with `harmful_count=10, helpful_count=1` → `prune_candidates["counter"] == 1`.
  - `test_corpus_entries_filterable`: `GET /corpus/entries?classification=tactical` returns only tactical.
  - `test_corpus_entries_filter_record_type`: `GET /corpus/entries?record_type=pattern` returns only patterns.
  - `test_corpus_entries_default_excludes_archived`: archived entries excluded unless `?archived=true`.
  - `test_restore_archived_entry`: seed an archived entry, POST `/corpus/entries/<id>/restore` returns 200 with the restored DTO; the entry's file is now in `<root>/<classification>/`, not `<root>/archived/`.
  - `test_restore_404_unknown`: POST restore on bogus id returns 404.
  - Run: `uv run pytest tests/api/test_corpus.py -v` → fail.
- [ ] **5.3** Implement `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/routes/corpus.py`:
  ```python
  from __future__ import annotations
  from datetime import datetime, timezone
  from fastapi import APIRouter, HTTPException, Query, Request
  from pi_harness.corpus.reader import CorpusReader
  from pi_harness.corpus.format import Classification, RecordType, parse_entry
  from pi_harness.corpus.prune import (
      prune_by_counter, prune_by_contradiction, prune_by_staleness,
      prune_by_dedup, prune_by_budget,
  )
  from pi_harness.corpus.curator import Curator
  from pi_harness.api.models import CorpusEntryDTO, CorpusHealthDTO

  router = APIRouter(prefix="/corpus", tags=["corpus"])

  SOFT_CAP = 50_000  # default from architecture doc §2

  def _entry_to_dto(entry, archived: bool = False) -> CorpusEntryDTO:
      preview = entry.body.strip().splitlines()[0][:80] if entry.body.strip() else ""
      return CorpusEntryDTO(
          id=entry.id,
          record_type=entry.record_type.value,
          classification=entry.classification.value,
          helpful_count=entry.helpful_count,
          harmful_count=entry.harmful_count,
          contradiction_count=entry.contradiction_count,
          created_at=entry.created_at,
          last_updated_at=entry.last_updated_at,
          last_referenced_run_id=entry.last_referenced_run_id,
          size_tokens=entry.size_tokens,
          archived=archived,
          body_preview=preview,
      )

  @router.get("/health", response_model=CorpusHealthDTO)
  def corpus_health(request: Request) -> CorpusHealthDTO:
      cfg = request.app.state.config
      reader = CorpusReader(cfg.corpus_root)
      now = datetime.now(timezone.utc)
      active = []
      for cls in Classification:
          active.extend(reader.find_by_classification(cls))
      total_tokens = sum(e.size_tokens for e in active)
      counter_count = sum(1 for e in active if prune_by_counter(e))
      contradiction_count = sum(1 for e in active if prune_by_contradiction(e))
      staleness_count = sum(1 for e in active if prune_by_staleness(e, now, recent_run_ids=[]))
      dedup_actions = prune_by_dedup(active, now=now)
      budget_actions = prune_by_budget(active, soft_cap=SOFT_CAP, now=now)
      stale = reader.find_unreferenced(days=7, now=now)
      # archived list — walk the archive subdir directly
      archived = []
      archive_root = cfg.corpus_root / "archived"
      if archive_root.exists():
          for path in sorted(archive_root.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:25]:
              archived.append(parse_entry(path))
      return CorpusHealthDTO(
          total_active_tokens=total_tokens,
          soft_cap_tokens=SOFT_CAP,
          pct_of_cap=total_tokens / SOFT_CAP if SOFT_CAP else 0.0,
          foundational_count=sum(1 for e in active if e.classification == Classification.FOUNDATIONAL),
          tactical_count=sum(1 for e in active if e.classification == Classification.TACTICAL),
          observational_count=sum(1 for e in active if e.classification == Classification.OBSERVATIONAL),
          archived_count=len(archived),
          prune_candidates={
              "counter": counter_count,
              "contradiction": contradiction_count,
              "staleness": staleness_count,
              "dedup": len(dedup_actions),
              "budget": len(budget_actions),
          },
          stale_entries=[_entry_to_dto(e) for e in stale[:50]],
          recently_archived=[_entry_to_dto(e, archived=True) for e in archived],
      )

  @router.get("/entries", response_model=list[CorpusEntryDTO])
  def list_entries(
      request: Request,
      classification: str | None = Query(default=None),
      record_type: str | None = Query(default=None),
      archived: bool = Query(default=False),
  ) -> list[CorpusEntryDTO]:
      cfg = request.app.state.config
      reader = CorpusReader(cfg.corpus_root)
      if archived:
          archive_root = cfg.corpus_root / "archived"
          entries = [parse_entry(p) for p in archive_root.rglob("*.md")] if archive_root.exists() else []
          return [_entry_to_dto(e, archived=True) for e in entries
                  if (record_type is None or e.record_type.value == record_type)
                  and (classification is None or e.classification.value == classification)]
      if classification:
          entries = reader.find_by_classification(Classification(classification))
      else:
          entries = []
          for cls in Classification:
              entries.extend(reader.find_by_classification(cls))
      if record_type:
          entries = [e for e in entries if e.record_type.value == record_type]
      return [_entry_to_dto(e) for e in entries]

  @router.post("/entries/{entry_id}/restore", response_model=CorpusEntryDTO)
  def restore_entry(request: Request, entry_id: str) -> CorpusEntryDTO:
      cfg = request.app.state.config
      curator = Curator(cfg)
      try:
          entry = curator.restore_archived(entry_id)
      except FileNotFoundError:
          raise HTTPException(status_code=404, detail="archived entry not found")
      return _entry_to_dto(entry)
  ```
- [ ] **5.4** Mount the router. Edit `pi_harness/api/server.py`:
  ```python
  from pi_harness.api.routes.corpus import router as corpus_router
  # … inside create_app:
  app.include_router(corpus_router)
  ```
- [ ] **5.5** Run: `uv run pytest tests/api/test_corpus.py -v` → expected: pass.
- [ ] **5.6** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add pi_harness/api tests/api && git commit -m "feat(api): corpus health/entries/restore routes"`

---

## Task 6 — `GET /guards/promotion-candidates`

- [ ] **6.1** Add to `pi_harness/api/models.py`:
  ```python
  class PromotionCandidateDTO(BaseModel):
      check_id: str
      name: str
      fire_count: int
      last_fired_at: datetime
      sample_violations: list[dict[str, Any]] = Field(default_factory=list)
  ```
- [ ] **6.2** Write failing test in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/api/test_guards.py`:
  - `test_promotion_candidates_returns_suggested_list`: `GET /guards/promotion-candidates` returns 200 with one candidate `{"check_id": "c1", "name": "schema-check", ...}` from the fixture stub.
  - Run: `uv run pytest tests/api/test_guards.py -v` → fail.
- [ ] **6.3** Implement `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/routes/guards.py`:
  ```python
  from __future__ import annotations
  from fastapi import APIRouter
  from pi_harness.api.models import PromotionCandidateDTO
  from pi_harness.guards.promote import suggest_promotions

  router = APIRouter(prefix="/guards", tags=["guards"])

  @router.get("/promotion-candidates", response_model=list[PromotionCandidateDTO])
  def promotion_candidates() -> list[PromotionCandidateDTO]:
      return [PromotionCandidateDTO.model_validate(c) for c in suggest_promotions()]
  ```
- [ ] **6.4** Mount in `server.py` (`app.include_router(guards_router)`).
- [ ] **6.5** Run: `uv run pytest tests/api/test_guards.py -v` → expected: pass.
- [ ] **6.6** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add pi_harness/api tests/api && git commit -m "feat(api): GET /guards/promotion-candidates from Plan 6"`

---

## Task 7 — WebSocket `/ws/runs/{run_id}` live event stream

- [ ] **7.1** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/api/test_websocket.py`:
  - Patch `pi_harness.trajectory.store.subscribe` to return an `AsyncIterator` over a small list of fake events (use an `async def` generator).
  - `test_websocket_streams_events_for_run`: open `client.websocket_connect("/ws/runs/r-001")`; read first message; assert it parses as JSON matching `TrajectoryEventDTO`. Read second message; assert agent_id differs. Close. Use `TestClient` (synchronous wrapper).
  - `test_websocket_404_unknown_run`: connect to `/ws/runs/r-nope`; assert connection closes with code 4404 (custom) or rejects with HTTP 404 — pick one, document, test.
  - Run: `uv run pytest tests/api/test_websocket.py -v` → fail.
- [ ] **7.2** Implement `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/routes/ws.py`:
  ```python
  from __future__ import annotations
  from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
  from pi_harness.api.models import TrajectoryEventDTO
  from pi_harness.trajectory.store import query_runs, subscribe

  router = APIRouter()

  @router.websocket("/ws/runs/{run_id}")
  async def ws_run(websocket: WebSocket, run_id: str) -> None:
      if not any(r.run_id == run_id for r in query_runs()):
          await websocket.close(code=4404, reason="run not found")
          return
      await websocket.accept()
      try:
          async for event in subscribe(run_id):
              dto = TrajectoryEventDTO.model_validate(event, from_attributes=True)
              await websocket.send_json(dto.model_dump(mode="json"))
      except WebSocketDisconnect:
          return
      except Exception:
          await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
          raise
  ```
- [ ] **7.3** Mount in `server.py` (`app.include_router(ws_router)`).
- [ ] **7.4** Run: `uv run pytest tests/api/test_websocket.py -v` → expected: pass.
- [ ] **7.5** Latency sanity: emit a real event from a test fixture, measure round-trip from `store.subscribe` yield to `websocket.send_json` completion using `time.perf_counter`. Add as `test_websocket_latency_under_500ms` (acceptance 7).
- [ ] **7.6** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add pi_harness/api tests/api && git commit -m "feat(api): WebSocket /ws/runs/{run_id} live event stream"`

---

## Task 8 — Frontend bootstrap (Next.js + Tailwind + pnpm)

- [ ] **8.1** Initialise Next.js manually (we want full control of files — skip `create-next-app`).
  - Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/package.json`:
    ```json
    {
      "name": "pi-harness-ui",
      "version": "0.1.0",
      "private": true,
      "scripts": {
        "dev": "next dev",
        "build": "next build",
        "start": "next start",
        "lint": "next lint",
        "typecheck": "tsc --noEmit",
        "gen:api": "openapi-typescript http://127.0.0.1:8800/openapi.json -o lib/api-types.ts",
        "test:e2e": "playwright test"
      },
      "dependencies": {
        "next": "14.2.5",
        "react": "18.3.1",
        "react-dom": "18.3.1",
        "@tanstack/react-query": "5.51.1",
        "lucide-react": "0.408.0"
      },
      "devDependencies": {
        "@playwright/test": "1.45.1",
        "@types/node": "20.14.10",
        "@types/react": "18.3.3",
        "@types/react-dom": "18.3.0",
        "autoprefixer": "10.4.19",
        "openapi-typescript": "7.0.2",
        "postcss": "8.4.39",
        "tailwindcss": "3.4.6",
        "typescript": "5.5.3"
      }
    }
    ```
- [ ] **8.2** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/tsconfig.json`:
  ```json
  {
    "compilerOptions": {
      "target": "ES2022",
      "lib": ["dom", "dom.iterable", "esnext"],
      "allowJs": false,
      "skipLibCheck": true,
      "strict": true,
      "noEmit": true,
      "esModuleInterop": true,
      "module": "esnext",
      "moduleResolution": "bundler",
      "resolveJsonModule": true,
      "isolatedModules": true,
      "jsx": "preserve",
      "incremental": true,
      "plugins": [{ "name": "next" }],
      "paths": { "@/*": ["./*"] }
    },
    "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
    "exclude": ["node_modules", "tests/ui"]
  }
  ```
- [ ] **8.3** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/next.config.js`:
  ```js
  /** @type {import('next').NextConfig} */
  const nextConfig = {
    reactStrictMode: true,
    env: {
      NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8800",
    },
  };
  module.exports = nextConfig;
  ```
- [ ] **8.4** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/tailwind.config.ts`:
  ```ts
  import type { Config } from "tailwindcss";
  const config: Config = {
    content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
    theme: { extend: {} },
    plugins: [],
  };
  export default config;
  ```
- [ ] **8.5** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/postcss.config.js`:
  ```js
  module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };
  ```
- [ ] **8.6** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/app/globals.css`:
  ```css
  @tailwind base;
  @tailwind components;
  @tailwind utilities;

  :root { color-scheme: light dark; }
  html, body { height: 100%; margin: 0; }
  body { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  ```
- [ ] **8.7** Add a `.gitignore` at `/Users/pranavnair/Desktop/Personal/mannschaft/ui/.gitignore`:
  ```
  node_modules/
  .next/
  out/
  next-env.d.ts
  .env.local
  playwright-report/
  test-results/
  ```
- [ ] **8.8** Install.
  - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm install`
  - Expected: lockfile written, no errors.
- [ ] **8.9** Smoke check.
  - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm typecheck`
  - Expected: passes (no source files yet — empty pass is fine).
- [ ] **8.10** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add ui/package.json ui/pnpm-lock.yaml ui/tsconfig.json ui/next.config.js ui/tailwind.config.ts ui/postcss.config.js ui/app/globals.css ui/.gitignore && git commit -m "chore(ui): Next.js 14 + Tailwind + pnpm scaffold"`

---

## Task 9 — `ui/lib/api.ts` typed client + TanStack Query provider

- [ ] **9.1** Generate the OpenAPI types. The backend must be running for this step.
  - Run (terminal A): `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run python -m pi_harness.api`
  - Run (terminal B): `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm gen:api`
  - Expected: `ui/lib/api-types.ts` written. Stop the backend with Ctrl-C.
- [ ] **9.2** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/lib/api.ts`:
  ```ts
  import type { components } from "./api-types";

  export type RunSummary = components["schemas"]["RunSummaryDTO"];
  export type RunDetail = components["schemas"]["RunDetailDTO"];
  export type Timeline = components["schemas"]["TimelineDTO"];
  export type TrajectoryEvent = components["schemas"]["TrajectoryEventDTO"];
  export type CorpusHealth = components["schemas"]["CorpusHealthDTO"];
  export type CorpusEntry = components["schemas"]["CorpusEntryDTO"];
  export type PromotionCandidate = components["schemas"]["PromotionCandidateDTO"];
  export type BranchRequest = components["schemas"]["BranchRequest"];
  export type BranchResponse = components["schemas"]["BranchResponse"];

  const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8800";

  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers || {}) },
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`);
    return res.json() as Promise<T>;
  }

  export const api = {
    listRuns: (q: { status?: string; limit?: number } = {}) => {
      const params = new URLSearchParams();
      if (q.status) params.set("status", q.status);
      if (q.limit) params.set("limit", String(q.limit));
      const qs = params.toString();
      return json<RunSummary[]>(`/runs${qs ? `?${qs}` : ""}`);
    },
    getRun: (runId: string) => json<RunDetail>(`/runs/${runId}`),
    getTimeline: (runId: string) => json<Timeline>(`/runs/${runId}/timeline`),
    branchRun: (runId: string, body: BranchRequest) =>
      json<BranchResponse>(`/runs/${runId}/branch`, { method: "POST", body: JSON.stringify(body) }),
    corpusHealth: () => json<CorpusHealth>("/corpus/health"),
    corpusEntries: (q: { classification?: string; record_type?: string; archived?: boolean } = {}) => {
      const params = new URLSearchParams();
      if (q.classification) params.set("classification", q.classification);
      if (q.record_type) params.set("record_type", q.record_type);
      if (q.archived) params.set("archived", "true");
      const qs = params.toString();
      return json<CorpusEntry[]>(`/corpus/entries${qs ? `?${qs}` : ""}`);
    },
    restoreEntry: (entryId: string) =>
      json<CorpusEntry>(`/corpus/entries/${entryId}/restore`, { method: "POST" }),
    promotionCandidates: () => json<PromotionCandidate[]>("/guards/promotion-candidates"),
    listSpecs: () => json<{ id: string; title: string; updated_at: string }[]>("/specs"),
    getSpec: (id: string) => json<{ id: string; title: string; body: string; frontmatter: Record<string, unknown> }>(`/specs/${id}`),
    saveSpec: (id: string, body: string) =>
      json<{ ok: boolean }>(`/specs/${id}`, { method: "PUT", body: JSON.stringify({ body }) }),
    lintSpec: (id: string) =>
      json<{ violations: { code: string; message: string; line?: number }[] }>(`/specs/${id}/lint`, { method: "POST" }),
    decomposeSpec: (id: string) =>
      json<{ tasks: { id: string; title: string; blocked_by: string[] }[] }>(`/specs/${id}/decompose`, { method: "POST" }),
    launchSpec: (id: string, body: { topology: string; sync_mode: string }) =>
      json<{ run_id: string }>(`/specs/${id}/launch`, { method: "POST", body: JSON.stringify(body) }),
  };
  ```
- [ ] **9.3** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/lib/query-client.tsx`:
  ```tsx
  "use client";
  import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
  import { ReactNode, useState } from "react";

  export function QueryProvider({ children }: { children: ReactNode }) {
    const [client] = useState(() => new QueryClient({
      defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
    }));
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  ```
- [ ] **9.4** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/lib/use-live-run.ts`:
  ```ts
  "use client";
  import { useEffect, useRef, useState } from "react";
  import type { TrajectoryEvent } from "./api";

  export function useLiveRun(runId: string | null) {
    const [events, setEvents] = useState<TrajectoryEvent[]>([]);
    const [status, setStatus] = useState<"idle" | "connecting" | "open" | "closed" | "error">("idle");
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
      if (!runId) return;
      const base = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8800";
      const wsUrl = base.replace(/^http/, "ws") + `/ws/runs/${runId}`;
      setStatus("connecting");
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen = () => setStatus("open");
      ws.onmessage = (msg) => {
        try { setEvents((prev) => [...prev, JSON.parse(msg.data) as TrajectoryEvent]); }
        catch { /* ignore malformed */ }
      };
      ws.onerror = () => setStatus("error");
      ws.onclose = () => setStatus("closed");
      return () => { ws.close(); };
    }, [runId]);

    return { events, status };
  }
  ```
- [ ] **9.5** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add ui/lib && git commit -m "feat(ui): typed API client, TanStack Query provider, live-run WS hook"`

---

## Task 10 — `ui/app/layout.tsx` + left rail nav (6 audit-order components)

- [ ] **10.1** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/components/LeftRail.tsx`:
  ```tsx
  "use client";
  import Link from "next/link";
  import { usePathname } from "next/navigation";
  import { Boxes, FileText, Wrench, Layers, Database, Users } from "lucide-react";

  // 6-component audit order from HARNESS_ARCHITECTURE.md §5
  const NAV = [
    { href: "/", label: "Workspace", icon: Boxes },
    { href: "/specs", label: "Prompt Shape", icon: FileText },
    { href: "/guards", label: "Tools", icon: Wrench },
    { href: "/corpus", label: "Context", icon: Layers },
    { href: "/memory", label: "Memory", icon: Database },
    { href: "/subagents", label: "Subagents", icon: Users },
  ];

  export function LeftRail() {
    const pathname = usePathname();
    return (
      <nav aria-label="Audit order" className="w-56 shrink-0 border-r border-zinc-200 dark:border-zinc-800 p-3">
        <div className="mb-4 text-xs font-mono uppercase tracking-wider text-zinc-500">Pi-Agent Harness</div>
        <ul className="space-y-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={`flex items-center gap-2 rounded px-2 py-1.5 text-sm ${
                    active
                      ? "bg-zinc-100 dark:bg-zinc-800 font-medium"
                      : "text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800/50"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  <span>{label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    );
  }
  ```
- [ ] **10.2** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/app/layout.tsx`:
  ```tsx
  import "./globals.css";
  import type { Metadata } from "next";
  import { LeftRail } from "@/components/LeftRail";
  import { QueryProvider } from "@/lib/query-client";

  export const metadata: Metadata = {
    title: "Pi-Agent Harness",
    description: "Symphony-style dashboard for the Pi-Agent Harness.",
  };

  export default function RootLayout({ children }: { children: React.ReactNode }) {
    return (
      <html lang="en">
        <body className="bg-white text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
          <QueryProvider>
            <div className="flex min-h-screen">
              <LeftRail />
              <main className="flex-1 overflow-auto p-6">{children}</main>
            </div>
          </QueryProvider>
        </body>
      </html>
    );
  }
  ```
- [ ] **10.3** Add empty stubs for `/memory` and `/subagents` so the LeftRail links don't 404. Each is a single-file route returning a "Coming soon" page (these are out of v1 scope per the architecture doc but listed in the audit order).
  - `/Users/pranavnair/Desktop/Personal/mannschaft/ui/app/memory/page.tsx`:
    ```tsx
    export default function MemoryPage() {
      return <div className="text-zinc-500">Memory inspector — v2.</div>;
    }
    ```
  - `/Users/pranavnair/Desktop/Personal/mannschaft/ui/app/subagents/page.tsx`:
    ```tsx
    export default function SubagentsPage() {
      return <div className="text-zinc-500">Subagent topology — v2.</div>;
    }
    ```
- [ ] **10.4** Run `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm typecheck` → expected: passes.
- [ ] **10.5** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add ui/app/layout.tsx ui/components/LeftRail.tsx ui/app/memory ui/app/subagents && git commit -m "feat(ui): root layout + 6-component audit-order left rail"`

---

## Task 11 — `ui/app/page.tsx` — run list (server component)

- [ ] **11.1** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/app/page.tsx`:
  ```tsx
  import Link from "next/link";
  import { api } from "@/lib/api";

  export const dynamic = "force-dynamic";

  export default async function Home() {
    const runs = await api.listRuns({ limit: 50 });
    return (
      <section>
        <header className="mb-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold">Workspace</h1>
          <Link href="/specs" className="rounded bg-zinc-900 px-3 py-1.5 text-sm text-white dark:bg-white dark:text-zinc-900">
            New run
          </Link>
        </header>
        <ul className="divide-y divide-zinc-200 rounded border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800" data-testid="run-list">
          {runs.map((r) => (
            <li key={r.run_id} className="flex items-center justify-between p-3 hover:bg-zinc-50 dark:hover:bg-zinc-900">
              <Link href={`/runs/${r.run_id}`} className="flex-1 grid grid-cols-5 gap-2 text-sm">
                <span className="font-mono">{r.run_id}</span>
                <span><Badge status={r.status} /></span>
                <span className="text-zinc-500">{r.topology}</span>
                <span>{r.agent_count} agents</span>
                <span className="text-right tabular-nums">${r.total_cost_usd.toFixed(3)}</span>
              </Link>
            </li>
          ))}
          {runs.length === 0 && <li className="p-4 text-sm text-zinc-500">No runs yet — start one from the spec editor.</li>}
        </ul>
      </section>
    );
  }

  function Badge({ status }: { status: string }) {
    const tone: Record<string, string> = {
      succeeded: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
      running: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
      failed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
      cancelled: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
      pending: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
    };
    return <span className={`rounded px-2 py-0.5 text-xs ${tone[status] || tone.pending}`}>{status}</span>;
  }
  ```
- [ ] **11.2** Run dev server to smoke-test rendering.
  - Run (terminal A): `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run python -m pi_harness.api`
  - Run (terminal B): `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm dev`
  - Open `http://localhost:3000` — expected: page renders, run rows visible. Stop both servers.
- [ ] **11.3** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add ui/app/page.tsx && git commit -m "feat(ui): landing page run list (server component)"`

---

## Task 12 — `ui/app/runs/[runId]/page.tsx` + `RunTimeline.tsx` + `ReliabilityGauges.tsx`

- [ ] **12.1** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/components/GuardIcon.tsx`:
  ```tsx
  import { Shield, Eye } from "lucide-react";

  type Firing = { name: string; status: "pass" | "fail" | "warn"; detail: string };

  export function GuardIcon({ kind, firings }: { kind: "guide" | "sensor"; firings: Firing[] }) {
    if (!firings.length) return null;
    const worst = firings.find((f) => f.status === "fail") || firings.find((f) => f.status === "warn") || firings[0];
    const tone = worst.status === "fail" ? "text-red-500" : worst.status === "warn" ? "text-amber-500" : "text-emerald-500";
    const Icon = kind === "guide" ? Shield : Eye;
    return (
      <span
        title={`${kind}: ${firings.map((f) => `${f.name} (${f.status}) — ${f.detail}`).join("; ")}`}
        data-testid={`${kind}-icon`}
        className={`inline-flex h-4 w-4 ${tone}`}
      >
        <Icon className="h-4 w-4" aria-label={`${kind}-${worst.status}`} />
      </span>
    );
  }
  ```
- [ ] **12.2** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/components/ReliabilityGauges.tsx`:
  ```tsx
  // Four-dimension reliability per HARNESS_ARCHITECTURE.md §5: Consistency / Robustness / Predictability / Safety.
  // v1 reads scores from a derived score per agent; if upstream doesn't expose them, fall back to "—".
  export function ReliabilityGauges({ scores }: { scores: Partial<Record<"consistency" | "robustness" | "predictability" | "safety", number>> }) {
    const dims: ("consistency" | "robustness" | "predictability" | "safety")[] = ["consistency", "robustness", "predictability", "safety"];
    return (
      <div className="grid grid-cols-2 gap-2" data-testid="reliability-gauges">
        {dims.map((dim) => {
          const v = scores[dim];
          const pct = v != null ? Math.round(v * 100) : null;
          return (
            <div key={dim} className="rounded border border-zinc-200 p-2 dark:border-zinc-800">
              <div className="text-xs uppercase tracking-wide text-zinc-500">{dim}</div>
              <div className="mt-1 text-lg font-semibold">{pct != null ? `${pct}%` : "—"}</div>
              <div className="mt-1 h-1 w-full rounded bg-zinc-100 dark:bg-zinc-800">
                <div className="h-1 rounded bg-emerald-500" style={{ width: pct != null ? `${pct}%` : "0%" }} />
              </div>
            </div>
          );
        })}
      </div>
    );
  }
  ```
- [ ] **12.3** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/components/CostPanel.tsx`:
  ```tsx
  import type { RunSummary } from "@/lib/api";
  export function CostPanel({ summary }: { summary: RunSummary }) {
    const tokens = summary.total_tokens_in + summary.total_tokens_out;
    return (
      <div className="rounded border border-zinc-200 p-3 text-sm dark:border-zinc-800" data-testid="cost-panel">
        <div className="text-xs uppercase tracking-wide text-zinc-500">Cost</div>
        <div className="mt-1 text-lg font-semibold">${summary.total_cost_usd.toFixed(3)}</div>
        <div className="mt-1 text-xs text-zinc-500">{tokens.toLocaleString()} tokens · {summary.agent_count} agents · {summary.topology}</div>
      </div>
    );
  }
  ```
- [ ] **12.4** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/components/RunTimeline.tsx`:
  ```tsx
  "use client";
  import { useState } from "react";
  import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
  import { api, type Timeline, type TrajectoryEvent } from "@/lib/api";
  import { useLiveRun } from "@/lib/use-live-run";
  import { GuardIcon } from "./GuardIcon";

  export function RunTimeline({ runId, initial }: { runId: string; initial: Timeline }) {
    const qc = useQueryClient();
    const { data: timeline } = useQuery({
      queryKey: ["timeline", runId],
      queryFn: () => api.getTimeline(runId),
      initialData: initial,
      refetchInterval: 5000,
    });
    const live = useLiveRun(runId);
    const [selected, setSelected] = useState<TrajectoryEvent | null>(null);
    const branch = useMutation({
      mutationFn: (stepId: string) => api.branchRun(runId, { step_id: stepId }),
      onSuccess: (resp) => {
        qc.invalidateQueries({ queryKey: ["runs"] });
        // navigate to new run
        window.location.href = `/runs/${resp.run_id}`;
      },
    });
    return (
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 space-y-4" data-testid="timeline">
          {timeline?.agents.map((row) => (
            <div key={row.agent_id} className="rounded border border-zinc-200 dark:border-zinc-800">
              <div className="border-b border-zinc-200 px-3 py-2 text-sm font-mono dark:border-zinc-800">{row.agent_id}</div>
              <ol className="divide-y divide-zinc-100 dark:divide-zinc-900">
                {row.events.map((ev) => (
                  <li
                    key={ev.step_id}
                    className="cursor-pointer px-3 py-2 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-900"
                    onClick={() => setSelected(ev)}
                    data-testid={`step-${ev.step_id}`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-zinc-500">{ev.step_id}</span>
                      <span className="text-zinc-700 dark:text-zinc-300">{ev.tool}</span>
                      <GuardIcon kind="guide" firings={ev.guide_firings} />
                      <GuardIcon kind="sensor" firings={ev.sensor_firings} />
                      <span className="ml-auto text-xs text-zinc-500">{ev.duration_ms} ms</span>
                      {ev.guide_firings.length > 0 && (
                        <button
                          className="rounded border border-zinc-300 px-1.5 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                          onClick={(e) => { e.stopPropagation(); branch.mutate(ev.step_id); }}
                          data-testid={`branch-${ev.step_id}`}
                        >
                          Branch
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          ))}
          {live.events.length > 0 && (
            <div className="rounded border border-blue-300 p-3 text-xs text-blue-700 dark:border-blue-700 dark:text-blue-300">
              Live · {live.events.length} new events streamed
            </div>
          )}
        </div>
        <aside className="space-y-3 text-sm">
          <div className="text-xs uppercase tracking-wide text-zinc-500">Inspector</div>
          {selected ? (
            <pre className="overflow-auto rounded border border-zinc-200 bg-zinc-50 p-2 text-xs dark:border-zinc-800 dark:bg-zinc-900">
              {JSON.stringify(selected, null, 2)}
            </pre>
          ) : (
            <div className="text-zinc-500">Select a step to inspect.</div>
          )}
        </aside>
      </div>
    );
  }
  ```
- [ ] **12.5** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/app/runs/[runId]/page.tsx`:
  ```tsx
  import { api } from "@/lib/api";
  import { RunTimeline } from "@/components/RunTimeline";
  import { ReliabilityGauges } from "@/components/ReliabilityGauges";
  import { CostPanel } from "@/components/CostPanel";

  export const dynamic = "force-dynamic";

  export default async function RunPage({ params }: { params: { runId: string } }) {
    const [detail, timeline] = await Promise.all([
      api.getRun(params.runId),
      api.getTimeline(params.runId),
    ]);
    return (
      <section className="space-y-4">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Run {detail.summary.run_id}</h1>
            <p className="text-sm text-zinc-500">{detail.summary.topology} · {detail.summary.status}</p>
          </div>
          <div className="flex items-center gap-2">
            <CostPanel summary={detail.summary} />
          </div>
        </header>
        <RunTimeline runId={params.runId} initial={timeline} />
        <div className="max-w-md">
          <ReliabilityGauges scores={{}} />
        </div>
      </section>
    );
  }
  ```
- [ ] **12.6** Run `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm typecheck`. Expected: passes.
- [ ] **12.7** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add ui/components ui/app/runs && git commit -m "feat(ui): run detail with timeline, guard icons, reliability gauges, branch action"`

---

## Task 13 — `ui/app/corpus/page.tsx` + `CorpusHealthGauge.tsx`

- [ ] **13.1** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/components/CorpusHealthGauge.tsx`:
  ```tsx
  import type { CorpusHealth } from "@/lib/api";

  export function CorpusHealthGauge({ health }: { health: CorpusHealth }) {
    const pct = Math.min(100, Math.round(health.pct_of_cap * 100));
    const tone = pct > 100 ? "bg-red-500" : pct > 85 ? "bg-amber-500" : "bg-emerald-500";
    return (
      <div className="rounded border border-zinc-200 p-3 dark:border-zinc-800" data-testid="corpus-gauge">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-medium">Token budget</h2>
          <span className="text-2xl font-semibold tabular-nums" data-testid="corpus-pct">{pct}%</span>
        </div>
        <div className="mt-2 h-2 w-full rounded bg-zinc-100 dark:bg-zinc-800">
          <div className={`h-2 rounded ${tone}`} style={{ width: `${Math.min(100, pct)}%` }} />
        </div>
        <div className="mt-2 text-xs text-zinc-500">
          {health.total_active_tokens.toLocaleString()} / {health.soft_cap_tokens.toLocaleString()} active tokens
        </div>
      </div>
    );
  }
  ```
- [ ] **13.2** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/app/corpus/page.tsx`:
  ```tsx
  "use client";
  import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
  import { api } from "@/lib/api";
  import { CorpusHealthGauge } from "@/components/CorpusHealthGauge";

  export default function CorpusPage() {
    const qc = useQueryClient();
    const health = useQuery({ queryKey: ["corpus-health"], queryFn: api.corpusHealth });
    const restore = useMutation({
      mutationFn: (id: string) => api.restoreEntry(id),
      onSuccess: () => qc.invalidateQueries({ queryKey: ["corpus-health"] }),
    });

    if (health.isPending) return <div className="text-zinc-500">Loading corpus…</div>;
    if (health.isError) return <div className="text-red-600">Error: {String(health.error)}</div>;
    const h = health.data!;

    return (
      <section className="space-y-6">
        <h1 className="text-xl font-semibold">Context · Corpus</h1>
        <CorpusHealthGauge health={h} />
        <div className="grid grid-cols-3 gap-3 text-sm">
          <Stat label="Foundational" value={h.foundational_count} />
          <Stat label="Tactical" value={h.tactical_count} />
          <Stat label="Observational" value={h.observational_count} />
        </div>
        <div>
          <h2 className="mb-2 text-sm font-medium">Prune candidates</h2>
          <div className="grid grid-cols-5 gap-2 text-sm">
            {Object.entries(h.prune_candidates).map(([trigger, n]) => (
              <div key={trigger} className="rounded border border-zinc-200 p-2 text-center dark:border-zinc-800">
                <div className="text-xs uppercase tracking-wide text-zinc-500">{trigger}</div>
                <div className="mt-1 text-lg font-semibold">{n}</div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h2 className="mb-2 text-sm font-medium">Stale entries (top 50)</h2>
          <ul className="space-y-1 text-sm" data-testid="stale-list">
            {h.stale_entries.map((e) => (
              <li key={e.id} className="rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800">
                <span className="font-mono text-xs text-zinc-500">{e.id}</span> · {e.body_preview || <em>empty</em>}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h2 className="mb-2 text-sm font-medium">Recently archived</h2>
          <ul className="space-y-1 text-sm" data-testid="archived-list">
            {h.recently_archived.map((e) => (
              <li key={e.id} className="flex items-center justify-between rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800">
                <span><span className="font-mono text-xs text-zinc-500">{e.id}</span> · {e.body_preview}</span>
                <button
                  className="rounded border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                  onClick={() => restore.mutate(e.id)}
                  data-testid={`restore-${e.id}`}
                >
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>
    );
  }

  function Stat({ label, value }: { label: string; value: number }) {
    return (
      <div className="rounded border border-zinc-200 p-3 dark:border-zinc-800">
        <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
        <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      </div>
    );
  }
  ```
- [ ] **13.3** Run `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm typecheck` → passes.
- [ ] **13.4** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add ui/app/corpus ui/components/CorpusHealthGauge.tsx && git commit -m "feat(ui): corpus health page with gauge, prune candidates, restore"`

---

## Task 14 — `ui/app/specs/page.tsx` + `SpecEditor.tsx`

- [ ] **14.1** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/components/SpecEditor.tsx`:
  ```tsx
  "use client";
  import { useState } from "react";
  import { useMutation } from "@tanstack/react-query";
  import { api } from "@/lib/api";

  export function SpecEditor({ specId, initialBody }: { specId: string; initialBody: string }) {
    const [body, setBody] = useState(initialBody);
    const save = useMutation({ mutationFn: () => api.saveSpec(specId, body) });
    const lint = useMutation({ mutationFn: () => api.lintSpec(specId) });
    const decompose = useMutation({ mutationFn: () => api.decomposeSpec(specId) });
    const launch = useMutation({
      mutationFn: () => api.launchSpec(specId, { topology: "sequential", sync_mode: "separate" }),
      onSuccess: (resp) => { window.location.href = `/runs/${resp.run_id}`; },
    });

    return (
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 space-y-2">
          <textarea
            className="h-[60vh] w-full rounded border border-zinc-200 p-3 font-mono text-sm dark:border-zinc-800 dark:bg-zinc-900"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onBlur={() => save.mutate()}
            data-testid="spec-textarea"
          />
          <div className="flex gap-2">
            <button onClick={() => lint.mutate()} data-testid="lint-btn"
              className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
              Lint
            </button>
            <button onClick={() => decompose.mutate()} data-testid="decompose-btn"
              className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
              Decompose
            </button>
            <button onClick={() => launch.mutate()} data-testid="launch-btn"
              className="rounded bg-zinc-900 px-3 py-1.5 text-sm text-white dark:bg-white dark:text-zinc-900">
              Launch
            </button>
          </div>
        </div>
        <aside className="space-y-3 text-sm">
          {lint.data && (
            <div data-testid="lint-results">
              <h3 className="mb-1 text-xs uppercase tracking-wide text-zinc-500">Lint violations</h3>
              {lint.data.violations.length === 0 ? <p className="text-emerald-600">Clean.</p> : (
                <ul className="space-y-1">
                  {lint.data.violations.map((v, i) => (
                    <li key={i} className="rounded border border-amber-200 bg-amber-50 px-2 py-1 dark:border-amber-800 dark:bg-amber-900/20">
                      <span className="font-mono text-xs">{v.code}</span> · {v.message}
                      {v.line && <span className="text-zinc-500"> (line {v.line})</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {decompose.data && (
            <div data-testid="decompose-results">
              <h3 className="mb-1 text-xs uppercase tracking-wide text-zinc-500">Decomposed tasks</h3>
              <ul className="space-y-1">
                {decompose.data.tasks.map((t) => (
                  <li key={t.id} className="rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800">
                    <span className="font-mono text-xs text-zinc-500">{t.id}</span> · {t.title}
                    {t.blocked_by.length > 0 && <span className="ml-2 text-xs text-zinc-500">blocked-by: {t.blocked_by.join(", ")}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    );
  }
  ```
- [ ] **14.2** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/app/specs/page.tsx`:
  ```tsx
  "use client";
  import { useState } from "react";
  import { useQuery } from "@tanstack/react-query";
  import { api } from "@/lib/api";
  import { SpecEditor } from "@/components/SpecEditor";

  export default function SpecsPage() {
    const specs = useQuery({ queryKey: ["specs"], queryFn: api.listSpecs });
    const [activeId, setActiveId] = useState<string | null>(null);
    const active = useQuery({
      queryKey: ["spec", activeId],
      queryFn: () => api.getSpec(activeId!),
      enabled: !!activeId,
    });

    return (
      <section className="space-y-4">
        <h1 className="text-xl font-semibold">Prompt Shape · Specs</h1>
        <div className="grid grid-cols-4 gap-4">
          <aside className="col-span-1 space-y-1">
            {specs.data?.map((s) => (
              <button
                key={s.id}
                onClick={() => setActiveId(s.id)}
                className={`block w-full rounded px-2 py-1.5 text-left text-sm ${
                  activeId === s.id ? "bg-zinc-100 dark:bg-zinc-800" : "hover:bg-zinc-50 dark:hover:bg-zinc-900"
                }`}
                data-testid={`spec-${s.id}`}
              >
                {s.title}
              </button>
            ))}
            {specs.data?.length === 0 && <p className="text-sm text-zinc-500">No specs yet.</p>}
          </aside>
          <div className="col-span-3">
            {active.data ? <SpecEditor specId={active.data.id} initialBody={active.data.body} /> :
              <p className="text-sm text-zinc-500">Pick a spec to edit.</p>}
          </div>
        </div>
      </section>
    );
  }
  ```
- [ ] **14.3** Run `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm typecheck` → passes.
- [ ] **14.4** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add ui/app/specs ui/components/SpecEditor.tsx && git commit -m "feat(ui): spec editor page with lint/decompose/launch actions"`

---

## Task 15 — `ui/app/guards/page.tsx`

- [ ] **15.1** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/app/guards/page.tsx`:
  ```tsx
  "use client";
  import { useQuery } from "@tanstack/react-query";
  import { Shield } from "lucide-react";
  import { api } from "@/lib/api";

  export default function GuardsPage() {
    const candidates = useQuery({ queryKey: ["promotion-candidates"], queryFn: api.promotionCandidates });
    return (
      <section className="space-y-4">
        <h1 className="text-xl font-semibold">Tools · Guards &amp; Sensors</h1>
        <div>
          <h2 className="mb-2 text-sm font-medium">Promotion candidates</h2>
          {candidates.isPending && <p className="text-zinc-500">Loading…</p>}
          {candidates.data?.length === 0 && <p className="text-sm text-zinc-500">No inferential checks are ready to promote.</p>}
          <ul className="space-y-2" data-testid="promotion-list">
            {candidates.data?.map((c) => (
              <li key={c.check_id} className="rounded border border-zinc-200 p-3 dark:border-zinc-800">
                <div className="flex items-center gap-2 text-sm">
                  <Shield className="h-4 w-4 text-amber-500" />
                  <span className="font-medium">{c.name}</span>
                  <span className="ml-auto text-xs text-zinc-500">fired {c.fire_count}× · last {new Date(c.last_fired_at).toLocaleString()}</span>
                </div>
                {c.sample_violations.length > 0 && (
                  <pre className="mt-2 overflow-auto rounded bg-zinc-50 p-2 text-xs dark:bg-zinc-900">
                    {JSON.stringify(c.sample_violations.slice(0, 3), null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        </div>
      </section>
    );
  }
  ```
- [ ] **15.2** Run `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm typecheck` → passes.
- [ ] **15.3** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add ui/app/guards && git commit -m "feat(ui): guards page lists promotion candidates"`

---

## Task 16 — Playwright smoke E2E

- [ ] **16.1** Install Playwright runtime.
  - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm exec playwright install chromium`
  - Expected: chromium binary downloaded.
- [ ] **16.2** Write `/Users/pranavnair/Desktop/Personal/mannschaft/ui/playwright.config.ts`:
  ```ts
  import { defineConfig } from "@playwright/test";
  export default defineConfig({
    testDir: "../tests/ui",
    timeout: 30_000,
    use: { baseURL: "http://localhost:3000", trace: "on-first-retry" },
    webServer: [
      {
        command: "uv run python -m pi_harness.api",
        cwd: "../",
        url: "http://127.0.0.1:8800/healthz",
        timeout: 30_000,
        reuseExistingServer: true,
      },
      {
        command: "pnpm dev",
        cwd: ".",
        url: "http://localhost:3000",
        timeout: 60_000,
        reuseExistingServer: true,
      },
    ],
  });
  ```
- [ ] **16.3** Create a shared fixture loader so the backend has runs to render. Write `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/api/_fixtures.py`:
  ```python
  """Test fixtures used by Playwright. Loaded by setting PI_HARNESS_FIXTURE_MODE=1."""
  from __future__ import annotations
  import os
  from datetime import datetime, timezone
  # If this env var is set, monkey-patch query_runs/query_events at import time
  # so the e2e suite has data without spinning up Plans 2/3/5/6/7.
  ```
  Then in `pi_harness/api/server.py`, add at the bottom of `create_app`:
  ```python
  if os.environ.get("PI_HARNESS_FIXTURE_MODE"):
      from pi_harness.api import _fixtures  # noqa: F401  (side-effecting patch)
  ```
  And in `_fixtures.py` add the side-effect patches:
  ```python
  import pi_harness.trajectory.store as _store
  _store.query_runs = lambda **kw: [
      _store.RunSummary(run_id="r-fixture-1", status="succeeded",
                        started_at=datetime(2026,5,25,tzinfo=timezone.utc),
                        ended_at=datetime(2026,5,25,0,5,tzinfo=timezone.utc),
                        agent_count=2, total_tokens_in=400, total_tokens_out=300,
                        total_cost_usd=0.012, topology="sequential"),
  ]
  _store.query_events = lambda run_id, **kw: [
      _store.TrajectoryEvent(run_id=run_id, agent_id="builder-1", step_id="s-1",
                             ts=datetime(2026,5,25,0,0,1,tzinfo=timezone.utc),
                             model="openai-fast", tool="edit_file", input="…", output="…",
                             duration_ms=1200, tokens_in=200, tokens_out=150,
                             outcome="ok", classification="computational",
                             corpus_refs=[], corpus_cited=[],
                             guide_firings=[{"name": "allowlist-edit", "status": "pass", "detail": "ok"}],
                             sensor_firings=[]),
  ]
  async def _subscribe(run_id):
      if False: yield None  # empty async generator
  _store.subscribe = _subscribe
  ```
  - Update the Playwright config to set `env: { PI_HARNESS_FIXTURE_MODE: "1" }` on the backend webServer block.
- [ ] **16.4** Write `/Users/pranavnair/Desktop/Personal/mannschaft/tests/ui/smoke.spec.ts`:
  ```ts
  import { test, expect } from "@playwright/test";

  test("landing page lists runs", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("run-list")).toBeVisible();
    await expect(page.getByText("r-fixture-1")).toBeVisible();
  });

  test("run detail shows timeline with guide icon", async ({ page }) => {
    await page.goto("/runs/r-fixture-1");
    await expect(page.getByTestId("timeline")).toBeVisible();
    await expect(page.getByTestId("guide-icon").first()).toBeVisible();
  });

  test("branch button enqueues a new run", async ({ page }) => {
    await page.goto("/runs/r-fixture-1");
    const branchBtn = page.getByTestId("branch-s-1");
    await expect(branchBtn).toBeVisible();
    // Click is allowed to fail navigation if the stub Coordinator returns
    // the same fixture, but the request must succeed (HTTP 200).
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/runs/r-fixture-1/branch") && r.request().method() === "POST"),
      branchBtn.click(),
    ]);
    expect(resp.status()).toBe(200);
  });

  test("corpus health page renders gauge", async ({ page }) => {
    await page.goto("/corpus");
    await expect(page.getByTestId("corpus-gauge")).toBeVisible();
    await expect(page.getByTestId("corpus-pct")).toContainText("%");
  });

  test("specs page loads", async ({ page }) => {
    await page.goto("/specs");
    await expect(page.getByText("Prompt Shape · Specs")).toBeVisible();
  });
  ```
- [ ] **16.5** Run the suite.
  - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm exec playwright test`
  - Expected: 5/5 pass. If specs page has zero items, the assertion on the header still passes; that test is intentionally minimal because Plan 7 is a separate plan.
- [ ] **16.6** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add ui/playwright.config.ts tests/ui pi_harness/api/_fixtures.py pi_harness/api/server.py && git commit -m "test(ui): Playwright smoke covering runs, timeline, branch, corpus, specs"`

---

## Task 17 — Final acceptance sweep

- [ ] **17.1** Run all backend tests.
  - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/api -v --tb=short`
  - Expected: every test passes.
- [ ] **17.2** Run typecheck + Playwright.
  - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm typecheck && pnpm exec playwright test`
  - Expected: both pass.
- [ ] **17.3** Walk each acceptance criterion explicitly.
  - [ ] **AC1** Backend launches and serves OpenAPI.
    - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run python -m pi_harness.api &` then `curl -sf http://127.0.0.1:8800/healthz && curl -sf http://127.0.0.1:8800/openapi.json | head -c 200` → both non-empty. `kill %1`.
  - [ ] **AC2** Frontend launches.
    - Run (in a fresh shell): `cd /Users/pranavnair/Desktop/Personal/mannschaft/ui && pnpm dev &`. Wait, then `curl -sf http://localhost:3000` → returns HTML. Kill.
  - [ ] **AC3** Run list renders fixture data — verified by `smoke.spec.ts::landing page lists runs`.
  - [ ] **AC4** Timeline shows Guide/Sensor icons — verified by `smoke.spec.ts::run detail shows timeline with guide icon`.
  - [ ] **AC5** Corpus token gauge shows % — verified by `smoke.spec.ts::corpus health page renders gauge`.
  - [ ] **AC6** Spec lint/decompose/launch wired — verified by `SpecEditor.tsx` mutation hooks and `smoke.spec.ts::specs page loads`. (Full lint→violations→render is exercised against Plan 7's real router; if Plan 7 isn't implemented yet, this AC is met by the structural test only — flag in Unresolved decisions.)
  - [ ] **AC7** WebSocket sub-500ms — verified by `tests/api/test_websocket.py::test_websocket_latency_under_500ms`.
- [ ] **17.4** Commit. `cd /Users/pranavnair/Desktop/Personal/mannschaft && git add . && git commit -m "chore(ui,api): final acceptance sweep" --allow-empty`

---

## Unresolved decisions (flag to Pranav)

These are explicitly **deferred** — Pranav will resolve them after seeing the scaffolded UI:

1. **Color palette + typography.** v1 uses Tailwind defaults (zinc/emerald/amber/red/blue). The architecture doc deliberately does not commit to a palette. Pranav restyles after seeing the wireframe.
2. **Component library.** v1 is hand-rolled — no shadcn, no Radix, no Material. If Pranav wants polished primitives (popovers, dialogs, command palette) we add shadcn/ui as a follow-up; the markup is intentionally semantic so the migration is straightforward.
3. **Iconography.** `lucide-react` is the only icon dependency. Easy to swap; chosen because it matches Symphony's clean line aesthetic.
4. **Reliability gauge data source.** Plan 2's schema does not currently emit per-agent Consistency/Robustness/Predictability/Safety scores. The `ReliabilityGauges` component renders `—` when scores are absent. Either (a) Plan 2 grows a derived-scores join, (b) we compute heuristics client-side from event counts, or (c) we punt to v2. Defer until Plan 2 has trajectory data to score against.
5. **Auth.** v1 is single-machine, localhost — no auth on the API. If Pranav exposes the API beyond localhost (cloud Pi deployment, share-link), we add an API key middleware. Out of scope for now.
6. **Spec-page acceptance when Plan 7 unfinished.** AC6 is structurally verified (component renders, buttons exist, calls fire) but the end-to-end lint-→-violations path is only meaningful once Plan 7 ships. Re-run `smoke.spec.ts::specs page loads` after Plan 7 to validate the full path.
7. **Topology / sync_mode picker for branch + launch.** The current Branch button reuses the parent's topology; the Launch button hard-codes `sequential` + `separate`. A topology picker UI (Plan 5 surface) is deferred until Pranav reviews the v1 dashboard.
8. **WebSocket reconnection.** `useLiveRun` does not retry on close. If runs are long-lived, add exponential backoff. Out of scope for v1.

---

## Cross-plan consumer notes

This plan is the **leaf** — nothing else consumes it. It does, however, depend on the public APIs of Plans 1, 2, 3, 5, 6, 7. If any of those drift, update:

- `pi_harness/api/models.py` (mirrors Plan 2's `RunSummary` / `TrajectoryEvent` and Plan 3's `CorpusEntry`).
- `tests/api/conftest.py` fixture stubs.
- `pi_harness/api/_fixtures.py` (Playwright fixtures).

Re-run `pnpm gen:api` to regenerate `ui/lib/api-types.ts` after any pydantic model change.
