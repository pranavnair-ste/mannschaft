# Observability Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the remaining observability layer: a single env-driven obs config, retry/backoff on the bridge POST, a live multi-run bridge tailer, a `pi-harness up` subprocess supervisor + `pi-harness doctor` preflight, a runtime deep-link served from the backend, and auth/port hardening of the fork server.

**Architecture:** One source of truth for obs settings lives on the env-driven `Config` (mirroring `DashboardConfig`). The bridge gains a retrying transport and a deterministic live tailer that re-translates a whole run each tick but ships only the new envelope tail (preserving the fork's `event_id` PK + `UNIQUE(session_id, seq)` idempotency). A new `Supervisor` (Popen + signal/atexit teardown) boots four processes: the fork's Bun server, the bridge tailer, the FastAPI dashboard, and the Next.js UI. The run-detail deep-link is moved off unwired build-time `NEXT_PUBLIC_*` env onto a backend `GET /observability/link` endpoint so the real token/port are runtime-resolved. Fork hardening is a cross-repo PR.

**Tech Stack:** Python 3.11, Typer, FastAPI/uvicorn, urllib, sqlite (WAL), pytest (+pytest-mock, pytest-timeout, freezegun); Next.js 14 (TS); Bun/TypeScript (fork repo).

**Decisions locked (2026-06-07):** Fork hardening = implement + open PR on `pranavnair-ste/pi-agent-observability` (never push `upstream`/disler). Fork path = `PI_HARNESS_OBS_FORK_DIR` (default `~/Desktop/Personal/pi-agent-observability`). Next.js boot = `next dev` (4 supervised processes).

**Test safety (MANDATORY for every task):** Activate the venv first (`source .venv/bin/activate`; bare `python` is not on PATH). Run only `python -m pytest -m "not smoke" …`. NEVER add `@pytest.mark.smoke` to new tests and never set `PI_HARNESS_RUN_SMOKE=1` — smoke launches a real ClawTeam team that git-commits to the branch. Implementation subagents must NOT run any `git` mutation (no add/commit/branch/push); the orchestrator handles all git.

---

## File Structure

**Create:**
- `pi_harness/observability/supervisor.py` — `Proc` dataclass + `Supervisor` (Popen lifecycle, readiness polling, signal/atexit teardown). One responsibility: own N child processes.
- `pi_harness/api/routes/observability.py` — `GET /observability/link` returning a runtime-resolved tokenized deep-link.
- `tests/observability/test_retry.py` — retry/backoff classifier + wrapper.
- `tests/observability/test_tailer.py` — live tailer (ship-tail, terminal stop, multi-run).
- `tests/observability/test_supervisor.py` — supervisor spawn/teardown/readiness (FakeProc).
- `tests/test_cli_up_doctor.py` — `up` + `doctor` CLI via CliRunner.
- `tests/api/test_observability_link.py` — deep-link endpoint.

**Modify:**
- `pi_harness/config.py` — add obs fields + validation to `Config`/`load_config`.
- `pi_harness/observability/bridge.py` — drop `devtoken` literal; add `timeout`, `_is_retryable`, `post_events_with_retry`, `tail_once`, `follow_runs`, `_TERMINAL`.
- `pi_harness/cli.py` — `observe --follow`; new `up` and `doctor` commands.
- `pi_harness/api/server.py` — register the observability router.
- `ui/lib/api.ts` — add `obsLink(runId)`.
- `ui/app/runs/[runId]/page.tsx` — use the backend link instead of `NEXT_PUBLIC_OBS_*`.
- `.env.example` — document `OBS_*` + `PI_HARNESS_OBS_*`.
- `tests/test_config.py`, `tests/observability/test_bridge.py`, `tests/observability/test_cli_observe.py` — update for new config/token sourcing.

**Fork repo (separate PR):**
- `apps/observability/server.ts`, `justfile`, `.env.sample`.

---

## Task 0: Obs config on `Config` (foundation)

**Files:**
- Modify: `pi_harness/config.py`
- Test: `tests/test_config.py`

Contract (env-driven, mirrors `DashboardConfig`/`OPENAI_API_KEY`):
- `obs_enabled: bool` ← `PI_HARNESS_OBS_ENABLED` truthy (`{"1","true","yes","on"}`), default `False`.
- `obs_host: str` ← `OBS_HOST`, default `"127.0.0.1"`.
- `obs_port: int` ← `OBS_PORT`, default `43190` (raise `ConfigError` if non-int / out of 1–65535).
- `obs_auth_token: str = field(repr=False)` ← `OBS_AUTH_TOKEN`.strip(), default `""` (NO `devtoken`).
- `obs_fork_dir: Path` ← `PI_HARNESS_OBS_FORK_DIR`, default `~/Desktop/Personal/pi-agent-observability`, via `_expand`.
- `obs_server_url` property → `OBS_SERVER_URL` if set, else `f"http://{obs_host}:{obs_port}"`.
- Validation: if `obs_enabled and not obs_auth_token` → `ConfigError("OBS_AUTH_TOKEN required when observability is enabled")`. When disabled, empty token is allowed.

- [ ] **Step 1: Write failing tests** in `tests/test_config.py`

```python
def test_obs_defaults_disabled(monkeypatch):
    for k in ("PI_HARNESS_OBS_ENABLED","OBS_HOST","OBS_PORT","OBS_AUTH_TOKEN",
              "PI_HARNESS_OBS_FORK_DIR","OBS_SERVER_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = load_config(env_file=None)
    assert cfg.obs_enabled is False
    assert cfg.obs_host == "127.0.0.1"
    assert cfg.obs_port == 43190
    assert cfg.obs_auth_token == ""
    assert cfg.obs_server_url == "http://127.0.0.1:43190"

def test_obs_server_url_composed_and_overridable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OBS_HOST", "127.0.0.1"); monkeypatch.setenv("OBS_PORT", "5000")
    assert load_config(env_file=None).obs_server_url == "http://127.0.0.1:5000"
    monkeypatch.setenv("OBS_SERVER_URL", "http://example:9/")
    assert load_config(env_file=None).obs_server_url == "http://example:9/"

def test_obs_enabled_requires_token(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PI_HARNESS_OBS_ENABLED", "1")
    monkeypatch.delenv("OBS_AUTH_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="OBS_AUTH_TOKEN"):
        load_config(env_file=None)

def test_obs_token_not_in_repr(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OBS_AUTH_TOKEN", "super-secret-xyz")
    assert "super-secret-xyz" not in repr(load_config(env_file=None))

def test_obs_port_invalid_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OBS_PORT", "not-a-port")
    with pytest.raises(ConfigError, match="OBS_PORT"):
        load_config(env_file=None)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_config.py -k obs -v`
Expected: FAIL (`AttributeError: 'Config' object has no attribute 'obs_enabled'`).

- [ ] **Step 3: Implement** — add fields to the `Config` dataclass and parsing to `load_config`. Add a module-level default and a `_bool_env` helper:

```python
DEFAULT_OBS_FORK_DIR = "~/Desktop/Personal/pi-agent-observability"

def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
```

In the `Config` dataclass (append after `trajectory_db_path`):

```python
    obs_enabled: bool
    obs_host: str
    obs_port: int
    obs_auth_token: str = field(repr=False)  # never echo the secret in reprs/tracebacks/logs
    obs_fork_dir: Path

    @property
    def obs_server_url(self) -> str:
        override = os.environ.get("OBS_SERVER_URL", "").strip()
        return override if override else f"http://{self.obs_host}:{self.obs_port}"
```

> NOTE: `obs_server_url` reads `OBS_SERVER_URL` at access time. That is acceptable here (a property, not a frozen field) and keeps back-compat with the existing `OBS_SERVER_URL` env. The token/host/port ARE frozen fields resolved in `load_config`.

In `load_config`, after the existing fields:

```python
    obs_enabled = _bool_env(os.environ.get("PI_HARNESS_OBS_ENABLED", ""))
    obs_host = os.environ.get("OBS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port_raw = os.environ.get("OBS_PORT", "43190").strip()
    try:
        obs_port = int(port_raw)
    except ValueError as exc:
        raise ConfigError(f"OBS_PORT must be an integer, got {port_raw!r}") from exc
    if not (1 <= obs_port <= 65535):
        raise ConfigError(f"OBS_PORT out of range 1-65535: {obs_port}")
    obs_auth_token = os.environ.get("OBS_AUTH_TOKEN", "").strip()
    if obs_enabled and not obs_auth_token:
        raise ConfigError("OBS_AUTH_TOKEN required when observability is enabled "
                          "(PI_HARNESS_OBS_ENABLED is set)")
    obs_fork_dir = _expand(os.environ.get("PI_HARNESS_OBS_FORK_DIR", DEFAULT_OBS_FORK_DIR))
```

Then pass these into the `Config(...)` constructor call. Update any direct `Config(...)` constructions in test fixtures (`tests/api/conftest.py`) to pass the new fields (use `obs_enabled=False, obs_host="127.0.0.1", obs_port=43190, obs_auth_token="", obs_fork_dir=tmp_path`).

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_config.py -k obs -v` → PASS.
- [ ] **Step 5: Fix fallout** — `python -m pytest -m "not smoke" -q` and fix any `Config(...)` constructor callers that now miss args (esp. `tests/api/conftest.py`).

---

## Task 1: Retry/backoff + timeout on the bridge transport

**Files:**
- Modify: `pi_harness/observability/bridge.py`
- Test: `tests/observability/test_retry.py`

Contract:
- Add `timeout: float = 15.0` to `post_events` (`urlopen(req, timeout=timeout)`).
- Remove the `devtoken` literal: `DEFAULT_TOKEN = os.environ.get("OBS_AUTH_TOKEN", "")`.
- `_is_retryable(exc)`: `True` for `urllib.error.HTTPError` with `.code in {408,429,500,502,503,504}`; `True` for `urllib.error.URLError` (no code: conn refused/DNS/reset); `True` for `socket.timeout`/`TimeoutError`; else `False` (permanent — e.g. 400/401/403/404/422).
- `post_events_with_retry(envelopes, url, token, *, timeout=15.0, max_attempts=4, base_delay=0.5, factor=2.0, max_delay=30.0, sleep=time.sleep)`: retry only retryable; on `HTTPError` 429 with a parseable `Retry-After` integer header, sleep that instead of the computed backoff; re-raise on permanent or when attempts exhausted.

- [ ] **Step 1: Write failing tests** `tests/observability/test_retry.py`

```python
import socket, urllib.error, io, pytest
from pi_harness.observability import bridge

def _http_error(code):
    return urllib.error.HTTPError("u", code, "msg", {}, io.BytesIO(b""))

def test_is_retryable_classification():
    assert bridge._is_retryable(_http_error(503)) is True
    assert bridge._is_retryable(_http_error(429)) is True
    assert bridge._is_retryable(_http_error(400)) is False
    assert bridge._is_retryable(_http_error(401)) is False
    assert bridge._is_retryable(urllib.error.URLError("conn refused")) is True
    assert bridge._is_retryable(socket.timeout()) is True
    assert bridge._is_retryable(ValueError("x")) is False

def test_retry_succeeds_after_transient(monkeypatch):
    calls = {"n": 0}; slept = []
    def fake_post(envs, url, token, *, timeout=15.0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("refused")
        return {"ingested": len(envs), "rejected": []}
    monkeypatch.setattr(bridge, "post_events", fake_post)
    out = bridge.post_events_with_retry([{"event_id": "a"}], "http://x", "t",
                                        sleep=slept.append, base_delay=0.5, factor=2.0)
    assert out == {"ingested": 1, "rejected": []}
    assert calls["n"] == 3
    assert slept == [0.5, 1.0]

def test_retry_reraises_permanent_immediately(monkeypatch):
    calls = {"n": 0}
    def fake_post(envs, url, token, *, timeout=15.0):
        calls["n"] += 1; raise _http_error(401)
    monkeypatch.setattr(bridge, "post_events", fake_post)
    with pytest.raises(urllib.error.HTTPError):
        bridge.post_events_with_retry([{}], "http://x", "t", sleep=lambda s: None)
    assert calls["n"] == 1

def test_retry_exhausts_and_reraises(monkeypatch):
    monkeypatch.setattr(bridge, "post_events",
                        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("x")))
    with pytest.raises(urllib.error.URLError):
        bridge.post_events_with_retry([{}], "http://x", "t", max_attempts=3, sleep=lambda s: None)
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/observability/test_retry.py -v` → FAIL (no `_is_retryable`).
- [ ] **Step 3: Implement** in `bridge.py` (add `import socket`, `import time`; change `DEFAULT_TOKEN`):

```python
DEFAULT_TOKEN = os.environ.get("OBS_AUTH_TOKEN", "")
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRYABLE_STATUS
    if isinstance(exc, urllib.error.URLError):  # conn refused / DNS / reset (HTTPError handled above)
        return True
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    return False

def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    try:
        val = exc.headers.get("Retry-After") if exc.headers else None
        return float(int(val)) if val and val.strip().isdigit() else None
    except Exception:
        return None

def post_events_with_retry(envelopes, url, token, *, timeout: float = 15.0,
                           max_attempts: int = 4, base_delay: float = 0.5,
                           factor: float = 2.0, max_delay: float = 30.0,
                           sleep=time.sleep) -> dict:
    attempt = 0
    while True:
        try:
            return post_events(envelopes, url, token, timeout=timeout)
        except Exception as exc:
            attempt += 1
            if attempt >= max_attempts or not _is_retryable(exc):
                raise
            delay = min(max_delay, base_delay * (factor ** (attempt - 1)))
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                ra = _retry_after_seconds(exc)
                if ra is not None:
                    delay = min(max_delay, ra)
            sleep(delay)
```

Change `post_events` signature to `def post_events(envelopes, url, token, *, timeout: float = 15.0)` and `urllib.request.urlopen(req, timeout=timeout)`. Have `backfill_run` call `post_events_with_retry` instead of `post_events` (root-cause hardening of the merged path).

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/observability/test_retry.py -v` → PASS.
- [ ] **Step 5: Guard regression** — `python -m pytest tests/observability -q`. If any existing test asserts the old `devtoken` default or a no-timeout `post_events`, update it to the new contract.

---

## Task 2: Live multi-run bridge tailer

**Files:**
- Modify: `pi_harness/observability/bridge.py`, `pi_harness/cli.py`
- Test: `tests/observability/test_tailer.py`

Key invariant (from the seq-hazard analysis): `envelopes_for_run` is deterministic and APPEND-ONLY as rows grow — the seq/event_id of any already-emitted envelope never changes when new rows arrive. So a live tailer must re-translate the WHOLE run each tick and ship only `envs[last_count:]`. Do NOT call `envelopes_for_run` on a new-rows-only slice (that resets seq to 0 → `UNIQUE(session_id, seq)` collision + different event_ids).

Contract:
- `_TERMINAL = {"succeeded", "failed", "cancelled"}` (module constant).
- `tail_once(run_id, last_count, *, url, token, db_path=None) -> int`: translate all rows, POST `envs[last_count:]` in batches of 50 via `post_events_with_retry`, return `len(envs)` (the new count). No-op when nothing new.
- `follow_runs(*, url, token, db_path=None, poll_interval=1.0, sleep=time.sleep, stop=None, max_polls=None) -> None`: each poll, enumerate `runs.query_run_summaries(db_path=db_path)`; for each non-`done` run call `tail_once`; after a run reaches a terminal status AND a poll added nothing new, mark it `done`. Stop when `stop()` is truthy, after `max_polls`, or never (daemon). `sleep(poll_interval)` at loop bottom (0.0 = no-op in tests).

- [ ] **Step 1: Write failing tests** `tests/observability/test_tailer.py` (real tmp SQLite; stub the transport)

```python
import pytest
from datetime import datetime, timezone
from pi_harness.observability import bridge
from pi_harness.trajectory import store, runs
from pi_harness.trajectory.schema import TrajectoryEvent

@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"; store.init_db(p)
    runs.register_run(run_id="r1", spec_id=None, topology="pipeline", sync_mode=None,
                      session_id=None, goal=None, team_name="team-a",
                      started_at=datetime(2026,6,7,tzinfo=timezone.utc),
                      run_spec_json="{}", db_path=p)
    return p

def _msg(step):
    return TrajectoryEvent(run_id="r1", agent_id="a1", step_id=step,
        ts=datetime(2026,6,7,tzinfo=timezone.utc), model="gpt", tool="",
        input={}, output={"text": f"hi {step}"}, duration_ms=0,
        tokens_in=1, tokens_out=1, outcome="success", classification="message")

def test_tail_once_ships_only_new(monkeypatch, db):
    posted = []
    monkeypatch.setattr(bridge, "post_events_with_retry",
                        lambda envs, url, token, **k: posted.extend(envs) or {"ingested": len(envs), "rejected": []})
    store.write_event(_msg("s1"), db_path=db)
    n1 = bridge.tail_once("r1", 0, url="http://x", token="t", db_path=db)
    assert n1 > 0 and len(posted) == n1
    first = list(posted); posted.clear()
    store.write_event(_msg("s2"), db_path=db)
    n2 = bridge.tail_once("r1", n1, url="http://x", token="t", db_path=db)
    assert n2 > n1
    # only the NEW tail shipped, and no event_id overlaps the first batch
    new_ids = {e["event_id"] for e in posted}
    assert new_ids.isdisjoint({e["event_id"] for e in first})
    assert len(posted) == n2 - n1

def test_follow_runs_stops_on_terminal(monkeypatch, db):
    posted = []
    monkeypatch.setattr(bridge, "post_events_with_retry",
                        lambda envs, url, token, **k: posted.extend(envs) or {"ingested": len(envs), "rejected": []})
    store.write_event(_msg("s1"), db_path=db)
    runs.mark_run_status("r1", "succeeded", db_path=db)
    polls = {"n": 0}
    def stop(): polls["n"] += 1; return polls["n"] >= 3
    bridge.follow_runs(url="http://x", token="t", db_path=db, poll_interval=0.0, sleep=lambda s: None, stop=stop)
    assert len(posted) > 0  # terminal run still drained once
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/observability/test_tailer.py -v` → FAIL (no `tail_once`).
- [ ] **Step 3: Implement** in `bridge.py`:

```python
from pi_harness.trajectory import runs as runs_mod  # already imports `runs as runs_mod`? confirm; reuse existing import

_TERMINAL = {"succeeded", "failed", "cancelled"}

def tail_once(run_id, last_count: int, *, url, token, db_path=None) -> int:
    ctx = _load_run_context(run_id, db_path=db_path)
    rows = _read_rows(run_id, db_path=db_path)
    envs = envelopes_for_run(rows, ctx)
    new = envs[last_count:]
    for i in range(0, len(new), 50):
        post_events_with_retry(new[i:i + 50], url, token)
    return len(envs)

def follow_runs(*, url, token, db_path=None, poll_interval: float = 1.0,
                sleep=time.sleep, stop=None, max_polls=None) -> None:
    counts: dict[str, int] = {}
    done: set[str] = set()
    polls = 0
    while True:
        for summary in runs_mod.query_run_summaries(db_path=db_path):
            rid = summary.run_id
            if rid in done:
                continue
            before = counts.get(rid, 0)
            counts[rid] = tail_once(rid, before, url=url, token=token, db_path=db_path)
            status = (runs_mod.get_run(rid, db_path=db_path) or {}).get("status")
            if status in _TERMINAL and counts[rid] == before:
                done.add(rid)
        polls += 1
        if stop is not None and stop():
            return
        if max_polls is not None and polls >= max_polls:
            return
        sleep(poll_interval)
```

> Confirm the existing import alias for `runs` in bridge.py (`from pi_harness.trajectory import runs as runs_mod` is already present per the file). Confirm `RunSummary.run_id` attribute name in `runs.py`; if it differs, adapt.

Wire CLI: in `cli.py` `observe`, add `follow: bool = typer.Option(False, "--follow", "-f", help="Stream events live to the fork until runs finish (Ctrl-C to stop).")`. When `--follow`, resolve `url/token` from `load_config()` (`cfg.obs_server_url`, `cfg.obs_auth_token`), echo a startup line, and call `bridge.follow_runs(url=…, token=…, db_path=db_path)`. Else keep the existing `backfill_run` path. Use `cfg.obs_auth_token` (not `bridge.DEFAULT_TOKEN`) for defaults; drop the `devtoken` mention in `--token` help.

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/observability/test_tailer.py -v` → PASS.
- [ ] **Step 5: Regression** — `python -m pytest tests/observability -q` → all pass.

---

## Task 3: Deep-link backend endpoint + frontend wiring

**Files:**
- Create: `pi_harness/api/routes/observability.py`
- Modify: `pi_harness/api/server.py`, `ui/lib/api.ts`, `ui/app/runs/[runId]/page.tsx`
- Test: `tests/api/test_observability_link.py`

Contract: `GET /observability/link?run_id=<id>` → `{"enabled": bool, "base": str, "url": str}` where `url = f"{base}/?token={quote(token)}#view=race&pool={run_id}&hide_after=never&show_hidden=1"`, `base = cfg.obs_server_url`, `token = cfg.obs_auth_token`. Read `cfg` from `request.app.state.config`.

- [ ] **Step 1: Write failing test** `tests/api/test_observability_link.py`

```python
def test_observability_link(client):  # `client` from tests/api/conftest.py
    r = client.get("/observability/link", params={"run_id": "run-xyz"})
    assert r.status_code == 200
    body = r.json()
    assert body["base"].startswith("http")
    assert "pool=run-xyz" in body["url"]
    assert "#view=race" in body["url"]
```

> Ensure the `client` fixture builds `create_app` with a `Config` whose obs fields are set (the conftest `cfg` gains the Task-0 fields). If the obs token is non-empty in the fixture, also assert `token=` appears in the url.

- [ ] **Step 2: Run to verify fail** — `python -m pytest tests/api/test_observability_link.py -v` → FAIL (404).
- [ ] **Step 3: Implement** `pi_harness/api/routes/observability.py`:

```python
from urllib.parse import quote
from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/observability/link")
def observability_link(run_id: str, request: Request) -> dict:
    cfg = request.app.state.config
    base = cfg.obs_server_url.rstrip("/")
    token = cfg.obs_auth_token
    frag = f"#view=race&pool={quote(run_id)}&hide_after=never&show_hidden=1"
    url = f"{base}/?token={quote(token)}{frag}" if token else f"{base}/{frag}"
    return {"enabled": cfg.obs_enabled, "base": base, "url": url}
```

Register in `api/server.py` `create_app`: `from pi_harness.api.routes.observability import router as observability_router` and `app.include_router(observability_router)` alongside the others.

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/api/test_observability_link.py -v` → PASS.
- [ ] **Step 5: Frontend** — in `ui/lib/api.ts` add:

```ts
export async function obsLink(runId: string): Promise<{enabled: boolean; base: string; url: string}> {
  const res = await fetch(`${API_BASE}/observability/link?run_id=${encodeURIComponent(runId)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`obsLink ${res.status}`);
  return res.json();
}
```

(Use the same `API_BASE`/`NEXT_PUBLIC_API_BASE` constant the file already defines.) In `ui/app/runs/[runId]/page.tsx` replace the hardcoded `process.env.NEXT_PUBLIC_OBS_URL ?? …`/`NEXT_PUBLIC_OBS_TOKEN ?? "devtoken"` href construction (line ~28) with a server-side fetch of `obsLink(detail.summary.run_id)` and use the returned `url` as the `<a href>` (fall back to a disabled/hidden link if `enabled` is false). Keep the visible link text unchanged.

- [ ] **Step 6: Type-check** — `cd ui && npx tsc --noEmit` (if available) → no new errors. If `tsc` isn't installed, skip with a note.

---

## Task 4: `Supervisor` + `pi-harness up` + `pi-harness doctor`

**Files:**
- Create: `pi_harness/observability/supervisor.py`
- Modify: `pi_harness/cli.py`
- Test: `tests/observability/test_supervisor.py`, `tests/test_cli_up_doctor.py`

Contract — `supervisor.py`:

```python
from __future__ import annotations
import atexit, signal, subprocess, sys, time, urllib.request
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Proc:
    name: str
    argv: list[str]
    cwd: Path | None = None
    env: dict | None = None
    health_url: str | None = None  # GET that returns <500 when ready

class Supervisor:
    def __init__(self, procs: list[Proc], *, sleep=time.sleep):
        self.procs = procs
        self._sleep = sleep
        self._children: list[tuple[Proc, subprocess.Popen]] = []
        self._tearing_down = False

    def start(self) -> None:
        for p in self.procs:
            child = subprocess.Popen(p.argv, cwd=str(p.cwd) if p.cwd else None,
                                     env=p.env, stdin=subprocess.DEVNULL)
            self._children.append((p, child))

    def wait_ready(self, *, timeout: float = 30.0, interval: float = 0.5) -> None:
        deadline = time.monotonic() + timeout
        for p, _ in self._children:
            if not p.health_url:
                continue
            while time.monotonic() < deadline:
                if self._probe(p.health_url):
                    break
                self._sleep(interval)

    @staticmethod
    def _probe(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
                return r.status < 500
        except Exception:
            return False

    def poll_once(self) -> Proc | None:
        for p, child in self._children:
            if child.poll() is not None:
                return p          # a child exited
        return None

    def teardown(self) -> None:
        if self._tearing_down:
            return
        self._tearing_down = True
        for _, child in reversed(self._children):
            try:
                child.terminate()
            except Exception:
                pass
        for _, child in reversed(self._children):
            try:
                child.wait(timeout=5)
            except Exception:
                try:
                    child.kill()
                except Exception:
                    pass

    def run(self, *, ready_timeout: float = 30.0, poll_interval: float = 1.0) -> int:
        atexit.register(self.teardown)
        def _handler(signum, frame):
            self.teardown(); raise SystemExit(128 + signum)
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
        self.start()
        try:
            self.wait_ready(timeout=ready_timeout)
            while True:
                dead = self.poll_once()
                if dead is not None:
                    return 1
                self._sleep(poll_interval)
        finally:
            self.teardown()
```

- [ ] **Step 1: Write failing tests** `tests/observability/test_supervisor.py` (FakeProc — never spawn real processes)

```python
from pi_harness.observability import supervisor as sup

class FakeProc:
    def __init__(self, exit_after=None):
        self._exit_after = exit_after; self._polls = 0
        self.terminated = False; self.killed = False
    def poll(self):
        self._polls += 1
        if self._exit_after is not None and self._polls > self._exit_after:
            return 0
        return None
    def wait(self, timeout=None): return 0
    def terminate(self): self.terminated = True
    def kill(self): self.killed = True

def test_start_spawns_all(monkeypatch):
    spawned = []
    monkeypatch.setattr(sup.subprocess, "Popen",
                        lambda argv, **k: spawned.append(argv) or FakeProc())
    s = sup.Supervisor([sup.Proc("a", ["x"]), sup.Proc("b", ["y"])])
    s.start()
    assert spawned == [["x"], ["y"]]

def test_teardown_terminates_in_reverse(monkeypatch):
    procs = [FakeProc(), FakeProc()]
    it = iter(procs)
    monkeypatch.setattr(sup.subprocess, "Popen", lambda argv, **k: next(it))
    s = sup.Supervisor([sup.Proc("a", ["x"]), sup.Proc("b", ["y"])])
    s.start(); s.teardown()
    assert all(p.terminated for p in procs)

def test_teardown_idempotent(monkeypatch):
    monkeypatch.setattr(sup.subprocess, "Popen", lambda argv, **k: FakeProc())
    s = sup.Supervisor([sup.Proc("a", ["x"])]); s.start()
    s.teardown(); s.teardown()  # no raise

def test_poll_detects_dead_child(monkeypatch):
    monkeypatch.setattr(sup.subprocess, "Popen", lambda argv, **k: FakeProc(exit_after=1))
    s = sup.Supervisor([sup.Proc("a", ["x"])]); s.start()
    s.poll_once()  # first poll alive
    assert s.poll_once() is not None  # second poll dead
```

- [ ] **Step 2: Run to verify fail** → FAIL (no module).
- [ ] **Step 3: Implement** `supervisor.py` as above.
- [ ] **Step 4: Run to verify pass** → PASS.
- [ ] **Step 5: CLI `up` + `doctor`** in `cli.py` (lazy imports inside body, per house style):

`up` builds the `Proc` list from `load_config()`:
- Fork: `Proc("fork", ["bun", <entry>], cwd=cfg.obs_fork_dir, env={**os.environ, "OBS_AUTH_TOKEN": cfg.obs_auth_token, "OBS_PORT": str(cfg.obs_port), "OBS_HOST": cfg.obs_host, "OBS_DEV": "1" if not cfg.obs_auth_token else ""}, health_url=f"{cfg.obs_server_url}/health")`. Determine `<entry>` by reading the fork's `package.json`/`justfile`; default `["bun", "run", "apps/observability/server.ts"]`.
- Bridge tailer: `Proc("bridge", [sys.executable, "-m", "pi_harness.cli", "observe", "--follow"], env=os.environ)`.
- FastAPI: `Proc("api", [sys.executable, "-m", "pi_harness.api.server"], env=os.environ, health_url="http://127.0.0.1:8800/healthz")`.
- Next.js: `Proc("ui", ["npm", "run", "dev"], cwd=Path("ui"), env=os.environ, health_url="http://127.0.0.1:3000")`.

Then `raise typer.Exit(Supervisor(procs).run())`. Echo the deep-link template and the fork UI URL before blocking. Add flags `--no-ui` (drop the Next.js proc) and `--ready-timeout`.

`doctor` preflights (each prints ✓/✗) and `raise typer.Exit(1)` if any hard check fails:
- `shutil.which("bun")` present; `cfg.obs_fork_dir` exists and contains the server entry.
- `shutil.which("npm")` present; `ui/node_modules` exists.
- ports 8800/3000/`cfg.obs_port` free (try `socket.socket().bind(("127.0.0.1", port))`).
- `cfg.obs_auth_token` non-empty when `cfg.obs_enabled`.
- prints the resolved deep-link template.

- [ ] **Step 6: CLI tests** `tests/test_cli_up_doctor.py` (CliRunner; patch `Supervisor.run` and `shutil.which`/`socket`):

```python
from typer.testing import CliRunner
from pi_harness.cli import app
from pi_harness.observability import supervisor as sup
runner = CliRunner()

def test_up_builds_procs_and_runs(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}
    def fake_run(self, **k): captured["procs"] = [p.name for p in self.procs]; return 0
    monkeypatch.setattr(sup.Supervisor, "run", fake_run)
    res = runner.invoke(app, ["up", "--no-ui"])
    assert res.exit_code == 0
    assert "fork" in captured["procs"] and "bridge" in captured["procs"] and "api" in captured["procs"]
    assert "ui" not in captured["procs"]

def test_doctor_reports(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code in (0, 1)  # depends on local env
    assert "bun" in res.stdout.lower()
```

- [ ] **Step 7: Run** — `python -m pytest tests/observability/test_supervisor.py tests/test_cli_up_doctor.py -v` → PASS.

---

## Task 5: Fork server auth/port hardening (SEPARATE REPO — cross-repo PR)

**Repo:** `~/Desktop/Personal/pi-agent-observability` (origin = `pranavnair-ste/pi-agent-observability`). NEVER push to `upstream` (disler). Work on branch `feat/auth-port-hardening`.

**Files:** `apps/observability/server.ts`, `justfile`, `.env.sample`.

Changes to `server.ts`:
- After `const AUTH_TOKEN = …` and `PORT`/`HOST` resolution, read `const DEV = ["1","true","yes","on"].includes((process.env.OBS_DEV ?? "").toLowerCase());`.
- Dev-token rejection: `if (!DEV && (!process.env.OBS_AUTH_TOKEN || ["devtoken","dev"].includes(process.env.OBS_AUTH_TOKEN))) { console.error("Refusing to start with a default/weak OBS_AUTH_TOKEN. Set a real token or OBS_DEV=1."); process.exit(1); }`.
- Port validation: `if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) { console.error(...); process.exit(1); }`.
- Non-loopback warning: if `HOST` not in `{"127.0.0.1","::1","localhost"}` and not `OBS_ALLOW_REMOTE` truthy → `console.warn` loudly (do not exit).
- Constant-time compare in `checkAuth`: replace both `=== AUTH_TOKEN` with a helper:

```ts
import { timingSafeEqual } from "node:crypto";
function safeEq(a: string, b: string): boolean {
  const ab = Buffer.from(a), bb = Buffer.from(b);
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}
```
Keep BOTH the `Authorization: Bearer` header path AND the `?token=` query path (the browser SSE/EventSource depends on the query param — do not remove it).

`justfile`: change `obs_token := env_var_or_default("OBS_AUTH_TOKEN", "devtoken")` to NOT default to `devtoken` — either require it or set `OBS_DEV=1` on the local convenience recipe. `.env.sample`: drop the literal `OBS_AUTH_TOKEN=devtoken`; document that a real token (or `OBS_DEV=1`) is required.

- [ ] **Step 1:** Read `apps/observability/server.ts` to confirm current line numbers for `AUTH_TOKEN`, `PORT`, `HOST`, `checkAuth`.
- [ ] **Step 2:** Apply the edits above.
- [ ] **Step 3:** Verify it boots with a real token: `OBS_AUTH_TOKEN=test-real-token OBS_PORT=43191 bun run apps/observability/server.ts &` then `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:43191/health` → `200`; `curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer test-real-token" http://127.0.0.1:43191/sessions` → `200`; with a wrong token → `401`. Kill the server.
- [ ] **Step 4:** Verify rejection: `OBS_AUTH_TOKEN=devtoken bun run apps/observability/server.ts` → exits non-zero with the refusal message; `OBS_AUTH_TOKEN=devtoken OBS_DEV=1 bun run …` → boots.
- [ ] **Step 5:** Run `scripts/smoke-server.sh` with a non-default token if present; confirm all routes pass.

---

## Self-Review

**Spec coverage:** (1) launcher → Task 4 (`Supervisor` + `up`). (2) auth/port hardening → Task 5 (fork) + Task 0 (token sourcing, no `devtoken`). (3) deep-link in a discoverable CLI/surface → Task 3 (backend endpoint + frontend) + `doctor`/`up` print the link (Task 4). (4) retry/backoff → Task 1. Foundation config → Task 0. Live tailer (required for a real one-command launch) → Task 2. `doctor` (preflight) → Task 4.

**Dependency order:** 0 → 1 → 2 → 3 → 4 on the mannschaft tree (sequential: bridge.py touched by 1+2, cli.py by 2+4). Task 5 (fork) is independent (separate repo) — runs in parallel.

**Type/name consistency:** `obs_server_url`/`obs_auth_token`/`obs_host`/`obs_port`/`obs_enabled`/`obs_fork_dir` used identically across Tasks 0/2/3/4. `post_events(…, timeout=)`, `post_events_with_retry`, `_is_retryable`, `tail_once`, `follow_runs`, `_TERMINAL`, `Supervisor`/`Proc` consistent. `RunSummary.run_id` + `get_run(...)["status"]` per the store findings (confirm at implementation).

**Open confirmations for implementers:** exact `RunSummary` attribute name; the fork's exact Bun entry path (`apps/observability/server.ts` vs `server.ts`); whether `tests/api/conftest.py`'s `cfg`/`client` fixtures need the new obs fields (they do — update them in Task 0).
