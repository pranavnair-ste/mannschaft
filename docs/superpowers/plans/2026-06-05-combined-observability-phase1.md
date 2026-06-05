# Combined Observability — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make real mannschaft runs render with assistant *prose* in the pi-observability fork's race/swimlane views, via an enriched capture + a productionized trajectory→`/events` bridge + a deep-link from Symphony.

**Architecture:** `agent_capture.py` keeps the assistant `text` (and `thinking`, usually empty) the pi stream already carries, in the message row's existing `output` JSON (no migration). A new `pi_harness/observability/bridge.py` tails `store.query_events_after`, translates each `TrajectoryEvent` into a fork `ObsEventEnvelope` (deterministic `uuid5` ids so re-tails are idempotent), synthesizes `session_start`/`turn_start`/`turn_end`, and POSTs to the fork. A `pi-harness observe` CLI backfills/tails a run; Symphony's run page deep-links into the fork.

**Tech Stack:** Python 3.12, Typer CLI, SQLite (`~/.pi-harness/trajectory.db`), the Bun fork on `127.0.0.1:43190`, Next.js (Symphony). Tests: pytest (`-m "not smoke"`).

**Spec:** `docs/superpowers/specs/2026-06-05-combined-observability-design.md`

**Out of scope (later phases/plans):** per-turn timing (TTFT/tps), thinking rendering, the fork custom-event renderer, the one-command launcher, auth hardening.

---

## File Structure

- `pi_harness/trajectory/agent_capture.py` — **modify** `_turn_message` + add `_assistant_text_and_thinking` helper. Keeps assistant text/thinking in `output`.
- `pi_harness/observability/__init__.py` — **create** (new package).
- `pi_harness/observability/bridge.py` — **create**. Pure translator + per-run envelope builder + POST/backfill. One responsibility: turn trajectory rows into fork events and ship them.
- `pi_harness/cli.py` — **modify**. Add `observe` Typer command (thin shim over `bridge.backfill_run`).
- `ui/app/runs/[runId]/page.tsx` — **modify**. Add "Open in observability" deep-link in the header.
- `tests/trajectory/test_agent_capture.py` — **modify**. Assert text/thinking extraction.
- `tests/observability/__init__.py`, `tests/observability/test_bridge.py` — **create**. Translator + envelope-builder + idempotency tests.

---

## Task 1: Capture — keep assistant text + thinking

**Files:**
- Modify: `pi_harness/trajectory/agent_capture.py` (`_turn_message`, ~lines 135-163; add helper above it)
- Test: `tests/trajectory/test_agent_capture.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/trajectory/test_agent_capture.py`:

```python
def test_turn_message_captures_text_and_thinking():
    from pi_harness.trajectory.agent_capture import PiEventParser
    line = json.dumps({
        "type": "turn_end",
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-8",
            "stopReason": "stop",
            "usage": {"input": 100, "output": 20, "cost": {"total": 0.01}},
            "content": [
                {"type": "thinking", "thinking": "weighing options", "thinkingSignature": "sig"},
                {"type": "text", "text": "Here is the answer."},
            ],
        },
    })
    parser = PiEventParser(run_id="r", agent_id="a")
    events = list(parser.feed(line))
    assert len(events) == 1
    out = events[0].output
    assert out["text"] == "Here is the answer."
    assert out["thinking"] == "weighing options"
    assert out["cost_usd"] == 0.01  # existing fields preserved


def test_turn_message_text_empty_on_tool_only_turn():
    from pi_harness.trajectory.agent_capture import PiEventParser
    line = json.dumps({
        "type": "turn_end",
        "message": {"role": "assistant", "model": "gpt-5.4-mini", "stopReason": "toolUse",
                    "usage": {"input": 5, "output": 5},
                    "content": [{"type": "toolCall", "id": "c1", "name": "ls", "arguments": {}}]},
    })
    out = list(PiEventParser(run_id="r", agent_id="a").feed(line))[0].output
    assert out["text"] == ""        # tool-only turns legitimately have no prose
    assert out["thinking"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/trajectory/test_agent_capture.py::test_turn_message_captures_text_and_thinking -v`
Expected: FAIL — `KeyError: 'text'` (output has no `text` key yet).

- [ ] **Step 3: Add the extraction helper**

Add above `_turn_message` in `pi_harness/trajectory/agent_capture.py`:

```python
def _assistant_text_and_thinking(msg: dict) -> tuple[str, str]:
    """Pull user-facing text and (usually empty) thinking from message.content[].

    content parts: {"type":"text","text":...}, {"type":"thinking","thinking":...},
    {"type":"toolCall",...}. Tool-only turns have no text part → "". Defensive:
    malformed content must never raise (audit #29)."""
    content = msg.get("content")
    if not isinstance(content, list):
        return "", ""
    texts, thinks = [], []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif part.get("type") == "thinking" and isinstance(part.get("thinking"), str):
            thinks.append(part["thinking"])
    return "".join(texts), "".join(thinks)
```

- [ ] **Step 4: Wire it into `_turn_message`**

In `_turn_message`, after computing `cost`, change the `output={...}` dict to include text/thinking:

```python
        text, thinking = _assistant_text_and_thinking(msg)
        return TrajectoryEvent(
            run_id=self.run_id,
            agent_id=self.agent_id,
            step_id=f"turn-{self._turn_index}",
            ts=self._now(),
            model=str(msg.get("model", "") or self._current_model),
            tool="",
            input={},
            output={
                "cost_usd": _safe_float(cost),
                "stopReason": msg.get("stopReason"),
                "responseId": msg.get("responseId"),
                "text": text,
                "thinking": thinking,
            },
            duration_ms=0,
            tokens_in=_safe_int(usage.get("input", 0)),
            tokens_out=_safe_int(usage.get("output", 0)),
            outcome="success",
            classification="message",
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/trajectory/test_agent_capture.py -v -m "not smoke"`
Expected: PASS (both new tests + existing ones).

- [ ] **Step 6: Commit**

```bash
git add pi_harness/trajectory/agent_capture.py tests/trajectory/test_agent_capture.py
git commit -m "feat(capture): keep assistant text+thinking in message output"
```

---

## Task 2: Bridge — pure translator (one row → one envelope)

**Files:**
- Create: `pi_harness/observability/__init__.py` (empty)
- Create: `pi_harness/observability/bridge.py`
- Create: `tests/observability/__init__.py` (empty), `tests/observability/test_bridge.py`

- [ ] **Step 1: Write the failing test**

Create `tests/observability/test_bridge.py`:

```python
from datetime import datetime, timezone
from pi_harness.trajectory.schema import TrajectoryEvent
from pi_harness.observability import bridge

CTX = bridge.RunContext(run_id="run-x", team_name="team-a", topology="pipeline")
TS = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)

def _ev(**kw):
    base = dict(run_id="run-x", agent_id="planner", step_id="s", ts=TS, model="claude-opus-4-8",
               tool="", input={}, output={}, duration_ms=0, tokens_in=0, tokens_out=0,
               outcome="success", classification="message")
    base.update(kw)
    return TrajectoryEvent(**base)

def test_translate_tool_call():
    ev = _ev(classification="tool_call", tool="bash", step_id="call_1", input={"command": "ls"})
    env = bridge.translate(ev, CTX, seq=3)
    assert env["type"] == "tool_call"
    assert env["pool"] == "run-x"
    assert env["tags"] == ["team-a", "pipeline"]
    assert env["agent_name"] == "planner"
    assert env["session_id"] == "run-x:planner"
    assert env["seq"] == 3
    assert env["ts"] == "2026-06-05T12:00:00.000Z"
    assert env["payload"]["tool_name"] == "bash"
    assert env["payload"]["args"] == {"command": "ls"}

def test_translate_message_carries_prose():
    ev = _ev(classification="message", step_id="turn-1", tokens_in=100, tokens_out=20,
             output={"cost_usd": 0.01, "stopReason": "stop", "text": "done.", "thinking": ""})
    env = bridge.translate(ev, CTX, seq=5)
    assert env["type"] == "assistant_message"
    assert env["payload"]["text"] == "done."
    assert env["payload"]["usage"]["cost_total"] == 0.01
    assert env["payload"]["usage"]["output"] == 20
    assert env["payload"]["stop_reason"] == "stop"

def test_translate_tool_result_extracts_text_and_error():
    ev = _ev(classification="tool_result", tool="bash", step_id="call_1", outcome="error",
             output={"content": [{"type": "text", "text": "boom"}]})
    env = bridge.translate(ev, CTX, seq=1)
    assert env["payload"]["content_text"] == "boom"
    assert env["payload"]["is_error"] is True

def test_event_id_is_deterministic():
    ev = _ev(classification="tool_call", tool="bash", step_id="call_1")
    a = bridge.translate(ev, CTX, seq=1, row_id=42)
    b = bridge.translate(ev, CTX, seq=1, row_id=42)
    assert a["event_id"] == b["event_id"]   # idempotent re-tail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/observability/test_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: pi_harness.observability`.

- [ ] **Step 3: Create the package + translator**

Create `pi_harness/observability/__init__.py` (empty). Create `pi_harness/observability/bridge.py`:

```python
"""Bridge: translate mannschaft TrajectoryEvent rows into pi-observability fork
ObsEventEnvelopes and POST them. The translator is a pure function; the tailer is
the only stateful/IO piece. Deterministic uuid5 event_ids make re-tails idempotent
against the fork's event_id PK + UNIQUE(session_id, seq)."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from pi_harness.trajectory.schema import TrajectoryEvent

# Fixed namespace so event_ids are stable across processes/restarts.
_NS = uuid.UUID("6f0d8a4e-0c2b-4e8a-9b1a-7c2d3e4f5a6b")
MAX_TEXT = 32_000  # fork MAX_TEXT_FIELD / MAX_RESULT_BYTES


@dataclass(frozen=True)
class RunContext:
    run_id: str
    team_name: str | None
    topology: str | None

    @property
    def pool(self) -> str:
        return self.run_id

    @property
    def tags(self) -> list[str]:
        return [t for t in (self.team_name, self.topology) if t]


def _iso(ts) -> str:
    # tz-aware UTC datetime -> ISO-8601 with ms + Z
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _provider_for(model: str) -> str:
    m = (model or "").lower()
    if m.startswith(("gpt", "o")):
        return "openai"
    if m.startswith("claude"):
        return "anthropic"
    return "unknown"


def _truncate(s: str) -> str:
    return s if len(s.encode()) <= MAX_TEXT else s.encode()[:MAX_TEXT].decode(errors="ignore")


def _result_text(output: dict) -> str:
    content = output.get("content")
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        joined = "".join(p for p in parts if p)
        if joined:
            return _truncate(joined)
    return _truncate(json.dumps(output))


def _eid(ctx: RunContext, agent_id: str, *parts: Any) -> str:
    return str(uuid.uuid5(_NS, ":".join(str(p) for p in (ctx.run_id, agent_id, *parts))))


def _base(ev: TrajectoryEvent, ctx: RunContext, etype: str, seq: int, eid: str, payload: dict) -> dict:
    return {
        "event_id": eid,
        "ts": _iso(ev.ts),
        "type": etype,
        "session_id": f"{ctx.run_id}:{ev.agent_id}",
        "cwd": "",
        "agent_name": ev.agent_id,
        "pool": ctx.pool,
        "tags": ctx.tags,
        "provider": _provider_for(ev.model),
        "model": ev.model or "",
        "seq": seq,
        "payload": payload,
    }


def translate(ev: TrajectoryEvent, ctx: RunContext, *, seq: int, row_id: int = 0) -> dict:
    """One trajectory row -> one fork envelope. row_id makes the event_id unique
    per source row; same (row_id, seq) -> same event_id (idempotent)."""
    out = dict(ev.output)
    if ev.classification == "tool_call":
        eid = _eid(ctx, ev.agent_id, "tool_call", row_id, ev.step_id)
        return _base(ev, ctx, "tool_call", seq, eid, {
            "tool_call_id": ev.step_id, "tool_name": ev.tool,
            "args": dict(ev.input), "args_truncated": False})
    if ev.classification == "tool_result":
        eid = _eid(ctx, ev.agent_id, "tool_result", row_id, ev.step_id)
        return _base(ev, ctx, "tool_result", seq, eid, {
            "tool_call_id": ev.step_id, "tool_name": ev.tool,
            "content_text": _result_text(out), "content_truncated": False,
            "is_error": ev.outcome == "error"})
    if ev.classification == "message":
        eid = _eid(ctx, ev.agent_id, "message", row_id, ev.step_id)
        return _base(ev, ctx, "assistant_message", seq, eid, {
            "text": _truncate(out.get("text", "") or ""),
            "thinking": _truncate(out.get("thinking", "") or ""),
            "tool_call_ids": [],
            "stop_reason": out.get("stopReason") or "stop",
            "usage": {"input": ev.tokens_in, "output": ev.tokens_out,
                      "cache_read": 0, "cache_write": 0,
                      "total_tokens": ev.tokens_in + ev.tokens_out,
                      "cost_total": out.get("cost_usd", 0.0)}})
    # task_transition / guide_fired / sensor_fired -> custom
    eid = _eid(ctx, ev.agent_id, "custom", row_id, ev.classification)
    return _base(ev, ctx, "custom", seq, eid, {
        "custom_type": ev.classification, "data": {"input": dict(ev.input), "output": out}})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/observability/test_bridge.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/observability/ tests/observability/
git commit -m "feat(observability): bridge translator row->fork envelope"
```

---

## Task 3: Bridge — per-run envelope builder (synthesize session/turn boundaries)

**Files:**
- Modify: `pi_harness/observability/bridge.py` (add `envelopes_for_run`)
- Test: `tests/observability/test_bridge.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/observability/test_bridge.py`:

```python
def test_envelopes_for_run_synthesizes_session_and_turns():
    rows = [
        (1, _ev(agent_id="planner", classification="tool_call", tool="bash", step_id="c1", input={"command": "ls"})),
        (2, _ev(agent_id="planner", classification="tool_result", tool="bash", step_id="c1",
                output={"content": [{"type": "text", "text": "ok"}]})),
        (3, _ev(agent_id="planner", classification="message", step_id="turn-1",
                output={"cost_usd": 0.01, "stopReason": "stop", "text": "done", "thinking": ""})),
    ]
    envs = bridge.envelopes_for_run(rows, CTX)
    types = [e["type"] for e in envs]
    assert types == ["session_start", "turn_start", "tool_call", "tool_result",
                     "assistant_message", "turn_end"]
    # seq is monotonic per session starting at 0
    assert [e["seq"] for e in envs] == [0, 1, 2, 3, 4, 5]
    assert all(e["session_id"] == "run-x:planner" for e in envs)

def test_envelopes_for_run_separates_agents():
    rows = [
        (1, _ev(agent_id="a1", classification="message", step_id="turn-1", output={"text": "x", "cost_usd": 0})),
        (2, _ev(agent_id="a2", classification="message", step_id="turn-1", output={"text": "y", "cost_usd": 0})),
    ]
    envs = bridge.envelopes_for_run(rows, CTX)
    a1 = [e for e in envs if e["session_id"] == "run-x:a1"]
    a2 = [e for e in envs if e["session_id"] == "run-x:a2"]
    assert [e["seq"] for e in a1] == [0, 1, 2, 3]  # session_start, turn_start, msg, turn_end
    assert [e["seq"] for e in a2] == [0, 1, 2, 3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/observability/test_bridge.py::test_envelopes_for_run_synthesizes_session_and_turns -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'envelopes_for_run'`.

- [ ] **Step 3: Implement `envelopes_for_run`**

Add to `pi_harness/observability/bridge.py`:

```python
def _synth(ctx: RunContext, agent_id: str, ts, etype: str, seq: int, kind: str, payload: dict) -> dict:
    eid = str(uuid.uuid5(_NS, ":".join((ctx.run_id, agent_id, kind))))
    fake = TrajectoryEvent(run_id=ctx.run_id, agent_id=agent_id, step_id="", ts=ts,
                           model="", tool="", input={}, output={}, duration_ms=0,
                           tokens_in=0, tokens_out=0, outcome="success", classification="message")
    env = _base(fake, ctx, etype, seq, eid, payload)
    return env


def envelopes_for_run(rows: list[tuple[int, TrajectoryEvent]], ctx: RunContext) -> list[dict]:
    """Ordered envelopes for a whole run. Per agent: one session_start, then
    turn_start/<events>/turn_end groups. seq is monotonic per session from 0.
    Deterministic — recomputable on restart (idempotent against the fork)."""
    seq: dict[str, int] = {}
    started: set[str] = set()
    turn_open: dict[str, bool] = {}
    turn_idx: dict[str, int] = {}
    out: list[dict] = []

    def nxt(sid: str) -> int:
        n = seq.get(sid, 0)
        seq[sid] = n + 1
        return n

    for row_id, ev in rows:
        sid = f"{ctx.run_id}:{ev.agent_id}"
        if sid not in started:
            started.add(sid)
            turn_open[sid] = False
            turn_idx[sid] = 1
            out.append(_synth(ctx, ev.agent_id, ev.ts, "session_start", nxt(sid),
                              "session", {"reason": "new"}))
        if not turn_open[sid]:
            out.append(_synth(ctx, ev.agent_id, ev.ts, "turn_start", nxt(sid),
                              f"turn:{turn_idx[sid]}:start", {"turn_index": turn_idx[sid]}))
            turn_open[sid] = True
        out.append(translate(ev, ctx, seq=nxt(sid), row_id=row_id))
        if ev.classification == "message":
            out.append(_synth(ctx, ev.agent_id, ev.ts, "turn_end", nxt(sid),
                              f"turn:{turn_idx[sid]}:end", {"turn_index": turn_idx[sid]}))
            turn_open[sid] = False
            turn_idx[sid] += 1
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/observability/test_bridge.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/observability/bridge.py tests/observability/test_bridge.py
git commit -m "feat(observability): per-run envelope builder with synth session/turn boundaries"
```

---

## Task 4: Bridge — POST + backfill_run

**Files:**
- Modify: `pi_harness/observability/bridge.py` (add `post_events`, `backfill_run`)
- Test: `tests/observability/test_bridge.py`

- [ ] **Step 1: Write the failing test (monkeypatched POST + store)**

Add to `tests/observability/test_bridge.py`:

```python
def test_backfill_run_reads_store_and_posts(monkeypatch):
    posted = []
    monkeypatch.setattr(bridge, "post_events",
                        lambda envs, url, token: posted.extend(envs) or {"ingested": len(envs)})
    monkeypatch.setattr(bridge, "_load_run_context",
                        lambda run_id, db_path=None: CTX)
    rows = [(1, _ev(agent_id="planner", classification="message", step_id="turn-1",
                    output={"text": "hi", "cost_usd": 0}))]
    monkeypatch.setattr(bridge, "_read_rows", lambda run_id, db_path=None: rows)
    n = bridge.backfill_run("run-x", url="http://x", token="t")
    assert n == 4  # session_start, turn_start, assistant_message, turn_end
    assert posted[0]["type"] == "session_start"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/observability/test_bridge.py::test_backfill_run_reads_store_and_posts -v`
Expected: FAIL — `AttributeError: ... 'backfill_run'`.

- [ ] **Step 3: Implement POST + IO seam + backfill**

Add to `pi_harness/observability/bridge.py`:

```python
import os
import urllib.request
from pi_harness.trajectory import runs as runs_mod
from pi_harness.trajectory import store as store_mod

DEFAULT_URL = os.environ.get("OBS_SERVER_URL", "http://127.0.0.1:43190")
DEFAULT_TOKEN = os.environ.get("OBS_AUTH_TOKEN", "devtoken")


def post_events(envelopes: list[dict], url: str, token: str) -> dict:
    """POST a batch to the fork's /events. Caller batches to <=50."""
    req = urllib.request.Request(
        f"{url}/events", data=json.dumps(envelopes).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def _read_rows(run_id: str, db_path=None) -> list[tuple[int, TrajectoryEvent]]:
    return store_mod.query_events_after(run_id, 0, db_path=db_path)


def _load_run_context(run_id: str, db_path=None) -> RunContext:
    rec = runs_mod.get_run(run_id, db_path=db_path) or {}
    return RunContext(run_id=run_id, team_name=rec.get("team_name"), topology=rec.get("topology"))


def backfill_run(run_id: str, *, url: str = DEFAULT_URL, token: str = DEFAULT_TOKEN,
                 db_path=None) -> int:
    """Translate ALL rows of run_id and POST them (batches of 50). Idempotent."""
    ctx = _load_run_context(run_id, db_path=db_path)
    rows = _read_rows(run_id, db_path=db_path)
    envs = envelopes_for_run(rows, ctx)
    for i in range(0, len(envs), 50):
        post_events(envs[i:i + 50], url, token)
    return len(envs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/observability/test_bridge.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/observability/bridge.py tests/observability/test_bridge.py
git commit -m "feat(observability): POST + backfill_run (idempotent run replay)"
```

---

## Task 5: CLI — `pi-harness observe`

**Files:**
- Modify: `pi_harness/cli.py` (add an `@app.command()` named `observe`)

- [ ] **Step 1: Write the failing test**

Create `tests/observability/test_cli_observe.py`:

```python
from typer.testing import CliRunner
from pi_harness.cli import app
from pi_harness.observability import bridge

def test_observe_calls_backfill(monkeypatch):
    calls = {}
    monkeypatch.setattr(bridge, "backfill_run",
                        lambda run_id, **kw: calls.setdefault("run", run_id) or 42)
    result = CliRunner().invoke(app, ["observe", "--run", "run-abc"])
    assert result.exit_code == 0
    assert calls["run"] == "run-abc"
    assert "42" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/observability/test_cli_observe.py -v`
Expected: FAIL — Typer reports no such command `observe`.

- [ ] **Step 3: Add the command**

Add to `pi_harness/cli.py` (near the other `@app.command()` defs; add `from pi_harness.observability import bridge as _bridge` at import time inside the function to avoid import cost):

```python
@app.command()
def observe(
    run: str = typer.Option(..., "--run", help="run_id to backfill/replay into the observability fork."),
    url: Optional[str] = typer.Option(None, "--url", help="Fork base URL (default OBS_SERVER_URL or http://127.0.0.1:43190)."),
    token: Optional[str] = typer.Option(None, "--token", help="Bearer token (default OBS_AUTH_TOKEN or devtoken)."),
) -> None:
    """Translate a run's trajectory rows and POST them to the pi-observability fork."""
    from pi_harness.observability import bridge
    n = bridge.backfill_run(
        run,
        url=url or bridge.DEFAULT_URL,
        token=token or bridge.DEFAULT_TOKEN,
    )
    typer.echo(f"bridged {n} events for {run}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/observability/test_cli_observe.py -v`
Expected: PASS.

- [ ] **Step 5: Manual smoke against the running fork (real run)**

With the fork server running on :43190 and a real run in the DB:
Run: `pi-harness observe --run run-ea742e20-4d21-4836-8e2b-53e09745c238`
Expected: prints `bridged <N> events ...`; the run appears in the fork at
`http://127.0.0.1:43190/?token=devtoken#view=race&pool=run-ea742e20-4d21-4836-8e2b-53e09745c238&hide_after=never&show_hidden=1`
with assistant_message rows now showing text on turns that produced prose.

- [ ] **Step 6: Commit**

```bash
git add pi_harness/cli.py tests/observability/test_cli_observe.py
git commit -m "feat(cli): pi-harness observe — backfill a run into the fork"
```

---

## Task 6: Symphony — deep-link to the fork

**Files:**
- Modify: `ui/app/runs/[runId]/page.tsx` (header right-side `div`, beside `<CostPanel/>`)

- [ ] **Step 1: Add the link**

In `ui/app/runs/[runId]/page.tsx`, change the header actions `div` to include an anchor. Use an env-overridable base URL with a sane default:

```tsx
        <div className="flex items-center gap-2">
          <a
            href={`${process.env.NEXT_PUBLIC_OBS_URL ?? "http://127.0.0.1:43190"}/?token=${process.env.NEXT_PUBLIC_OBS_TOKEN ?? "devtoken"}#view=race&pool=${detail.summary.run_id}&hide_after=never&show_hidden=1`}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded border border-zinc-300 px-2 py-1 text-sm hover:border-zinc-500"
          >
            Open in observability ↗
          </a>
          <CostPanel summary={detail.summary} />
        </div>
```

(The fork's `auto-add-lanes` is on by default, so `pool=<run_id>` populates the race lanes without listing each agent; `hide_after=never&show_hidden=1` makes finished runs visible.)

- [ ] **Step 2: Type-check / build the UI**

Run: `cd ui && npx tsc --noEmit`
Expected: no new type errors.

- [ ] **Step 3: Manual verification**

Start Symphony (`cd ui && pnpm dev` or the project's usual command) + the fork server, open a run page, click "Open in observability ↗".
Expected: a new tab opens the fork's race view filtered to that run's pool.

- [ ] **Step 4: Commit**

```bash
git add ui/app/runs/\[runId\]/page.tsx
git commit -m "feat(ui): deep-link from run page to observability fork"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** Capture enrichment for text → Task 1. Bridge translator + envelope synthesis + idempotent ids → Tasks 2-4. `pi-harness observe` backfill → Task 5. Symphony deep-link → Task 6. (Thinking *rendering*, timing, fork custom-renderer, launcher, auth = explicitly Phase 2/3, separate plans.) Thinking *capture* is included in Task 1 (free; usually empty).
- **Placeholder scan:** none — every code/command step carries real content.
- **Type consistency:** `RunContext`, `translate(ev, ctx, *, seq, row_id)`, `envelopes_for_run(rows, ctx)`, `post_events`, `backfill_run`, `_read_rows`, `_load_run_context` are consistent across Tasks 2-5. `query_events_after` returns `list[tuple[int, TrajectoryEvent]]` (matches `_read_rows`). `get_run` returns a dict (matches `_load_run_context`).
- **Smoke safety:** no task launches a ClawTeam team; the e2e uses an existing real run + monkeypatched IO. Run pytest with `-m "not smoke"`.
