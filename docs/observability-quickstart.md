# Observability Stack — Quickstart

Start the full local observability stack with one command. `ms up` boots **four** processes and tears them all down cleanly on `Ctrl-C`:

> The CLI is `ms` (`pi-harness` still works as a legacy alias).

| Process | Port | Role |
|---|---|---|
| Fork Bun server | `43190` | Observability dashboard + event store (race / swimlane / replay views) |
| Bridge tailer | — | Streams trajectory events from your runs into the fork, live |
| FastAPI (Symphony backend) | `8800` | Run list, cost, reliability, the deep-link endpoint |
| Next.js (Symphony UI) | `3000` | The harness dashboard; each run page deep-links into the fork |

---

## 1. Prerequisites (one-time)

- **bun** installed (`which bun`) — runs the fork server.
- **The fork checkout** at `~/Desktop/Personal/pi-agent-observability` (override with `PI_HARNESS_OBS_FORK_DIR`).
- **UI deps**: `cd ui && npm install` (creates `ui/node_modules`).
- **Ports `43190`, `8800`, `3000` free.**

`ms doctor` (step 3) verifies all of these for you.

## 2. Configure (one-time)

Config comes from the environment (or a `.env` in the repo root). Activate the venv first — bare `python` isn't on PATH:

```bash
cd ~/Desktop/Personal/mannschaft
source .venv/bin/activate
```

Set these (export in your shell, or put them in `.env`):

```bash
export OPENAI_API_KEY=sk-...                  # already required by the harness
export OBS_AUTH_TOKEN=$(openssl rand -hex 16) # any non-empty secret
export PI_HARNESS_OBS_ENABLED=1               # enforces the token + shows the deep-link
```

> **Why set a token?** With a real `OBS_AUTH_TOKEN`, the browser dashboard's live stream and the tokenized deep-link work end-to-end. You *can* run tokenless with `OBS_DEV=1`, but the browser's live SSE stream will then return 401 — so setting a token is the recommended path.

**Optional overrides:** `OBS_HOST` (default `127.0.0.1`), `OBS_PORT` (default `43190`), `PI_HARNESS_OBS_FORK_DIR`, `PI_HARNESS_TRAJECTORY_DB_PATH` (which runs DB to read; default `~/.pi-harness/trajectory.db`). Keep the FastAPI/UI on `8800`/`3000` — `up`'s readiness checks expect them there.

## 3. Preflight

```bash
ms doctor
```

Prints ✓/✗ for bun, the fork checkout, npm, UI deps, each port, and the token, then the deep-link template. **Fix any ✗ before starting** (it exits non-zero on a hard failure).

## 4. Start it

```bash
ms up
```

It prints the fork UI URL + the deep-link template, boots all four processes, and **blocks** (it's the supervisor). On startup the bridge ships *every existing run* in your trajectory DB into the fork, then keeps tailing for new ones.

Flags:
- `--no-ui` — skip the Next.js UI (boots the backend trio only).
- `--ready-timeout SECONDS` — health-check wait before tailing (default `30`).

## 5. Open the dashboards

- **Fork observability UI** (race / swimlane of all runs) — use the **tokenized** URL `up` prints:
  `http://127.0.0.1:43190/?token=<your-token>`
- **Symphony UI** — `http://localhost:3000` → open a run → **"Open in observability ↗"** (deep-links straight into that run's race view; resolved at runtime, no rebuild needed).

## 6. See it in action (live)

With `up` running, launch a run in a **second terminal** — its agents' events stream into the dashboard in real time. Use the example spec that ships on your machine, or create your own:

```bash
source .venv/bin/activate

# Option A — use an existing spec
ms spec ls                                            # list specs in ~/.pi-harness/specs/
ms launch ~/.pi-harness/specs/dark-mode-toggle.md --detach

# Option B — author a new one
ms spec new my-demo --title "My demo feature"
ms spec edit my-demo                                  # write the PRD in $EDITOR
ms launch ~/.pi-harness/specs/my-demo.md --detach
```

> **Heads-up:** `launch` spins up a real ClawTeam team (live coding agents, tmux panes, git worktrees, and model cost/time) — it's the genuine product command, not a dry run. `--detach` prints the `run_id` and returns immediately so you can watch the run stream into the dashboard. Drop `--detach` to block until it finishes.

Now switch to the fork UI (`http://127.0.0.1:43190/?token=<token>`) and watch the run appear in the race/swimlane view as agents think, call tools, and emit results.

## 7. Stop it

`Ctrl-C` in the `up` terminal. The supervisor tears down all four children in reverse order (graceful `terminate` → 5s wait → `kill`). uvicorn takes a couple of seconds to drain — that's expected; ports free up once it finishes.

## Standalone subcommands (without the full launcher)

| Command | Use |
|---|---|
| `ms observe --follow` | Run **just** the live bridge tailer (the fork must already be up) |
| `ms observe --run <run_id>` | One-shot **backfill** of a single past run into the fork |
| `ms doctor` | Preflight checks any time |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `doctor` says a port is busy | Free `43190`/`8800`/`3000` (`lsof -nP -iTCP:<port> -sTCP:LISTEN`) or stop whatever's on it |
| Dashboard loads but the live stream shows 401 | You're running tokenless — set `OBS_AUTH_TOKEN` and restart `up` |
| `up` exits right away (a child died) | Check the printed logs; usually a busy port, missing `bun`, or missing `ui/node_modules` |
| `doctor` reports "bun on PATH ✗" | Install bun, or point `PI_HARNESS_OBS_FORK_DIR` at your fork checkout |
| No runs in the dashboard | You have no runs yet — `ms launch <spec>` to create one, or `observe --run <id>` to backfill a past run |
