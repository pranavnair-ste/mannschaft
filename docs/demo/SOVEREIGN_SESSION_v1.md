# Sovereign Session (`ms chat`) — v1 User Manual

UC4 · Sovereign multi-agent coding harness · local open-weight models on a Mac Studio
Version 1.0 · 2026-06-30

> A **Claude-Code-style interactive coding agent that runs on your own local
> model** instead of a cloud frontier model. You chat with it in your terminal;
> it works hands-on in your repo with its read / bash / edit / write tools. When
> a job is big enough to want a parallel team, it offers — with your explicit
> say-so — to dispatch the proven mannschaft multi-agent pipeline **in the
> background**, and narrates that team's progress back into the chat. No OpenAI,
> no Anthropic, no data leaving the box (unless you deliberately pick a cloud
> orchestrator for a team run).

---

## 1. What changed in v1

Before v1, mannschaft was batch-shaped: `ms launch <spec>` was the front door and
the multi-agent team pipeline *was* the product. v1 inverts that. The front door
is now an **interactive sovereign session** — `ms chat`. The team pipeline still
exists, unchanged, but it is now a **power tool the session summons in the
background**, not the thing you start with.

| You want to… | v1 way |
|---|---|
| Work interactively with a local-model agent | `ms chat` |
| Have it do small/medium work itself | just ask it, in `ms chat` |
| Shape a fuzzy idea into a spec | ask it to plan — it runs the `shape-spec` skill |
| Build something team-sized | it offers to dispatch a team (`pi-harness` skill); you confirm |
| Watch a dispatched team | `ms status <run_id>` (or the dashboard deep-link) |
| Stop a dispatched team | `ms stop <run_id>` |

The headless `ms launch <spec>` path survives **unchanged** for CI / scripted use.
This manual is about the new interactive front door.

---

## 2. Prerequisites

All commands assume you are in the repo with the venv active:

```bash
cd ~/Desktop/Personal/mannschaft && source .venv/bin/activate
```

### 2.1 Start a local model server (required for the sovereign default)

`ms chat` defaults to your **local** model. It will not start the session if no
local OpenAI-compatible server is reachable — it does a preflight check and exits
with an instruction. Start one first. The default local endpoint is
`http://localhost:8080/v1` (the `mlx_lm.server` default port) and the default
model is `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit`:

```bash
mlx_lm.server --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit --port 8080
```

Leave that running in its own terminal. (On the demo Mac Studio this is the
Qwen3.6-35B-A3B endpoint served by oMLX on the same `:8080/v1` contract.)

> If the server isn't up, `ms chat` prints exactly this and exits non-zero:
> ```
> error: no local model server reachable at http://localhost:8080/v1
>   start one first, e.g.:
>     mlx_lm.server --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit --port 8080
>   or point a bucket at the API with `ms models set`.
> ```

### 2.2 Confirm the harness sees the model

```bash
ms models list
```

This prints the current orchestrator/builder buckets and the local models
available at `http://localhost:8080/v1`. If the local section shows your model,
you're ready.

### 2.3 (Optional, only for team dispatch) The observability dashboard

You do **not** need the dashboard to use `ms chat` solo. You only want it when you
dispatch a team and want the visual run view. One-time:

```bash
ms setup-obs        # clone + pin the dashboard, provision the auth token
ms doctor           # preflight — expect all ✓
```

Then, when you want it live (see §6), `ms up`.

### 2.4 (Optional) A cloud key — only for the *mixed* team config

The session itself is fully local. You only need a cloud key if, for a *team
dispatch*, you choose a cloud orchestrator (the proven reliable config — see §7):

```bash
ms models key --provider openai      # hidden prompt; validated on entry
```

---

## 3. Start the session — `ms chat`

```bash
ms chat
```

This launches an **ungagged** interactive `pi` session on your local model:
interactive REPL, persistent sessions, skills, and `AGENTS.md` / `CLAUDE.md`
context discovery are all **on** (the batch `ms launch` path deliberately turns
all of that off; here it's deliberately on). Under the hood it runs roughly:

```
pi --provider harness-local --model <your-local-model> \
   --thinking off \
   --session-dir ~/.pi-harness/sessions \
   --skill <repo>/skills \
   --append-system-prompt <harness-orientation-prompt>
```

`--thinking off` is set for local Qwen models (they run away with thinking on);
it is omitted for cloud models.

### 3.1 First-run note: the raw-clawteam skill is retired

On first `ms chat`, the harness **reversibly disables** the stale pi skill at
`~/.pi/agent/skills/clawteam` (it taught a value-stripped shortcut around the
mannschaft pipeline). It is moved aside, never deleted, and the move is logged so
you can restore it:

```
note: disabled the raw-clawteam pi skill (moved …/clawteam -> …/clawteam.disabled);
restore with `mv …/clawteam.disabled …/clawteam` if you want it back.
```

This is idempotent — a no-op on later runs. It guarantees the session routes
teams through `ms launch`, never raw `clawteam`.

### 3.2 Overriding the session model

By default the session uses your most capable configured (reasoning-bucket) model,
which is local by default. To override per-invocation:

```bash
ms chat --provider api --model gpt-5.4        # run the session on a cloud model
ms chat --provider local --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit
```

Override is per-launch and does not change your saved bucket defaults.

---

## 4. Working solo (the common case)

Inside `ms chat`, just talk to it like any coding agent. It works **hands-on** in
your current repo:

- reads files, greps, runs commands (`bash`),
- edits and writes files directly,
- iterates with you turn by turn.

This is the right mode for: understanding a codebase, a focused bug fix, a
single-file or small multi-file change, scripting, exploration. It will *not*
silently spin up a team — for team-sized work it asks first (§5–§6).

---

## 5. Shaping a spec — the `shape-spec` skill

When you want to define **what** to build before building it (a feature, a PRD,
a fuzzy idea), ask the session to plan it. It runs the **`shape-spec`** skill: a
short collaborative conversation that accretes, one question at a time:

- **Goal** — one or two sentences: what should exist when done.
- **Acceptance criteria** — concrete, checkable (e.g. "`POST /todos` returns 201
  with a generated id").
- **Constraints** — language / runtime / libraries / scope limits.
- **Non-goals** — explicitly out of scope.

It then scaffolds and fills the existing harness spec format:

```bash
ms spec new <id> --title "<title>"     # scaffolds ~/.pi-harness/specs/<id>.md
```

…and the session edits `~/.pi-harness/specs/<id>.md` to fill in the fields.

**Linting is advisory now, not a gate.** The session may run:

```bash
ms lint ~/.pi-harness/specs/<id>.md --json
```

…and weave any findings into the conversation as *suggestions*. It will never
refuse to proceed on a lint warning. (The standalone `ms lint` command still exits
by severity — 0 clean / 1 errors / 2 warnings — if you want a hard check.)

When the spec is ready, the session asks whether to build it now. If yes, it
proceeds to model selection (§7) and dispatch (§6). If you'd rather it build solo,
it just does the work hands-on.

---

## 6. Dispatching a team — the `pi-harness` skill (background + observable)

For team-sized work — multi-file features, parallelizable scope, or anytime you
ask for "a team" / "the harness" — the session uses the **`pi-harness`** skill.

**It always confirms with you before dispatching.** Expect something like:
*"This is team-sized — spin up an agentic team to build it in the background?
[y/n]"*. Nothing launches without a yes.

On confirmation it:

1. (Unless you say "use my defaults") runs `choose-team-models` (§7).
2. Launches the mannschaft pipeline **in the background** so the chat stays live:
   ```bash
   ms launch <spec-path> --detach
   ```
   This decomposes the spec once, builds the task DAG, runs the ClawTeam team on
   an isolated `run/<id>` branch, and **returns immediately** with a `run_id`:
   ```
   run-abc123
     isolated on branch: run/run-abc123
     detached — stop it with: ms stop run-abc123
   ```
3. Surfaces the **observability deep-link** for that run (see §6.2) and tells you
   that you can ask for "status" anytime.

> The session never re-runs `ms decompose` before `ms launch` — launch decomposes
> once. And it never shells out to raw `clawteam`; `ms launch` is the only path.

### 6.1 Checking progress — `ms status`

Ask the session for status anytime, or run it yourself. `ms status` reads the
trajectory store (not the live team, which may be torn down), so it works during
*and* after a run:

```bash
ms status run-abc123            # concise human-readable summary
ms status run-abc123 --json     # machine-readable (what the skill narrates from)
```

The human form is one block: run id, status, agent count, tokens in/out, cost
(shown as `$0.00 (sovereign)` for a fully-local run), elapsed wall-clock, the run
branch, and a per-agent line (last classification / tool / outcome). The session
turns this into plain-language progress while you keep working with it.

### 6.2 The dashboard — `ms up` + the deep-link

For the visual run view, boot the observability stack (the dispatch skill will
tell you to do this if it isn't already running):

```bash
ms up
```

`ms up` boots the fork's Bun observability server (default
`http://127.0.0.1:43190`), the live bridge tailer, the FastAPI dashboard (`:8800`),
and the Next.js UI (`:3000`). It prints the UI URL and a **run deep-link
template**:

```
observability fork UI: http://127.0.0.1:43190/
run deep-link template: http://127.0.0.1:43190/?token=<token>#view=race&pool=<run_id>&hide_after=never&show_hidden=1
```

Substitute your `run_id` for `<run_id>` to jump straight to that run. If the
dashboard isn't running, observation simply degrades to `ms status` text — it
never blocks you.

### 6.3 On completion

When `ms status` shows a terminal state, the session reports success or failure
and the run branch, and offers to diff / review / merge. The work lives on
`run/<id>`:

```bash
git diff main...run/run-abc123        # review what the team built
```

On failure, the branch is there for inspection; `--keep-alive` on the original
launch leaves the team up for debugging.

### 6.4 Stopping a run — `ms stop`

To stop a detached (or stuck) run — killing its agents to halt any credit burn and
cleaning up its team + run worktree:

```bash
ms stop run-abc123
# -> stopped run-abc123
```

---

## 7. Choosing team models — `choose-team-models` (sovereign vs mixed)

Right before a dispatch (after `shape-spec`, or when `pi-harness` offers it), the
session runs the **`choose-team-models`** skill to pick which model is
orchestrator and which is builder for the run. It first shows the roster:

```bash
ms models list
```

Then it explains the trade-off and asks you to choose:

- **Sovereign (the default):** orchestrator **and** builder both local. $0,
  offline, fully private. **Caveat:** a fully-local autonomous team on a ~30B
  model may struggle to converge on complex decompositions.
- **Mixed (most reliable — the proven config):** orchestrator = a cloud reasoning
  model (e.g. `gpt-5.4`) for dependable decomposition + review; builder = local
  for sovereign, cost-free code generation. This is the config that produced green
  runs in prior testing.

**Single-local-server constraint:** `mlx_lm.server` serves exactly **one** model.
So "orchestrator = local model A *and* builder = a *different* local model B" is
**not servable** from one local server. Allowed combinations: the *same* local
model for both buckets, **or** a mixed cloud/local split. The skill warns and
re-asks if you pick two different local models.

The choice is applied (and is **sticky** — it becomes your new default) one bucket
at a time:

```bash
ms models set --bucket orchestrator --provider api   --model gpt-5.4
ms models set --bucket builder      --provider local --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit
```

(If a cloud bucket needs a key, set it once with `ms models key --provider openai`.
`ms models set` refuses while a run is actively building, so set models between
runs.)

After applying, the session hands off to the `pi-harness` dispatch skill (§6).

> **Recommendation for the demo:** sovereign-by-default for the interactive session
> and solo work; **mixed** (cloud orchestrator + local builder) for any non-trivial
> *team* dispatch, since it's the proven-to-converge roster.

---

## 8. Quick reference (real commands)

```bash
# prerequisites
mlx_lm.server --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit --port 8080
ms models list

# the session
ms chat
ms chat --provider api --model gpt-5.4          # override session model

# specs (the session drives these via shape-spec)
ms spec new <id> --title "<title>"
ms lint ~/.pi-harness/specs/<id>.md --json      # advisory

# team models (the session drives these via choose-team-models)
ms models set --bucket orchestrator --provider api   --model gpt-5.4
ms models set --bucket builder      --provider local --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit
ms models key --provider openai

# team dispatch + observe (the session drives these via pi-harness)
ms launch <spec-path> --detach                  # returns run_id, runs in background
ms status <run_id>                              # human-readable
ms status <run_id> --json                       # machine-readable
ms up                                           # boot the dashboard
ms stop <run_id>                                # stop + clean up a run
```

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `ms chat` exits with "no local model server reachable" | Start `mlx_lm.server` (§2.1), or override with `ms chat --provider api --model <id>`. |
| The session won't dispatch a team | By design — it always asks first. Confirm with "yes". |
| A fully-local team stalls / never converges | Switch to the mixed roster (cloud orchestrator + local builder) via `choose-team-models` / `ms models set`. |
| Dashboard deep-link doesn't load | Run `ms up`; if it complains, run `ms doctor` and `ms setup-obs`. Observation still works via `ms status` text without the UI. |
| `ms models set` refuses | A run is actively building — set models between runs. |
| A detached run is stuck or burning credit | `ms stop <run_id>`. |
| Want the old raw-clawteam pi skill back | `mv ~/.pi/agent/skills/clawteam.disabled ~/.pi/agent/skills/clawteam` (see §3.1). |

---

## 10. What's deferred (v1 scope)

v1 is Phases 1–3 of the sovereign-session restructure. A few things are
intentionally out of scope and tracked in
[`docs/superpowers/EXPANSION-DECISIONS.md`](../superpowers/EXPANSION-DECISIONS.md):

- **Live, token-by-token streaming** of team events *into the chat transcript*
  (Phase 4 pi extension). Today observation is on-demand `ms status` narration +
  the dashboard deep-link.
- **Per-run model overrides** isolated from your global defaults — v1 is sticky
  (`ms models set` changes the defaults).
- **Auto-booting the dashboard** from `ms chat` — v1 surfaces the link and tells
  you to run `ms up`.
- **Bare `ms` aliasing to `ms chat`** — bare `ms` still shows help; the session is
  `ms chat`.
