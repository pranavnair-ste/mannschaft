# Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the Python package skeleton, environment-driven `Config`, and a tested `ClawTeam` subprocess wrapper that all other Pi-Agent Harness plans (Plans 2-8) import from.

**Architecture:** A `uv`-managed Python package named `pi_harness` exposes (a) a frozen `Config` dataclass that reads from `.env` and is the single source of truth for paths, model names, and the OpenAI key; (b) a `ClawTeamClient` class that shells out to the `clawteam` CLI for team launch, task listing, inbox reading, completion-wait, and tear-down; and (c) a `pi-openai` ClawTeam profile generator that pins OpenAI reasoning/fast tiers to ClawTeam roles. Tests use `pytest` with a `smoke` marker reserved for the one real-CLI integration test.

**Tech Stack:** Python 3.10+, `uv` for env/dependencies, `pytest` + `pytest-asyncio` for tests, `python-dotenv` for env loading, `tomli-w` for profile TOML emission, `clawteam==0.2.*` as a runtime dependency we shell out to, `pi-coding-agent` (npm) as the ClawTeam executor for the smoke test.

---

## File Structure

```
mannschaft/
  pyproject.toml                     # uv project metadata + deps + pytest config
  .python-version                    # pins Python 3.10
  .gitignore                         # ignores .venv, __pycache__, .env, build artifacts
  .env.example                       # template for required env vars
  pi_harness/
    __init__.py                      # exposes __version__
    config.py                        # Config dataclass + load_config()
    clawteam_profile.py              # generate_pi_openai_profile(config) -> TOML str
    clawteam/
      __init__.py                    # re-exports ClawTeamClient
      client.py                      # ClawTeamClient subprocess wrapper
  profiles/
    pi-openai.toml                   # committed regenerable profile
  tests/
    __init__.py                      # empty
    test_config.py                   # env loader + defaults
    test_clawteam_profile.py         # profile TOML structure
    test_clawteam_client.py          # mocked subprocess wrapper
    test_smoke_launch.py             # @pytest.mark.smoke real launch
  docs/
    README-FOUNDATION.md             # install + smoke-test guide
```

---

## Prerequisites

External tools the engineer must install before starting:

- **Python 3.10+** (check with `python3 --version`)
- **uv** — Python package/env manager
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Node 20+** with `npm` (needed by pi-coding-agent at smoke-test time)
- **tmux** (ClawTeam spawns tmux panes; on macOS: `brew install tmux`)
- **git** (you presumably have it)
- **ClawTeam CLI** — installed inside the project venv via `pyproject.toml`; do NOT install globally.
- **pi-coding-agent** — installed globally via npm at smoke-test time:
  ```bash
  npm install -g @mariozechner/pi-coding-agent
  ```
- **OpenAI API key** — needed only for the smoke test; set `OPENAI_API_KEY=sk-...` in `.env`.

Previous plans: none. This plan is the foundation.

---

## Tasks

### Task 1: Create `pyproject.toml` and pin Python

- [ ] **Step 1.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/.python-version`:
  ```
  3.10
  ```
- [ ] **Step 1.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/pyproject.toml`:
  ```toml
  [project]
  name = "pi-harness"
  version = "0.1.0"
  description = "Pi-Agent Harness — Symphony-style multi-agent orchestrator with expertise loop."
  readme = "docs/README-FOUNDATION.md"
  requires-python = ">=3.10"
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
  ]

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["pi_harness"]

  [tool.pytest.ini_options]
  testpaths = ["tests"]
  markers = [
    "smoke: integration test that launches a real ClawTeam team (requires OPENAI_API_KEY).",
  ]
  addopts = "-ra --strict-markers"
  asyncio_mode = "auto"
  ```
- [ ] **Step 1.3** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv sync --extra dev`
  Expected: a `.venv/` directory appears; output ends with `Installed N packages` (N >= 4) and no error.
- [ ] **Step 1.4** — Run: `uv run python -c "import sys; print(sys.version_info[:2])"`
  Expected: `(3, 10)` or higher minor (e.g. `(3, 12)`).
- [ ] **Step 1.5** — Run: `uv run python -c "import clawteam, dotenv, tomli_w; print('ok')"`
  Expected: `ok`.
- [ ] **Step 1.6** — Commit:
  ```bash
  git add pyproject.toml .python-version uv.lock
  git commit -m "chore: bootstrap uv project with pi-harness skeleton"
  ```

---

### Task 2: Create `.gitignore` and `.env.example`

- [ ] **Step 2.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/.gitignore`:
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
  ```
- [ ] **Step 2.3** — Run: `ls /Users/pranavnair/Desktop/Personal/mannschaft/.env.example && ls /Users/pranavnair/Desktop/Personal/mannschaft/.gitignore`
  Expected: both paths print, no error.
- [ ] **Step 2.4** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && git check-ignore -v .env 2>&1 || echo "no .env yet, ok"`
  Expected: either `no .env yet, ok` (if no .env file exists) or a line showing `.gitignore:N:.env`. Either is acceptable.
- [ ] **Step 2.5** — Commit:
  ```bash
  git add .gitignore .env.example
  git commit -m "chore: add gitignore and env example"
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
      assert cfg.clawteam_state_dir == home / ".clawteam"
      assert cfg.corpus_root == home / ".pi-harness" / "corpus"
      assert cfg.trajectory_db_path == home / ".pi-harness" / "trajectory.db"


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
      assert cfg.clawteam_state_dir == tmp_path / "claw"
      assert cfg.corpus_root == tmp_path / "corpus"
      assert cfg.trajectory_db_path == tmp_path / "traj.db"


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
          clawteam_state_dir: Directory ClawTeam owns. Never write to this from
              harness code; ClawTeam manages it.
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
  Replace the file body with:
  ```python
  """Pi-Agent Harness — Symphony-style multi-agent orchestrator with expertise loop."""

  from pi_harness.config import Config, ConfigError, load_config

  __version__ = "0.1.0"

  __all__ = ["__version__", "Config", "ConfigError", "load_config"]
  ```
- [ ] **Step 5.3** — Update the test file so the `test_config_applies_default_paths` assertions account for `Path.resolve()`. The current test uses raw `home / ".clawteam"` paths; resolve them too. Edit `/Users/pranavnair/Desktop/Personal/mannschaft/tests/test_config.py` and replace the body of `test_config_applies_default_paths` and `test_config_overrides_via_env` to call `.resolve(strict=False)` on the expected values. Final versions:
  ```python
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
  ```
- [ ] **Step 5.4** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_config.py -v`
  Expected: `6 passed`.
- [ ] **Step 5.5** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run python -c "from pi_harness import Config, load_config; print(Config.__name__)"`
  Expected: `Config`
- [ ] **Step 5.6** — Commit:
  ```bash
  git add pi_harness/config.py pi_harness/__init__.py tests/__init__.py tests/test_config.py
  git commit -m "feat: add frozen Config dataclass with env loader"
  ```

---

### Task 6: Write failing tests for `clawteam_profile.generate_pi_openai_profile`

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


  def test_profile_returns_valid_toml_string(cfg):
      """generate_pi_openai_profile returns a parseable TOML string."""
      from pi_harness.clawteam_profile import generate_pi_openai_profile

      toml_text = generate_pi_openai_profile(cfg)

      assert isinstance(toml_text, str)
      parsed = tomllib.loads(toml_text)
      assert isinstance(parsed, dict)


  def test_profile_declares_name_and_executor(cfg):
      """Profile must declare profile.name='pi-openai' and executor='pi-coding-agent'."""
      from pi_harness.clawteam_profile import generate_pi_openai_profile

      parsed = tomllib.loads(generate_pi_openai_profile(cfg))

      assert parsed["profile"]["name"] == "pi-openai"
      assert parsed["profile"]["executor"] == "pi-coding-agent"


  def test_profile_maps_reasoning_to_orchestrator_and_reviewer(cfg):
      """Orchestrator + reviewer roles map to reasoning_model."""
      from pi_harness.clawteam_profile import generate_pi_openai_profile

      parsed = tomllib.loads(generate_pi_openai_profile(cfg))

      assert parsed["roles"]["orchestrator"]["model"] == "gpt-5"
      assert parsed["roles"]["reviewer"]["model"] == "gpt-5"


  def test_profile_maps_fast_to_builder_and_scout(cfg):
      """Builder + scout roles map to fast_model."""
      from pi_harness.clawteam_profile import generate_pi_openai_profile

      parsed = tomllib.loads(generate_pi_openai_profile(cfg))

      assert parsed["roles"]["builder"]["model"] == "gpt-5-mini"
      assert parsed["roles"]["scout"]["model"] == "gpt-5-mini"


  def test_profile_injects_openai_provider(cfg):
      """Provider block must declare openai and reference the env-var name (not the literal key)."""
      from pi_harness.clawteam_profile import generate_pi_openai_profile

      toml_text = generate_pi_openai_profile(cfg)
      parsed = tomllib.loads(toml_text)

      assert parsed["provider"]["name"] == "openai"
      assert parsed["provider"]["api_key_env"] == "OPENAI_API_KEY"
      assert "sk-profile-test" not in toml_text, "API key value must not be embedded"


  def test_profile_write_to_disk(cfg, tmp_path):
      """write_pi_openai_profile writes a regenerable TOML file."""
      from pi_harness.clawteam_profile import write_pi_openai_profile

      target = tmp_path / "pi-openai.toml"
      written = write_pi_openai_profile(cfg, target)

      assert written == target
      assert target.exists()
      parsed = tomllib.loads(target.read_text())
      assert parsed["profile"]["name"] == "pi-openai"
  ```
- [ ] **Step 6.2** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_clawteam_profile.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'pi_harness.clawteam_profile'`.

---

### Task 7: Implement `pi_harness/clawteam_profile.py`

- [ ] **Step 7.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/clawteam_profile.py`:
  ```python
  """Generator for the ``pi-openai`` ClawTeam profile.

  ClawTeam profiles are TOML documents that tell ClawTeam which executor binary
  to spawn for each role and which model that executor should call. The harness
  emits this profile programmatically so model assignments stay in lockstep with
  :class:`pi_harness.config.Config`.
  """

  from __future__ import annotations

  from pathlib import Path

  import tomli_w

  from pi_harness.config import Config

  __all__ = [
      "PROFILE_NAME",
      "EXECUTOR_NAME",
      "build_profile_dict",
      "generate_pi_openai_profile",
      "write_pi_openai_profile",
  ]

  PROFILE_NAME = "pi-openai"
  EXECUTOR_NAME = "pi-coding-agent"


  def build_profile_dict(config: Config) -> dict:
      """Build the in-memory profile dict, before TOML serialization.

      Role assignments follow the architecture doc:
      - orchestrator + reviewer -> reasoning tier (heavier)
      - builder + scout         -> fast tier (cheap, parallel)
      """
      return {
          "profile": {
              "name": PROFILE_NAME,
              "executor": EXECUTOR_NAME,
              "description": (
                  "Pi-Agent Harness profile pinning OpenAI reasoning/fast tiers "
                  "to ClawTeam roles. Regenerated from pi_harness.config.Config."
              ),
          },
          "provider": {
              "name": "openai",
              "api_key_env": "OPENAI_API_KEY",
          },
          "roles": {
              "orchestrator": {
                  "model": config.reasoning_model,
                  "tier": "reasoning",
              },
              "reviewer": {
                  "model": config.reasoning_model,
                  "tier": "reasoning",
              },
              "builder": {
                  "model": config.fast_model,
                  "tier": "fast",
              },
              "scout": {
                  "model": config.fast_model,
                  "tier": "fast",
              },
          },
      }


  def generate_pi_openai_profile(config: Config) -> str:
      """Return the pi-openai profile as a TOML string."""
      return tomli_w.dumps(build_profile_dict(config))


  def write_pi_openai_profile(config: Config, target: Path) -> Path:
      """Write the pi-openai profile to ``target`` and return the path."""
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(generate_pi_openai_profile(config))
      return target
  ```
- [ ] **Step 7.2** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_clawteam_profile.py -v`
  Expected: `6 passed`.
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
  assert data['profile']['name'] == 'pi-openai'
  assert data['roles']['orchestrator']['model'] == 'gpt-5'
  assert data['roles']['builder']['model'] == 'gpt-5-mini'
  print('ok')
  "
  ```
  Expected: `ok`.
- [ ] **Step 7.5** — Commit:
  ```bash
  git add pi_harness/clawteam_profile.py profiles/pi-openai.toml tests/test_clawteam_profile.py
  git commit -m "feat: add pi-openai ClawTeam profile generator"
  ```

---

### Task 8: Write failing tests for `ClawTeamClient` (mocked subprocess)

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
  from pathlib import Path
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
              profile="pi-openai",
          )

      assert mock_run.called
      cmd = mock_run.call_args.args[0]
      assert cmd[0] == "clawteam"
      assert cmd[1] == "launch"
      assert "--template" in cmd and "hello-team" in cmd
      assert "--name" in cmd and "my-team" in cmd
      assert "--goal" in cmd and "ship it" in cmd
      assert "--profile" in cmd and "pi-openai" in cmd


  def test_launch_team_raises_on_nonzero_exit(cfg):
      from pi_harness.clawteam.client import ClawTeamClient, ClawTeamCLIError

      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stderr="boom", returncode=2)

          with pytest.raises(ClawTeamCLIError, match="boom"):
              client.launch_team(
                  template="x", team_name="y", goal="z", profile="pi-openai"
              )


  def test_list_tasks_parses_json(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      payload = [
          {"id": "t1", "title": "build", "state": "done"},
          {"id": "t2", "title": "test", "state": "in_progress"},
      ]
      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stdout=json.dumps(payload))
          tasks = client.list_tasks("my-team")

      assert tasks == payload
      cmd = mock_run.call_args.args[0]
      assert cmd[:2] == ["clawteam", "board"]
      assert "--team" in cmd and "my-team" in cmd
      assert "--json" in cmd


  def test_read_inbox_parses_json(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      payload = [{"from": "leader", "to": "builder", "body": "hi"}]
      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stdout=json.dumps(payload))
          messages = client.read_inbox("my-team", "builder")

      assert messages == payload
      cmd = mock_run.call_args.args[0]
      assert "inbox" in cmd
      assert "--team" in cmd and "my-team" in cmd
      assert "--agent" in cmd and "builder" in cmd


  def test_wait_for_completion_returns_when_all_done(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      done = [{"id": "t1", "state": "done"}, {"id": "t2", "state": "done"}]
      client = ClawTeamClient(cfg)
      with patch.object(ClawTeamClient, "list_tasks", return_value=done):
          result = client.wait_for_completion("my-team", timeout=2.0, poll_interval=0.01)

      assert result is True


  def test_wait_for_completion_times_out(cfg):
      from pi_harness.clawteam.client import ClawTeamClient, ClawTeamTimeout

      pending = [{"id": "t1", "state": "in_progress"}]
      client = ClawTeamClient(cfg)
      with patch.object(ClawTeamClient, "list_tasks", return_value=pending):
          with pytest.raises(ClawTeamTimeout):
              client.wait_for_completion("my-team", timeout=0.05, poll_interval=0.01)


  def test_wait_for_completion_fails_on_failed_task(cfg):
      from pi_harness.clawteam.client import ClawTeamClient, ClawTeamRunFailure

      mixed = [{"id": "t1", "state": "done"}, {"id": "t2", "state": "failed"}]
      client = ClawTeamClient(cfg)
      with patch.object(ClawTeamClient, "list_tasks", return_value=mixed):
          with pytest.raises(ClawTeamRunFailure, match="t2"):
              client.wait_for_completion("my-team", timeout=1.0, poll_interval=0.01)


  def test_tear_down_invokes_destroy(cfg):
      from pi_harness.clawteam.client import ClawTeamClient

      client = ClawTeamClient(cfg)
      with patch("pi_harness.clawteam.client.subprocess.run") as mock_run:
          mock_run.return_value = _completed(stdout="ok")
          client.tear_down("my-team")

      cmd = mock_run.call_args.args[0]
      assert cmd[:2] == ["clawteam", "destroy"]
      assert "--name" in cmd and "my-team" in cmd
      assert "--yes" in cmd


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
  )

  __all__ = [
      "ClawTeamClient",
      "ClawTeamCLIError",
      "ClawTeamRunFailure",
      "ClawTeamTimeout",
  ]
  ```
- [ ] **Step 9.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/clawteam/client.py`:
  ```python
  """Thin subprocess wrapper over the ``clawteam`` CLI.

  Each public method shells out to ``clawteam <verb>`` and parses its output.
  Output parsing assumes ClawTeam 0.2.x emits JSON when ``--json`` is passed.
  """

  from __future__ import annotations

  import json
  import os
  import subprocess
  import time
  from dataclasses import dataclass
  from typing import Any, Mapping, Sequence

  from pi_harness.config import Config

  __all__ = [
      "ClawTeamClient",
      "ClawTeamCLIError",
      "ClawTeamTimeout",
      "ClawTeamRunFailure",
      "TERMINAL_STATES",
      "FAILURE_STATES",
  ]

  TERMINAL_STATES = frozenset({"done", "completed", "failed", "cancelled"})
  FAILURE_STATES = frozenset({"failed", "cancelled"})


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
      """Wrapper around the ``clawteam`` CLI.

      Args:
          config: Project :class:`Config`. Used to locate the state directory and
              inject the OpenAI key into subprocess env.
          binary: Override the CLI binary name (handy for tests / pinned installs).
      """

      config: Config
      binary: str = "clawteam"

      def _env(self) -> dict[str, str]:
          env = dict(os.environ)
          env["OPENAI_API_KEY"] = self.config.openai_api_key
          env["CLAWTEAM_STATE_DIR"] = str(self.config.clawteam_state_dir)
          return env

      def _run(self, args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess:
          cmd = [self.binary, *args]
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

      def launch_team(
          self,
          template: str,
          team_name: str,
          goal: str,
          profile: str,
      ) -> subprocess.CompletedProcess:
          """Spawn a new ClawTeam team.

          Args:
              template: Name of a built-in or registered team template.
              team_name: Unique team name; becomes the state-dir leaf.
              goal: Free-form goal string passed to the leader agent.
              profile: ClawTeam profile name (e.g. ``"pi-openai"``).
          """
          return self._run(
              [
                  "launch",
                  "--template", template,
                  "--name", team_name,
                  "--goal", goal,
                  "--profile", profile,
              ]
          )

      def list_tasks(self, team_name: str) -> list[Mapping[str, Any]]:
          """Return the task board for ``team_name`` as a list of dicts."""
          result = self._run(
              ["board", "--team", team_name, "--json"],
          )
          payload = json.loads(result.stdout or "[]")
          if not isinstance(payload, list):
              raise ClawTeamCLIError(
                  ["clawteam", "board"],
                  0,
                  f"expected JSON list, got {type(payload).__name__}",
              )
          return payload

      def read_inbox(self, team_name: str, agent: str) -> list[Mapping[str, Any]]:
          """Read the inbox of ``agent`` inside ``team_name``."""
          result = self._run(
              ["inbox", "--team", team_name, "--agent", agent, "--json"],
          )
          payload = json.loads(result.stdout or "[]")
          if not isinstance(payload, list):
              raise ClawTeamCLIError(
                  ["clawteam", "inbox"],
                  0,
                  f"expected JSON list, got {type(payload).__name__}",
              )
          return payload

      def wait_for_completion(
          self,
          team_name: str,
          timeout: float,
          poll_interval: float = 5.0,
      ) -> bool:
          """Block until every task on the board reaches a terminal state.

          Returns:
              ``True`` if all tasks finished cleanly within ``timeout``.

          Raises:
              ClawTeamRunFailure: If any task reaches a failure state.
              ClawTeamTimeout: If ``timeout`` elapses before all tasks finish.
          """
          deadline = time.monotonic() + timeout
          while True:
              tasks = self.list_tasks(team_name)
              if tasks:
                  failed = [t for t in tasks if t.get("state") in FAILURE_STATES]
                  if failed:
                      failed_ids = ", ".join(str(t.get("id", "?")) for t in failed)
                      raise ClawTeamRunFailure(
                          f"team={team_name!r} task(s) failed: {failed_ids}"
                      )
                  if all(t.get("state") in TERMINAL_STATES for t in tasks):
                      return True
              if time.monotonic() >= deadline:
                  raise ClawTeamTimeout(
                      f"team={team_name!r} did not finish within {timeout:.1f}s"
                  )
              time.sleep(poll_interval)

      def tear_down(self, team_name: str) -> subprocess.CompletedProcess:
          """Destroy ``team_name`` and free its worktrees."""
          return self._run(["destroy", "--name", team_name, "--yes"])
  ```
- [ ] **Step 9.3** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest tests/test_clawteam_client.py -v`
  Expected: `9 passed`.
- [ ] **Step 9.4** — Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest -m "not smoke" -v`
  Expected: all 21 tests pass (`6 + 6 + 9 = 21`).
- [ ] **Step 9.5** — Commit:
  ```bash
  git add pi_harness/clawteam/__init__.py pi_harness/clawteam/client.py tests/test_clawteam_client.py
  git commit -m "feat: add ClawTeamClient subprocess wrapper"
  ```

---

### Task 10: Smoke test — real ClawTeam launch with pi-coding-agent

This task creates a 2-agent ClawTeam template inline (no external template file), launches it, waits for completion, and asserts the board shows two completed tasks. It runs only under `pytest -m smoke` so unit runs stay fast and free.

- [ ] **Step 10.1** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/tests/test_smoke_launch.py`:
  ```python
  """Smoke test: launch a real 2-agent ClawTeam with pi-coding-agent.

  Skipped by default. To run:

      OPENAI_API_KEY=sk-... uv run pytest -m smoke -v

  Prerequisites:
      - clawteam CLI installed (uv sync)
      - pi-coding-agent installed globally: npm install -g @mariozechner/pi-coding-agent
      - tmux installed
      - OPENAI_API_KEY exported
  """

  from __future__ import annotations

  import os
  import shutil
  import subprocess
  import textwrap
  import time
  import uuid
  from pathlib import Path

  import pytest

  pytestmark = pytest.mark.smoke


  def _which_or_skip(binary: str) -> str:
      path = shutil.which(binary)
      if not path:
          pytest.skip(f"required binary {binary!r} not on PATH")
      return path


  @pytest.fixture(scope="module")
  def real_cfg(tmp_path_factory):
      """A Config that points at a sandboxed ClawTeam state dir."""
      from pi_harness.config import load_config

      if not os.environ.get("OPENAI_API_KEY", "").startswith("sk-"):
          pytest.skip("OPENAI_API_KEY not set (or not sk-*); smoke test skipped")

      state_dir = tmp_path_factory.mktemp("clawteam-state")
      os.environ["PI_HARNESS_CLAWTEAM_STATE_DIR"] = str(state_dir)
      return load_config(env_file=None)


  @pytest.fixture(scope="module")
  def installed_template(real_cfg, tmp_path_factory) -> str:
      """Register a tiny 2-agent template named ``pi-smoke`` with ClawTeam.

      Layout: a leader that spawns a single builder task. The builder writes a
      single file ``hello.txt`` and reports done. Total OpenAI cost: a few cents.
      """
      _which_or_skip("clawteam")
      _which_or_skip("tmux")
      _which_or_skip("pi-coding-agent")

      tmpl_dir = tmp_path_factory.mktemp("templates") / "pi-smoke"
      tmpl_dir.mkdir(parents=True, exist_ok=True)
      (tmpl_dir / "team.toml").write_text(textwrap.dedent("""
          [team]
          name = "pi-smoke"
          description = "Two-agent smoke template for pi-harness foundation tests."

          [[agents]]
          name = "leader"
          role = "orchestrator"
          instructions = '''
          Create exactly one task titled "write-hello" assigned to builder with
          body: "Write the file hello.txt containing the single word HELLO. Then
          mark the task done." Do not create other tasks. When the builder task
          is done, exit.
          '''

          [[agents]]
          name = "builder"
          role = "builder"
          instructions = '''
          When you receive the "write-hello" task, create hello.txt at the
          worktree root with the single word HELLO. Then mark the task done.
          '''
      """).strip() + "\n")

      result = subprocess.run(
          ["clawteam", "template", "register", "--path", str(tmpl_dir)],
          capture_output=True,
          text=True,
          env={**os.environ, "CLAWTEAM_STATE_DIR": str(real_cfg.clawteam_state_dir)},
      )
      if result.returncode != 0:
          pytest.skip(
              f"clawteam template register failed (rc={result.returncode}): "
              f"{result.stderr.strip() or result.stdout.strip()}"
          )

      return "pi-smoke"


  def test_smoke_launch_completes(real_cfg, installed_template, tmp_path_factory):
      """Launch a 2-agent team, wait for completion, then tear down."""
      from pi_harness.clawteam import ClawTeamClient
      from pi_harness.clawteam_profile import write_pi_openai_profile

      profile_path = tmp_path_factory.mktemp("profile") / "pi-openai.toml"
      write_pi_openai_profile(real_cfg, profile_path)

      reg = subprocess.run(
          ["clawteam", "profile", "register", "--path", str(profile_path)],
          capture_output=True,
          text=True,
          env={
              **os.environ,
              "CLAWTEAM_STATE_DIR": str(real_cfg.clawteam_state_dir),
          },
      )
      assert reg.returncode == 0, f"profile register failed: {reg.stderr or reg.stdout}"

      team_name = f"pi-smoke-{uuid.uuid4().hex[:8]}"
      client = ClawTeamClient(real_cfg)

      try:
          client.launch_team(
              template=installed_template,
              team_name=team_name,
              goal="Write hello.txt with the word HELLO.",
              profile="pi-openai",
          )

          start = time.monotonic()
          client.wait_for_completion(team_name, timeout=300.0, poll_interval=5.0)
          elapsed = time.monotonic() - start
          assert elapsed < 300.0

          tasks = client.list_tasks(team_name)
          assert tasks, "expected at least one task on the board"
          assert all(t.get("state") in {"done", "completed"} for t in tasks), (
              f"not all tasks completed cleanly: {tasks}"
          )

          team_state_dir = real_cfg.clawteam_state_dir / team_name
          assert team_state_dir.exists(), (
              f"expected ClawTeam state dir at {team_state_dir}"
          )
      finally:
          try:
              client.tear_down(team_name)
          except Exception:
              pass
  ```
- [ ] **Step 10.2** — Install the npm executor (one-time, on the engineer's machine):
  ```bash
  npm install -g @mariozechner/pi-coding-agent
  ```
  Expected: install completes; `which pi-coding-agent` prints a path.
- [ ] **Step 10.3** — Sanity-check the unit suite is unaffected:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && uv run pytest -m "not smoke" -v
  ```
  Expected: same `21 passed` as before; no smoke test runs.
- [ ] **Step 10.4** — Run the smoke test against real OpenAI:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && \
  OPENAI_API_KEY=sk-your-real-key uv run pytest -m smoke -v --timeout=360
  ```
  Expected: `1 passed` within five minutes. Cost: a few cents.
- [ ] **Step 10.5** — Verify ClawTeam state landed on disk:
  ```bash
  ls ~/.clawteam/ 2>/dev/null || ls "$PI_HARNESS_CLAWTEAM_STATE_DIR" 2>/dev/null
  ```
  Expected: at least one directory named `pi-smoke-<hex>` (the smoke run's team).
- [ ] **Step 10.6** — Verify `clawteam board show` lists completed tasks:
  ```bash
  TEAM=$(ls -1t ~/.clawteam | grep '^pi-smoke-' | head -1)
  clawteam board show --team "$TEAM"
  ```
  Expected: at least one task with state `done` or `completed`.
- [ ] **Step 10.7** — Commit:
  ```bash
  git add tests/test_smoke_launch.py
  git commit -m "test: add smoke test for real ClawTeam 2-agent launch"
  ```

---

### Task 11: Write `docs/README-FOUNDATION.md`

- [ ] **Step 11.1** — Create directory: `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/docs`
- [ ] **Step 11.2** — Write `/Users/pranavnair/Desktop/Personal/mannschaft/docs/README-FOUNDATION.md`:
  ```markdown
  # Pi-Agent Harness — Foundation

  This is Plan 1 of 8. It establishes the Python package, the `Config` object every other
  module imports, and a tested subprocess wrapper around the `clawteam` CLI.

  ## Prerequisites

  - Python 3.10+
  - `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
  - Node 20+ and `npm`
  - `tmux` (macOS: `brew install tmux`)
  - `pi-coding-agent`: `npm install -g @mariozechner/pi-coding-agent`
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

  Expected: 21 tests pass.

  ## Run the smoke test (real ClawTeam launch, ~1-3 minutes, a few cents)

  ```bash
  OPENAI_API_KEY=sk-... uv run pytest -m smoke -v --timeout=360
  ```

  This:

  1. Generates the `pi-openai` ClawTeam profile from `pi_harness.config.Config`.
  2. Registers a tiny 2-agent template named `pi-smoke` with ClawTeam.
  3. Launches a team, waits for its single "write-hello" task to complete.
  4. Asserts every task on the board reached a terminal `done`/`completed` state.
  5. Tears the team down.

  After the smoke run, inspect state:

  ```bash
  TEAM=$(ls -1t ~/.clawteam | grep '^pi-smoke-' | head -1)
  clawteam board show --team "$TEAM"
  ls ~/.clawteam/"$TEAM"
  ```

  ## What this plan exposes for downstream plans

  | Symbol                                            | Used by Plans |
  | ------------------------------------------------- | ------------- |
  | `pi_harness.config.Config`, `load_config`         | all           |
  | `pi_harness.clawteam.ClawTeamClient`              | 2, 5, 7       |
  | `pi_harness.clawteam_profile.generate_pi_openai_profile` | 5      |
  | `profiles/pi-openai.toml`                         | 5             |

  ## Regenerating the committed profile

  ```bash
  OPENAI_API_KEY=sk-placeholder uv run python -c "
  from pathlib import Path
  from pi_harness.config import load_config
  from pi_harness.clawteam_profile import write_pi_openai_profile
  write_pi_openai_profile(load_config(env_file=None), Path('profiles/pi-openai.toml'))
  "
  ```
  ```
- [ ] **Step 11.3** — Verify Markdown renders without errors (best-effort):
  ```bash
  uv run python -c "
  text = open('/Users/pranavnair/Desktop/Personal/mannschaft/docs/README-FOUNDATION.md').read()
  assert '## Prerequisites' in text
  assert 'pi_harness.config.Config' in text
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
  Expected: `21 passed` in under 5 seconds.
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
  from pi_harness.clawteam_profile import generate_pi_openai_profile, write_pi_openai_profile, PROFILE_NAME
  print(__version__, PROFILE_NAME)
  "
  ```
  Expected: `0.1.0 pi-openai`.
- [ ] **Step 12.4** — Verify final git state is clean:
  ```bash
  cd /Users/pranavnair/Desktop/Personal/mannschaft && git status --short
  ```
  Expected: no output (working tree clean). If there are untracked files from this plan, stage and commit them with `chore: tidy foundation` before considering the plan done.

---

## Acceptance criteria (mirrors the brief)

1. `uv sync && uv run pytest -m "not smoke"` passes — see Step 12.1.
2. `OPENAI_API_KEY=sk-... uv run pytest -m smoke` runs a real ClawTeam launch via `pi-coding-agent` and passes within 5 minutes — see Step 10.4.
3. After smoke, `clawteam board show --team <pi-smoke-...>` lists completed tasks — see Step 10.6.
4. ClawTeam state is visible at `~/.clawteam/<team_name>/` — see Step 10.5.
