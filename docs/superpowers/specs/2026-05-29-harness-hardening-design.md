# Mannschaft Harness Hardening — Design Spec

**Date:** 2026-05-29
**Status:** Approved design, pending implementation plan
**Track:** A (harness core hole-fixes). Track B (the plugin skills package) is the explicit follow-on and is *out of scope* here.

---

## 1. Problem

The harness is powerful but hard to use. Today, safety-critical behavior and basic
ergonomics are left to the *operator* (or to an agent remembering to do the right
thing) rather than enforced by the core:

- `launch` runs agents against your **currently checked-out branch** — agents
  git-commit into your working tree (the documented "smoke-test hazard").
- Failed/timed-out runs are **left live**, burning credit, with no teardown.
- Missing prerequisites surface as **raw subprocess errors** (`clawteam: not found`)
  rather than actionable messages.
- There is **no single entry point** — a newcomer "wouldn't know how to start it."
- Using a **local model** requires ~6 manual, undocumented steps outside the harness.

## 2. Guiding principle (default vs. skill vs. explicit command)

> **A behavior belongs in the harness core if it must hold no matter who or what
> invokes the bare CLI.** That covers two things: *safety* (don't trash my branch,
> don't burn credit, fail fast) and *one-command ergonomics* (a newcomer can start).
> A behavior stays a **skill** only if it needs an LLM's judgment or conversation.
> A behavior becomes an **explicit command** (not a silent default) when it is heavy
> or surprising (e.g. downloading multi-GB model weights).

**The test:** *"If a teammate ran the bare CLI with no Claude in the loop, would they
still trash their branch / burn credit / be lost?"* If yes → fix the core.

Corollary: a skill that exists only to paper over a confusing CLI is a smell. We fix
the core first (Track A); the skill layer (Track B) then becomes thin and honest.

## 3. Scope

**In scope (Track A):** changes to the `pi_harness` Python package + CLI listed in §5.

**Out of scope (Track B, follow-on):** the plugin skills package — a `podium`/maestro
front-door skill, an `author-spec` lint-iteration skill, and a `watch`/narrate skill.
Referenced where relevant, designed separately.

## 4. Spike findings (grounding the isolation design)

Verified by reading ClawTeam 0.2.x source in `.venv/.../clawteam/`:

- ClawTeam has a first-class worktree system (`clawteam/workspace/`):
  - `WorkspaceManager.create_workspace` → `git worktree add -b <branch> <path> <base_ref>`
    at `{data_dir}/workspaces/{team}/{agent}`, where `base_ref = base_branch =
    current_branch(repo)` captured at manager init (`manager.py:52`).
  - `merge_workspace` (`manager.py:169`) checkpoints then `git merge` the agent branch
    into `target_branch or base_branch`.
  - `cleanup_workspace` / `cleanup_team` remove worktrees; `conflicts.py` does
    cross-branch overlap detection.
- The `clawteam launch` CLI takes `--workspace/--no-workspace` (config key `workspace`,
  values `auto|always|never`) and `--repo`.
- **The harness opts out by omission**: `ClawTeamClient.launch_team` (`client.py:122`)
  sends only `launch TEMPLATE --team Y --goal Z [--profile P]` — no `--workspace`, no
  `--repo` — and `clawteam launch` defaults to `no-workspace`. That is *why* runs land
  on the user's branch.

**Conclusion:** isolation is not something we build — it is something we *enable and
own the boundary of*. One impl detail to confirm during planning: whether `clawteam
launch` itself merges agent branches into base, or leaves them dangling (decides
whether the harness merges `agent → run` branch or ClawTeam does).

## 5. The fixes

Each fix notes: the default behavior, the opt-out, and how it's verified.

### 5.1 CLI identity & ergonomics
- Register three console scripts in `[project.scripts]`, all → `pi_harness.cli:app`:
  - `mannschaft` — canonical, self-documenting (used in docs/scripts).
  - `ms` — daily shorthand.
  - `pi-harness` — **kept as a deprecated alias** (nothing breaks).
- Rationale: `pi-harness` wrongly implies the `pi` executor; the harness is
  executor-agnostic (also drives `codex`). `mannschaft` is the product name.
- **Verify:** `ms --version`, `mannschaft --version`, `pi-harness --version` all work;
  `pyproject` declares all three.

### 5.2 Run isolation — the branch hazard (safety, default ON)
- **Default:** every run is isolated. Before launch the harness establishes a
  run-level branch `run/<run_id>` (off current HEAD) and points ClawTeam at an
  isolated boundary (`--repo`/`--workspace`) so per-agent worktrees nest inside it.
  The user's checked-out branch is **never touched**.
- **Merge policy: review-then-merge — never auto-merge.** On success the harness
  reports: *"work is on branch `run/<run_id>` — diff and merge when ready."* This
  matches the user's separate-branch → merge → downstream-audit workflow and keeps a
  human gate on what enters mainline.
- **Opt-out:** `--in-place` for power users who knowingly want to run in the current
  tree.
- **Verify:** unit test (mock git + ClawTeamClient) asserting (a) a `run/<id>` branch
  is created off HEAD, (b) the user's branch HEAD is unchanged after a run, (c)
  `--in-place` skips branch creation.

### 5.3 Guaranteed teardown + snapshot-on-failure (safety, default ON)
- **Problem:** only clean successes tear down today; failed/timed-out teams are left
  live and keep burning credit. `team cleanup` alone does **not** kill agents — the
  tmux session must be killed first.
- **Default:** always tear down on exit (success *and* failure): kill the tmux session
  **first**, then `team cleanup`.
- On failure/timeout, **`clawteam team snapshot` before teardown** (ClawTeam snapshots
  capture config, tasks, events, sessions, costs). This removes the only reason to
  leave failed teams live — full debuggability is preserved without live panes.
- **Opt-out:** `--keep-alive` leaves a failed team running for live attach/poking.
- **Also fix the dashboard finalizer bug:** `spec/editor.py:58` `_finalize_run` calls
  `coordinator.wait_for_completion(handle)` with no `timeout`, raising a `TypeError`
  swallowed by a broad `except` — so dashboard-launched runs never finalize. Pass the
  timeout (or make it optional) so the API path finalizes like the CLI path.
- **Verify:** unit tests asserting teardown ordering (tmux kill before cleanup),
  snapshot-before-teardown on the failure path, and a regression test for the
  finalizer signature.

### 5.4 Launch preflight (fail fast, friendly)
- Before shelling out, `launch` preflights and fails with a **copy-pasteable fix** per
  miss instead of a raw subprocess error:
  - `clawteam` reachable **via the venv** (not bare PATH — it lives at
    `.venv/bin/clawteam`), `tmux`, a `pi`/`codex` executor, `OPENAI_API_KEY`
    (`load_config`).
  - If a bucket is `local`: the local server is reachable and the model is present.
- **Verify:** unit tests with each prerequisite mocked-missing assert the specific
  remediation string and a clean non-zero exit (no traceback).

### 5.5 `ms doctor` (preflight as a command)
- Standalone command running all §5.4 checks plus environment footguns, printing a
  checklist with the exact fix per item. Footguns to encode: `clawteam`-in-venv,
  `uv sync --extra dev` (plain `uv sync` skips dev deps), `pi` not `pi-coding-agent`,
  nvm PATH inside tmux panes, and the three ports (ClawTeam board 8080, API 8800,
  UI 3000).
- This is the substance; the Track-B skill is just a thin conversational wrapper over
  `ms doctor`.
- **Verify:** unit test snapshotting the checklist for a fully-satisfied env and for a
  few seeded-missing envs.

### 5.6 `ms quickstart` (zero → first run)
- Guided path: `doctor` → bootstrap (`.env` from `.env.example`, `uv sync --extra
  dev`) → scaffold a first spec → lint/dry-run. Directly answers "I wouldn't know how
  to start it."
- **Headless note:** must degrade gracefully when non-interactive (no blocking
  prompts); resolve in planning.
- **Verify:** integration test driving the non-interactive path end-to-end (no live
  team launch).

### 5.7 `ms serve --with-ui` (the GUI in one command)
- Today `serve` boots only the backend (8800). `--with-ui` additionally health-gates
  `GET /healthz`, starts the frontend (`pnpm dev`, 3000), and opens the browser. The
  three coupled values (backend port, frontend `NEXT_PUBLIC_API_BASE`, backend CORS
  origin) are derived from one source so they can't drift. Clean shutdown of both
  processes (kill the `next` process group to avoid orphans).
- **Verify:** test that `--with-ui` spawns both, health-gates before starting the
  frontend, and that the derived env values are consistent.

### 5.8 Local-model story (the `models` group + `ms local`)
- `ms models` — show current picks (orchestrator/builder, `api|local`, model).
- `ms models use <bucket> <model>` — non-interactive setter (scriptable).
- **`ms local`** — the interactive wizard (the user's vision):
  1. Start Ollama if it's not up (probe `:11434`).
  2. Scan **installed** models (`ollama list` / `GET /v1/models`).
  3. Show them, per bucket; user picks (or types a new tag).
  4. A new tag → **confirmed** `ollama pull <tag>` with visible progress (the only
     heavy/destructive step; never silent).
  5. Record the choice (`~/.pi-harness/models.json`) + register the `harness-local`
     provider (`ensure_pi_provider` → `~/.pi/agent/models.json`).
  6. Optional smoke: `pi --print --provider harness-local --model <id>` (with
     `stdin=DEVNULL` — pi hangs otherwise) to prove pi reaches it.
- `ms models pull <tag>` — explicit pull.
- **`launch` only PREFLIGHTS local** (§5.4); it never auto-serves or auto-pulls.
- **Mental model:** Ollama doesn't serve models individually — the daemon makes all
  pulled models available; "selecting" a model = recording the pick + registering the
  provider. A pull only happens for a model not yet on disk.
- **Scope:** Ollama-first; structure leaves room for LM Studio (`:1234`) / vLLM later.
- **Verify:** unit tests (mock `ollama`/httpx) for: server-down → start, scan parsing,
  pick-installed (no pull), pick-new (confirm + pull), provider registration.

## 6. Cross-cutting rules
- Safety defaults are **ON** with explicit opt-outs (`--in-place`, `--keep-alive`).
- Every new command/flag ships with tests run under `-m "not smoke"`. **No new
  smoke-triggering tests** (smoke launches a real team that commits/spends).
- Backward compatibility: `pi-harness` and all existing flags keep working.

## 7. Suggested phasing (separate branch → merge each)
1. **Identity** (§5.1) — trivial, foundational.
2. **Safety core** (§5.2 isolation, §5.3 teardown/snapshot + finalizer bug) — the
   critical phase; highest value.
3. **Preflight + doctor** (§5.4, §5.5).
4. **Ergonomics** (§5.6 quickstart, §5.7 serve --with-ui).
5. **Local-model story** (§5.8).

Each phase is its own branch → merge → downstream audit. The detailed step-by-step
lands in the implementation plan (writing-plans).

## 8. Open questions (resolve in planning / micro-spikes)
- Does `clawteam launch` auto-merge agent branches into base, or leave them? (Decides
  whether the harness merges `agent → run/<id>` or ClawTeam does.)
- Dedicated run *worktree dir* vs. run *branch* in the same tree — which gives the
  cleanest "your branch untouched" guarantee with least disk churn?
- `ms quickstart` behavior under headless/agent invocation.
- Whether `ms` and `mannschaft` should be the names committed, or held until a final
  naming pass.

## 9. Out of scope (Track B — follow-on package)
The plugin skills package: a `podium`/maestro front-door that routes the happy path,
an `author-spec` skill (LLM-driven lint-to-1.0 iteration), and a `watch`/narrate skill
(read-only trajectory.db). Designed after Track A lands, when these become thin
orchestration over a hardened core.
