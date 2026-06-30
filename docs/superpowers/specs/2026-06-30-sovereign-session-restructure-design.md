# Design: Sovereign Session Restructure

- **Date:** 2026-06-30
- **Status:** Approved (design); pending implementation plan
- **Branch:** `feat/sovereign-session-restructure`
- **Scope:** v1 = Phases 1–3. Phase 4 (live-streaming extension) explicitly deferred.

## Summary

Invert the product's center of gravity. Today mannschaft is batch-shaped: `ms launch <spec>`
is the front door and the multi-agent team pipeline is the product. After this restructure, an
**interactive, sovereign `pi` session** is the front door — "a Claude Code, but driven by a local
model instead of Opus 4.8" — and the existing team pipeline becomes **a skill that session can
summon in the background, with the user's explicit say-so.**

The headless `ms launch` path survives unchanged for CI/scripted use. Nothing in the proven
coordinator / decomposer / ClawTeam / trajectory / improve pipeline is rewritten; the net-new
code is small and concentrated in a launcher, one status command, and four authored skills.

## Background: current state (grounded)

- **100% batch, no human in the loop.** `ms launch <spec>` → lint (blocking) → decompose once
  (LLM) → build a `RunSpec` → `Coordinator.launch` → ClawTeam team → each role agent runs `pi`
  *once, gagged* → trajectory capture → improve → teardown. The WebSocket (`api/routes/ws.py`)
  is a read-only tailer. There is no place a human types a turn mid-run.
- **`pi` already is a Claude-Code-style loop.** The harness does not implement its own agent
  loop. `pi` (v0.73.1) is a multi-turn, tool-using agent (`read, bash, edit, write`) that talks
  to the local model over an OpenAI-compatible endpoint and tracks cost. The harness deliberately
  suppresses pi's interactive session with `--print --mode json --no-session --no-context-files
  --no-extensions --no-skills` (`pi_harness/agent_wrapper.py`). The `--no-session` flag is the
  tell: pi's interactive mode exists and is being switched off.
- **pi natively provides every pillar we need.** Interactive REPL (bare `pi`), persistent
  sessions (`--session/--continue/--resume/--fork/--session-dir`), a skills system
  (`--skill <path>`, `SKILL.md` with `name`/`description` frontmatter + `references/` — the same
  convention as Claude Code / superpowers), and an extension system that can register custom
  tools and CLI flags (`pi install`, `--extension`).
- **Two team systems already shadow ours.** There is an installed pi skill at
  `~/.pi/agent/skills/clawteam/SKILL.md` that drives the **raw `clawteam` CLI directly**, and pi
  ships its own native teams via `@tmustier/pi-agent-teams` (`~/.pi/agent/teams/`). Both bypass
  everything that makes mannschaft valuable (the decomposer, Spec format, trajectory capture,
  bucket/model mapping, the improve/corpus loop). A real constraint follows: the session must be
  routed through the **mannschaft pipeline** (`ms launch`), not raw clawteam.
- **Model selection already exists.** `HarnessSettings` (`pi_harness/settings.py`) holds
  `orchestrator` and `builder` `BucketConfig`s (provider + model), persisted to
  `~/.pi-harness/models.json`. `ms models set/list/key` manage them. Local default:
  `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit` at `http://localhost:8080/v1` (OpenAI-compatible,
  thinking-off). `pi_models.ensure_pi_provider` idempotently registers the local provider into
  `~/.pi/agent/models.json`. `ms launch` already supports `--detach` (returns a `run_id` and exits).

## Goals

1. An interactive sovereign coding session (`ms chat`) on the local model, hands-on by default,
   that coexists with `ms launch`.
2. The team pipeline reachable from that session as a skill, dispatched **in the background** with
   an explicit user-confirmation gate.
3. **In-chat observability** of a dispatched team: agent-narrated text summaries from a concise
   status command, plus a surfaced deep-link to the existing observability-fork dashboard.
4. Replace the blocking linter with an interactive spec-shaping conversation.
5. A guided per-dispatch model-roster choice (orchestrator vs builder) that operationalizes the
   sovereign / mixed-mode trade-off.

## Non-goals (v1)

- Live, token-by-token streaming of team events *into the chat transcript* (Phase 4 extension).
- Per-run model overrides that leave global defaults untouched (deferred enhancement; v1 is sticky).
- Retiring `ms launch` (it stays as the headless/CI entry point).
- Multi-session management UX, a session GUI, or any new dashboard work.

## Key decisions (locked)

| # | Decision |
|---|----------|
| D1 | Front door = interactive **ungagged `pi`** via new `ms chat`; coexists with `ms launch`. |
| D2 | Solo agent is **hands-on (A)** — `read/bash/edit/write` in the working tree — *and* gives **explicit control (C)** via a conversational confirmation gate before any team dispatch. |
| D3 | Skills are pluggable `SKILL.md` (pi-native convention). We ship harness skills; users can add their own. |
| D4 | The team pipeline is exposed **as a skill (approach 2a)** that shells out to `ms launch`. No new runtime. Evolve to an extension later (2c). |
| D5 | The stale raw-clawteam pi skill is **automatically and reversibly retired** (moved aside, idempotent, logged) on `ms chat` first-run, so the session routes through the mannschaft pipeline. |
| D6 | The blocking linter is **demoted to advisory**; an interactive **shape-spec** skill replaces it as the way specs are created. |
| D7 | Team dispatch is **background/detached** so the chat stays live and observable. |
| D8 | In-chat observation v1 = **option A**: background dispatch + concise `ms status` narration + surfaced **observability-fork deep-link**. The fork dashboard stays. |
| D9 | Live inline streaming = **Phase 4 pi extension** (fast-follow B), out of v1 scope. |
| D10 | A **choose-team-models** skill runs after brainstorming (and as a pre-step on the casual path) to pick orchestrator/builder models per dispatch. v1 is **sticky** — it writes settings via `ms models set`. |
| D11 | Session defaults to the **local** model (reasoning-bucket model); API buckets stay selectable. |

## Architecture

### The inversion

```
BEFORE:  ms launch <spec>  →  [decompose → teams → build]            (the product)

AFTER:   ms chat  →  sovereign pi session (local model, hands-on)    (the product)
                         │
                         ├─ does work directly: read / bash / edit / write
                         │
                         └─ summons the team pipeline as a skill, in the background,
                            with confirmation  →  [decompose → teams → build]   (a power tool)
```

### On-ramps to a team

Both end in the same `ms launch` pipeline; they differ only in how intent is shaped.

```
Formal:  shape-spec (brainstorm)  →  choose-team-models  →  pi-harness (confirm → detach → observe)

Casual:  …chatting…  →  agent: "this is team-sized — pick models / use defaults?"
                         →  choose-team-models (optional)  →  pi-harness (confirm → detach → observe)
```

## Components by phase

### Phase 1 — Sovereign session front door (`ms chat`)

New Typer command in `pi_harness/cli.py`. Launches **ungagged** interactive `pi`.

- **Preflight:** `ensure_pi_provider(...)` (idempotent local-provider registration into
  `~/.pi/agent/models.json`); verify the local OpenAI-compatible server is reachable via a
  lightweight check against the configured local `base_url` (the same *kind* of preflight
  `ms doctor` performs for the observability stack — a new check for the model endpoint, not a
  reuse of doctor's obs-port checks). If unreachable, print a clear instruction to start
  `mlx_lm.server` and exit non-zero.
- **Composed argv (illustrative):**
  ```
  pi --provider <session-provider> --model <session-model> \
     --thinking off \
     --session-dir <PI_HARNESS_HOME>/sessions \
     --skill <repo>/skills \
     --append-system-prompt <harness-orientation-prompt>
  ```
  Crucially *without* `--print`, `--no-session`, `--no-skills`, `--no-context-files`.
- **Session model:** the reasoning-bucket model by default (most capable configured), overridable
  via a flag and/or settings. Local by default per D11.
- **Skills loading:** load the repo's `skills/` dir explicitly via `--skill`; keep discovery on so
  user-authored skills are picked up. (Retirement of the stale clawteam skill is handled in P2.)
- **System prompt:** a short harness-orientation appended prompt — you are a sovereign local
  coding agent; work hands-on; for team-sized work, offer to dispatch a team via the pi-harness
  skill after confirming; once launched, surface the dashboard deep-link.
- **Context files:** allow pi's `AGENTS.md`/`CLAUDE.md` discovery (Claude-Code-like) — i.e. do not
  pass `--no-context-files`.

### Phase 2 — Harness-as-a-skill + `ms status` + retire raw clawteam skill

**Rewrite `skills/pi-harness/SKILL.md`** (today it is a Claude-Code `/pi-harness` slash command
that lints-and-stops, forbids `--detach`, and uses the legacy `pi-harness` name). New behavior,
targeted at the pi solo session:

1. Trigger when the agent judges work is team-sized *or* the user asks.
2. **Confirm with the user before dispatching** ("spin up an agentic team for this? [y/n]").
3. Offer/launch `choose-team-models` (P3) unless the user opts to use current defaults.
4. Launch in the **background**: `ms launch <spec> --detach` → capture the `run_id`.
5. **Surface the observability-fork deep-link**: `<dashboard>/runs/<run_id>`. If the dashboard
   isn't running, tell the user to start it with `ms up`.
6. Poll **on demand** (and optionally on a cadence): `ms status <run_id>` → narrate progress.
7. On completion: report terminal state + the run branch; offer review/merge.
8. Keep "**never shell out to raw `clawteam`**." Drop the lint-and-stop and the no-`--detach` rule.

**New `ms status <run_id>` command** (`pi_harness/cli.py`): concise, **agent-consumable**
(`--json` + human-readable). Reads the trajectory store and ClawTeam task state to report:
per-task status, current step, tokens, cost, elapsed wall-clock, terminal state, and the run
branch. This is the data source that makes in-chat observation work without an extension.

**Retire the stale raw-clawteam pi skill** (`~/.pi/agent/skills/clawteam`): **automatically and
reversibly** disabled on `ms chat` first-run setup — *moved aside* (e.g. renamed to
`clawteam.disabled/` or relocated to a harness-managed backup dir), never hard-deleted, so it is
recoverable. The operation is **idempotent** (no-op if already disabled / absent) and **logged**
(one line telling the user what was moved and how to restore it). The mannschaft skill is
installed/loaded in its place so the session cannot take the value-stripped shortcut.

### Phase 3 — Brainstorm-to-spec + choose-team-models + de-gate the linter

**New `skills/shape-spec/SKILL.md`** — interactive spec-shaping (the superpowers-brainstorming
shape, harness-native): accrete goal / constraints / non-goals / acceptance criteria through
dialogue, then write the **existing Spec format** via `ms spec new` (+ edits). Surface
`ms lint --json` output as **advisory suggestions** woven into the conversation, never as a gate.
Chain into `choose-team-models` → `pi-harness`.

**New `skills/choose-team-models/SKILL.md`** — guided model-roster selection before dispatch:

1. `ms models list` to show current buckets + available models (local + configured API).
2. Ask: orchestrator model? builder model? — surfacing the recommendation inline: *for reliable
   autonomous decomposition, point orchestrator at an API model (gpt-5.x); the builder can stay
   local/sovereign* (the proven mixed config, offered as the suggested default).
3. **Encode the single-local-server constraint:** `mlx_lm.server` serves one model, so
   "orchestrator=local-A + builder=local-B (distinct)" is not servable from one local server —
   warn and steer to same-local-model-for-both or a mixed API/local split.
4. Apply via `ms models set --bucket orchestrator …` and `ms models set --bucket builder …`
   (**sticky** per D10), then chain into `pi-harness`.

Invokable both as the chained middle step (formal on-ramp) and as a pre-step the dispatch skill
offers (casual on-ramp).

**De-gate the linter:** remove the launch-blocking `_lint_or_die` / score≥1.0 requirement from the
`ms launch` / decompose path in `pi_harness/cli.py`. `ms lint` remains as an optional advisory
command; the linter library is unchanged and reused by `shape-spec`.

### Phase 4 — deferred (fast-follow B)

A pi **extension** (npm/git package) registering `dispatch_team` / `team_status` tools that stream
team events **live, inline** into the transcript. Needed because pi tool calls are
request/response, so a skill cannot stream a live feed into a turn (a `tail -f` blocks the turn).
Out of v1 scope; tracked as the immediate fast-follow.

## Control & data flow (team dispatch, v1)

```
pi session ──(bash tool)──► ms launch <spec> --detach ──► run_id
     │                                                       │
     │                          Coordinator → ClawTeam → pi workers → trajectory store (SQLite)
     │                                                       │
     ├──(bash, on demand)──► ms status <run_id> ◄── trajectory store + ClawTeam task state
     │        └─► narrate summary in chat
     │
     └──► surface <dashboard>/runs/<run_id>  (fork dashboard, already deep-linked)

on terminal: ms status reports done/failed + branch → agent offers review/merge (or `ms stop`).
```

## Model & sovereignty defaults; model-ceiling mitigation

- The interactive session runs on the **local** model by default (sovereign, $0, offline-capable);
  human steering makes the local 30B viable for turn-by-turn work.
- **Known risk (from prior runs):** a *fully local* autonomous team — decompose + all roles on
  Qwen-30B — may not converge (model ceiling). The proven green config used **API reasoning
  (gpt-5.x) + local builder**. `choose-team-models` makes this an explicit, guided choice at
  dispatch time rather than buried knowledge: sovereign-by-default, mixed-mode one prompt away.
  No code change beyond the skill — it drives existing `ms models set`.

## What stays untouched (reuse map)

`Coordinator` / topology / decomposer / `runspec` / ClawTeam integration / `agent_wrapper`
capture / trajectory store / improve+corpus loop; `ms launch --detach`, `ms stop`, `ms observe`,
`ms up`, `ms setup-obs`, `ms doctor`; the **fork dashboard** and its deep-links; the Spec format
and `ms spec *`; `HarnessSettings` + `ms models *`; `pi_models.ensure_pi_provider`.

## Error handling

- **Local server down:** `ms chat` preflight (the new local-`base_url` reachability check)
  detects an unreachable endpoint → instruct to start `mlx_lm.server` → exit non-zero. (The same
  check is available to skills before dispatch.)
- **Team dispatch failure:** surfaced via `ms status` (terminal = failed) + the run branch for
  inspection; `--keep-alive` leaves the team up for debugging; `ms stop <run_id>` cleans up.
- **Dashboard not running:** the dispatch skill still returns the `run_id` and instructs `ms up`;
  observation degrades to `ms status` text only, never blocks.
- **Mis-routing to raw clawteam:** prevented by retiring the stale skill (P2) and the explicit
  "never raw clawteam" instruction in the dispatch skill.

## Testing strategy

- **`ms chat` launcher (unit):** assert the composed argv (gag-flags absent: no `--print`,
  `--no-session`, `--no-skills`, `--no-context-files`; correct `--provider/--model/--skill/
  --session-dir`); `ensure_pi_provider` idempotency; preflight behavior with mocked reachability
  (reachable → spawn; unreachable → instruction + non-zero). The interactive TUI itself is pi's,
  not under test.
- **`ms status` (integration):** seed a trajectory store + ClawTeam task state → assert the JSON
  shape and the human summary for in-progress / completed / failed runs.
- **De-gating (regression):** assert `ms launch` / decompose proceed on a low-score spec (advisory
  only); assert `ms lint` still reports scores/violations.
- **Skills (validation + e2e):** validate `SKILL.md` frontmatter and that every `ms` command a
  skill invokes exists; e2e the underlying command paths (`ms launch --detach`, `ms status`,
  `ms spec new`, `ms models set/list`), which are all testable.
- All tests run under `-m "not smoke"` (smoke launches a real ClawTeam team that commits to the
  branch).

## Scope & assumed defaults

- **v1 = Phases 1–3.** Phase 4 deferred.
- Session model = reasoning-bucket model by default, overridable.
- `ms chat` does **not** auto-boot the dashboard; the dispatch skill surfaces the link and says
  `ms up` if needed.
- Bare `ms` keeps showing help; the session is `ms chat`.
- Model-roster selection is **sticky** (writes settings); per-run isolated overrides deferred.

## Deferred enhancements (post-v1)

- Phase 4 pi extension for live inline team-event streaming.
- Per-run model overrides on `ms launch` (isolated from global defaults).
- Optional auto-boot / health-managed dashboard from `ms chat`.
- `ms` bare-invocation aliasing to `ms chat`.
