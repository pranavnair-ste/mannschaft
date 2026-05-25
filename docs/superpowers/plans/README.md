# Pi-Agent Harness — Implementation Plans

These plans implement the architecture committed in `../../HARNESS_ARCHITECTURE.md` (2026-05-25). Eight sub-projects, each producing working, testable software on its own.

## Plan ordering

Topological order over the cross-plan dependency graph. **Plan 1 must run first**; subsequent plans depend on earlier outputs as noted.

| # | Plan | Depends on | Est. time | File |
|---|---|---|---|---|
| 1 | Foundation | — | 4-6h | [`2026-05-25-foundation.md`](2026-05-25-foundation.md) |
| 2 | Trajectory store | 1 | 8-10h | [`2026-05-25-trajectory-store.md`](2026-05-25-trajectory-store.md) |
| 3 | Mulch corpus + Curator | 1 | 16-22h | [`2026-05-25-mulch-corpus-and-curator.md`](2026-05-25-mulch-corpus-and-curator.md) |
| 4 | Improve-agent | 2 + 3 | 10-14h | [`2026-05-25-improve-agent.md`](2026-05-25-improve-agent.md) |
| 5 | Topology layer | 1, 3, 4 | 16-20h | [`2026-05-25-topology-layer.md`](2026-05-25-topology-layer.md) |
| 6 | Guides + Sensors | 2 (+ alongside 5) | 12-16h | [`2026-05-25-guides-and-sensors.md`](2026-05-25-guides-and-sensors.md) |
| 7 | Spec layer | 1, 5 | 8-10h | [`2026-05-25-spec-layer.md`](2026-05-25-spec-layer.md) |
| 8 | Symphony UX | 2, 5, 6, 7 | 16-22h | [`2026-05-25-symphony-ux.md`](2026-05-25-symphony-ux.md) |

Total ballpark: **90-130 hours** of focused engineering for v1.

## Parallelizable pairs

- After Plan 1: **Plans 2 and 3 are independent** of each other → can run in parallel.
- After Plans 2 + 3 land: **Plan 4 must finish before Plan 5**, but **Plans 6 and 7 can run alongside Plan 5**.
- Plan 8 is the leaf; everything else must be in place first.

## Cross-plan assumptions to verify on first run

Subagents flagged these explicitly. Resolve them at the boundary between plans:

1. **ClawTeam CLI surface** (Plan 1) — assumed flags: `--template/--name/--goal/--profile`, plus `clawteam board`, `clawteam inbox`, `clawteam destroy`, `clawteam template register`. Verify against `clawteam --help` on your installed v0.2.x. Mismatch is a one-line fix in `pi_harness/clawteam/client.py`.
2. **OpenAI model IDs** (Plans 1, 4, 7) — defaults in `pi_harness/config.py` are placeholders. Set `OPENAI_REASONING_MODEL` and `OPENAI_FAST_MODEL` in `.env` to the actual IDs you want.
3. **OpenAI API shape** (Plan 4) — locked to `chat.completions.create` with JSON-mode rather than Responses API (reasoning-tier strict schema support varies). Swap point is `_call_llm` in `pi_harness/improve/agent.py`.
4. **pi-coding-agent stdout schema** (Plans 2, 6) — assumed event shape documented in `pi_harness/trajectory/capture.py` and `pi_harness/guards/runner.py` docstrings. Verify against pi-coding-agent's actual emit format on first ClawTeam launch; adjust the normalizer if needed.
5. **Cross-plan type names** (Plans 5 ↔ 7) — `RunSpec` / `AgentSpec` field names assumed in Plan 7 must match Plan 5's definitions. Single edit site if they drift: `_run_spec_from_tasks` in `pi_harness/spec/editor.py`.
6. **Linter rule enable/disable** (Plan 7) — only env-var wordlist (`PI_HARNESS_VAGUE_WORDS`) is configurable in v1. Rule on/off requires a future `Config.lint_disabled` field; not blocking.

## Execution choice

Two ways to implement each plan (per the writing-plans skill):

- **Subagent-Driven** (recommended for Plans 2-8) — dispatch a fresh subagent per task, two-stage review between tasks. Uses `superpowers:subagent-driven-development`.
- **Inline Execution** — run tasks in your active session with batch checkpoints. Uses `superpowers:executing-plans`. Suggested for Plan 1 (you want to be in the loop on the foundation).

## Where to start

Plan 1 (`2026-05-25-foundation.md`) is the entry point. No other plan compiles without it. Verify prerequisites listed in Plan 1's Prerequisites section first (Python 3.10+, uv, Node 20+, tmux, ClawTeam, pi-coding-agent, OpenAI API key with credit).
