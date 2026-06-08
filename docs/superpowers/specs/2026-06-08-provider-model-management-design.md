# Spec — Provider & Model Management (CLI + GUI)

> **Status:** Approved design (2026-06-08) · **Owner:** Pranav · **Builds on:** Phase 1 (`feat/sovereign-local-default`) · **Branch:** `feat/provider-model-management`
> **Source:** in-session brainstorm 2026-06-08; three locked decisions below.

## 1. Background & problem

After Phase 1, mannschaft defaults to local MLX and supports cloud (`api`) as an opt-in fallback. But the cloud path is awkward: the `/settings` picker has a **hardcoded** model list, **no API-key field** (the key must be hand-placed in `.env`), **no cloud model discovery**, **no guided setup**, and **no way to switch models mid-session** safely. Local discovery exists (`GET /settings/models/local-models`) but cloud has no equivalent.

This feature adds a **provider & model management layer**: connect a provider (OpenAI-via-key or local), discover the models actually available to you, assign them to the orchestrator/builder buckets, and switch later from **CLI and GUI** — with switching **blocked while a run is building**.

## 2. Goals / non-goals

**Goals**
- Discover models from two sources — the local server *and* the user's OpenAI key — in CLI and GUI.
- Let the user **enter an API key securely** (masked, chmod-600 storage, never logged).
- A **setup flow**: choose provider → key/local → discover → assign models to buckets.
- A **mid-session switch** (`ms models` + GUI quick-switcher) that is **blocked during an active run**.

**Non-goals (v1)**
- Providers other than **OpenAI** for cloud discovery (Anthropic/Google/OpenRouter are later; the adapter seam is designed to allow them).
- OS-keychain storage (chmod-600 file only, per decision).
- A literal in-dashboard `/`-command palette (CLI command + GUI quick-switcher only, per decision).
- Auto-registering cloud providers in pi's registry beyond what's needed (tracked as a Phase-1 follow-up).

## 3. Locked decisions
1. **Surface:** CLI `ms models` **and** a GUI quick-switcher (no command palette).
2. **Cloud scope:** **OpenAI only** to start; adapter seam for later providers.
3. **Key storage:** **chmod-600 file** at `~/.config/pi-harness/.env` (existing secrets convention).

**Design choices made (within the approved design):**
- Key entry **= validation + discovery in one step** (enter key → list `/v1/models` → valid? + list).
- **Enhance the existing `/settings` picker**, not a separate wizard component; `ms setup` wraps the same backend.
- **Idle gate is backend-authoritative** (HTTP 409), reflected by CLI/GUI.

## 4. Architecture — five components

```
 CLI (ms models / ms setup / ms models key)        GUI (/settings + header quick-switcher)
                 │                                              │
                 └───────────────┬──────────────────────────────┘
                                 │  HTTP (loopback)
                 ┌───────────────▼───────────────────────────┐
                 │  api/routes/settings.py (extended)         │
                 │   PUT /settings/key   GET .../cloud-models │
                 │   GET /settings/run-active                 │
                 │   PUT /settings/models (409 if run active) │
                 └───────┬───────────────────┬────────────────┘
                         │                   │
                ┌────────▼─────┐     ┌────────▼─────────┐
                │ keystore.py  │     │ discovery.py     │
                │ (chmod-600)  │     │ local + openai   │
                └──────────────┘     └──────────────────┘
```

### 4.1 `pi_harness/keystore.py` (new)
- Single secret home: `~/.config/pi-harness/.env` (honor an env override; chmod 600 on write; create parent dir).
- API: `set_key(provider, value)`, `get_key(provider) -> str|None`, `has_key(provider) -> bool`, `mask(value) -> str` (e.g. `sk-…last4`).
- Maps provider → env var (`openai` → `OPENAI_API_KEY`).
- **Never logs the value.** On write, set file mode 600. The launch path must load this file into the environment (extend `config.py`'s `load_dotenv` to also read it, or have it be the `.env` source) so the pi subprocess inherits the key.

### 4.2 `pi_harness/discovery.py` (new)
- `list_models(provider, *, base_url=None, api_key=None) -> list[str]`.
  - `local`: `GET <base_url>/v1/models` (reuse the loopback/SSRF-guarded logic already in the settings route; factor it here).
  - `openai`: `GET https://api.openai.com/v1/models` with bearer key; filter to chat-capable ids (keep `gpt-*`, `o*`; drop embeddings/audio/image/moderation). Host is fixed (no SSRF surface).
- A non-200 / network error returns a typed result the callers can render as a hint (mirrors the existing `{models, error}` shape), and for key validation signals invalid/unreachable distinctly.

### 4.3 `api/routes/settings.py` (extended)
- `PUT /settings/key` — body `{provider, api_key}`. Validate by calling `discovery.list_models("openai", api_key=...)`; on success store via keystore and return `{ok: true, masked, models}`. **Never echo the raw key.** On invalid key → 400 with a non-leaky message.
- `GET /settings/models/cloud-models?provider=openai` — discover using the stored key; `{models, error?}`.
- `GET /settings/run-active` — `{active: bool, run_id?: str}` (source of truth for the gate).
- `PUT /settings/models` — **return 409 if a run is active** (before persisting), else behave as today.

### 4.4 CLI — `ms models` group (in `cli.py`)
- `ms models` — print current bucket selection + available models (local always; cloud if a key is stored).
- `ms models set --bucket {orchestrator|builder} --provider {local|api} --model <id>` — persist; **error if a run is active** (calls the same run-active check). Validates the model is in the discovered set (warn-only if discovery unavailable).
- `ms models key --provider openai` — **hidden-input prompt** (no echo), validate+store via keystore.
- `ms setup` — wizard: provider → (cloud: key→validate+discover | local: base_url→discover) → choose models per bucket → save. `ms doctor` points here on a fresh box.

### 4.5 GUI — `ui/app/settings/page.tsx` + header quick-switcher
- Add a **masked API-key field** + **Connect** button (calls `PUT /settings/key`); on success the cloud model field becomes a dropdown from **real discovery** (replacing the hardcoded `API_MODELS`).
- The existing bucket cards remain the assignment step; first-run (no key/settings) reads as the setup wizard.
- A **header quick-switcher** (per-bucket model dropdown) that **disables while a run is active** (polls `GET /settings/run-active`), tooltip “stop the run to switch.”

## 5. Key flows
- **Initial setup:** `ms setup` / first-run GUI → provider → key(validate+discover)/local(base_url+discover) → assign → save.
- **Re-discover:** `ms models` / GUI “Discover” re-queries both sources.
- **Mid-session switch:** quick-switcher / `ms models set` → backend 409 while building; GUI greys the control; CLI errors clearly.

## 6. Idle gate
Backend-authoritative. `GET /settings/run-active` is the single source of truth; `PUT /settings/models` and `ms models set` consult it and refuse with 409 / a clear CLI error when a run is in progress. **The exact run-active signal is pinned during planning** (candidate: coordinator/run state already used by `ms stop` + the trajectory `runs`/active-run tracking). Rationale: `agent_wrapper` reads settings per agent spawn, so a mid-run change would inconsistently affect later-spawned agents.

## 7. Security requirements (non-negotiable)
- Key never logged, never echoed, never returned raw (masked only).
- Stored file is chmod 600; parent dir created with safe perms.
- Cloud calls go only to the fixed OpenAI host; local calls keep the existing loopback/RFC1918 SSRF guard.
- Cloud-model listing is **opt-in** (only when the user adds a key / picks api) — no auto-phone-home — preserving the air-gap default.

## 8. Error handling
- Invalid/unreachable key → 400 (HTTP) / clear CLI message; never leak the key or raw upstream error.
- Discovery failure → `{models: [], error}` hint, not a 500; UI shows the hint.
- Switch while building → 409 / CLI error naming the active run.
- Missing key at launch for an `api` bucket → the existing Phase-1 `ConfigError` guard (lazy, clear).

## 9. Testing strategy
- **keystore:** set/get/has/mask round-trip; file mode is 600; value never appears in logs/reprs; env-override honored. (tmp HOME.)
- **discovery:** openai list filters non-chat ids (mock HTTP); local reuses guarded fetch; error shape on non-200; injected HTTP client for tests.
- **routes:** `PUT /settings/key` validates+stores+masks (never echoes raw); `cloud-models` returns discovered list; `run-active` reflects state; `PUT /settings/models` → 409 when active. (TestClient + mocked discovery + tmp HOME.)
- **CLI:** `ms models set` blocked when active; `ms models key` reads hidden input (monkeypatched) and stores; `ms setup` happy path. (typer CliRunner + tmp HOME.)
- **GUI:** component-level where practical; otherwise manual verification via `ms up` against a running backend (recorded in a runbook).
- Run with `-m "not smoke"`.

## 10. Phasing
- **Phase A — backend + CLI:** keystore, discovery, the four route changes, run-active, `ms models`/`ms models key`/`ms setup`. Fully TDD-able; sufficient for an end-to-end CLI test.
- **Phase B — GUI:** key field + real discovery wiring + header quick-switcher + idle polling.

## 11. Open items (pin during planning)
- The authoritative run-active signal (§6).
- Whether `config.py` should load `~/.config/pi-harness/.env` directly or the repo `.env` symlinks to it (keystore must land where the launch path reads).
- Exact OpenAI chat-model id filter rules.
