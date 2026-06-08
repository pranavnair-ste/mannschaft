# Phase 1 — Sovereign Harness Adaptation (cloud → local default) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** mannschaft boots and runs a full agent task driven *only* by the local MLX model, with **no `OPENAI_API_KEY` set** and no external calls; cloud (`api`) becomes explicit opt-in.

**Architecture:** Two model-selection layers must both default to local. (1) **Live path:** `settings.py` defaults → `agent_wrapper._resolve_provider_model()` hands pi `--provider harness-local --model <mlx-id>`. (2) **Registration path:** `clawteam_profile.build_profile_specs()` registers the ClawTeam agent as `pi` pointed at the local endpoint. `config.py` stops hard-requiring the key; enforcement moves to the point an `api` bucket is actually used. The launch path registers the local provider in pi's `models.json` so a run works without first opening the Settings UI.

**Tech Stack:** Python 3.11, pytest, Typer, FastAPI, pi 0.73.1 CLI, ClawTeam v0.2.0, mlx_lm.server (isolated, `http://localhost:8080/v1`).

**Run tests with:** `pytest -m "not smoke" -q` (smoke launches a real ClawTeam team that commits to your branch — never in CI/unattended).

---

### Task 0: Branch + checkpoint the pre-existing WIP

**Files:** none created; git hygiene only.

- [ ] **Step 1: Commit the pre-existing `ms`-rename + obs-docs WIP on its own commit** (so Phase 1 starts from a clean tree). These changes are unrelated to Phase 1.

```bash
cd ~/Desktop/Personal/mannschaft
git add pi_harness/api/routes/runs.py pi_harness/cli.py pi_harness/spec/editor.py \
        pi_harness/spec/runspec.py pyproject.toml tests/test_cli.py \
        README.md docs/observability-quickstart.md WORKFLOW_md_example.png
git commit -m "chore: checkpoint ms-rename + observability quickstart docs (pre-Phase-1)"
```

- [ ] **Step 2: Create the Phase 1 branch**

```bash
git checkout -b feat/sovereign-local-default
```

- [ ] **Step 3: Confirm a green baseline before changing anything**

Run: `pytest -m "not smoke" -q`
Expected: PASS (record the count; this is the regression baseline).

---

### Task 1: Make `OPENAI_API_KEY` optional in `config.py`

**Files:**
- Modify: `pi_harness/config.py:95-99` (the hard raise) + docstrings at `:40-41`, `:87-88`
- Test: `tests/test_config.py:78-85`

- [ ] **Step 1: Flip the failing test** — replace `test_config_missing_key_raises` (currently asserts a raise) with the sovereign expectation.

In `tests/test_config.py`, replace the function at line 78:

```python
def test_config_missing_key_ok_for_local(monkeypatch):
    """No OPENAI_API_KEY is fine — local is the sovereign default; the key is
    only required when an `api` bucket is actually selected (enforced in
    agent_wrapper, not here)."""
    from pi_harness.config import load_config

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = load_config(env_file=None)
    assert cfg.openai_api_key == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_config.py::test_config_missing_key_ok_for_local -q`
Expected: FAIL — `ConfigError: OPENAI_API_KEY is required`.

- [ ] **Step 3: Make the key optional** — in `pi_harness/config.py`, replace the raise block (lines 95-99):

```python
    # Sovereign default: the key is OPTIONAL. A local-provider run needs none.
    # Enforcement is deferred to the point of use — agent_wrapper raises a clear
    # ConfigError if an `api` bucket is selected without a key (see Task 2).
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
```

Update the docstring at line 40 (`openai_api_key: OpenAI API key (required).`) →
`openai_api_key: OpenAI API key (optional; required only when an 'api' provider bucket is selected).`
and delete the `Raises: ConfigError: If OPENAI_API_KEY is unset.` line from `load_config` (lines 87-88).

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_config.py -q`
Expected: PASS (the other tests that `setenv` the key still pass unchanged).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/config.py tests/test_config.py
git commit -m "feat(config): make OPENAI_API_KEY optional (sovereign local default)"
```

---

### Task 2: `api` bucket requires a key — enforce at resolve time

**Files:**
- Modify: `pi_harness/agent_wrapper.py:54-63` (`_resolve_provider_model`)
- Test: `tests/test_agent_wrapper.py` (new tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_wrapper.py`:

```python
def test_resolve_local_bucket_needs_no_key(monkeypatch):
    from pi_harness import agent_wrapper
    from pi_harness.settings import HarnessSettings, BucketConfig

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        agent_wrapper, "load_settings", lambda: HarnessSettings(
            orchestrator=BucketConfig(provider="local", model="mlx-x"),
            builder=BucketConfig(provider="local", model="mlx-y"),
        ), raising=False,
    )
    assert agent_wrapper._resolve_provider_model("reasoning") == (
        agent_wrapper.LOCAL_PROVIDER_NAME, "mlx-x")


def test_resolve_api_bucket_without_key_raises(monkeypatch):
    from pi_harness import agent_wrapper
    from pi_harness.config import ConfigError
    from pi_harness.settings import HarnessSettings, BucketConfig

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        agent_wrapper, "load_settings", lambda: HarnessSettings(
            orchestrator=BucketConfig(provider="api", model="gpt-5"),
            builder=BucketConfig(provider="local", model="mlx-y"),
        ), raising=False,
    )
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        agent_wrapper._resolve_provider_model("reasoning")
```

Note: `_resolve_provider_model` imports `load_settings` inside the function today. Hoist it to a module-level `from pi_harness.settings import load_settings` import so the monkeypatch target exists. (Add `import pytest` at the top of the test file if absent.)

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_agent_wrapper.py -k resolve -q`
Expected: FAIL (`test_resolve_api_bucket_without_key_raises` does not raise; monkeypatch target may be missing).

- [ ] **Step 3: Implement** — in `pi_harness/agent_wrapper.py`, hoist the import to module scope and replace the `api` branch (lines 58-60):

```python
    if cfg.provider == "api":
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            from pi_harness.config import ConfigError
            raise ConfigError(
                f"bucket {bucket!r} selects the 'api' provider but OPENAI_API_KEY "
                "is unset. Set it, or switch the bucket to 'local' (the sovereign "
                "default)."
            )
        return ("openai", cfg.model)
```

(`os` is already imported at the top of `agent_wrapper.py`.)

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_agent_wrapper.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/agent_wrapper.py tests/test_agent_wrapper.py
git commit -m "feat(agent_wrapper): require OPENAI_API_KEY only when an api bucket is selected"
```

---

### Task 3: Default both buckets to the local MLX model

**Files:**
- Modify: `pi_harness/settings.py:34` and `:66-70`
- Test: `tests/test_settings.py:21-29`

- [ ] **Step 1: Flip the failing test** — replace `test_load_settings_returns_defaults_when_file_missing` (lines 21-29):

```python
def test_load_settings_returns_defaults_when_file_missing(home: Path) -> None:
    s = load_settings()
    assert s.orchestrator.provider == "local"
    assert s.orchestrator.model == "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
    assert s.builder.provider == "local"
    assert s.builder.model == "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
    assert s.local_base_url == "http://localhost:8080/v1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_settings.py::test_load_settings_returns_defaults_when_file_missing -q`
Expected: FAIL (got `api`/`gpt-5`/`:11434`).

- [ ] **Step 3: Implement** — in `pi_harness/settings.py`:

Line 34 → `DEFAULT_LOCAL_BASE_URL = "http://localhost:8080/v1"  # mlx_lm.server default port`

After line 34 add:
```python
DEFAULT_LOCAL_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
```

Replace `_default_settings` (lines 66-70):
```python
def _default_settings() -> HarnessSettings:
    return HarnessSettings(
        orchestrator=BucketConfig(provider="local", model=DEFAULT_LOCAL_MODEL),
        builder=BucketConfig(provider="local", model=DEFAULT_LOCAL_MODEL),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_settings.py -q`
Expected: PASS (the partial-file test at :61 sets values explicitly; verify it still passes — if it asserted the old default for an unset field, update it to the new local default).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/settings.py tests/test_settings.py
git commit -m "feat(settings): default both buckets to local MLX (Qwen3-Coder-30B-A3B-4bit @ :8080)"
```

---

### Task 4: ClawTeam profiles → pi agent, settings-driven, key optional

**Files:**
- Modify: `pi_harness/clawteam_profile.py:43` (`DEFAULT_AGENT_CLI`), `:88-113` (`ProfileSpec`), `:116-139` (`build_profile_specs`)
- Test: `tests/test_clawteam_profile.py`

- [ ] **Step 1: Write/adjust the failing tests** — in `tests/test_clawteam_profile.py`, the `cfg` fixture must run under a temp home so `load_settings()` returns the local defaults. Add at the top of the file (after imports):

```python
@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path / "home"))
    yield
```

Replace the two model/key assertions:
- Line 38 `assert reasoning.api_key_env == "OPENAI_API_KEY"` →
```python
    assert reasoning.agent == "pi"
    assert reasoning.command == "pi"
    assert reasoning.provider_is_local is True
    assert reasoning.api_key_env is None
    assert reasoning.base_url == "http://localhost:8080/v1"
```
- Line 49 `assert fast.api_key_env == "OPENAI_API_KEY"` → mirror the above for `fast`.
- Line 89 `by_name["pi-openai-reasoning"]["api_key_env"] == "OPENAI_API_KEY"` → assert the doc dict has `agent == "pi"` and no `api_key_env` key (local profile).

Add a new test for the api fallback:
```python
def test_api_bucket_profile_keeps_key_env(cfg, monkeypatch):
    from pi_harness.settings import save_settings, HarnessSettings, BucketConfig
    save_settings(HarnessSettings(
        orchestrator=BucketConfig(provider="api", model="gpt-5"),
        builder=BucketConfig(provider="api", model="gpt-5-mini"),
    ))
    specs = build_profile_specs(cfg)
    reasoning = next(s for s in specs if s.name == "pi-openai-reasoning")
    assert reasoning.agent == "pi"
    assert reasoning.api_key_env == "OPENAI_API_KEY"
    assert reasoning.base_url is None
    assert reasoning.model == "gpt-5"
```

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_clawteam_profile.py -q`
Expected: FAIL (agent is `codex`; no `provider_is_local`; api_key_env not None).

- [ ] **Step 3: Implement** — in `pi_harness/clawteam_profile.py`:

Line 43 → `DEFAULT_AGENT_CLI = "pi"`

In `ProfileSpec` (after `base_url` field) add a derived flag and make `api_key_env` optional:
```python
    api_key_env: Optional[str] = None
    ...
    base_url: Optional[str] = None

    @property
    def provider_is_local(self) -> bool:
        return self.base_url is not None
```
In `to_set_args`, guard the key flag:
```python
        args: List[str] = [self.name, "--agent", self.agent, "--model", self.model]
        if self.api_key_env is not None:
            args.extend(["--api-key-env", self.api_key_env])
        args.extend(["--description", self.description])
        if self.command is not None:
            args.extend(["--command", self.command])
        if self.base_url is not None:
            args.extend(["--base-url", self.base_url])
        return args
```

Rewrite `build_profile_specs` to derive provider/model/base_url from `HarnessSettings`:
```python
def build_profile_specs(config: Config) -> List[ProfileSpec]:
    """Build the two profile specs from the live HarnessSettings (local-first).
    `config` is retained for the api-fallback key env source."""
    from pi_harness.settings import load_settings

    settings = load_settings()

    def _spec(name: str, tier: str, bucket, desc: str) -> ProfileSpec:
        if bucket.provider == "local":
            return ProfileSpec(
                name=name, agent=DEFAULT_AGENT_CLI, model=bucket.model,
                api_key_env=None, tier=tier, description=desc,
                command="pi", base_url=settings.local_base_url,
            )
        return ProfileSpec(
            name=name, agent=DEFAULT_AGENT_CLI, model=bucket.model,
            api_key_env="OPENAI_API_KEY", tier=tier, description=desc,
            command="pi", base_url=None,
        )

    return [
        _spec(PROFILE_NAME_REASONING, "reasoning", settings.orchestrator,
              "LLMCoder reasoning tier — orchestrator + reviewer roles."),
        _spec(PROFILE_NAME_FAST, "fast", settings.builder,
              "LLMCoder fast tier — builder + scout roles."),
    ]
```

Update `_spec_to_doc_dict` (lines 142-155) to only include `api_key_env` when not None (it already guards `command`/`base_url`; add the same guard for `api_key_env`).

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_clawteam_profile.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/clawteam_profile.py tests/test_clawteam_profile.py
git commit -m "feat(clawteam_profile): pi agent, settings-driven local profiles, optional key env"
```

---

### Task 5: Register the local provider on the launch path

**Files:**
- Modify: `pi_harness/pi_models.py` (new helper), `pi_harness/cli.py:148` (call it in `launch`)
- Test: `tests/test_pi_models.py` (new test)

- [ ] **Step 1: Write the failing test** — add to `tests/test_pi_models.py`:

```python
def test_ensure_local_provider_from_settings_registers_when_local(tmp_path):
    from pi_harness.pi_models import ensure_local_provider_from_settings
    from pi_harness.settings import HarnessSettings, BucketConfig
    import json

    models_path = tmp_path / "models.json"
    settings = HarnessSettings(
        orchestrator=BucketConfig(provider="local", model="mlx-a"),
        builder=BucketConfig(provider="local", model="mlx-b"),
        local_base_url="http://localhost:8080/v1",
    )
    assert ensure_local_provider_from_settings(settings, pi_models_path=models_path) is True
    data = json.loads(models_path.read_text())
    prov = data["providers"]["harness-local"]
    assert prov["baseUrl"] == "http://localhost:8080/v1"
    assert {m["id"] for m in prov["models"]} == {"mlx-a", "mlx-b"}


def test_ensure_local_provider_noop_when_all_api(tmp_path):
    from pi_harness.pi_models import ensure_local_provider_from_settings
    from pi_harness.settings import HarnessSettings, BucketConfig

    models_path = tmp_path / "models.json"
    settings = HarnessSettings(
        orchestrator=BucketConfig(provider="api", model="gpt-5"),
        builder=BucketConfig(provider="api", model="gpt-5-mini"),
    )
    assert ensure_local_provider_from_settings(settings, pi_models_path=models_path) is False
    assert not models_path.exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_pi_models.py -k ensure_local_provider -q`
Expected: FAIL — `ImportError: cannot import name 'ensure_local_provider_from_settings'`.

- [ ] **Step 3: Implement** — append to `pi_harness/pi_models.py` (and add the name to `__all__`):

```python
def ensure_local_provider_from_settings(
    settings=None, *, pi_models_path: Path | str | None = None
) -> bool:
    """If any bucket selects `local`, register the harness-local provider in
    pi's models.json (so a run works without first opening the Settings UI).
    Returns True if a registration was performed."""
    from pi_harness.agent_wrapper import LOCAL_PROVIDER_NAME
    from pi_harness.settings import load_settings

    s = settings if settings is not None else load_settings()
    local_models = [
        b.model for b in (s.orchestrator, s.builder) if b.provider == "local"
    ]
    if not local_models:
        return False
    ensure_pi_provider(
        name=LOCAL_PROVIDER_NAME,
        base_url=s.local_base_url,
        model_ids=local_models,
        pi_models_path=pi_models_path,
    )
    return True
```

In `pi_harness/cli.py`, in `launch()` right after `cfg = load_config()` (line 148):
```python
    from pi_harness.pi_models import ensure_local_provider_from_settings
    ensure_local_provider_from_settings()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_pi_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/pi_models.py pi_harness/cli.py tests/test_pi_models.py
git commit -m "feat(launch): auto-register local provider from settings on the run path"
```

---

### Task 6: Full-suite green + air-gap acceptance

**Files:** none new; verification + runbook pointer.

- [ ] **Step 1: Full regression**

Run: `pytest -m "not smoke" -q`
Expected: PASS, with no decrease from the Task 0 baseline count.

- [ ] **Step 2: No-key import/CLI smoke (unit-level air-gap proof)**

Run:
```bash
env -u OPENAI_API_KEY .venv/bin/python -c "
from pi_harness.config import load_config
from pi_harness.agent_wrapper import _resolve_provider_model, LOCAL_PROVIDER_NAME
load_config(env_file=None)
assert _resolve_provider_model('reasoning')[0] == LOCAL_PROVIDER_NAME
assert _resolve_provider_model('fast')[0] == LOCAL_PROVIDER_NAME
print('OK: no key, both buckets resolve local')
"
```
Expected: `OK: no key, both buckets resolve local`.

- [ ] **Step 3: Live end-to-end (requires Runbook 0 — the MLX server running).** This is the real acceptance gate and is operator-verified, not a unit test. With `mlx_lm.server` up on `:8080` and the dev model loaded, run a tiny spec through `ms launch` **with networking to the internet disabled** and confirm: the run completes, `trajectory.db` shows per-step `tokens_in/out` + `duration_ms`, and `~/.pi/agent/models.json` has the `harness-local` provider. Record the result in `docs/runbooks/00-local-serving.md`. **If pi's `--provider/--model/--base-url` or the ClawTeam profile model interact unexpectedly with `agent_wrapper --bucket`, fix the normalizer here** (the PRD's "verify against the real CLI" mandate).

- [ ] **Step 4: Open the PR**

```bash
git push -u origin feat/sovereign-local-default
gh pr create --fill --title "Phase 1: sovereign local-default harness"
```

---

## Self-review notes
- **Spec coverage (PRD Phase 1):** key-optional ✅ T1; settings local default ✅ T3; pi_models launch registration ✅ T5; clawteam_profile codex→pi + base_url + generalized tiers ✅ T4; air-gap test ✅ T6. The PRD's "add local serving config to config.py" is satisfied by keeping base-URL authority in `settings.py` (single source) rather than duplicating into `config.py` — noted intentional deviation.
- **Open integration risk (T6 Step 3):** how ClawTeam consumes the registered profile model vs. `agent_wrapper --bucket` is verified-on-first-run, not assumed. Budget adjustment time.
- **Not in scope (later phases):** tool-calling reliability (Plan B), benchmark runner (Plan C), evidence store (Plan D).
