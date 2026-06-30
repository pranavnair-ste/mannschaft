---
name: pi-harness
description: >
  Use when work is large enough to benefit from a parallel agentic team — the
  user asks to "build/implement X with a team", "spin up agents", "run the
  harness", or the current task clearly exceeds efficient solo work. Dispatches
  the mannschaft team pipeline IN THE BACKGROUND via `ms launch --detach`, after
  confirming with the user, and surfaces live observability in the chat. Never
  shells out to raw clawteam.
version: 1.0.0
---

# pi-harness — dispatch an agentic team (background + observable)

You are the sovereign session. This skill lets you summon the mannschaft
multi-agent pipeline as a power tool. The team runs in the background so the
chat stays live and you can report progress.

## When to use
- The user explicitly asks for a team / the harness, OR
- You judge the work is team-sized (multi-file feature, parallelizable scope).

## Protocol

1. **Have a spec.** If the user has a spec file or `~/.pi-harness/specs/<id>.md`,
   use it. If not, use the `shape-spec` skill first to build one interactively.

2. **CONFIRM before dispatching.** Always ask, e.g.: "This is team-sized — spin
   up an agentic team to build it in the background? [y/n]". Do not launch
   without a yes.

3. **Pick models.** Unless the user says "use my defaults", run the
   `choose-team-models` skill so they can set orchestrator/builder per dispatch
   (recommend API reasoning + local builder for reliable decomposition).

4. **Launch in the background** with Bash:
   `ms launch <spec-path> --detach`
   Capture the printed `run_id` (and the `isolated on branch:` line if shown).

5. **Surface observability.** Tell the user the run_id and the fork dashboard
   deep-link `<dashboard>/runs/<run_id>`. If the dashboard isn't running, tell
   them to start it: `ms up`. Say they can ask "status" anytime.

6. **Report progress on demand / on a cadence** with Bash:
   `ms status <run_id> --json`
   Summarize it in plain language (tasks done, current agent activity, tokens,
   cost, elapsed). Keep working with the user in the meantime.

7. **On completion** (`ms status` shows a terminal state): report success/failure
   and the run branch; offer to diff/review/merge. On failure, surface the
   branch for inspection; `ms stop <run_id>` cleans up a stuck run.

## Do NOT
- Do not launch without explicit confirmation.
- Do not block the session waiting for the team (always `--detach`).
- Do not shell out to `clawteam` directly — `ms launch` is the only path.
- Do not re-run `ms decompose` before `ms launch` (launch decomposes once).
