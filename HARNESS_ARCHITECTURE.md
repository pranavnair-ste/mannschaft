# Pi-Agent Harness — Architecture

> Date: 2026-05-25 · Author: Pranav (with Claude) · Status: **Committed.** v1 = OpenAI-only via pi-agent, ClawTeam for orchestration, 10-20 agent scale, open-source.

---

## Vision

A Symphony-style dashboard for a multi-agent harness that **compounds across runs**. Every trajectory feeds a curated expertise corpus that primes the next run; agents and models are plug-and-play; the user picks topology.

## Pillars

1. **Self-improving** — trajectories + improve-agent + deterministic curator build expertise over time.
2. **Expertise-loaded** — agents prime from a federated, progressively-disclosed corpus.
3. **Multi-agent** — first-class orchestration; production hardening above 10 agents.
4. **Plug-and-play models** — per-agent model assignment, cloud + local.
5. **Sync or separate** — user picks topology and sync-mode at run launch.
6. **Dashboard UX** — Symphony-style; intervene / branch / replay at Guide and Sensor boundaries.

---

## Layered stack

```
┌──────────────────────────────────────────────────────────────────────┐
│ NEW: Spec layer            editor + linter + decomposer               │  pillar: design-first
│ NEW: Symphony UX           dashboard; extends ClawTeam's board        │  pillar 6
│ NEW: Topology layer        5 named modes over ClawTeam's leader/worker│  pillar 5
│ NEW: Guides + Sensors      hooks/validators/judges + Promote-to-Guide │  pillar 6
│ NEW: Improve-agent + Curator   post-hoc; curator is code              │  pillar 1
│ NEW: Trajectory store      SQLite event log; extends ClawTeam state   │  pillar 1
├──────────────────────────────────────────────────────────────────────┤
│ ADOPT: ClawTeam            orchestration: leader/worker, tasks, inbox,│  pillar 3, 5
│                            worktrees, profiles, board UI baseline     │
│ ADOPT: Mulch               corpus format (6 record types)             │  pillar 2
├──────────────────────────────────────────────────────────────────────┤
│ WRAP: pi-agent             executor via ClawTeam profile;             │  pillar 4
│                            multi-provider LLM layer (OpenAI key v1)   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## What we build (the six new layers)

### 1. Trajectory store

- **Purpose:** the dataset. Substrate for improve-agent, replay, eval, debugging.
- **Mechanic:** SQLite + structured event log, extending ClawTeam's JSON task state with per-step detail. Schema: `{run_id, agent_id, step_id, ts, model, tool, input, output, duration_ms, tokens_in/out, outcome, classification, corpus_refs, corpus_cited}`. `corpus_refs` / `corpus_cited` feed the curator's pruning logic (which entries were primed vs actually used). Events sourced from pi-agent-core's stream + ClawTeam task transitions.
- **Doubles as the workflow checkpointer** (so we skip LangGraph).
- **Source:** Ch6 ("The Harness is the Dataset"), Ch8 (Debugging Agents).

### 2. Improve-agent + Curator

- **Purpose:** self-improvement loop without rot AND without unbounded growth.
- **Mechanic:** post-hoc improve-agent reads recent trajectories + git, emits **candidate updates** AND **prune candidates** for the expertise corpus. A **code-path** curator (NOT an LLM) applies them using PRESERVE / APPEND / DATE / REMOVE rules and the pruning logic below.
- **Execution-Learning separation:** agents read corpus during runs, never write. Only the improve-agent writes, and only post-hoc.
- **Per-entry metadata** (Mulch-style): `{id, classification (foundational | tactical | observational), helpful_count, harmful_count, contradiction_count, created_at, last_updated_at, last_referenced_run_id, size_tokens}`.
- **Pruning triggers** (any one creates a prune candidate):
  - **Counter:** `harmful_count > helpful_count` → demote one classification tier.
  - **Contradiction:** `contradiction_count >= 3` → remove.
  - **Staleness** (per classification):
    - Foundational — never auto-prune; surface for human review only.
    - Tactical — auto-archive if 0 references in last K runs (default K=50).
    - Observational — auto-archive after 7 days unreferenced, hard-delete after 30 days.
  - **Token budget:** corpus has a soft cap (default 50k metadata tokens loaded at prime). When breached, lowest-utility entries (helpful_count / size_tokens × recency_decay) archive first.
  - **Semantic dedup:** periodic curator pass merges near-duplicate entries; highest-utility wording survives, counters sum.
- **Prune actions** (graduated, not binary delete):
  - **Archive** — out of active prime set, still queryable, restorable.
  - **Demote** — drop classification tier (foundational → tactical → observational).
  - **Merge** — two duplicates become one; counters combine.
  - **Delete** — only after 90 days archived AND no restoration.
- **Audit:** every prune is a git commit on the corpus with trigger + reason; counters preserved in archive for evidence.
- **Trajectory→corpus link:** every step logs `corpus_refs: [entry_id, …]` (which entries were primed) and `corpus_cited: [entry_id, …]` (which entries the output actually used, when detectable). Improve-agent uses these to update counters and `last_referenced_run_id`.
- **Source:** Ch7 (Self-Improving Expert Commands), Ch8 (Knowledge Evolution: PRESERVE/APPEND/DATE/REMOVE + Grow-and-Refine), Ch4 (ACE helpful/harmful counters), Ch2 (multi-contradiction rule before remove).

### 3. Guides + Sensors

- **Purpose:** control-system surface; convert harness behavior into structural constraints.
- **Mechanic:** thin layer over pi-agent-core's tool/event stream. Guides = pre-action (allowlist, validators, schema). Sensors = post-action (judge agents, eval). Dashboard renders the 2×2 (computational/inferential × feedforward/feedback) per step. **"Promote to Guide"** button converts a frequently-firing inferential check into a deterministic rule.
- **Source:** Ch6 (Harness as Control System).

### 4. Topology layer

- **Purpose:** pillar 5 surface — user picks how agents are wired per run.
- **Mechanic:** topology selector at run launch with 5 named modes:
  - **Sequential** (default) — `A → B → C → D`; maps to ClawTeam task DAG with linear `--blocked-by` chain.
  - **Parallel** — `A → {B, C, D} → merge`; leader spawns N workers via ClawTeam, merges at task completion.
  - **Synthesis** — `Q → {Expert1, Expert2, Expert3} → vote`; Parallel plus a synthesis agent at merge.
  - **Nested** — `Coord → {Sub → {Worker}}`; nested ClawTeam teams.
  - **Persistent** — `Session_n ↔ shared_state`; persists corpus + trajectory across runs (this is pillar 1's storage).
- Each mode is a thin coordinator over ClawTeam's leader/worker + task DAG + inbox primitives.
- **Sync All / Separate** toggle rewrites every agent's ClawTeam profile (`--profile`) to a single executor/model OR keeps per-agent assignments.
- **Source:** Ch9 (Execution Topologies), Ch7 (Patterns).

### 5. Symphony UX (dashboard)

- **Purpose:** pillar 6.
- **Mechanic:** extends ClawTeam's `board serve` web UI baseline (Kanban + tmux-attach view) with the richer surface below.
  - **Left rail:** 6-component audit order (Workspace / Prompt Shape / Tools / Context / Memory / Subagents).
  - **Center:** run timeline with Guide/Sensor inline icons, branch / replay actions at every Guide checkpoint.
  - **Right pane:** trajectory inspector + reliability gauges (Consistency / Robustness / Predictability / Safety).
  - **Cost panel:** cost-per-successful-task, not per-call. Token + cost data sourced from pi-agent's built-in tracking.
  - **Corpus health view:** token-budget gauge (% of soft cap), prune-candidates queue (counter / contradiction / staleness / dedup, grouped by trigger), stale-entries filter sortable by `last_referenced_run_id`, "recently archived" with one-click restore.
- **Source:** Ch6 (Harness Stack), Ch8 (Debugging + Production Concerns).

### 6. Spec layer

- **Purpose:** mitigate design-as-bottleneck.
- **Mechanic:** new-project flow lands in a spec editor — not a chat box. Linter checks for missing acceptance criteria, unbounded scope, vague terms. A decomposition assistant agent breaks specs into parallelizable units (emitted as ClawTeam tasks with `--blocked-by` dependencies) before any run launches. Specs versioned in git as the canonical artifact.
- **Source:** Ch9 (Specs as Source Code, Design as Bottleneck).

---

## Adopted prior art

- **ClawTeam** (HKUDS/ClawTeam, MIT, v0.2 active development) — *orchestration layer*: Python + tmux + git worktrees per agent, leader/worker topology, TOML team templates with variable substitution. Provides task DAG (`--blocked-by` auto-unblock), inbox (P2P + broadcast), worktree isolation (`clawteam/{team}/{agent}`), profile-based executor swap. Pin to a specific v0.2.x tag — API may shift.
- **pi-agent** (earendil-works/pi, TS/Node) — *executor*: multi-provider LLM layer (`pi-ai`) + agent loop (`pi-agent-core`). Adopt the bottom two packages; skip `pi-tui` and `pi-coding-agent` CLI (we have our own surface). Plugs into ClawTeam via custom profile. v1 uses OpenAI API key only; pillar 4's other providers are config-only adds in v2.
- **Mulch** (Jaymin West) — corpus *format*: append-only files, 6 record types (convention / pattern / failure / decision / reference / guide), three classifications (foundational / tactical / observational). Adopt format + prime/record bracketing. Re-implement the writer ourselves because our curator is code, not an LLM.
- **Symphony** (OpenAI Symphony) — *UX metaphor* only. Build the dashboard ourselves on top of ClawTeam's `board serve` baseline.
- **Avoided:** OpenClaw (use pi-agent or Claude Code as ClawTeam's spawned executor instead).

## Optional integrations (bind per agent, not in harness core)

- **Serena MCP** — LSP-backed structural code understanding (40+ languages).
- **Aider Repo Map** — tree-sitter + PageRank summary for cold-start codebase awareness.

Both are tools an agent uses, not harness components.

## Explicitly NOT in v1

- **LangGraph** — write own state machine. ClawTeam handles orchestration state; trajectory store handles event detail. No graph framework needed.
- **Multi-machine orchestration** — single-machine in v1. ClawTeam v0.4 adds Redis transport for cross-machine; revisit then.
- **Multi-provider** — pi-agent supports it but we ship OpenAI-only in v1. Anthropic / Google / Ollama are config-only adds in v2.
- **Full OS sandboxing / multi-tenant control plane** — Warren-class territory. Defer.
- **Eval golden sets + reliability dashboards** — ship the log schema (with the 4-dimension fields) now; build the eval UI later.
- **Production Mode** (watchdog chains, full mail-based coordination above 10 agents, merge queue) — design for it, ship at v2. ClawTeam's inbox covers the messaging piece already.

---

## Decisions (resolved 2026-05-25)

1. **Build target** — open-source (MIT). Matches ClawTeam, pi-agent, Mulch. Differentiation lives in dashboard + expertise loop, not source secrecy.
2. **Default model posture** — cloud-first; OpenAI API key only for v1. pi-agent's multi-provider layer means Anthropic / Google / local are config-only adds in v2.
3. **Scale ambition v1** — 10-20 agents. Justifies the Symphony dashboard. Production Mode designed-for but not shipped in v1.
4. **Executor** — pi-agent (via ClawTeam profile). Wraps OpenAI for v1; multi-provider in v2 with no refactor.
5. **Orchestration layer** — ClawTeam (HKUDS), pinned to a specific v0.2.x tag. OpenClaw avoided.

## Role → model tier mapping (defaults; per-agent override via ClawTeam profile)

- **Orchestrator + Reviewer** → OpenAI reasoning tier (heavier, expensive).
- **Builder + Scout** → OpenAI fast tier (cheap, parallel-friendly).
- Specific model names assigned at config time, not baked into the doc — OpenAI lineup shifts.

## Differentiation slot

Nothing in the surveyed landscape occupies:

> An orchestrator that doubles as a learning system — every run's trajectories become expertise that primes the next run, exposed through a Symphony-style dashboard, with model and executor swapped by ClawTeam profile.

Neighbors and what they're missing:
- ClawTeam (alone) — orchestration + Kanban board, no expertise loop, no spec/learning layer.
- Gas Town / Overstory — orchestration, no expertise loop, no dashboard.
- LangGraph — durable graphs, no fleet supervision, no learning loop.
- Claude Code / Codex / pi-agent (alone) — executors, not orchestrators.
- CrewAI / AutoGen — multi-agent frameworks, no compounding harness asset.

The novel surface is **trajectory store + improve-agent + Mulch corpus + spec layer + Symphony UX**. ClawTeam handles orchestration, pi-agent handles execution, Mulch handles corpus format — the rest is the differentiation.

---

## Source material

- `HARNESS_RESEARCH.md` (2026-05-19 brainstorm)
- Jaymin West, *Agentic Engineering Book*, chapters 1-10 (analyzed 2026-05-25 via parallel subagents)
- github.com/HKUDS/ClawTeam
- github.com/earendil-works/pi (pi-agent monorepo)
- Mulch (Jaymin West)
