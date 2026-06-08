# Provider & Model Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Connect a provider (OpenAI-via-key or local), discover available models, assign to buckets, and switch from CLI + GUI — switching blocked while a run is active.

**Spec:** `docs/superpowers/specs/2026-06-08-provider-model-management-design.md`. **Branch:** `feat/provider-model-management` (stacked on Phase 1).

**Architecture (verified surface map):** key in a chmod-600 file (`~/.config/pi-harness/.env`); a discovery module (local + OpenAI); HTTP routes + an in-process CLI; GUI in Phase B. Verified facts:
- **Run-active = `query_run_summaries(status="running", limit=1, db_path=…)`** (`trajectory/runs.py:238`). Terminal = {succeeded,failed,cancelled}. Same call from route (`request.app.state.config.trajectory_db_path`) and CLI (`load_config().trajectory_db_path`).
- **Key reaches pi via `ClawTeamClient._env()` (`clawteam/client.py:90-93`) = `Config.openai_api_key`.** So extend `config.py:load_config()` to load the keystore file `override=True` after the repo `.env`. The agent_wrapper does NOT source the key.
- **Router-prefix trap:** existing router prefix is `/settings/models`; `/settings/key` + `/settings/run-active` need a SECOND `APIRouter(prefix="/settings")`. `/cloud-models` hangs off the existing one.
- **CLI is in-process** (no loopback HTTP anywhere today). Persist via `save_settings` + replicate `ensure_pi_provider` for local buckets.
- **Bucket vocab:** user-facing = `orchestrator|builder` (settings), NOT `reasoning|fast` (wrapper).

**Run tests with:** `pytest -m "not smoke" -q`.

---

## Phase A — backend + CLI (TDD; the e2e-testable spine)

### Task 1: `keystore.py` — chmod-600 secret store
**Files:** Create `pi_harness/keystore.py`, `tests/test_keystore.py`.

- [ ] **T1.1 Tests (RED):** `tests/test_keystore.py` (tmp keystore via `PI_HARNESS_KEYSTORE_PATH`):
  - `set_key("openai","sk-abcdEFGH")` then `get_key("openai")=="sk-abcdEFGH"`, `has_key("openai")` True.
  - After `set_key`, `oct(path.stat().st_mode & 0o777) == "0o600"`.
  - `mask("sk-abcdEFGH")` returns something containing only the last 4 (`EFGH`) and never the full key.
  - **Preserve foreign lines:** pre-write the file with `PI_HARNESS_SMOKE_EXECUTOR=pi\n`, then `set_key("openai","sk-x")`; both keys present afterwards.
  - `keystore_path()` honors `PI_HARNESS_KEYSTORE_PATH`.
- [ ] **T1.2 Implement:** mirror `settings.py:58-64` for `keystore_path()` (env override `PI_HARNESS_KEYSTORE_PATH`, default `~/.config/pi-harness/.env`). Use `dotenv.set_key`/`dotenv_values` (preserves other lines) OR a careful line-merge; `path.parent.mkdir(parents=True, exist_ok=True)`; `os.chmod(path, 0o600)` after every write. `PROVIDER_ENV = {"openai": "OPENAI_API_KEY"}`. `mask(v)` → `f"{v[:3]}…{v[-4:]}"` (guard short values). Never log the value.
- [ ] **T1.3 GREEN + commit** `feat(keystore): chmod-600 provider key store`.

### Task 2: `config.py` loads the keystore (key reaches launch env)
**Files:** Modify `pi_harness/config.py:90-95`; `tests/test_config.py`.

- [ ] **T2.1 Test (RED):** with `OPENAI_API_KEY` unset in env, write `sk-fromkeystore` into a tmp keystore (`PI_HARNESS_KEYSTORE_PATH`), call `load_config(env_file=None)`, assert `cfg.openai_api_key == "sk-fromkeystore"`.
- [ ] **T2.2 Implement:** in `load_config`, after the repo `.env` block, add:
  ```python
  from pi_harness.keystore import keystore_path
  ks = keystore_path()
  if ks.exists():
      load_dotenv(ks, override=True)   # keystore is the canonical secret home; wins over a stale repo .env
  ```
  (Read keystore AFTER repo `.env` with `override=True`; then the existing `os.environ.get("OPENAI_API_KEY")` read picks it up.)
- [ ] **T2.3 GREEN + full suite + commit** `feat(config): load keystore secrets so they reach the launch env`.

### Task 3: `discovery.py` — local + OpenAI model listing
**Files:** Create `pi_harness/url_validation.py` (move `validate_local_url`), `pi_harness/discovery.py`, `tests/test_discovery.py`. Modify `api/routes/settings.py` to re-import `validate_local_url` (keep name importable — 5 SSRF tests depend on it).

- [ ] **T3.1 Tests (RED):** `tests/test_discovery.py` (monkeypatch `pi_harness.discovery.httpx.get`):
  - openai: a fake `{"data":[{"id":"gpt-5"},{"id":"text-embedding-3-large"},{"id":"o3"},{"id":"whisper-1"},{"id":"dall-e-3"}]}` → `{"models":["gpt-5","o3"]}` (chat-only filter).
  - openai 401 / `httpx.HTTPError` → `{"models":[], "error": "..."}` (no raise, no key/body leak).
  - local: an SSRF target (e.g. `http://169.254.169.254`) → error, not a fetch (reuses `validate_local_url`).
- [ ] **T3.2 Implement:** move `validate_local_url` to `pi_harness/url_validation.py` verbatim; in `settings.py` replace the def with `from pi_harness.url_validation import validate_local_url` (name stays importable). `discovery.list_models(provider, *, base_url=None, api_key=None) -> dict`:
  - `local`: `validate_local_url(base_url)`; `httpx.get(base_url.rstrip('/')+'/models', timeout=3.0, follow_redirects=False)`; parse `data[].id`.
  - `openai`: `httpx.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=5.0)`; filter ids: keep `id.startswith(("gpt-","o"))` and not any banned substring `{"embedding","whisper","tts","dall-e","-audio","-image","moderation","-realtime"}`.
  - Any `(httpx.HTTPError, ValueError)` or non-200 → `{"models":[], "error": <non-leaky>}`.
- [ ] **T3.3 GREEN + run `test_settings.py` (SSRF tests still pass) + commit** `feat(discovery): local + OpenAI model discovery; extract url_validation`.

### Task 4: settings routes — key / cloud-models / run-active / 409 gate
**Files:** Modify `pi_harness/api/routes/settings.py`, `pi_harness/api/server.py`; extend `tests/api/test_settings.py`.

- [ ] **T4.1 Tests (RED):** in `tests/api/test_settings.py` (reuse `client`/`cfg`/`seed_run` fixtures; `PI_HARNESS_KEYSTORE_PATH`→tmp; monkeypatch `discovery.list_models`):
  - `PUT /settings/key {provider:"openai", api_key:"sk-live"}` with discovery returning models → 200, body has `masked` (not the raw key) + `models`; keystore now has the key.
  - `PUT /settings/key` with discovery returning `{error}` → 400, raw key NOT in body.
  - `GET /settings/models/cloud-models?provider=openai` → discovered list when key stored; `{error}` when not.
  - `GET /settings/run-active` → `{active:true, run_id}` when `seed_run(status="running")`, else `{active:false}`.
  - `PUT /settings/models` → **409** when a running run is seeded; 200 when idle.
- [ ] **T4.2 Implement:**
  - Add `settings_router = APIRouter(prefix="/settings", tags=["settings"])`; put `PUT /key` (`KeyBody(provider: Literal["openai"], api_key: str=Field(min_length=1))`) + `GET /run-active` on it. Add `@router.get("/cloud-models")` on the existing `/settings/models` router.
  - `PUT /key`: `r = discovery.list_models("openai", api_key=body.api_key)`; if `r.get("error") or not r["models"]` → `HTTPException(400, "invalid or unauthorized key")`; else `keystore.set_key("openai", body.api_key)`, return `{"ok":True,"masked":keystore.mask(body.api_key),"models":r["models"]}`.
  - `GET /run-active`: `rows = query_run_summaries(status="running", limit=1, db_path=request.app.state.config.trajectory_db_path)`; `{"active":bool(rows),"run_id": rows[0].run_id if rows else None}`.
  - `put_settings`: add `request: Request`; before `save_settings`, `if query_run_summaries(status="running", limit=1, db_path=request.app.state.config.trajectory_db_path): raise HTTPException(409, f"run {...} is active; stop it before switching models")`.
  - `server.py`: import + `include_router` the new `settings_router` (alongside the existing one).
- [ ] **T4.3 GREEN + full suite + commit** `feat(api): key/cloud-models/run-active routes + 409 model-switch gate`.

### Task 5: CLI — `ms models` group + `ms setup`
**Files:** Modify `pi_harness/cli.py`; extend `tests/test_cli.py`.

- [ ] **T5.1 Tests (RED):** CliRunner + tmp `PI_HARNESS_HOME`/`PI_HARNESS_KEYSTORE_PATH`:
  - `ms models set --bucket orchestrator --provider local --model mlx-x` when a running run is seeded in the tmp trajectory db → exit 1, message names the active run; settings NOT changed.
  - same when idle → exit 0; `models.json` shows orchestrator local/mlx-x.
  - `ms models key --provider openai` with `getpass.getpass` monkeypatched to return `"sk-cli"` and `discovery.list_models` monkeypatched to return models → stores via keystore; the key never appears in stdout.
- [ ] **T5.2 Implement:** `models_app = typer.Typer(help="…")`; `app.add_typer(models_app, name="models")` (mirror `spec_app` at cli.py:457). Commands:
  - `set(bucket: str, provider: str, model: str)`: load_config; `if query_run_summaries(status="running", limit=1, db_path=cfg.trajectory_db_path): echo(err) + raise Exit(1)`. Build new `HarnessSettings` from current `load_settings()` swapping the named bucket (`orchestrator|builder`), `save_settings`, and if provider local call `ensure_local_provider_from_settings()` (replicate the route's pi_models side-effect).
  - `key(provider: str = "openai")`: lazy `import getpass`; `val = getpass.getpass("API key: ")`; `r = discovery.list_models("openai", api_key=val)`; on error echo + Exit(1); else `keystore.set_key("openai", val)`; echo masked only.
  - `list()` (default): print current bucket selection + `discovery.list_models` for local (always) and openai (if `keystore.has_key`).
  - `setup()` standalone `@app.command()`: prompt provider → key/local → discover → choose models → save (compose the above).
- [ ] **T5.3 GREEN + full suite + commit** `feat(cli): ms models {set,key,list} + ms setup (idle-gated, in-process)`.

### Task 6: Phase A acceptance
- [ ] Full suite green (`-m "not smoke"`), no regressions.
- [ ] Manual: `ms models key` (paste a real key) → `ms models set --bucket orchestrator --provider api --model gpt-5` → confirm `models.json` + keystore; with the mlx server up, `ms models set ... --provider local` and a quick `ms launch` still works. Record in the spec/runbook.

---

## Phase B — GUI (manual-verified; no JS test harness in ui/)
- `ui/lib/api.ts`: add `setApiKey` (PUT /settings/key), `getCloudModels`, `getRunActive` (fetch-wrapped, BASE at api.ts:23).
- `ui/lib/use-run-active.ts` (new): TanStack `useQuery` `refetchInterval: 2000`.
- `ui/components/ModelQuickSwitcher.tsx` (new): per-bucket dropdown; `disabled` + `opacity-60` while `useRunActive().data.active`; tooltip "stop the run to switch".
- `ui/app/settings/page.tsx`: masked API-key field + Connect (`setApiKey`); on success replace hardcoded `API_MODELS` with `getCloudModels`; inline 400/409 in `text-red-600`. **UI never sees the raw key** — only the masked string.
- `ui/app/layout.tsx`: mount `ModelQuickSwitcher` (or a settings-page "Quick Switch" card if header is heavy).
- Verify via `ms up` against the running backend; record screenshots.

## Self-review
- Spec coverage: keystore ✅T1; key-to-launch ✅T2; discovery ✅T3; routes+409 ✅T4; CLI+setup ✅T5; GUI ✅PhaseB. Idle gate single-source ✅ (T4/T5 same `query_run_summaries`). Security (mask/chmod/no-leak) ✅ T1/T3/T4.
- Gotchas honored: 2nd router (T4), `request` param (T4), preserve `.env` lines + re-chmod (T1), override order (T2), `validate_local_url` importable (T3), in-process CLI + `ensure_pi_provider` for local (T5), `orchestrator|builder` vocab (T5), smoke excluded.
