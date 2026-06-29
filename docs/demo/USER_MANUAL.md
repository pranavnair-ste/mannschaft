# Mannschaft — Sovereign Multi-Agent Coding Harness · User Manual

UC4 · Pi Coding Agent product development · local open-weight models on a Mac Studio
Version 0.1 · 2026-06-29

> A multi-agent coding harness that runs **entirely on your own hardware**. You
> write a spec; the harness lints it, decomposes it into a dependency-ordered task
> plan, runs a team of coding agents in isolated git worktrees, merges their work,
> and captures every step to a live dashboard. The agents are driven by a local
> model (Qwen3.6-35B-A3B served by oMLX on the Mac Studio) — **no OpenAI, no
> Anthropic, no data leaving the box.**

## 1. What this is

This is the **Pi-agent harness** — the "controllable harness" track of *LLM in a
Box* (UC4). Where a coding assistant (UC2) helps you edit one file, this harness
takes a whole spec and orchestrates a team of agents to build it. You get:

- **Design-first specs** — a linter that refuses vague specs, and an LLM
  **decomposer** that turns a clean spec into a dependency-ordered task DAG.
- **Multi-agent orchestration** — agents run concurrently, each in its own git
  worktree off an isolated run branch; their work is merged automatically with
  conflict detection.
- **A live observability dashboard** — every run's tasks, agent events, tokens,
  and wall-clock time, streamed live and replayable.
- **Sovereignty** — keyless local execution against your own oMLX endpoint;
  loopback or your private Tailnet only; fully air-gappable.

## 2. How it fits together

```
   spec.md ──ms lint──▶ score 1.0 gate ──ms decompose──▶ task DAG (blocked_by)
                                                              │
                                                         ms launch
                                                              │
            ┌─────────────────────────────────────────────────────────────┐
            │  ClawTeam team on an isolated run/<id> branch                 │
            │   ├─ agent: builder   (own git worktree)  ─┐                  │
            │   ├─ agent: scout     (own git worktree)   ├─▶ auto-merge ──▶ run/<id>
            │   └─ agent: reviewer  (own git worktree)  ─┘   (conflict-aware)│
            └─────────────────────────────────────────────────────────────┘
                                       │
                          trajectory store (SQLite)
                       events · tokens · wall-clock · cost
                                       │
                          ms up ─▶ live dashboard (race / swimlane / replay)
```

Each agent is a **pi** process driven by the local model. The harness never calls
a frontier API: the orchestrator and builder buckets both default to the local
provider, and the decomposer talks directly to the local endpoint.

## 3. What's in the box

| Component | Role |
| --- | --- |
| `ms spec` / `ms lint` | Author specs; the linter gates on acceptance criteria + bounded scope (score must be 1.0) |
| `ms decompose` | LLM decomposition of a clean spec into a dependency-ordered task DAG |
| `ms launch` | Run the team: spawn agents in isolated worktrees, drain the DAG, auto-merge |
| `ms up` / `ms observe` | Boot the live dashboard; translate a run's trajectory into it |
| `ms setup` / `ms setup-obs` | One-time: pick the local provider+model; clone+pin the dashboard and mint its token |
| `ms doctor` | Preflight: bun, dashboard checkout, ports, token |
| `ms models` | Discover and assign local/cloud models per agent bucket |
| `~/.pi-harness/models.json` | Which provider+model each bucket uses; the local endpoint URL |

## 4. Prerequisites

- A **Mac Studio running oMLX** serving `Qwen3.6-35B-A3B-MLX-4bit` (UC1's primary
  pick). Reachable either on the Mac Studio itself (`http://localhost:15100/v1`)
  or from a dev machine over your Tailnet (`http://<tailscale-ip>:15100/v1`).
- **bun** and **npm** on PATH (for the observability dashboard + UI).
- The harness venv: `source .venv/bin/activate` in the mannschaft checkout.
- **No OpenAI key required** — the sovereign default path is keyless.

## 5. First-time setup (the night before)

```bash
cd ~/Desktop/Personal/mannschaft
source .venv/bin/activate

# 1. Point the harness at your local model. Fully-sovereign (both buckets local);
#    use the 8-bit builder for full multi-task builds (4-bit is fine for decompose
#    + interactive use). Thinking is disabled for local models automatically.
ms models set --bucket orchestrator --provider local --model Qwen3.6-35B-A3B-MLX-4bit
ms models set --bucket builder      --provider local --model Qwen3.6-35B-A3B-MLX-8bit
#    Higher-quality (NON-sovereign) alternative — frontier planner + local builder:
#      ms models set --bucket orchestrator --provider api --model gpt-5   # needs OPENAI_API_KEY
#    Set the endpoint URL in ~/.pi-harness/models.json -> "local_base_url".
#    Co-located on the Mac Studio:  http://localhost:15100/v1
#    From a laptop over Tailscale:  http://100.x.y.z:15100/v1   (allowed by the
#    SSRF guard as a private Tailnet address; metadata/public IPs stay blocked)

# 2. Stand up the dashboard (clones+pins it, mints a persistent token, enables it):
ms setup-obs

# 3. Confirm everything is ready:
ms doctor          # expect all ✓ (bun, dashboard checkout, ports, token)
ms models list     # confirms the local endpoint is reachable + lists served models
```

`ms setup-obs` clones the dashboard to `~/.pi-harness/obs-dashboard` at the pinned
`v0.3.0` ref and writes a persistent `OBS_AUTH_TOKEN` to the keystore — so it works
on a fresh machine with no manual scavenger hunt.

## 6. The run, step by step

```bash
# Lint the spec — must score 1.0 before it can be decomposed or launched.
ms lint docs/demo/uc4-todo-api.spec.md          # -> score: 1.00

# Decompose it into a task DAG (driven by the LOCAL model, no key, ~10s).
ms decompose docs/demo/uc4-todo-api.spec.md     # -> JSON task list with blocked_by edges

# Boot the live dashboard (in a second terminal / on a second screen):
ms up                                            # opens the dashboard; Ctrl-C tears it down

# Launch the team. Agents run in isolated worktrees and merge automatically.
ms launch docs/demo/uc4-todo-api.spec.md
#   prints the run_id + the isolated run/<id> branch; watch it live in the dashboard
```

> **On local-model convergence.** A full autonomous multi-task *build* does
> converge on a local model with the right setup. Validated run: a 5-task
> interactive-dashboard build (data → KPIs → charts → filter → README) from an
> Excel file completed end-to-end in **~2.5 minutes** with **`gpt-5` orchestrator +
> `Qwen3.6-35B-A3B-MLX-8bit` builder**, thinking off, $0 build cost. Two settings
> make this reliable and are **on by default** (no action needed):
> - **Builder thinking is disabled for local models** (`local_disable_thinking`),
>   so each turn isn't a slow reasoning trace.
> - **Output cap raised to 16384 tokens**, so an agent can write a whole file in
>   one turn (a 4096 cap truncated mid-file and stalled the run).
>
> Use the **8-bit** builder for full builds (the 4-bit model is weaker at sustained
> coding once thinking is off); 4-bit is fine for decomposition and interactive use.
> For a fully-sovereign build use a local orchestrator too; `gpt-5` as orchestrator
> is a higher-quality (non-sovereign) option that sends the spec to OpenAI. See
> `DEMO.md` for the beat sheet.

## 7. The live dashboard

`ms up` boots four processes — the dashboard server, a live event bridge, the
FastAPI backend, and the Next.js UI — and opens the dashboard. As a run executes
(or when you load a captured run), you see:

- **Race / swimlane views** of the agents working concurrently.
- **Per-run trajectory** — every tool call, message, and task transition.
- **Standard measures** — total tokens (prompt + completion) and **total
  wall-clock time** per run.
- **Cost** — cloud runs show dollars; a fully-local run shows **"Local · sovereign
  · $0 external"** rather than a misleading `$0.000`.

If a process doesn't come up, `ms up` says which one and why (use `ms up --strict`
to fail hard in CI-style checks).

## 8. Where the data lives

- Every run is recorded to the trajectory store (`~/.pi-harness/trajectory.db`):
  per-step events, token counts, timings, and a run summary (tokens + wall-clock).
- `ms observe <run_id>` translates a stored run into the dashboard — this is how
  you replay a previously-captured run.

## 9. Sovereignty & data handling

- The harness calls **only** your local oMLX endpoint — no frontier API is in the
  path. The default provider is `local` and needs no API key.
- Local endpoints are **SSRF-validated** to loopback / RFC-1918 / RFC-6598
  (Tailnet) addresses; link-local, cloud-metadata (169.254.169.254), and public
  IPs are rejected.
- Fully **air-gappable**: once the model weights are downloaded, nothing in the
  run path needs the network. (Launch the oMLX/model server with
  `HF_HUB_OFFLINE=1` for a sealed box.)

## 10. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ms models list` can't reach the endpoint | Check `local_base_url` in `~/.pi-harness/models.json`; confirm oMLX is serving and the port is right. |
| Decompose or agent turns are slow / verbose | A thinking model with thinking left on. The harness disables it for local models by default (`local_disable_thinking`) — for both the decomposer and the agent loop; confirm your model alias resolves to a served Qwen model. |
| `ms up` shows no live events | Run `ms doctor`; ensure `ms setup-obs` has run (token + dashboard checkout). |
| A local build stalls mid-file (agent deletes/rewrites a file) | Was the 4096-token output cap; now raised to 16384 automatically. If you still see `stopReason="length"`, the file is larger than one turn — split the task or raise the model's `maxTokens` in `~/.pi/agent/models.json`. Prefer the **8-bit** builder for full builds. |
| Dashboard port in use | `ms doctor` reports busy ports; free them or stop a prior `ms up`. |
| Recover after Ctrl-C during a launch | `ms stop <run_id>` kills the team and cleans up its worktree. |

## 11. Appendix — command & config reference

```bash
ms doctor                 # preflight the observability stack
ms setup                  # interactive: pick provider + assign bucket models
ms setup-obs [--update]   # clone+pin the dashboard, mint token, enable observability
ms lint <spec>            # 0 clean / 1 errors / 2 warnings
ms decompose <spec>       # spec -> task DAG (JSON), local model, no key
ms launch <spec>          # run the team (add --timeout, --detach, --keep-alive)
ms up [--strict|--no-ui]  # boot the live dashboard
ms observe <run_id>       # push a stored run to the dashboard
ms models list            # show bucket assignments + discovered models
ms stop <run_id>          # stop a run and clean up
```

`~/.pi-harness/models.json`:

```json
{
  "orchestrator": { "provider": "local", "model": "Qwen3.6-35B-A3B-MLX-4bit" },
  "builder":      { "provider": "local", "model": "Qwen3.6-35B-A3B-MLX-8bit" },
  "local_base_url": "http://localhost:15100/v1",
  "decompose_max_tokens": 2048,
  "local_disable_thinking": true
}
```

`local_disable_thinking: true` (the default) turns off Qwen's reasoning trace for
**both** the decomposer and the local agent loop. The harness also registers local
Qwen models in pi's registry with a generous output cap (16384 tokens) so an agent
can write a whole file in one turn. For the highest-quality (non-sovereign) split,
set `orchestrator` to `{ "provider": "api", "model": "gpt-5" }` and keep `builder`
local — the validated mixed configuration.
