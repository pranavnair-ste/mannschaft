# UC4 Demo Runbook — Sovereign Multi-Agent Coding Harness

A ~10-minute demo of a fully self-hosted multi-agent coding harness: **a spec is
linted, decomposed by a local model into a dependency-ordered task plan, and built
by a team of coding agents in isolated git worktrees — all driven by
Qwen3.6-35B-A3B on the Mac Studio, captured live in a dashboard. Nothing leaves the
box.**

```
spec ─▶ ms lint ─▶ ms decompose ─▶ task DAG ─▶ ms launch ─▶ agents in worktrees ─▶ auto-merge
                    (local model)                              │
                                                     live dashboard (ms up)
```

## One-time setup (the night before)

```bash
cd ~/Desktop/Personal/mannschaft && source .venv/bin/activate
# point both buckets at the local Mac Studio model (see USER_MANUAL §5),
# then stand up the dashboard and preflight:
ms setup-obs
ms doctor          # expect all ✓
ms models list     # confirms the local endpoint is reachable
make -f docs/demo/Makefile warm   # pay the model load cost once
```

## Launch (one command)

```bash
make -f docs/demo/Makefile demo    # preflight + warm + boot the live dashboard
```

Leave the dashboard on a second screen. Run the beats below in a second terminal.

## The beats

**0. Frame it (30s).** "This is our multi-agent coding harness — it takes a whole
spec and runs a *team* of agents to build it, driven entirely by a model on our own
Mac Studio. No OpenAI, no Anthropic, nothing leaves the building." Point at the
dashboard and the model name.

**1. Design-first: the spec + the gate (1m).** Open `docs/demo/uc4-todo-api.spec.md`.
"Work starts from a spec, not a chat box." Run:

```bash
ms lint docs/demo/uc4-todo-api.spec.md          # -> score: 1.00
```

"The linter refuses vague specs — no acceptance criteria, no bounded scope, no
launch. This one scores 1.0."

**2. Decompose LIVE on the local model (1.5m — the strong beat).**

```bash
ms decompose docs/demo/uc4-todo-api.spec.md
```

In ~10 seconds the **local** model returns a task DAG: a scout task, three parallel
builder tasks (one per endpoint), and a test task that depends on all three. Point
out: "This is the sovereign model planning the work — parallelizable tasks with
real dependency edges, produced in about ten seconds." (The harness validates the
DAG — unique ids, resolvable dependencies, no cycles — and self-corrects the model
if it slips.)

**3. The live dashboard (1m).** Switch to the dashboard. Show the race/swimlane
view, the per-run trajectory, and the **standard measures**: total tokens and
**total wall-clock** per run. "Every step of every agent is captured here, live."

**4. Launch the team (2–3m — the orchestration beat).**

```bash
ms launch docs/demo/uc4-todo-api.spec.md
```

It prints the run id and an **isolated `run/<id>` branch**. Switch to the dashboard
and watch it fill in real time: the agents spawn, the model starts emitting tool
calls (read/write/run), and task transitions tick over. "Each agent works in its
own git worktree off an isolated branch — your working branch is never touched —
and their work is merged automatically, with conflicts detected rather than
clobbered."

> **Honest framing (say this).** "Decomposition and orchestration are reliable on
> the local model. Driving a *full* autonomous build to completion on a local model
> is exactly the frontier UC3/UC4 is here to measure — so I'm showing the agents
> working live; if it doesn't finish in demo time, that finding *is* the result."
> If you prefer a guaranteed end-state, load the pre-captured run instead:
> `ms observe <captured_run_id>` (see Fallback below) and narrate the same story.

**5. The measurement (1m).** Back to the dashboard: tokens (prompt + completion)
and wall-clock per run; cost shows **"Local · sovereign · $0 external"** — not a
misleading $0.000, because there is no external spend. "This is the like-for-like
evidence trail UC4 produces for every run."

**6. Close (30s).** "Controllable, observable, and sovereign: a team of agents that
plans and builds from a spec, on hardware we own, with every token and second
accounted for."

## Fallback (always have one ready)

A real captured run is checked in at `docs/demo/fallback-run/` (114 events on the
local Mac Studio model; 3 endpoint tasks built in ~2.5 min). Load it and view it:

```bash
sqlite3 ~/.pi-harness/trajectory.db < docs/demo/fallback-run/run.sql
sqlite3 ~/.pi-harness/trajectory.db < docs/demo/fallback-run/events.sql
ms observe run-34301807-0b17-4ddb-9d5f-72e9dcb8b050
```

Use this for Beat 4 if you don't want to risk a live local build on stage. The
captured run shows the same agents-in-worktrees + tool-call stream. (See
`docs/demo/fallback-run/README.md`.)

## Talking points (mixed audience)

- **Leadership:** sovereignty (no third-party API anywhere in the path), runs on
  hardware we own, and a full per-run evidence trail (tokens + wall-clock) for a
  go/no-go on T&E.
- **Technical:** spec→DAG decomposition with a self-correcting validator, ClawTeam
  agents in isolated git worktrees with conflict-aware auto-merge, and live
  trajectory capture from the pi agent stream — all keyless against local oMLX.

## Notes & troubleshooting

- **First decompose slow?** Model load cost — `make warm` pays it once before you
  present.
- **Live build stalls?** Expected at the frontier on a local model; switch to the
  captured run (`ms observe`). Stop a stuck run with `ms stop <run_id>`.
- **Dashboard empty?** `ms doctor`; ensure `ms setup-obs` has run.
- **Reset for a clean rehearsal vs. live run:** use a fresh run; prior runs remain
  in the dashboard's history.
