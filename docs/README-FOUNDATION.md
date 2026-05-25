# Pi-Agent Harness — Foundation

This is Plan 1 of 8. It establishes the Python package, the `Config` object every other
module imports, and a tested subprocess wrapper around the real `clawteam` 0.2.x CLI.

## Prerequisites

- Python 3.11+ (uv will install if missing)
- `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node 20+ and `npm`
- `tmux` (macOS: `brew install tmux`)
- ONE of:
  - `@openai/codex`: `npm install -g @openai/codex` (binary: `codex` — matches `openai-official` preset)
  - `@mariozechner/pi-coding-agent`: `npm install -g @mariozechner/pi-coding-agent` (binary: `pi`)
- An OpenAI API key (smoke test only)

## Install

```bash
cd /Users/pranavnair/Desktop/Personal/mannschaft
cp .env.example .env        # then edit .env and set OPENAI_API_KEY
uv sync --extra dev
```

## Run the unit suite (fast, no network)

```bash
uv run pytest -m "not smoke" -v
```

Expected: 29 tests pass (6 config + 10 profile + 13 client).

## Run the smoke test (real ClawTeam launch, ~1-3 minutes, a few cents)

```bash
OPENAI_API_KEY=sk-... uv run pytest -m smoke -v --timeout=360
```

This:

1. Auto-detects a coding-agent CLI (`codex` first, then `pi-coding-agent`).
2. Registers `pi-openai-reasoning` + `pi-openai-fast` profiles via `clawteam profile set`.
3. Installs a tiny 2-agent template `pi-smoke` at `<data-dir>/templates/pi-smoke.toml`.
4. Launches a team, waits for its "write-hello" task to complete.
5. Asserts every task on the board reached `completed`.
6. Tears the team down via `clawteam team cleanup`.

## How profiles are registered

ClawTeam 0.2.x profiles are single (agent CLI, model, provider) tuples — *not* TOML files
loaded from disk. To get per-role models we register **two** profiles:

| Profile name           | Model         | Roles it should be assigned to |
| ---------------------- | ------------- | ------------------------------ |
| `pi-openai-reasoning`  | `gpt-5`       | orchestrator, reviewer         |
| `pi-openai-fast`       | `gpt-5-mini`  | builder, scout                 |

Per-agent profile assignment lives in the team template (Plan 5 — topology — emits
team templates that reference these names). The committed `profiles/pi-openai.toml`
is a regenerable human-readable mirror of the spec list — useful for diffs, not
consumed by ClawTeam.

Regenerate it:

```bash
OPENAI_API_KEY=sk-placeholder uv run python -c "
from pathlib import Path
from pi_harness.config import load_config
from pi_harness.clawteam_profile import write_pi_openai_profile
write_pi_openai_profile(load_config(env_file=None), Path('profiles/pi-openai.toml'))
"
```

## What this plan exposes for downstream plans

| Symbol                                                  | Used by Plans |
| ------------------------------------------------------- | ------------- |
| `pi_harness.config.Config`, `load_config`               | all           |
| `pi_harness.clawteam.ClawTeamClient`                    | 2, 5          |
| `pi_harness.clawteam.ClawTeamClient.create_task`        | 5             |
| `pi_harness.clawteam_profile.build_profile_specs`       | 5             |
| `pi_harness.clawteam_profile.ROLE_PROFILE_MAP`          | 5             |
| `profiles/pi-openai.toml`                               | 5             |

> **Cross-plan note:** Plans 5/7's earlier drafts assumed
> `launch_team(team_toml_path, run_id) -> RunHandle`. The actual Plan 1 surface is
> `install_template(name, toml_text)` + `launch_team(template, team_name, goal,
> profile=None)` + `create_task(team, subject, owner=, blocked_by=)`. The corrected
> Plan 5 (`2026-05-25-topology-layer.md`) follows this flow already; Plan 7 consumes
> Plan 5's `Coordinator.launch(RunSpec)` rather than touching the ClawTeam client
> directly.
