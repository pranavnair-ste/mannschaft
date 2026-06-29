# Mannschaft UC4 Demo Product — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn mannschaft into a clean, standable-up *sovereign multi-agent coding harness* that demos on a Mac Studio with local models — one-command stand-up, honest live metrics, a curated spec that reliably runs on local Qwen, a user manual + demo runbook, and a pre-baked fallback.

**Architecture:** Five focused phases. P1 makes a cross-machine Mac-Studio deployment legal (SSRF guard). P2 is the stand-up DX keystone (auto-clone+pin the dashboard, auto-provision token, run-from-anywhere) from the already-approved `2026-06-09-observability-simpler-to-use-design.md`. P3 closes the two stage-visible honesty gaps (wall-clock per run, local cost). P4 produces a curated demo spec rehearsed on the real Mac Studio model + a captured fallback run. P5 ships the USER_MANUAL + DEMO + one-command launcher.

**Tech Stack:** Python 3.11, Typer CLI, FastAPI, aiosqlite/SQLite, ClawTeam 0.2.x, pi-agent (`pi` 0.73.1), Next.js UI, Bun (observability fork), MLX/oMLX local serving.

## Global Constraints

- **Demo framing (locked):** "orchestration + observability + sovereignty." Show decompose → small curated launch → live dashboard → worktree isolation + auto-merge → sovereignty. Do NOT stage a full from-scratch autonomous build on local; do NOT claim review-gate, custom-tooling, resumability, or UC3↔UC4 comparison as working.
- **Demo model:** `Qwen3.6-35B-A3B-MLX-4bit` on the Mac Studio oMLX endpoint (UC1's primary pick).
- **Sovereignty:** no frontier API in the demo path; keyless local. Air-gappable.
- **Test hazard:** run `pytest -m "not smoke"` — smoke launches a real ClawTeam team that git-commits to the branch. Keep the worktree-leak guard (`tests/conftest.py`) green.
- **Baseline:** 658 tests green at `main` (296e0f6). Every phase must keep them green.
- **Branch discipline (user pref):** work on a feature branch, merge, then downstream-audit. Prefer root-cause fixes over stubs.

---

## Phase 1 — Make the live decompose beat reliable + cross-machine deployment

### Task 1.0: Disable thinking + cap tokens on structured-output (decompose) calls — DEMO-CRITICAL

**Why (rehearsed 2026-06-29 against the Mac Studio Qwen3.6-35B-A3B):** the decomposer's `_call_llm` sets **no `max_tokens`** and does not disable thinking. On a thinking-model (Qwen3.6) this **runs away for minutes**. With `max_tokens` + `enable_thinking=False`, the real decompose prompt returns a **valid 7-task DAG in 10.3s @ 80.9 tok/s, first attempt**. This is the difference between a snappy live beat and an on-stage hang. See memory `reference_omlx_thinking_mode`.

**Files:**
- Modify: `pi_harness/spec/decomposer.py:54-61` (`_call_llm`)
- Possibly: `pi_harness/settings.py` (a `local_disable_thinking: bool = True` + `decompose_max_tokens: int = 2048` knob on the local bucket/settings)
- Test: `tests/spec/test_decomposer.py`

**Interfaces:**
- Produces: `_call_llm(client, *, model, messages, max_tokens=None, disable_thinking=False) -> str` — when `disable_thinking`, passes `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`; always passes `max_tokens` when set. `Decomposer` reads these from settings (default: thinking off + 2048 cap for a `local` reasoning bucket; untouched for `api`).

- [ ] **Step 1: Failing test** — a fake client records kwargs; assert that for a local bucket `_call_llm`/`decompose` is invoked with `max_tokens` set and `extra_body["chat_template_kwargs"]["enable_thinking"] is False`; for an `api` bucket, no `enable_thinking` is sent.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — thread `max_tokens` + `disable_thinking` from settings through `Decomposer.decompose` → `_call_llm`. Keep `api` behavior unchanged (no extra_body) to avoid breaking OpenAI.
- [ ] **Step 4: Run** — `pytest tests/spec/test_decomposer.py -v` PASS; then live-verify: `ms decompose docs/demo/uc4-todo-api.spec.md` against the Mac Studio model completes in ~10s with a valid DAG.
- [ ] **Step 5: Commit** — `git commit -m "fix(decomposer): cap tokens + disable thinking for local structured-output calls"`

### Task 1.2: Allow Tailscale/CGNAT (RFC-6598) local endpoints (cross-machine deployment)

**Why:** The documented v1 deployment is "a handful of Mac Studios" serving "an internal developer team," and UC2 already reaches the Mac Studio oMLX over Tailscale (`100.94.117.87:15100`). The current guard (`url_validation.py`) only allows loopback or RFC-1918, so a laptop→shared-Mac-Studio config is **blocked** (100.64.0.0/10 is RFC-6598 CGNAT, which Tailscale uses; `is_private` is False). Root-cause fix: allow RFC-6598 shared address space while still blocking link-local/metadata/public.

**Files:**
- Modify: `pi_harness/url_validation.py:18-53`
- Test: `tests/test_url_validation.py`

**Interfaces:**
- Produces: `validate_local_url(url: str) -> str` — unchanged signature; now also accepts hosts in `100.64.0.0/10`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_url_validation.py  (add)
import pytest
from pi_harness.url_validation import validate_local_url

def test_allows_tailscale_cgnat():
    # RFC-6598 shared address space (Tailscale / CGNAT) — a sovereign LAN/Tailnet.
    assert validate_local_url("http://100.94.117.87:15100/v1") == "http://100.94.117.87:15100/v1"

def test_still_blocks_metadata_ip():
    with pytest.raises(ValueError):
        validate_local_url("http://169.254.169.254/latest/meta-data")

def test_still_blocks_public_ip():
    with pytest.raises(ValueError):
        validate_local_url("http://8.8.8.8:15100/v1")
```

- [ ] **Step 2: Run to verify the CGNAT test fails** — `pytest tests/test_url_validation.py -k cgnat -v` → FAIL (currently blocked).

- [ ] **Step 3: Implement** — in `_is_allowed_host`/the IP branch of `validate_local_url`, add a shared-address-space allowance:

```python
import ipaddress
_CGNAT = ipaddress.ip_network("100.64.0.0/10")  # RFC 6598 (Tailscale / CGNAT)
# inside the IP-classification block, after the loopback/private allow and
# BEFORE the final reject, treat CGNAT as allowed (it is a sovereign LAN/Tailnet,
# not the public internet); link-local (169.254/16, incl. metadata) stays blocked:
if ip in _CGNAT:
    return url
```

- [ ] **Step 4: Run** — `pytest tests/test_url_validation.py -v` → all PASS.

- [ ] **Step 5: Commit** — `git commit -m "fix(ssrf): allow RFC-6598 CGNAT (Tailscale) local endpoints; keep metadata/public blocked"`

---

## Phase 2 — Stand-up DX keystone

Implements P1 of `docs/superpowers/specs/2026-06-09-observability-simpler-to-use-design.md` (Components 1 + 2 + run-from-anywhere). Outcome: on a fresh Mac Studio checkout with only `bun`+`npm`, `ms setup-obs` then `ms up` boots everything; failures are loud.

### Task 2.1: Dashboard bootstrap (auto-clone at pinned ref)

**Files:**
- Create: `pi_harness/observability/bootstrap.py`
- Modify: `pi_harness/config.py` (add `obs_fork_ref`; change `DEFAULT_OBS_FORK_DIR` → `~/.pi-harness/obs-dashboard`)
- Test: `tests/observability/test_bootstrap.py`

**Interfaces:**
- Produces:
  - `ensure_dashboard(cfg) -> Path` — missing dir → `git clone` + `git checkout <obs_fork_ref>` + best-effort `bun install`; existing dir → validate `apps/observability/server.ts` exists, never mutate git state, warn on ref mismatch.
  - `class BootstrapError(RuntimeError)` — carries captured stderr.
  - `cfg.obs_fork_ref: str` from `PI_HARNESS_OBS_FORK_REF`, default `"v0.3.0"`.
  - `cfg.obs_fork_dir` default `~/.pi-harness/obs-dashboard` (env `PI_HARNESS_OBS_FORK_DIR` still honored).

- [ ] **Step 1: Write failing tests** (mock `subprocess.run` for `git`/`bun`):

```python
# tests/observability/test_bootstrap.py
from pathlib import Path
import pytest
from pi_harness.observability import bootstrap

def test_missing_dir_clones_and_checks_out(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    cfg = type("C", (), {"obs_fork_dir": tmp_path / "dash", "obs_fork_ref": "v0.3.0"})()
    # make the server entry appear after "clone"
    (tmp_path / "dash" / "apps" / "observability").mkdir(parents=True)
    (tmp_path / "dash" / "apps" / "observability" / "server.ts").write_text("x")
    bootstrap.ensure_dashboard(cfg)
    assert any("clone" in c for c in calls)
    assert any("checkout" in c and "v0.3.0" in c for c in calls)

def test_existing_dir_never_mutates_git(tmp_path, monkeypatch):
    d = tmp_path / "dash" / "apps" / "observability"; d.mkdir(parents=True)
    (d / "server.ts").write_text("x")
    forbidden = {"clone", "checkout", "reset", "pull"}
    def fake_run(cmd, **kw):
        assert not (forbidden & set(cmd)), f"must not mutate: {cmd}"
        class R: returncode = 0; stdout = "abc123"; stderr = ""
        return R()
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    cfg = type("C", (), {"obs_fork_dir": tmp_path / "dash", "obs_fork_ref": "v0.3.0"})()
    bootstrap.ensure_dashboard(cfg)  # validates + warns only
```

- [ ] **Step 2: Run** → FAIL (module missing).
- [ ] **Step 3: Implement `bootstrap.py`** per spec §4 Component 1 (typed `BootstrapError` wrapping captured stderr; `_run()` helper; clone URL `https://github.com/pranavnair-ste/pi-agent-observability`; best-effort `bun install` warns-don't-fail). Add `obs_fork_ref` + new default dir to `config.py`.
- [ ] **Step 4: Run** → `pytest tests/observability/test_bootstrap.py -v` PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(obs): bootstrap auto-clone+pin dashboard at v0.3.0"`

### Task 2.2: Persistent token + `obs_enabled` + `ms setup-obs`

**Files:**
- Modify: `pi_harness/observability/bootstrap.py` (add `ensure_obs_token`), `pi_harness/cli.py` (add `setup-obs` command), `pi_harness/keystore.py` (reuse), `pi_harness/config.py`
- Test: `tests/observability/test_bootstrap.py` (extend), `tests/test_cli_setup_obs.py`

**Interfaces:**
- Produces: `ensure_obs_token(cfg) -> str` — returns existing non-weak `OBS_AUTH_TOKEN` (env/keystore) or generates `secrets.token_hex(16)`, appends to `~/.pi-harness/keystore` (`0o600`), idempotent. `ms setup-obs [--update]` — clone+token+enable.

- [ ] **Step 1: Write failing tests** — token written `0o600`, idempotent (existing preserved), `PI_HARNESS_OBS_ENABLED=1` persisted.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `ensure_obs_token` + `ms setup-obs` (clone via `ensure_dashboard`, provision token, persist enable flag) per spec §4 Component 2.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(obs): persistent OBS token + ms setup-obs one-shot"`

### Task 2.3: Run-from-anywhere + loud boot

**Files:**
- Modify: `pi_harness/cli.py:313` (UI `cwd`), `pi_harness/cli.py:371` (doctor `node_modules` check), `pi_harness/observability/supervisor.py` (`wait_ready` returns per-proc readiness)
- Test: `tests/test_cli_doctor.py`, `tests/observability/test_supervisor.py`

**Interfaces:**
- Produces: `repo_root() -> Path` (anchored on `Path(__file__).resolve().parents[1]`); `Supervisor.wait_ready() -> dict[str, bool]`; `ms up` prints which procs came up + a one-line hint on any not-ready health-checked proc; `ms up --strict` exits non-zero on failure.

- [ ] **Step 1–5:** TDD `repo_root()` (UI boots regardless of cwd), `wait_ready` per-proc report, `--strict` exit. Commit `fix(obs): run-from-anywhere + loud wait_ready surfacing`.

### Task 2.4 (ops): Tag the dashboard fork `v0.3.0`

- [ ] In `~/Desktop/Personal/pi-agent-observability` (remote `pranavnair-ste/pi-agent-observability`): `git tag v0.3.0 <current main sha>` and `git push origin v0.3.0`. (D5 of the spec.) Verify `git ls-remote --tags` shows it. *No code; gating for the pinned clone to resolve on a fresh box.*

---

## Phase 3 — Honest live metrics (stage-visible)

### Task 3.1: Total wall-clock per run

**Why:** The doc's "Standard measures" mandate "total wall-clock time per run" as a MUST. Today only `started_at`/`ended_at` exist; nothing derives or shows elapsed time.

**Files:**
- Modify: `pi_harness/trajectory/runs.py` (RunSummary + `_summarize_run`), `pi_harness/api/models.py` (RunSummaryDTO), `ui/components/CostPanel.tsx` (or run-detail), `ui/lib/api.ts` (type)
- Test: `tests/trajectory/test_runs.py`, `tests/ui/` (offline Playwright)

**Interfaces:**
- Produces: `RunSummary.wall_clock_s: float | None` (= `ended_at - started_at` parsed as ISO; `None` while running); `RunSummaryDTO.wall_clock_s`.

- [ ] **Step 1: Failing test** — a run with `started_at`/`ended_at` 12.5s apart → `summary.wall_clock_s == 12.5`; a running (no `ended_at`) run → `None`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — parse both ISO timestamps (`datetime.fromisoformat`), compute seconds, guard `None`. Thread through DTO + UI (render `12.5s` next to tokens in CostPanel).
- [ ] **Step 4: Run** — `pytest tests/trajectory/test_runs.py -v` + UI `tsc` + Playwright PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(metrics): total wall-clock per run (standard measure)"`

### Task 3.2: Honest cost on local

**Why:** Cost reads `$0.000` for the local model (not in price table; pi reports 0) — misleading on stage.

**Files:**
- Modify: `pi_harness/trajectory/runs.py` (RunSummary), `pi_harness/api/models.py`, `ui/components/CostPanel.tsx`
- Test: `tests/trajectory/test_runs.py`, `tests/ui/`

**Interfaces:**
- Produces: `RunSummary.sovereign: bool` (True when all run buckets are provider `local`, derived from the stored RunSpec) → UI renders **"Local · sovereign · $0 external"** instead of `$0.000`; cloud runs keep the dollar figure.

- [ ] **Step 1: Failing test** — a run whose serialized RunSpec has all-local buckets → `summary.sovereign is True`; a run with an `api` bucket → `False`.
- [ ] **Step 2–4:** implement (read provider from `run_spec_json`), thread to UI, conditional render. Tests + Playwright PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(metrics): label local runs sovereign instead of \$0.000"`

---

## Phase 4 — Curated demo spec + Mac-Studio rehearsal + fallback

### Task 4.1: Author the curated demo spec

**Files:**
- Create: `docs/demo/uc4-todo-api.spec.md` (a mannschaft spec: goal + acceptance criteria + constraints + non-goals)

- [ ] Author a **small** spec sized to converge on local Qwen (final size set by the rehearsal in this session — default: in-memory Todo REST API, 3–4 acceptance criteria). Must pass `ms lint` at 1.0.
- [ ] **Verify:** `ms lint docs/demo/uc4-todo-api.spec.md` → score 1.0; `ms decompose docs/demo/uc4-todo-api.spec.md` (pointed at the Mac Studio model) → valid task DAG. Record tok/s + wall-clock.
- [ ] Commit `docs(demo): curated UC4 demo spec`.

### Task 4.2: Rehearse end-to-end on the Mac Studio model & set the live envelope

- [ ] Point settings at the Mac Studio (`ms models set --bucket orchestrator --provider local --base-url http://100.94.117.87:15100/v1 --model Qwen3.6-35B-A3B-MLX-4bit`, same for builder) — requires Phase 1 (SSRF) merged.
- [ ] `ms launch docs/demo/uc4-todo-api.spec.md` with a generous `--timeout`. Observe: does it complete? how long? does trajectory capture + the dashboard render it?
- [ ] **Decision gate:** if it reliably completes < ~5 min, the live launch is a demo beat. If not, shrink the spec to 1 task OR demo decompose-only live and use the captured run (4.3) for the launch beat. Record the verdict in `DEMO.md`.

### Task 4.3: Capture a pre-baked fallback run

- [ ] Run the curated spec to completion once (Mac Studio model, or cloud if local stalls — fallback is for *display* resilience, framed honestly). Export the trajectory so `ms observe <run_id>` / the dashboard can replay it offline.
- [ ] Store under `docs/demo/fallback-run/` (trajectory rows + a note on how to load it). Commit `docs(demo): pre-baked fallback run for the dashboard`.

---

## Phase 5 — User manual, demo runbook, one-command launcher

### Task 5.1: One-command launcher

**Files:**
- Create: `docs/demo/Makefile` (or extend `ms` with a thin `demo` wrapper)

- [ ] `make demo` (modeled on `VSCodeAssistant/Makefile`): preflight (`ms doctor`), warm the model (one throwaway call), `ms setup-obs` if needed, `ms up`, open the dashboard. `make preflight`, `make reset` (clean run state), `make rehearse` (decompose-only).
- [ ] Commit `feat(demo): one-command make demo launcher`.

### Task 5.2: USER_MANUAL.md + DEMO.md

**Files:**
- Create: `docs/demo/USER_MANUAL.md`, `docs/demo/DEMO.md`

- [ ] **USER_MANUAL.md** (modeled on `VSCodeAssistant/USER_MANUAL.md`): what it is, the architecture diagram (spec → decompose → agents in worktrees → merge → dashboard), prerequisites (Mac Studio + oMLX + bun), one-time setup ("night before"), the `ms` command surface, sovereignty & data-handling, troubleshooting, appendix (config).
- [ ] **DEMO.md** (modeled on `VSCodeAssistant/DEMO.md`): a ~7-minute beat sheet matching the locked framing — (0) frame sovereignty, (1) lint+decompose live on local, (2) launch the curated spec, (3) watch concurrent agents + trajectory in the dashboard, (4) show isolated worktrees + auto-merge, (5) the standard measures (tokens + wall-clock), (6) close. Each beat: exact command + what to say + the honest caveat. Name the fallback explicitly.
- [ ] Commit `docs(demo): user manual + demo runbook`.

---

## Self-Review (spec coverage)

- Stand-up DX → Phase 2 (2.1–2.4). ✓
- USER_MANUAL + DEMO + one-command launch → Phase 5. ✓
- Wall-clock + local-cost honesty → Phase 3. ✓
- Curated spec + fallback → Phase 4. ✓
- Cross-machine Mac Studio (enabling the above on the real deployment) → Phase 1. ✓
- Deferred (named as roadmap, NOT built): UC4d custom tooling/MCP, UC4e review gate, UC4b resumability, UC3↔UC4 comparison view, UC6 VS Code integration.

## Execution order (deadline-aware)

Rehearsal already done this session (decompose converges in ~10s on the Mac Studio model with thinking off; live launch sizing TBD in 4.2).

1. **Phase 1** — Task 1.0 (thinking/max_tokens, demo-critical) + Task 1.2 (SSRF) → 2. **Phase 3** (small, stage-visible) → 3. **Phase 2** (keystone DX) → 4. **Phase 4** (curated spec, live-launch envelope via 4.2, fallback) → 5. **Phase 5** (docs + launcher last, once the real flow is pinned).
