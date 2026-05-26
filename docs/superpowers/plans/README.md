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
| 7 | Spec layer + CLI + slash command | 1, 5 | 14-18h | [`2026-05-25-spec-layer.md`](2026-05-25-spec-layer.md) |
| 8 | Symphony UX | 2, 5, 6, 7 | 16-22h | [`2026-05-25-symphony-ux.md`](2026-05-25-symphony-ux.md) |

Total ballpark: **96-138 hours** of focused engineering for v1 (Plan 7 grew by 6-8h after the CLI + slash-command additions in the 2026-05-26 audit).

## Parallelizable pairs

- After Plan 1: **Plans 2 and 3 are independent** of each other → can run in parallel.
- After Plans 2 + 3 land: **Plan 4 must finish before Plan 5**, but **Plans 6 and 7 can run alongside Plan 5**.
- Plan 8 is the leaf; everything else must be in place first.

## Cross-plan assumptions to verify on first run

Subagents flagged these explicitly. Resolve them at the boundary between plans:

1. **ClawTeam CLI surface** (Plan 1) — **RESOLVED 2026-05-26.** ClawTeam 0.2.0's real CLI shape is now reflected throughout Plans 1, 2, 5. Real verbs: `clawteam launch TEMPLATE --team Y --goal Z [--profile P]`, top-level `clawteam --json` (not per-subcommand), `clawteam task list TEAM`, `clawteam task create TEAM SUBJECT --blocked-by`, `clawteam inbox peek TEAM`, `clawteam team cleanup TEAM --force`, `clawteam profile set NAME --agent ... --model ...`. Templates are registered by dropping a TOML at `~/.clawteam/templates/<name>.toml` (top-level `--data-dir` does NOT change template lookup). Task statuses are `pending|in_progress|completed|blocked` (no `failed`/`cancelled`). Plan 1's `ClawTeamClient` exposes these as instance methods: `install_template`, `launch_team`, `create_task`, `list_tasks`, `peek_inbox`, `wait_for_completion`, `cleanup_team`, `register_profile`.
2. **OpenAI model IDs** (Plans 1, 4, 7) — defaults in `pi_harness/config.py` are `gpt-5` (reasoning) and `gpt-5-mini` (fast). Override via `PI_HARNESS_REASONING_MODEL` / `PI_HARNESS_FAST_MODEL` in `.env`.
3. **OpenAI API shape** (Plan 4) — locked to `chat.completions.create` with JSON-mode rather than Responses API (reasoning-tier strict schema support varies). Swap point is `_call_llm` in `pi_harness/improve/agent.py`.
4. **pi-coding-agent stdout schema** (Plans 2, 6) — assumed event shape documented in `pi_harness/trajectory/capture.py` and `pi_harness/guards/runner.py` docstrings. Verify against the real emit format on first ClawTeam launch; adjust the normalizer if needed. Note: the npm package `@mariozechner/pi-coding-agent` installs a binary named `pi` (not `pi-coding-agent`); `@openai/codex` installs `codex`.
5. **Cross-plan type names** (Plans 5 ↔ 7) — `RunSpec` / `AgentSpec` field names assumed in Plan 7 must match Plan 5's definitions. Single edit site if they drift: `_run_spec_from_tasks` in `pi_harness/spec/editor.py`. Plan 5 added `RunSpec.executor` and `RunSpec.sync_profile` plus `AgentSpec.task_prompt` after the CLI audit — Plan 7's decomposer must populate these when emitting a `RunSpec`.
6. **Linter rule enable/disable** (Plan 7) — only env-var wordlist (`PI_HARNESS_VAGUE_WORDS`) is configurable in v1. Rule on/off requires a future `Config.lint_disabled` field; not blocking.
7. **Plan 1 `Config` API surface** (Plans 6, 7, 8) — **RESOLVED 2026-05-26.** Plan 1 ships `pi_harness.config.load_config(env_file=".env") -> Config` (a frozen dataclass). There is NO `Config.load()` classmethod, no `Config.from_env()`. Fields: `openai_api_key`, `reasoning_model`, `fast_model`, `clawteam_state_dir`, `corpus_root`, `trajectory_db_path` (with `_path` suffix). Dashboard knobs (api_host, api_port, frontend_origin) live on a separate `DashboardConfig` introduced in Plan 8, NOT on Plan 1's Config.

## Execution choice

Two ways to implement each plan (per the writing-plans skill):

- **Subagent-Driven** (recommended for Plans 2-8) — dispatch a fresh subagent per task, two-stage review between tasks. Uses `superpowers:subagent-driven-development`.
- **Inline Execution** — run tasks in your active session with batch checkpoints. Uses `superpowers:executing-plans`. Suggested for Plan 1 (you want to be in the loop on the foundation).

## Where to start

Plan 1 (`2026-05-25-foundation.md`) is the entry point. No other plan compiles without it. Verify prerequisites listed in Plan 1's Prerequisites section first (Python 3.11+, uv, Node 20+, tmux, ClawTeam, one of `@openai/codex` or `@mariozechner/pi-coding-agent`, OpenAI API key with credit).
