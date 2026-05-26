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

## Integration / merge checklist

When merging a plan branch (`worktree-agent-...` or `feat/...`) into `main`:

1. **`uv sync --extra dev`** before re-running tests, every time `pyproject.toml`
   changed. Plain `uv sync` does NOT install `[project.optional-dependencies] dev`,
   even when its output reads like a success ("Resolved N packages / Checked N
   packages"). If you skip this step, `uv run pytest` may fall back to a pytest
   outside the project venv and surface misleading `ModuleNotFoundError`s on deps
   that ARE installed in the venv (we hit this with `aiosqlite` after Plan 2's
   merge — the test collector was the wrong pytest, not the dep that was missing).
2. **Remove parallel-dev `sys.modules` stubs.** If a plan was developed in a
   worktree alongside an active sibling plan, `tests/conftest.py` may have
   installed a `sys.modules[...]` shim for the sibling's not-yet-landed module so
   the in-progress plan could run tests in isolation. After the sibling lands, the
   stub will shadow the real module during test collection — drop it in a
   `chore(tests):` commit. Example: commit `0406e26` removed Plan 3's
   `pi_harness.trajectory` stub once Plan 2 landed.
3. **Expect a `pyproject.toml` conflict when two parallel branches both add
   deps.** Plans 2+3 happened to auto-merge cleanly because their alphabetical
   inserts fell on different lines; Plans 4+6 conflicted because both inserted
   into the same line region AND both added `openai` with different specs.
   Resolution pattern: combine the two diffs into one alphabetically-ordered
   `dependencies = [...]` block, and for any duplicated package take the
   **intersection** of the version specs (e.g. `openai>=1.0.0` ∩ `openai>=1.0,<3.0`
   = `openai>=1.0,<3.0`). Then stage the resolved file.
4. **Regenerate the lockfile.** Delete `uv.lock` and run `uv lock` once. Git's
   textual 3-way merge of parallel `uv.lock` diffs is best-effort at best — a
   clean re-resolve is the only way to guarantee coherence against the merged
   `pyproject.toml`.
5. **Run the full suite.** `uv run pytest --tb=short -q`. Reference counts after
   each plan lands: 31 (Plan 1) → 59 (+Plan 2) → 140 (+Plan 3) → 162 (+Plan 4) →
   230 (+Plan 6). Two smoke tests skip without an `OPENAI_API_KEY` in the
   pytest env; that's expected.

### Avoiding the stub-cleanup step on future parallel pairs

Item 2 above is a cost of how Plan 3 was structured, not an inherent cost of
parallel development. For the next pair of siblings developed concurrently, prefer
in order:

- **Local `typing.Protocol` over imported concrete type.** If a sibling only
  needs structural attribute access on the other's types (e.g., a `.run_id` and
  a `.corpus_refs` field), define the shape as a `Protocol` in *this* plan and
  accept a callable returning `Iterable[ThatProtocol]`. No cross-plan import, no
  stub.
- **Self-erasing stub guard, if a stub is unavoidable.** Replace
  `if pkg in sys.modules: return` with a `try: import pkg; return / except
  ImportError: pass` pattern at the top of the installer. Once the sibling lands
  on `main`, the real module satisfies the import and the stub never installs —
  no cleanup commit required.

Promote shared types to a `pi_harness/contracts/` module only if the same shape
would otherwise need to be redeclared in 3+ plans.
