# Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the Python package skeleton, environment-driven `Config`, and a tested `ClawTeamClient` subprocess wrapper that all other Pi-Agent Harness plans (Plans 2-8) import from.

**Architecture:** A `uv`-managed Python package named `pi_harness` exposes (a) a frozen `Config` dataclass that reads from `.env` and is the single source of truth for paths, model names, and the OpenAI key; (b) a `ClawTeamClient` class that shells out to the real `clawteam` 0.2.x CLI for team launch, task listing, inbox peek, completion-wait, profile registration, template install, and cleanup; and (c) `pi-openai` profile specs that pin OpenAI reasoning + fast tiers as **two** ClawTeam profiles (`pi-openai-reasoning`, `pi-openai-fast`) so per-role model assignments work the way ClawTeam expects (one profile = one agent CLI + one model). Tests use `pytest` with a `smoke` marker reserved for the one real-CLI integration test.

**Tech Stack:** Python 3.11+ (stdlib `tomllib` is required), `uv` for env/dependencies, `pytest` + `pytest-asyncio` + `pytest-timeout` for tests, `python-dotenv` for env loading, `tomli-w` for TOML emission, `clawteam==0.2.*` as a runtime dependency we shell out to. The smoke test auto-detects an installed coding-agent CLI: it tries `codex` (`@openai/codex`) first, then `pi-coding-agent` (`@mariozechner/pi-coding-agent`), and skips cleanly if neither is on `PATH`.

> **Why a rewrite over the original draft:** The original plan assumed CLI shapes like `clawteam launch --template X --name Y`, `clawteam destroy --name X --yes`, `clawteam board --json`, `clawteam profile register --path X`, and `clawteam template register --path X`. None of those match ClawTeam 0.2.0. Real verbs: `clawteam launch TEMPLATE --team Y --goal Z [--profile P]`, `clawteam team cleanup TEAM --force`, top-level `clawteam --json task list TEAM`, `clawteam profile set NAME --agent ... --model ...` (CLI-arg-driven, not file-based), and templates are registered by **dropping a TOML file at `<data-dir>/templates/<name>.toml`**. ClawTeam profiles are also single-(agent, model) pairs, so the "one profile, four roles, two models" idea in the draft is impossible — hence two profiles, with per-agent profile assignment encoded in the team template.

---

## File Structure

```
mannschaft/
  pyproject.toml                     # uv project metadata + deps + pytest config
  .python-version                    # pins Python 3.11
  .gitignore                         # ignores .venv, __pycache__, .env, build artifacts
  .env.example                       # template for required env vars
  pi_harness/
    __init__.py                      # exposes __version__ + Config re-exports
    config.py                        # Config dataclass + load_config()
    clawteam_profile.py              # PiOpenAIProfileSpec + helpers (CLI-args + doc TOML)
    clawteam/
      __init__.py                    # re-exports ClawTeamClient + exceptions
      client.py                      # ClawTeamClient subprocess wrapper
  profiles/
    pi-openai.toml                   # committed regenerable documentation TOML (both specs)
  tests/
    __init__.py                      # empty
    test_config.py                   # env loader + defaults
    test_clawteam_profile.py         # profile-spec structure + doc TOML
    test_clawteam_client.py          # mocked subprocess wrapper
    test_smoke_launch.py             # @pytest.mark.smoke real launch
  docs/
    README-FOUNDATION.md             # install + smoke-test guide
```

---

## Prerequisites

External tools the engineer must install before starting:

- **Python 3.11+** (uv will install it if missing; check with `python3 --version`)
- **uv** — Python package/env manager
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # then ensure ~/.local/bin is on PATH
  ```
- **Node 20+** with `npm` (needed by the smoke-test coding-agent CLI)
- **tmux** (ClawTeam's default backend; on macOS: `brew install tmux`)
- **git** (you presumably have it)
- **ClawTeam CLI** — installed inside the project venv via `pyproject.toml`; do NOT install globally.
- **A coding-agent CLI for the smoke test** — install ONE of:
  ```bash
  npm install -g @openai/codex                  # default; matches openai-official preset
  # OR
  npm install -g @mariozechner/pi-coding-agent
  ```
- **OpenAI API key** — needed only for the smoke test; set `OPENAI_API_KEY=sk-...` in `.env`.

Previous plans: none. This plan is the foundation.

---

## Tasks

### Task 1: Create `pyproject.toml` and pin Python

- [ ] **Step 1.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/.python-version`:
  ```
  3.11
  ```
- [ ] **Step 1.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/pyproject.toml`:
  ```toml
  [project]
  name = "pi-harness"
  version = "0.1.0"
  description = "Pi-Agent Harness — Symphony-style multi-agent orchestrator with expertise loop."
  requires-python = ">=3.11"
  license = { text = "MIT" }
  authors = [{ name = "Pranav Nair", email = "pranav.sunilnair@stengg.com" }]
  dependencies = [
    "clawteam==0.2.*",
    "python-dotenv>=1.0,<2.0",
    "tomli-w>=1.0,<2.0",
  ]

  [project.optional-dependencies]
  dev = [
    "pytest>=8.0,<9.0",
    "pytest-asyncio>=0.23,<1.0",
    "pytest-timeout>=2.3,<3.0",
  ]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["pi_harness"]

  [tool.pytest.ini_options]
  testpaths = ["tests"]
  markers = [
    "smoke: integration test that launches a real ClawTeam team (requires OPENAI_API_KEY and a coding-agent CLI).",
  ]
  addopts = "-ra --strict-markers"
  asyncio_mode = "auto"
  ```
  > **Note:** The `readme` key is intentionally omitted. The Hatchling build backend validates the readme path at build time, but the README is created in Task 11. Omitting the key keeps the bootstrap order clean. The package README is `docs/README-FOUNDATION.md` regardless; PyPI publication is not in scope for v1.
- [ ] **Step 1.3** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv sync --extra dev`
  Expected: a `.venv/` directory appears; output ends with `Installed N packages` (N >= 4) and no error.
- [ ] **Step 1.4** — Run: `uv run python -c "import sys; print(sys.version_info[:2])"`
  Expected: `(3, 11)` or higher minor (e.g. `(3, 12)`).
- [ ] **Step 1.5** — Run: `uv run python -c "import clawteam, dotenv, tomli_w, tomllib; print('ok')"`
  Expected: `ok`.
- [ ] **Step 1.6** — Commit:
  ```bash
  git add pyproject.toml .python-version uv.lock
  git commit -m "chore: bootstrap uv project with pi-harness skeleton"
  ```

---

### Task 2: Create `.gitignore` and `.env.example`

- [ ] **Step 2.1** — Replace `/Users/pranavnair/Desktop/Personal/mannschaft/.gitignore` contents with the expanded form (the file already has a minimal version from the worktree bootstrap commit):
  ```
  # Python
  __pycache__/
  *.py[cod]
  *.egg-info/
  .pytest_cache/
  .ruff_cache/
  .mypy_cache/
  build/
  dist/

  # uv / venv
  .venv/
  .python-version.local

  # env
  .env
  .env.local

  # OS
  .DS_Store

  # Editors
  .vscode/
  .idea/

  # Worktrees (kept from bootstrap commit; do not commit worktree trees)
  .worktrees/

  # Harness state (must never land in repo)
  /.pi-harness-local/
  ```
- [ ] **Step 2.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/.env.example`:
  ```
  # Copy to .env and fill in. The .env file is gitignored.

  # Required for any run that hits OpenAI (smoke test included).
  OPENAI_API_KEY=sk-replace-me

  # Model assignments. Override per environment as needed.
  PI_HARNESS_REASONING_MODEL=gpt-5
  PI_HARNESS_FAST_MODEL=gpt-5-mini

  # Storage paths. Leave unset to use defaults.
  # PI_HARNESS_CLAWTEAM_STATE_DIR=~/.clawteam
  # PI_HARNESS_CORPUS_ROOT=~/.pi-harness/corpus
  # PI_HARNESS_TRAJECTORY_DB_PATH=~/.pi-harness/trajectory.db

  # Smoke-test executor override (auto-detects codex first, then pi-coding-agent).
  # PI_HARNESS_SMOKE_EXECUTOR=codex
  ```
- [ ] **Step 2.3** — Run: `ls /Users/pranavnair/Desktop/Personal/mannschaft/.env.example && ls /Users/pranavnair/Desktop/Personal/mannschaft/.gitignore`
  Expected: both paths print, no error.
- [ ] **Step 2.4** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && git check-ignore -v -- .env 2>&1 || echo "no .env yet, ok"`
  Expected: either `no .env yet, ok` (if no .env file exists) or a line showing `.gitignore:N:.env`. Either is acceptable.
- [ ] **Step 2.5** — Commit:
  ```bash
  git add .gitignore .env.example
  git commit -m "chore: expand gitignore and add env example"
  ```

---

### Task 3: Bootstrap `pi_harness/__init__.py` with version

- [ ] **Step 3.1** — Create the directory: `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness`
- [ ] **Step 3.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/__init__.py`:
  ```python
  """Pi-Agent Harness — Symphony-style multi-agent orchestrator with expertise loop."""

  __version__ = "0.1.0"

  __all__ = ["__version__"]
  ```
- [ ] **Step 3.3** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run python -c "import pi_harness; print(pi_harness.__version__)"`
  Expected: `0.1.0`
- [ ] **Step 3.4** — Commit:
  ```bash
  git add pi_harness/__init__.py
  git commit -m "feat: bootstrap pi_harness package with version"
  ```

---

### Task 4: Write failing test for `Config` defaults

- [ ] **Step 4.1** — Create test scaffold: `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/tests`
- [ ] **Step 4.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/tests/__init__.py`:
  ```python
  ```
  (Empty file.)
- [ ] **Step 4.3** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/tests/test_config.py`:
  ```python
  """Unit tests for pi_harness.config.Config."""

  from __future__ import annotations

  import os
  from pathlib import Path

  import pytest


  def test_config_loads_required_openai_key(monkeypatch, tmp_path):
      """Config must read OPENAI_API_KEY from env."""
      from pi_harness.config import load_config

      monkeypatch.setenv("OPENAI_API_KEY", "sk-test-abc")
      monkeypatch.delenv("PI_HARNESS_REASONING_MODEL", raising=False)
      monkeypatch.delenv("PI_HARNESS_FAST_MODEL", raising=False)
      monkeypatch.delenv("PI_HARNESS_CLAWTEAM_STATE_DIR", raising=False)
      monkeypatch.delenv("PI_HARNESS_CORPUS_ROOT", raising=False)
      monkeypatch.delenv("PI_HARNESS_TRAJECTORY_DB_PATH", raising=False)

      cfg = load_config(env_file=None)

      assert cfg.openai_api_key == "sk-test-abc"


  def test_config_applies_default_paths(monkeypatch):
      """Unset path env vars resolve to documented defaults under HOME."""
      from pi_harness.config import load_config

      monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
      monkeypatch.delenv("PI_HARNESS_CLAWTEAM_STATE_DIR", raising=False)
      monkeypatch.delenv("PI_HARNESS_CORPUS_ROOT", raising=False)
      monkeypatch.delenv("PI_HARNESS_TRAJECTORY_DB_PATH", raising=False)

      cfg = load_config(env_file=None)

      home = Path(os.path.expanduser("~"))
      assert cfg.clawteam_state_dir == (home / ".clawteam").resolve(strict=False)
      assert cfg.corpus_root == (home / ".pi-harness" / "corpus").resolve(strict=False)
      assert cfg.trajectory_db_path == (home / ".pi-harness" / "trajectory.db").resolve(strict=False)


  def test_config_applies_default_models(monkeypatch):
      """Unset model env vars resolve to documented defaults."""
      from pi_harness.config import load_config

      monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
      monkeypatch.delenv("PI_HARNESS_REASONING_MODEL", raising=False)
      monkeypatch.delenv("PI_HARNESS_FAST_MODEL", raising=False)

      cfg = load_config(env_file=None)

      assert cfg.reasoning_model == "gpt-5"
      assert cfg.fast_model == "gpt-5-mini"


  def test_config_overrides_via_env(monkeypatch, tmp_path):
      """All overridable fields honor env vars."""
      from pi_harness.config import load_config

      monkeypatch.setenv("OPENAI_API_KEY", "sk-override")
      monkeypatch.setenv("PI_HARNESS_REASONING_MODEL", "gpt-5-pro")
      monkeypatch.setenv("PI_HARNESS_FAST_MODEL", "gpt-5-nano")
      monkeypatch.setenv("PI_HARNESS_CLAWTEAM_STATE_DIR", str(tmp_path / "claw"))
      monkeypatch.setenv("PI_HARNESS_CORPUS_ROOT", str(tmp_path / "corpus"))
      monkeypatch.setenv("PI_HARNESS_TRAJECTORY_DB_PATH", str(tmp_path / "traj.db"))

      cfg = load_config(env_file=None)

      assert cfg.reasoning_model == "gpt-5-pro"
      assert cfg.fast_model == "gpt-5-nano"
      assert cfg.clawteam_state_dir == (tmp_path / "claw").resolve(strict=False)
      assert cfg.corpus_root == (tmp_path / "corpus").resolve(strict=False)
      assert cfg.trajectory_db_path == (tmp_path / "traj.db").resolve(strict=False)


  def test_config_missing_key_raises(monkeypatch):
      """No OPENAI_API_KEY in env (and no .env file) must raise."""
      from pi_harness.config import load_config, ConfigError

      monkeypatch.delenv("OPENAI_API_KEY", raising=False)

      with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
          load_config(env_file=None)


  def test_config_is_frozen(monkeypatch):
      """Config dataclass must be immutable to prevent accidental mutation by callers."""
      from pi_harness.config import load_config

      monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
      cfg = load_config(env_file=None)

      with pytest.raises(Exception):
          cfg.openai_api_key = "sk-other"  # type: ignore[misc]
  ```
- [ ] **Step 4.4** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_config.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'pi_harness.config'` (or `ImportError`).

---

### Task 5: Implement `pi_harness/config.py` to satisfy Task 4 tests

- [ ] **Step 5.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/config.py`:
  ```python
  """Environment-driven configuration for the Pi-Agent Harness.

  All other modules (trajectory, corpus, topology, ...) import ``Config`` from
  here and never re-read environment variables themselves.
  """

  from __future__ import annotations

  import os
  from dataclasses import dataclass
  from pathlib import Path
  from typing import Optional

  from dotenv import load_dotenv

  __all__ = ["Config", "ConfigError", "load_config"]


  class ConfigError(RuntimeError):
      """Raised when required configuration is missing or invalid."""


  DEFAULT_REASONING_MODEL = "gpt-5"
  DEFAULT_FAST_MODEL = "gpt-5-mini"
  DEFAULT_CLAWTEAM_STATE_DIR = "~/.clawteam"
  DEFAULT_CORPUS_ROOT = "~/.pi-harness/corpus"
  DEFAULT_TRAJECTORY_DB_PATH = "~/.pi-harness/trajectory.db"


  @dataclass(frozen=True)
  class Config:
      """Frozen configuration snapshot.

      Attributes:
          openai_api_key: OpenAI API key (required).
          reasoning_model: Model assigned to orchestrator + reviewer roles.
          fast_model: Model assigned to builder + scout roles.
          clawteam_state_dir: Directory ClawTeam owns. The harness passes this to
              every ``clawteam`` invocation via ``--data-dir``; ClawTeam manages
              its contents.
          corpus_root: Root directory for the expertise corpus (Plan 3 owns it).
          trajectory_db_path: SQLite file path for the trajectory store (Plan 2).
      """

      openai_api_key: str
      reasoning_model: str
      fast_model: str
      clawteam_state_dir: Path
      corpus_root: Path
      trajectory_db_path: Path


  def _expand(path_str: str) -> Path:
      return Path(os.path.expanduser(path_str)).resolve(strict=False)


  def load_config(env_file: Optional[str | Path] = ".env") -> Config:
      """Load and validate configuration.

      Args:
          env_file: Optional path to a dotenv file. Pass ``None`` to skip loading
              (tests do this). If the file is missing it is silently ignored.

      Returns:
          A frozen :class:`Config`.

      Raises:
          ConfigError: If ``OPENAI_API_KEY`` is unset.
      """
      if env_file is not None:
          env_path = Path(env_file)
          if env_path.exists():
              load_dotenv(env_path, override=False)

      api_key = os.environ.get("OPENAI_API_KEY", "").strip()
      if not api_key:
          raise ConfigError(
              "OPENAI_API_KEY is required. Set it in the environment or in a .env file."
          )

      return Config(
          openai_api_key=api_key,
          reasoning_model=os.environ.get(
              "PI_HARNESS_REASONING_MODEL", DEFAULT_REASONING_MODEL
          ),
          fast_model=os.environ.get(
              "PI_HARNESS_FAST_MODEL", DEFAULT_FAST_MODEL
          ),
          clawteam_state_dir=_expand(
              os.environ.get("PI_HARNESS_CLAWTEAM_STATE_DIR", DEFAULT_CLAWTEAM_STATE_DIR)
          ),
          corpus_root=_expand(
              os.environ.get("PI_HARNESS_CORPUS_ROOT", DEFAULT_CORPUS_ROOT)
          ),
          trajectory_db_path=_expand(
              os.environ.get("PI_HARNESS_TRAJECTORY_DB_PATH", DEFAULT_TRAJECTORY_DB_PATH)
          ),
      )
  ```
- [ ] **Step 5.2** — Update `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/__init__.py` to also re-export `Config`:
  ```python
  """Pi-Agent Harness — Symphony-style multi-agent orchestrator with expertise loop."""

  from pi_harness.config import Config, ConfigError, load_config

  __version__ = "0.1.0"

  __all__ = ["__version__", "Config", "ConfigError", "load_config"]
  ```
- [ ] **Step 5.3** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_config.py -v`
  Expected: `6 passed`.
- [ ] **Step 5.4** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run python -c "from pi_harness import Config, load_config; print(Config.__name__)"`
  Expected: `Config`
- [ ] **Step 5.5** — Commit:
  ```bash
  git add pi_harness/config.py pi_harness/__init__.py tests/__init__.py tests/test_config.py
  git commit -m "feat: add frozen Config dataclass with env loader"
  ```

---

### Task 6: Write failing tests for `clawteam_profile` (two-profile spec)

ClawTeam profiles are single (agent CLI, model, provider) tuples registered via `clawteam profile set NAME --agent ... --model ... --api-key-env ...`. To pin the reasoning tier to orchestrator/reviewer roles and the fast tier to builder/scout roles, we register **two** profiles and let the team template assign one per agent. The module exposes:

- `PROFILE_NAME_REASONING = "pi-openai-reasoning"`, `PROFILE_NAME_FAST = "pi-openai-fast"`
- `ProfileSpec` dataclass: the data needed to call `clawteam profile set`
- `build_profile_specs(config) -> list[ProfileSpec]` → two specs
- `generate_pi_openai_profile(config) -> str` → human-readable TOML (committed at `profiles/pi-openai.toml`) for documentation + diffing; not consumed by ClawTeam directly
- `write_pi_openai_profile(config, target) -> Path`

- [ ] **Step 6.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/tests/test_clawteam_profile.py`:
  ```python
  """Unit tests for pi_harness.clawteam_profile."""

  from __future__ import annotations

  import tomllib

  import pytest


  @pytest.fixture
  def cfg(monkeypatch):
      """Build a Config from a known env."""
      from pi_harness.config import load_config

      monkeypatch.setenv("OPENAI_API_KEY", "sk-profile-test")
      monkeypatch.setenv("PI_HARNESS_REASONING_MODEL", "gpt-5")
      monkeypatch.setenv("PI_HARNESS_FAST_MODEL", "gpt-5-mini")
      return load_config(env_file=None)


  def test_build_profile_specs_returns_two_specs(cfg):
      from pi_harness.clawteam_profile import build_profile_specs

      specs = build_profile_specs(cfg)

      assert len(specs) == 2
      names = {s.name for s in specs}
      assert names == {"pi-openai-reasoning", "pi-openai-fast"}


  def test_reasoning_spec_pins_reasoning_model(cfg):
      from pi_harness.clawteam_profile import build_profile_specs

      specs = {s.name: s for s in build_profile_specs(cfg)}

      reasoning = specs["pi-openai-reasoning"]
      assert reasoning.model == "gpt-5"
      assert reasoning.api_key_env == "OPENAI_API_KEY"
      assert reasoning.tier == "reasoning"


  def test_fast_spec_pins_fast_model(cfg):
      from pi_harness.clawteam_profile import build_profile_specs

      specs = {s.name: s for s in build_profile_specs(cfg)}

      fast = specs["pi-openai-fast"]
      assert fast.model == "gpt-5-mini"
      assert fast.api_key_env == "OPENAI_API_KEY"
      assert fast.tier == "fast"


  def test_spec_to_set_args_emits_clawteam_profile_set_flags(cfg):
      """ProfileSpec.to_set_args returns argv-style flags for `clawteam profile set`."""
      from pi_harness.clawteam_profile import build_profile_specs

      specs = {s.name: s for s in build_profile_specs(cfg)}
      args = specs["pi-openai-reasoning"].to_set_args()

      # The profile name is the first positional arg; the rest are flags.
      assert args[0] == "pi-openai-reasoning"
      assert "--agent" in args
      assert "--model" in args
      assert "gpt-5" in args
      assert "--api-key-env" in args
      assert "OPENAI_API_KEY" in args


  def test_profile_doc_toml_is_parseable(cfg):
      """generate_pi_openai_profile returns a TOML string parseable by tomllib."""
      from pi_harness.clawteam_profile import generate_pi_openai_profile

      toml_text = generate_pi_openai_profile(cfg)
      parsed = tomllib.loads(toml_text)

      assert isinstance(parsed, dict)


  def test_profile_doc_toml_lists_both_profiles(cfg):
      """The doc TOML must enumerate both profile specs with their model assignments."""
      from pi_harness.clawteam_profile import generate_pi_openai_profile

      parsed = tomllib.loads(generate_pi_openai_profile(cfg))

      assert "profiles" in parsed
      by_name = {p["name"]: p for p in parsed["profiles"]}
      assert by_name["pi-openai-reasoning"]["model"] == "gpt-5"
      assert by_name["pi-openai-fast"]["model"] == "gpt-5-mini"
      assert by_name["pi-openai-reasoning"]["api_key_env"] == "OPENAI_API_KEY"


  def test_profile_doc_toml_does_not_embed_secret(cfg):
      """The TOML must reference the env var, never the literal key value."""
      from pi_harness.clawteam_profile import generate_pi_openai_profile

      toml_text = generate_pi_openai_profile(cfg)

      assert "sk-profile-test" not in toml_text


  def test_role_mapping_maps_reasoning_to_orchestrator_and_reviewer(cfg):
      from pi_harness.clawteam_profile import ROLE_PROFILE_MAP

      assert ROLE_PROFILE_MAP["orchestrator"] == "pi-openai-reasoning"
      assert ROLE_PROFILE_MAP["reviewer"] == "pi-openai-reasoning"


  def test_role_mapping_maps_fast_to_builder_and_scout(cfg):
      from pi_harness.clawteam_profile import ROLE_PROFILE_MAP

      assert ROLE_PROFILE_MAP["builder"] == "pi-openai-fast"
      assert ROLE_PROFILE_MAP["scout"] == "pi-openai-fast"


  def test_write_pi_openai_profile_writes_to_disk(cfg, tmp_path):
      from pi_harness.clawteam_profile import write_pi_openai_profile

      target = tmp_path / "pi-openai.toml"
      written = write_pi_openai_profile(cfg, target)

      assert written == target
      assert target.exists()
      parsed = tomllib.loads(target.read_text())
      assert {p["name"] for p in parsed["profiles"]} == {
          "pi-openai-reasoning",
          "pi-openai-fast",
      }
  ```
- [ ] **Step 6.2** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_clawteam_profile.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'pi_harness.clawteam_profile'`.

---

### Task 7: Implement `pi_harness/clawteam_profile.py`

- [ ] **Step 7.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/clawteam_profile.py`:
  ```python
  """Pi-OpenAI ClawTeam profile specs.

  ClawTeam profiles (v0.2.x) are single (agent CLI, model, provider) tuples
  registered via ``clawteam profile set NAME --agent ... --model ...``. To pin
  reasoning vs. fast model tiers to different role groups, the harness registers
  **two** profiles:

  - ``pi-openai-reasoning`` — heavier tier; mapped to orchestrator + reviewer
  - ``pi-openai-fast``       — cheap tier; mapped to builder + scout

  Per-role profile assignment lives in the team template (see Plan 5). This
  module just owns the spec data + a regenerable documentation TOML committed at
  ``profiles/pi-openai.toml``.
  """

  from __future__ import annotations

  from dataclasses import dataclass
  from pathlib import Path
  from typing import Dict, List, Optional

  import tomli_w

  from pi_harness.config import Config

  __all__ = [
      "PROFILE_NAME_REASONING",
      "PROFILE_NAME_FAST",
      "DEFAULT_AGENT_CLI",
      "ROLE_PROFILE_MAP",
      "ProfileSpec",
      "build_profile_specs",
      "generate_pi_openai_profile",
      "write_pi_openai_profile",
  ]

  PROFILE_NAME_REASONING = "pi-openai-reasoning"
  PROFILE_NAME_FAST = "pi-openai-fast"

  # ClawTeam's `--agent` flag accepts one of claude/codex/gemini/kimi/nanobot.
  # We default to `codex` (the official OpenAI Codex CLI) for both profiles,
  # because the OpenAI key flow matches the built-in `openai-official` preset.
  # Override via ProfileSpec(command=...) to use a different binary (e.g. the
  # smoke test optionally swaps to `pi-coding-agent`).
  DEFAULT_AGENT_CLI = "codex"

  ROLE_PROFILE_MAP: Dict[str, str] = {
      "orchestrator": PROFILE_NAME_REASONING,
      "reviewer": PROFILE_NAME_REASONING,
      "builder": PROFILE_NAME_FAST,
      "scout": PROFILE_NAME_FAST,
  }


  @dataclass(frozen=True)
  class ProfileSpec:
      """Everything needed to register a single ClawTeam profile.

      Attributes:
          name: Profile name (positional arg to ``clawteam profile set``).
          agent: One of ClawTeam's known agent-CLI names (``--agent``).
          model: Model identifier passed to the agent CLI (``--model``).
          api_key_env: Source env var holding the API key (``--api-key-env``).
          tier: ``"reasoning"`` or ``"fast"`` — documentation only.
          description: Human-readable description (``--description``).
          command: Override the agent command (e.g. ``"pi-coding-agent"``).
          base_url: Optional provider base URL (``--base-url``).
      """

      name: str
      agent: str
      model: str
      api_key_env: str
      tier: str
      description: str
      command: Optional[str] = None
      base_url: Optional[str] = None

      def to_set_args(self) -> List[str]:
          """Return positional + flag args for ``clawteam profile set``.

          The full subprocess call is ``["clawteam", "profile", "set", *args]``.
          """
          args: List[str] = [
              self.name,
              "--agent", self.agent,
              "--model", self.model,
              "--api-key-env", self.api_key_env,
              "--description", self.description,
          ]
          if self.command is not None:
              args.extend(["--command", self.command])
          if self.base_url is not None:
              args.extend(["--base-url", self.base_url])
          return args


  def build_profile_specs(config: Config) -> List[ProfileSpec]:
      """Build the two profile specs from a Config snapshot."""
      return [
          ProfileSpec(
              name=PROFILE_NAME_REASONING,
              agent=DEFAULT_AGENT_CLI,
              model=config.reasoning_model,
              api_key_env="OPENAI_API_KEY",
              tier="reasoning",
              description=(
                  "Pi-Agent Harness reasoning tier — used by orchestrator + reviewer roles."
              ),
          ),
          ProfileSpec(
              name=PROFILE_NAME_FAST,
              agent=DEFAULT_AGENT_CLI,
              model=config.fast_model,
              api_key_env="OPENAI_API_KEY",
              tier="fast",
              description=(
                  "Pi-Agent Harness fast tier — used by builder + scout roles."
              ),
          ),
      ]


  def _spec_to_doc_dict(spec: ProfileSpec) -> dict:
      d = {
          "name": spec.name,
          "agent": spec.agent,
          "model": spec.model,
          "api_key_env": spec.api_key_env,
          "tier": spec.tier,
          "description": spec.description,
      }
      if spec.command is not None:
          d["command"] = spec.command
      if spec.base_url is not None:
          d["base_url"] = spec.base_url
      return d


  def generate_pi_openai_profile(config: Config) -> str:
      """Return a documentation-only TOML describing both profile specs.

      This file is *not* consumed by ClawTeam directly (ClawTeam registers
      profiles via ``clawteam profile set`` CLI args). It exists so the intended
      profile shapes are reviewable in git and regenerable from
      :class:`Config`.
      """
      doc = {
          "documentation": {
              "note": (
                  "This TOML is a human-readable mirror of "
                  "pi_harness.clawteam_profile.build_profile_specs(config). "
                  "Profiles are actually registered with `clawteam profile set`. "
                  "Regenerate via the snippet in docs/README-FOUNDATION.md."
              ),
          },
          "role_profile_map": dict(ROLE_PROFILE_MAP),
          "profiles": [_spec_to_doc_dict(s) for s in build_profile_specs(config)],
      }
      return tomli_w.dumps(doc)


  def write_pi_openai_profile(config: Config, target: Path) -> Path:
      """Write the documentation TOML to ``target`` and return the path."""
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(generate_pi_openai_profile(config))
      return target
  ```
- [ ] **Step 7.2** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_clawteam_profile.py -v`
  Expected: `10 passed`.
- [ ] **Step 7.3** — Generate the committed copy at `profiles/pi-openai.toml`. Run:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && \
  OPENAI_API_KEY=sk-placeholder-for-codegen uv run python -c "
  from pathlib import Path
  from pi_harness.config import load_config
  from pi_harness.clawteam_profile import write_pi_openai_profile
  cfg = load_config(env_file=None)
  out = write_pi_openai_profile(cfg, Path('profiles/pi-openai.toml'))
  print(f'wrote {out}')
  "
  ```
  Expected: `wrote /Users/pranavnair/Desktop/Personal/mannschaft/profiles/pi-openai.toml`.
- [ ] **Step 7.4** — Verify the file:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run python -c "
  import tomllib
  data = tomllib.loads(open('profiles/pi-openai.toml').read())
  names = {p['name'] for p in data['profiles']}
  assert names == {'pi-openai-reasoning', 'pi-openai-fast'}, names
  models = {p['name']: p['model'] for p in data['profiles']}
  assert models['pi-openai-reasoning'] == 'gpt-5'
  assert models['pi-openai-fast'] == 'gpt-5-mini'
  print('ok')
  "
  ```
  Expected: `ok`.
- [ ] **Step 7.5** — Commit:
  ```bash
  git add pi_harness/clawteam_profile.py profiles/pi-openai.toml tests/test_clawteam_profile.py
  git commit -m "feat: add pi-openai ClawTeam profile specs (reasoning + fast tiers)"
  ```

---

### Task 8: Write failing tests for `ClawTeamClient` (mocked subprocess)

`ClawTeamClient` is a subprocess wrapper. Each method maps to one real `clawteam` invocation:

| Wrapper method | Real CLI |
|---|---|
| `launch_team(template, team, goal, profile=None)` | `clawteam --data-dir D launch TEMPLATE --team Y --goal Z [--profile P]` |
| `list_tasks(team)` | `clawteam --data-dir D --json task list TEAM` |
| `peek_inbox(team, agent=None, limit=10)` | `clawteam --data-dir D --json inbox peek TEAM [--agent A] --limit N` |
| `register_profile(spec)` | `clawteam --data-dir D profile set NAME --agent ... --model ... ...` |
| `install_template(name, toml_text)` | (writes `<data-dir>/templates/<name>.toml`; no CLI call) |
| `cleanup_team(team)` | `clawteam --data-dir D team cleanup TEAM --force` |
| `wait_for_completion(team, timeout, poll_interval)` | (polls `list_tasks`; raises on terminal failure / timeout) |

The state-dir is passed via the top-level `--data-dir` flag (not the `CLAWTEAM_STATE_DIR` env var) — that's what real ClawTeam 0.2.0 supports.

- [ ] **Step 8.1** — Create the clawteam sub-package directory: `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/clawteam`
- [ ] **Step 8.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/tests/test_clawteam_client.py`:
  ```python
  """Unit tests for pi_harness.clawteam.client.ClawTeamClient.

  All subprocess calls are mocked. The real-CLI integration lives in
  tests/test_smoke_launch.py.
  """

  from __future__ import annotations

  import json
  import subprocess
  from unittest.mock import MagicMock, patch

  import pytest


  @pytest.fixture
  def cfg(monkeypatch, tmp_path):
      from pi_harness.config import load_config

      monkeypatch.setenv("OPENAI_API_KEY", "sk-client-test")
      monkeypatch.setenv("PI_HARNESS_CLAWTEAM_STATE_DIR", str(tmp_path / "claw"))
      return load_config(env_file=None)


  def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
      cp = MagicMock(spec=subprocess.CompletedProcess)
      cp.stdout = stdout
      cp.stderr = stderr
      cp.returncode = returncode
      return cp


  def test_launch_team_invokes_clawteam_launch(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stdout="launched")
          client.launch_team(
              template="hello-team",
              team_name="my-team",
              goal="ship it",
              profile="pi-openai-fast",
          )

      assert mock_run.called
      cmd = mock_run.call_args.args[0]
      assert cmd[0] == "clawteam"
      assert "--data-dir" in cmd
      assert "launch" in cmd
      # Template is positional, immediately after `launch`
      launch_idx = cmd.index("launch")
      assert cmd[launch_idx + 1] == "hello-team"
      assert "--team" in cmd and "my-team" in cmd
      assert "--goal" in cmd and "ship it" in cmd
      assert "--profile" in cmd and "pi-openai-fast" in cmd


  def test_launch_team_without_profile_omits_flag(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed()
          client.launch_team(
              template="hello-team", team_name="my-team", goal="x"
          )

      cmd = mock_run.call_args.args[0]
      assert "--profile" not in cmd


  def test_launch_team_raises_on_nonzero_exit(cfg):
      from pi_harness.clawteam.client import ClawTeamClient, ClawTeamCLIError

      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stderr="boom", returncode=2)

          with pytest.raises(ClawTeamCLIError, match="boom"):
              client.launch_team(template="x", team_name="y", goal="z")


  def test_list_tasks_parses_json(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      payload = [
          {"task_id": "t1", "title": "build", "status": "completed"},
          {"task_id": "t2", "title": "test", "status": "in_progress"},
      ]
      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stdout=json.dumps(payload))
          tasks = client.list_tasks("my-team")

      assert tasks == payload
      cmd = mock_run.call_args.args[0]
      assert cmd[0] == "clawteam"
      assert "--json" in cmd
      task_idx = cmd.index("task")
      assert cmd[task_idx:task_idx + 3] == ["task", "list", "my-team"]


  def test_peek_inbox_parses_json(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      payload = [{"from": "leader", "to": "builder", "body": "hi"}]
      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stdout=json.dumps(payload))
          messages = client.peek_inbox("my-team", agent="builder", limit=5)

      assert messages == payload
      cmd = mock_run.call_args.args[0]
      assert "--json" in cmd
      inbox_idx = cmd.index("inbox")
      assert cmd[inbox_idx:inbox_idx + 3] == ["inbox", "peek", "my-team"]
      assert "--agent" in cmd and "builder" in cmd
      assert "--limit" in cmd and "5" in cmd


  def test_register_profile_invokes_profile_set(cfg):
      from pi_harness.clawteam.client import ClawTeamClient
      from pi_harness.clawteam_profile import build_profile_specs

      client = ClawTeamClient(cfg)
      specs = build_profile_specs(cfg)
      reasoning = next(s for s in specs if s.name == "pi-openai-reasoning")

      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed()
          client.register_profile(reasoning)

      cmd = mock_run.call_args.args[0]
      assert "profile" in cmd and "set" in cmd
      assert "pi-openai-reasoning" in cmd
      assert "--model" in cmd and "gpt-5" in cmd
      assert "--api-key-env" in cmd and "OPENAI_API_KEY" in cmd


  def test_install_template_writes_file_under_data_dir(cfg):
      """install_template writes <data-dir>/templates/<name>.toml without shelling out."""
      from pi_harness.clawteam.client import ClawTeamClient

      client = ClawTeamClient(cfg)
      toml_text = '[template]\nname = "pi-smoke"\n'

      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          target = client.install_template("pi-smoke", toml_text)

      assert not mock_run.called, "install_template must not shell out"
      assert target == cfg.clawteam_state_dir / "templates" / "pi-smoke.toml"
      assert target.exists()
      assert target.read_text() == toml_text


  def test_cleanup_team_invokes_team_cleanup_force(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stdout="ok")
          client.cleanup_team("my-team")

      cmd = mock_run.call_args.args[0]
      cleanup_idx = cmd.index("cleanup")
      assert cmd[cleanup_idx - 1] == "team"
      assert cmd[cleanup_idx + 1] == "my-team"
      assert "--force" in cmd


  def test_wait_for_completion_returns_when_all_done(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      done = [
          {"task_id": "t1", "status": "completed"},
          {"task_id": "t2", "status": "completed"},
      ]
      client = ClawTeamClient(cfg)
      with patch.object(ClawTeamClient, "list_tasks", return_value=done):
          result = client.wait_for_completion("my-team", timeout=2.0, poll_interval=0.01)

      assert result is True


  def test_wait_for_completion_times_out(cfg):
      from pi_harness.clawteam.client import ClawTeamClient, ClawTeamTimeout

      pending = [{"task_id": "t1", "status": "in_progress"}]
      client = ClawTeamClient(cfg)
      with patch.object(ClawTeamClient, "list_tasks", return_value=pending):
          with pytest.raises(ClawTeamTimeout):
              client.wait_for_completion("my-team", timeout=0.05, poll_interval=0.01)


  def test_wait_for_completion_fails_on_failed_task(cfg):
      from pi_harness.clawteam.client import ClawTeamClient, ClawTeamRunFailure

      mixed = [
          {"task_id": "t1", "status": "completed"},
          {"task_id": "t2", "status": "failed"},
      ]
      client = ClawTeamClient(cfg)
      with patch.object(ClawTeamClient, "list_tasks", return_value=mixed):
          with pytest.raises(ClawTeamRunFailure, match="t2"):
              client.wait_for_completion("my-team", timeout=1.0, poll_interval=0.01)


  def test_client_passes_data_dir_top_level(cfg):
      """Every invocation must pass --data-dir before the subcommand."""
      from pi_harness.clawteam.client import ClawTeamClient

      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stdout="[]")
          client.list_tasks("my-team")

      cmd = mock_run.call_args.args[0]
      # --data-dir must come before any subcommand
      data_idx = cmd.index("--data-dir")
      task_idx = cmd.index("task")
      assert data_idx < task_idx
      assert cmd[data_idx + 1] == str(cfg.clawteam_state_dir)


  def test_client_reexport_from_subpackage(cfg):
      """pi_harness.clawteam re-exports ClawTeamClient for ergonomic import."""
      from pi_harness.clawteam import ClawTeamClient as Reexport
      from pi_harness.clawteam.client import ClawTeamClient

      assert Reexport is ClawTeamClient
  ```
- [ ] **Step 8.3** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_clawteam_client.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'pi_harness.clawteam'`.

---

### Task 9: Implement `pi_harness/clawteam/client.py` and the sub-package init

- [ ] **Step 9.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/clawteam/__init__.py`:
  ```python
  """Subprocess-based wrapper around the ``clawteam`` CLI.

  Plans 2, 5, and 7 import ``ClawTeamClient`` (and the typed exceptions) from
  this package.
  """

  from pi_harness.clawteam.client import (
      ClawTeamCLIError,
      ClawTeamClient,
      ClawTeamRunFailure,
      ClawTeamTimeout,
      TERMINAL_STATUSES,
      FAILURE_STATUSES,
  )

  __all__ = [
      "ClawTeamClient",
      "ClawTeamCLIError",
      "ClawTeamRunFailure",
      "ClawTeamTimeout",
      "TERMINAL_STATUSES",
      "FAILURE_STATUSES",
  ]
  ```
- [ ] **Step 9.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/clawteam/client.py`:
  ```python
  """Thin subprocess wrapper over the real ``clawteam`` 0.2.x CLI.

  Each public method shells out to exactly one ``clawteam`` invocation (with the
  exception of ``install_template``, which writes a TOML file under the data
  dir, because ClawTeam has no template-registration verb).

  The top-level ``--data-dir`` flag from ``Config.clawteam_state_dir`` is
  injected on every call so multiple harness instances can sandbox state.
  """

  from __future__ import annotations

  import json
  import os
  import subprocess
  import time
  from dataclasses import dataclass
  from pathlib import Path
  from typing import Any, List, Mapping, Optional, Sequence

  from pi_harness.clawteam_profile import ProfileSpec
  from pi_harness.config import Config

  __all__ = [
      "ClawTeamClient",
      "ClawTeamCLIError",
      "ClawTeamTimeout",
      "ClawTeamRunFailure",
      "TERMINAL_STATUSES",
      "FAILURE_STATUSES",
  ]

  # ClawTeam task statuses (TaskList output). The harness treats anything not in
  # TERMINAL_STATUSES as "still running".
  TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
  FAILURE_STATUSES = frozenset({"failed", "cancelled"})


  class ClawTeamCLIError(RuntimeError):
      """Raised when the ClawTeam CLI exits with a non-zero status."""

      def __init__(self, command: Sequence[str], returncode: int, stderr: str) -> None:
          self.command = list(command)
          self.returncode = returncode
          self.stderr = stderr
          super().__init__(
              f"clawteam command {self.command!r} exited {returncode}: {stderr.strip()}"
          )


  class ClawTeamTimeout(TimeoutError):
      """Raised when ``wait_for_completion`` exceeds the deadline."""


  class ClawTeamRunFailure(RuntimeError):
      """Raised when ``wait_for_completion`` observes a failed task."""


  @dataclass
  class ClawTeamClient:
      """Wrapper around the ``clawteam`` 0.2.x CLI.

      Args:
          config: Project :class:`Config`. ``clawteam_state_dir`` is passed via
              ``--data-dir`` on every call; the OpenAI key is forwarded via the
              subprocess env.
          binary: Override the CLI binary name (handy for tests / pinned installs).
      """

      config: Config
      binary: str = "clawteam"

      def _env(self) -> dict[str, str]:
          env = dict(os.environ)
          env["OPENAI_API_KEY"] = self.config.openai_api_key
          return env

      def _base_args(self, *, json_output: bool = False) -> List[str]:
          """Top-level clawteam args (binary + global flags) before any subcommand."""
          args: List[str] = [self.binary, "--data-dir", str(self.config.clawteam_state_dir)]
          if json_output:
              args.append("--json")
          return args

      def _run(
          self,
          subcommand: Sequence[str],
          *,
          json_output: bool = False,
          check: bool = True,
      ) -> subprocess.CompletedProcess:
          cmd = [*self._base_args(json_output=json_output), *subcommand]
          result = subprocess.run(
              cmd,
              capture_output=True,
              text=True,
              env=self._env(),
              check=False,
          )
          if check and result.returncode != 0:
              raise ClawTeamCLIError(cmd, result.returncode, result.stderr or result.stdout)
          return result

      # ---- team lifecycle ------------------------------------------------- #

      def launch_team(
          self,
          template: str,
          team_name: str,
          goal: str,
          profile: Optional[str] = None,
      ) -> subprocess.CompletedProcess:
          """Spawn a new ClawTeam team from a template.

          Real invocation: ``clawteam --data-dir D launch TEMPLATE --team Y --goal Z [--profile P]``
          """
          sub: List[str] = [
              "launch", template,
              "--team", team_name,
              "--goal", goal,
          ]
          if profile is not None:
              sub.extend(["--profile", profile])
          return self._run(sub)

      def cleanup_team(self, team_name: str) -> subprocess.CompletedProcess:
          """Destroy ``team_name`` and free its worktrees.

          Real invocation: ``clawteam --data-dir D team cleanup TEAM --force``
          """
          return self._run(["team", "cleanup", team_name, "--force"])

      # ---- read state ----------------------------------------------------- #

      def list_tasks(self, team_name: str) -> List[Mapping[str, Any]]:
          """Return the task board for ``team_name`` as a list of dicts.

          Real invocation: ``clawteam --data-dir D --json task list TEAM``
          """
          result = self._run(["task", "list", team_name], json_output=True)
          payload = json.loads(result.stdout or "[]")
          if not isinstance(payload, list):
              raise ClawTeamCLIError(
                  [*self._base_args(json_output=True), "task", "list", team_name],
                  0,
                  f"expected JSON list, got {type(payload).__name__}",
              )
          return payload

      def peek_inbox(
          self,
          team_name: str,
          agent: Optional[str] = None,
          limit: int = 10,
      ) -> List[Mapping[str, Any]]:
          """Peek at the inbox of ``agent`` inside ``team_name`` (non-destructive).

          Real invocation: ``clawteam --data-dir D --json inbox peek TEAM [--agent A] --limit N``
          """
          sub: List[str] = ["inbox", "peek", team_name, "--limit", str(limit)]
          if agent is not None:
              sub.extend(["--agent", agent])
          result = self._run(sub, json_output=True)
          payload = json.loads(result.stdout or "[]")
          if not isinstance(payload, list):
              raise ClawTeamCLIError(
                  [*self._base_args(json_output=True), *sub],
                  0,
                  f"expected JSON list, got {type(payload).__name__}",
              )
          return payload

      # ---- profile + template setup -------------------------------------- #

      def register_profile(self, spec: ProfileSpec) -> subprocess.CompletedProcess:
          """Create or update a ClawTeam profile from a :class:`ProfileSpec`.

          Real invocation: ``clawteam --data-dir D profile set NAME --agent ... --model ... ...``
          """
          return self._run(["profile", "set", *spec.to_set_args()])

      def install_template(self, name: str, toml_text: str) -> Path:
          """Drop a user-template TOML at ``<data-dir>/templates/<name>.toml``.

          ClawTeam has no CLI verb to register templates — user templates are
          loaded automatically from the templates dir. Returns the target path.
          """
          templates_dir = self.config.clawteam_state_dir / "templates"
          templates_dir.mkdir(parents=True, exist_ok=True)
          target = templates_dir / f"{name}.toml"
          target.write_text(toml_text)
          return target

      # ---- completion polling -------------------------------------------- #

      def wait_for_completion(
          self,
          team_name: str,
          timeout: float,
          poll_interval: float = 5.0,
      ) -> bool:
          """Block until every task on the board reaches a terminal status.

          Returns:
              ``True`` if all tasks finished cleanly within ``timeout``.

          Raises:
              ClawTeamRunFailure: If any task reaches a failure status.
              ClawTeamTimeout: If ``timeout`` elapses before all tasks finish.
          """
          deadline = time.monotonic() + timeout
          while True:
              tasks = self.list_tasks(team_name)
              if tasks:
                  failed = [t for t in tasks if t.get("status") in FAILURE_STATUSES]
                  if failed:
                      failed_ids = ", ".join(
                          str(t.get("task_id", t.get("id", "?"))) for t in failed
                      )
                      raise ClawTeamRunFailure(
                          f"team={team_name!r} task(s) failed: {failed_ids}"
                      )
                  if all(t.get("status") in TERMINAL_STATUSES for t in tasks):
                      return True
              if time.monotonic() >= deadline:
                  raise ClawTeamTimeout(
                      f"team={team_name!r} did not finish within {timeout:.1f}s"
                  )
              time.sleep(poll_interval)
  ```
- [ ] **Step 9.3** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_clawteam_client.py -v`
  Expected: `13 passed`.
- [ ] **Step 9.4** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest -m "not smoke" -v`
  Expected: all 29 tests pass (`6 config + 10 profile + 13 client = 29`).
- [ ] **Step 9.5** — Commit:
  ```bash
  git add pi_harness/clawteam/__init__.py pi_harness/clawteam/client.py tests/test_clawteam_client.py
  git commit -m "feat: add ClawTeamClient subprocess wrapper for clawteam 0.2.x CLI"
  ```

---

### Task 10: Smoke test — real ClawTeam launch with a coding-agent CLI

This task uses the real `clawteam` 0.2.x CLI to:

1. Pick an available coding-agent CLI (`codex` preferred, falls back to `pi-coding-agent`).
2. Register `pi-openai-reasoning` + `pi-openai-fast` profiles via `client.register_profile`.
3. Install a tiny 2-agent `pi-smoke` template (leader + builder) via `client.install_template`.
4. Launch the team, poll until completion, then cleanup.

It runs only under `pytest -m smoke` so unit runs stay fast and free.

- [ ] **Step 10.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/tests/test_smoke_launch.py`:
  ```python
  """Smoke test: launch a real 2-agent ClawTeam with a coding-agent CLI.

  Skipped by default. To run:

      OPENAI_API_KEY=sk-... uv run pytest -m smoke -v --timeout=360

  Prerequisites:
      - clawteam CLI installed (via `uv sync`)
      - tmux installed (`brew install tmux` on macOS)
      - ONE of:
            npm install -g @openai/codex                  (preferred; default executor)
            npm install -g @mariozechner/pi-coding-agent  (alternative)
      - OPENAI_API_KEY exported (must start with `sk-`)
  """

  from __future__ import annotations

  import os
  import shutil
  import textwrap
  import time
  import uuid
  from dataclasses import replace

  import pytest

  pytestmark = pytest.mark.smoke


  def _detect_executor() -> str:
      """Pick a coding-agent CLI: respect PI_HARNESS_SMOKE_EXECUTOR, else codex, else pi-coding-agent."""
      override = os.environ.get("PI_HARNESS_SMOKE_EXECUTOR", "").strip()
      candidates = [override] if override else ["codex", "pi-coding-agent"]
      for cand in candidates:
          if cand and shutil.which(cand):
              return cand
      pytest.skip(
          "No coding-agent CLI found on PATH. Install one:\n"
          "  npm install -g @openai/codex\n"
          "  npm install -g @mariozechner/pi-coding-agent"
      )


  def _which_or_skip(binary: str) -> str:
      path = shutil.which(binary)
      if not path:
          pytest.skip(f"required binary {binary!r} not on PATH")
      return path


  @pytest.fixture(scope="module")
  def monkeypatch_module():
      """Module-scoped monkeypatch (pytest's default is function-scoped)."""
      from _pytest.monkeypatch import MonkeyPatch

      mp = MonkeyPatch()
      yield mp
      mp.undo()


  @pytest.fixture(scope="module")
  def real_cfg(tmp_path_factory, monkeypatch_module):
      """A Config that points at a sandboxed ClawTeam state dir."""
      from pi_harness.config import load_config

      if not os.environ.get("OPENAI_API_KEY", "").startswith("sk-"):
          pytest.skip("OPENAI_API_KEY not set (or not sk-*); smoke test skipped")

      _which_or_skip("clawteam")
      _which_or_skip("tmux")

      state_dir = tmp_path_factory.mktemp("clawteam-state")
      monkeypatch_module.setenv("PI_HARNESS_CLAWTEAM_STATE_DIR", str(state_dir))
      return load_config(env_file=None)


  def test_smoke_launch_completes(real_cfg):
      """End-to-end: register profiles, install template, launch, wait, cleanup."""
      from pi_harness.clawteam import ClawTeamClient
      from pi_harness.clawteam_profile import build_profile_specs

      executor = _detect_executor()
      client = ClawTeamClient(real_cfg)

      # 1. Register both profiles, overriding `command` to the detected executor.
      for spec in build_profile_specs(real_cfg):
          spec = replace(spec, command=executor)
          client.register_profile(spec)

      # 2. Install a tiny 2-agent template.
      template_toml = textwrap.dedent(f"""
          [template]
          name = "pi-smoke"
          description = "Two-agent smoke template for pi-harness foundation tests."
          command = ["{executor}"]
          backend = "tmux"

          [template.leader]
          name = "leader"
          type = "orchestrator"
          task = '''You are the leader. Create exactly one task assigned to builder titled "write-hello" with this body:
          "Write a file named hello.txt at the worktree root containing the single word HELLO. Then mark this task completed."
          Use: clawteam task create {{team_name}} --title write-hello --owner builder --body "<above>"
          Then poll `clawteam task list {{team_name}}` every 15 seconds. When the builder task is completed, exit.
          Do not create any other tasks. Do not modify any files yourself.'''

          [[template.agents]]
          name = "builder"
          type = "builder"
          task = '''You are the builder. Wait for a task assigned to you. When you receive "write-hello", create hello.txt at the
          worktree root with the single word HELLO and nothing else. Then mark the task completed via
          `clawteam task update {{team_name}} <task_id> --status completed`. Exit immediately after.'''
      """).strip() + "\n"

      template_path = client.install_template("pi-smoke", template_toml)
      assert template_path.exists()

      # 3. Launch a team.
      team_name = f"pi-smoke-{uuid.uuid4().hex[:8]}"
      try:
          client.launch_team(
              template="pi-smoke",
              team_name=team_name,
              goal="Write hello.txt with the word HELLO.",
          )

          # 4. Wait for completion (5 minute cap; typical run < 2 min).
          start = time.monotonic()
          client.wait_for_completion(team_name, timeout=300.0, poll_interval=5.0)
          elapsed = time.monotonic() - start
          assert elapsed < 300.0

          # 5. Verify the board.
          tasks = client.list_tasks(team_name)
          assert tasks, "expected at least one task on the board"
          assert all(t.get("status") == "completed" for t in tasks), (
              f"not all tasks completed cleanly: {tasks}"
          )

          # 6. Verify ClawTeam state dir for this team exists.
          team_state_dir = real_cfg.clawteam_state_dir / "teams" / team_name
          assert team_state_dir.exists(), (
              f"expected ClawTeam team state at {team_state_dir}"
          )
      finally:
          try:
              client.cleanup_team(team_name)
          except Exception:
              pass
  ```
- [ ] **Step 10.2** — Install ONE coding-agent CLI (one-time, on the engineer's machine):
  ```bash
  # Default — matches the openai-official preset ClawTeam ships with
  npm install -g @openai/codex
  # OR (alternative)
  npm install -g @mariozechner/pi-coding-agent
  ```
  Expected: install completes; `which codex` (or `which pi-coding-agent`) prints a path.
- [ ] **Step 10.3** — Sanity-check the unit suite is unaffected:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest -m "not smoke" -v
  ```
  Expected: same `29 passed` as before; no smoke test runs.
- [ ] **Step 10.4** — Run the smoke test against real OpenAI:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && \
  OPENAI_API_KEY=sk-your-real-key uv run pytest -m smoke -v --timeout=360
  ```
  Expected: `1 passed` within five minutes. Cost: a few cents.
- [ ] **Step 10.5** — Verify ClawTeam state landed on disk:
  ```bash
  # The smoke test uses a temp dir, but the path is printed in pytest output if --capture=no.
  # To inspect manually after a run, look for the most recent pytest tmp dir:
  find /tmp /private/var/folders -name "teams" -type d -path "*/clawteam-state*" 2>/dev/null | head -5
  ```
  Expected: at least one path. (Optional — the assertion inside the test already verifies this.)
- [ ] **Step 10.6** — Commit:
  ```bash
  git add tests/test_smoke_launch.py
  git commit -m "test: add smoke test for real ClawTeam 2-agent launch via coding-agent CLI"
  ```

---

### Task 11: Write `docs/README-FOUNDATION.md`

- [ ] **Step 11.1** — Create directory: `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/docs`
- [ ] **Step 11.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/docs/README-FOUNDATION.md`:
  ````markdown
  # Pi-Agent Harness — Foundation

  This is Plan 1 of 8. It establishes the Python package, the `Config` object every other
  module imports, and a tested subprocess wrapper around the real `clawteam` 0.2.x CLI.

  ## Prerequisites

  - Python 3.11+ (uv will install if missing)
  - `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
  - Node 20+ and `npm`
  - `tmux` (macOS: `brew install tmux`)
  - ONE of:
    - `@openai/codex`: `npm install -g @openai/codex` (default; matches `openai-official` preset)
    - `@mariozechner/pi-coding-agent`: `npm install -g @mariozechner/pi-coding-agent`
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
  > `launch_team(team_toml_path, run_id) -> RunHandle`. The actual Plan 1 surface
  > is `install_template(name, toml_text)` + `launch_team(template, team_name, goal,
  > profile=None)` + `create_task(team, subject, owner=, blocked_by=)`. The corrected
  > Plan 5 (`2026-05-25-topology-layer.md`) follows this flow already; Plan 7
  > consumes Plan 5's `Coordinator.launch(RunSpec)` rather than touching the
  > ClawTeam client directly.
  ````
- [ ] **Step 11.3** — Verify Markdown renders without errors (best-effort):
  ```bash
  uv run python -c "
  text = open('/Users/pranavnair/Desktop/Personal/mannschaft/docs/README-FOUNDATION.md').read()
  assert '## Prerequisites' in text
  assert 'pi_harness.config.Config' in text
  assert 'pi-openai-reasoning' in text
  print('ok')
  "
  ```
  Expected: `ok`.
- [ ] **Step 11.4** — Commit:
  ```bash
  git add docs/README-FOUNDATION.md
  git commit -m "docs: add foundation README with install + smoke-test guide"
  ```

---

### Task 12: Acceptance check — green unit suite, profile regen idempotent

- [ ] **Step 12.1** — Confirm a clean unit run:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest -m "not smoke" -v
  ```
  Expected: `29 passed` in under 5 seconds.
- [ ] **Step 12.2** — Confirm the committed profile matches a fresh regeneration (idempotency):
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && \
  OPENAI_API_KEY=sk-placeholder-for-codegen uv run python -c "
  from pathlib import Path
  from pi_harness.config import load_config
  from pi_harness.clawteam_profile import generate_pi_openai_profile
  cfg = load_config(env_file=None)
  fresh = generate_pi_openai_profile(cfg)
  committed = Path('profiles/pi-openai.toml').read_text()
  assert fresh == committed, 'profile drift detected; rerun the regen command in README'
  print('idempotent')
  "
  ```
  Expected: `idempotent`.
- [ ] **Step 12.3** — Confirm import surface for downstream plans:
  ```bash
  uv run python -c "
  from pi_harness import Config, load_config, __version__
  from pi_harness.clawteam import ClawTeamClient, ClawTeamCLIError, ClawTeamTimeout, ClawTeamRunFailure
  from pi_harness.clawteam_profile import (
      build_profile_specs, generate_pi_openai_profile, write_pi_openai_profile,
      PROFILE_NAME_REASONING, PROFILE_NAME_FAST, ROLE_PROFILE_MAP,
  )
  print(__version__, PROFILE_NAME_REASONING, PROFILE_NAME_FAST)
  "
  ```
  Expected: `0.1.0 pi-openai-reasoning pi-openai-fast`.
- [ ] **Step 12.4** — Verify final git state is clean:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && git status --short
  ```
  Expected: no output (working tree clean). If there are untracked files from this plan, stage and commit them with `chore: tidy foundation` before considering the plan done.

---

## Acceptance criteria (mirrors the brief)

1. `uv sync && uv run pytest -m "not smoke"` passes (29 tests) — see Step 12.1.
2. `OPENAI_API_KEY=sk-... uv run pytest -m smoke` runs a real ClawTeam launch via the detected coding-agent CLI and passes within 5 minutes — see Step 10.4.
3. After smoke, `clawteam --data-dir <sandbox> task list <pi-smoke-...>` lists tasks with status `completed` — verified inside the test.
4. ClawTeam team state is visible at `<sandbox>/teams/<team_name>/` — verified inside the test.
