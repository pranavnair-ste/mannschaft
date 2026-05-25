# Guides + Sensors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the control-system surface for the Pi-Agent Harness — Guides fire before every pi-coding-agent tool call, Sensors fire after, and a Promote-to-Guide mechanic suggests converting frequent inferential sensors into deterministic Guides.

**Architecture:** A `GuardRunner` sits between pi-coding-agent's tool stream and actual tool execution. It runs an ordered chain of `Guide` callables on each `ActionIntent` (first deny short-circuits) and an ordered chain of `Sensor` callables on each `ActionResult`. Both kinds emit `TrajectoryEvent`s (`classification="guide_fired" | "sensor_fired"`) to Plan 2's SQLite store. The `promote` module performs offline statistical analysis on stored sensor firings to suggest stub Guides users can review and install.

**Tech Stack:** Python 3.10+, `uv`, `pytest`, `pydantic` (typed dicts/dataclasses), `jsonschema` (schema validation), `unittest.mock` (mock the OpenAI client in `JudgeAgentSensor` tests).

---

## Context for the Engineer (Zero-Knowledge Briefing)

You are building **Plan 6 of 8** for the Pi-Agent Harness ("mannschaft"). The architecture document is `/Users/pranavnair/Desktop/Personal/mannschaft/HARNESS_ARCHITECTURE.md` — read it before starting (especially the "Guides + Sensors" section under "What we build" and the Fowler 2×2 reference).

**What the harness is:** A multi-agent orchestrator for software-development agents. Per-agent executor is `pi-coding-agent` (a TypeScript agent loop from earendil-works/pi). The harness wraps it with a trajectory store, an expertise corpus, an improve-loop, a topology selector, this guides/sensors layer, a spec editor, and a Symphony-style dashboard.

**What you own:** Everything under `pi_harness/guards/`. Six Python files and a parallel `tests/guards/` tree. No UI, no orchestration logic — those are other plans.

**The Fowler 2×2 model (key concept):**

|              | Feedforward (before action) | Feedback (after action) |
|--------------|-----------------------------|-------------------------|
| Computational | Guide (deterministic rule, e.g. allowlist) | Sensor (deterministic check, e.g. regex assertion) |
| Inferential   | Guide (LLM-judged rule)     | Sensor (LLM-judged check, e.g. judge agent) |

Each `Guide` and `Sensor` is declared with a `GuardKind` indicating its quadrant. v1 ships built-ins for three of four quadrants (computational-feedforward, computational-feedback, inferential-feedback); inferential-feedforward is supported via the protocol but no built-in. The "Promote to Guide" mechanic converts a frequently-firing inferential-feedback sensor into a computational-feedforward guide (moves up and left in the 2×2).

**Dependencies — what is already built when you start:**
- **Plan 1** provides `pi_harness.config.Config` with fields including `openai_api_key: str`, `openai_fast_model: str`, `harness_root: Path`. Import as `from pi_harness.config import Config`.
- **Plan 2** provides:
  - `pi_harness.trajectory.schema.TrajectoryEvent` — a `pydantic.BaseModel` with fields `run_id: str`, `agent_id: str`, `step_id: str`, `ts: datetime`, `tool: str | None`, `input: dict | None`, `output: dict | None`, `outcome: str`, `classification: str`, `metadata: dict`.
  - `pi_harness.trajectory.store.write_event(event: TrajectoryEvent) -> None` — appends to SQLite.
  - `pi_harness.trajectory.store.query_events(filter: dict) -> list[TrajectoryEvent]` — reads filtered events.
- **Plan 5** (Topology) will import from you. It calls `Coordinator.launch(..., guides=[...], sensors=[...])` which constructs a `GuardRunner` per agent. You do not need to write Plan 5; you only need to provide a clean API.

**What pi-coding-agent looks like from your side (assumed contract):**
pi-coding-agent is a TypeScript module. We invoke it from Python via subprocess and intercept its tool-call protocol over stdio (newline-delimited JSON). Each tool-call event from the agent is a JSON object of shape `{type: "tool_call", id, name, input}` and each tool-result is `{type: "tool_result", id, output, exit_code?}`. The harness Python layer reads these from the agent's stdout, runs guides on tool-call events, runs sensors on tool-result events, and writes a synthetic `tool_result` back to the agent's stdin if a guide denies.

**You will not implement the subprocess wiring** — that belongs to a later integration phase. Your `GuardRunner` accepts already-parsed dict-shaped `ActionIntent` and `ActionResult` payloads. Document the assumed JSON shape and flag it for verification against pi-coding-agent's actual stdout protocol.

---

## File Structure (lock decomposition here)

```
pi_harness/guards/
  __init__.py        # public re-exports: GuardKind, GuardResult, Guide, Sensor, ActionIntent, ActionResult, GuardRunner, register_guide, register_sensor, load_user_guards
  types.py           # GuardKind enum, GuardResult dataclass, Guide / Sensor protocols, ActionIntent / ActionResult typed dicts, registry decorators
  guides.py          # AllowlistGuide, PathScopeGuide, SchemaValidatorGuide, RateLimitGuide
  sensors.py         # RegexAssertionSensor, ExitCodeSensor, JudgeAgentSensor, TokenBudgetSensor
  runner.py          # GuardRunner — attach_guides, attach_sensors, intercept_tool_call, intercept_tool_result
  promote.py         # PromotionSuggestion dataclass, suggest_promotions(trajectory_store, min_fires, low_variance_threshold)

tests/guards/
  __init__.py
  test_types.py      # GuardResult validation, GuardKind values, registry decorators
  test_guides.py     # each built-in guide unit-tested
  test_sensors.py    # each built-in sensor unit-tested; JudgeAgentSensor mocks OpenAI client
  test_runner.py     # intercept_tool_call short-circuit, event emission ordering
  test_promote.py    # synthetic trajectory; verify promotion candidate is emitted with stub code
```

Each file has one responsibility: `types` defines protocols/data, `guides` and `sensors` are built-in implementations, `runner` orchestrates, `promote` analyzes history offline. User-authored guards live outside this tree at `~/.pi-harness/guards/*.py`.

---

## Task 0: Project Scaffolding

**Files:**
- Create: `pi_harness/guards/__init__.py` (empty placeholder)
- Create: `tests/guards/__init__.py` (empty)
- Modify: `pyproject.toml` (add `jsonschema` dependency)

- [ ] **Step 1: Verify prerequisites**

Run:
```bash
ls /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/config.py
ls /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/schema.py
ls /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/trajectory/store.py
```

Expected: all three files exist. If not, Plans 1 and 2 are not complete — stop and raise.

- [ ] **Step 2: Create the guards package init (empty)**

Create `pi_harness/guards/__init__.py` with a single line:
```python
"""Guides + Sensors — control-system surface for pi-coding-agent tool stream."""
```

- [ ] **Step 3: Create the tests package init**

Create `tests/guards/__init__.py` as an empty file.

- [ ] **Step 4: Add jsonschema dependency**

In `pyproject.toml` find the `[project] dependencies` array and add `"jsonschema>=4.21"`. `pydantic` is already present from Plan 2.

Then run:
```bash
uv sync
```

Expected: install completes, `jsonschema` listed in lockfile.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/__init__.py tests/guards/__init__.py pyproject.toml uv.lock
git commit -m "chore(guards): scaffold guards package + add jsonschema dep"
```

---

## Task 1: GuardKind enum + GuardResult dataclass

**Files:**
- Modify: `pi_harness/guards/types.py` (new file)
- Test: `tests/guards/test_types.py`

- [ ] **Step 1: Write failing test for GuardKind values**

Create `tests/guards/test_types.py`:
```python
from pi_harness.guards.types import GuardKind, GuardResult


def test_guardkind_has_four_quadrants():
    assert GuardKind.COMPUTATIONAL_GUIDE.value == "computational_guide"
    assert GuardKind.INFERENTIAL_GUIDE.value == "inferential_guide"
    assert GuardKind.COMPUTATIONAL_SENSOR.value == "computational_sensor"
    assert GuardKind.INFERENTIAL_SENSOR.value == "inferential_sensor"


def test_guardresult_allow_default_metadata_empty():
    r = GuardResult(allow=True, reason="ok")
    assert r.allow is True
    assert r.reason == "ok"
    assert r.confidence is None
    assert r.metadata == {}


def test_guardresult_deny_with_confidence_and_metadata():
    r = GuardResult(allow=False, reason="schema fail", confidence=0.92, metadata={"path": "/x"})
    assert r.allow is False
    assert r.confidence == 0.92
    assert r.metadata["path"] == "/x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: `ImportError` (module not yet created).

- [ ] **Step 3: Implement GuardKind + GuardResult**

Create `pi_harness/guards/types.py`:
```python
"""Types for the guides/sensors control surface."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GuardKind(str, Enum):
    """The Fowler 2x2 quadrant a guard occupies.

    Feedforward (before action) = Guide. Feedback (after action) = Sensor.
    Deterministic rule = Computational. LLM judgment = Inferential.
    """

    COMPUTATIONAL_GUIDE = "computational_guide"
    INFERENTIAL_GUIDE = "inferential_guide"
    COMPUTATIONAL_SENSOR = "computational_sensor"
    INFERENTIAL_SENSOR = "inferential_sensor"


@dataclass
class GuardResult:
    """The decision a Guide or Sensor returns."""

    allow: bool
    reason: str
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/types.py tests/guards/test_types.py
git commit -m "feat(guards): add GuardKind enum and GuardResult dataclass"
```

---

## Task 2: ActionIntent and ActionResult typed dicts

**Files:**
- Modify: `pi_harness/guards/types.py`
- Modify: `tests/guards/test_types.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_types.py`:
```python
from pi_harness.guards.types import ActionIntent, ActionResult


def test_action_intent_required_keys():
    intent: ActionIntent = {
        "run_id": "r1",
        "agent_id": "builder",
        "step_id": "s1",
        "tool": "bash",
        "input": {"cmd": "ls"},
    }
    assert intent["tool"] == "bash"
    assert intent["input"]["cmd"] == "ls"


def test_action_result_required_keys():
    result: ActionResult = {
        "run_id": "r1",
        "agent_id": "builder",
        "step_id": "s1",
        "tool": "bash",
        "input": {"cmd": "ls"},
        "output": {"stdout": "a\nb"},
        "exit_code": 0,
        "duration_ms": 42,
    }
    assert result["exit_code"] == 0
```

- [ ] **Step 2: Run test (verify fail)**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: ImportError for ActionIntent/ActionResult.

- [ ] **Step 3: Add typed dicts to `pi_harness/guards/types.py`**

Append:
```python
from typing import TypedDict


class ActionIntent(TypedDict, total=False):
    """pi-coding-agent's pending tool call.

    Shape mirrors pi-coding-agent's stdout JSON line for `{type: "tool_call"}`.
    Required keys: run_id, agent_id, step_id, tool, input.
    """

    run_id: str
    agent_id: str
    step_id: str
    tool: str
    input: dict[str, Any]


class ActionResult(TypedDict, total=False):
    """pi-coding-agent's tool result.

    Shape mirrors pi-coding-agent's stdout JSON line for `{type: "tool_result"}`,
    augmented with timing collected by the GuardRunner.
    Required keys: run_id, agent_id, step_id, tool, input, output.
    Optional: exit_code (for bash-like tools), duration_ms.
    """

    run_id: str
    agent_id: str
    step_id: str
    tool: str
    input: dict[str, Any]
    output: dict[str, Any]
    exit_code: int
    duration_ms: int
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/types.py tests/guards/test_types.py
git commit -m "feat(guards): add ActionIntent and ActionResult typed dicts"
```

---

## Task 3: Guide / Sensor protocols

**Files:**
- Modify: `pi_harness/guards/types.py`
- Modify: `tests/guards/test_types.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_types.py`:
```python
from pi_harness.guards.types import Guide, Sensor


def test_guide_protocol_accepts_callable():
    def my_guide(intent: ActionIntent) -> GuardResult:
        return GuardResult(allow=True, reason="ok")

    g: Guide = my_guide  # type-check only; runtime: assigns
    out = g({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash", "input": {}})
    assert out.allow is True


def test_sensor_protocol_accepts_callable():
    def my_sensor(result: ActionResult) -> GuardResult:
        return GuardResult(allow=True, reason="ok")

    s: Sensor = my_sensor
    out = s({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash", "input": {}, "output": {}})
    assert out.allow is True


def test_guide_must_expose_kind_attribute():
    """Concrete guides/sensors expose .kind; the Protocol does not require it,
    but the GuardRunner inspects it. Verify it's discoverable on a stub."""

    class StubGuide:
        kind = GuardKind.COMPUTATIONAL_GUIDE

        def __call__(self, intent):
            return GuardResult(allow=True, reason="ok")

    s = StubGuide()
    assert s.kind == GuardKind.COMPUTATIONAL_GUIDE
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: ImportError for Guide / Sensor.

- [ ] **Step 3: Add protocols to `pi_harness/guards/types.py`**

Append:
```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class Guide(Protocol):
    """Pre-action callable. Inspects an ActionIntent, returns a GuardResult.

    Concrete implementations should expose a `kind: GuardKind` class attribute
    so the GuardRunner can route them and the dashboard can group them.
    """

    kind: GuardKind

    def __call__(self, intent: ActionIntent) -> GuardResult: ...


@runtime_checkable
class Sensor(Protocol):
    """Post-action callable. Inspects an ActionResult, returns a GuardResult.

    `allow=False` from a sensor does not cancel the action (the tool already ran)
    but does emit a sensor_fired event with `outcome="deny"`, which feeds
    promote.suggest_promotions and the dashboard's flag list.
    """

    kind: GuardKind

    def __call__(self, result: ActionResult) -> GuardResult: ...
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/types.py tests/guards/test_types.py
git commit -m "feat(guards): add Guide and Sensor protocols"
```

---

## Task 4: User-defined registry decorators

**Files:**
- Modify: `pi_harness/guards/types.py`
- Modify: `tests/guards/test_types.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_types.py`:
```python
from pi_harness.guards.types import register_guide, register_sensor, GUIDE_REGISTRY, SENSOR_REGISTRY


def test_register_guide_adds_to_registry():
    GUIDE_REGISTRY.clear()

    @register_guide(name="my_guide")
    class MyGuide:
        kind = GuardKind.COMPUTATIONAL_GUIDE

        def __call__(self, intent):
            return GuardResult(allow=True, reason="ok")

    assert "my_guide" in GUIDE_REGISTRY
    assert GUIDE_REGISTRY["my_guide"] is MyGuide


def test_register_sensor_adds_to_registry():
    SENSOR_REGISTRY.clear()

    @register_sensor(name="my_sensor")
    class MySensor:
        kind = GuardKind.COMPUTATIONAL_SENSOR

        def __call__(self, result):
            return GuardResult(allow=True, reason="ok")

    assert "my_sensor" in SENSOR_REGISTRY
    assert SENSOR_REGISTRY["my_sensor"] is MySensor


def test_register_guide_rejects_duplicate_name():
    GUIDE_REGISTRY.clear()

    @register_guide(name="dup")
    class A:
        kind = GuardKind.COMPUTATIONAL_GUIDE
        def __call__(self, intent): return GuardResult(allow=True, reason="")

    import pytest
    with pytest.raises(ValueError, match="already registered"):
        @register_guide(name="dup")
        class B:
            kind = GuardKind.COMPUTATIONAL_GUIDE
            def __call__(self, intent): return GuardResult(allow=True, reason="")
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: ImportError.

- [ ] **Step 3: Add registries to `pi_harness/guards/types.py`**

Append:
```python
GUIDE_REGISTRY: dict[str, type] = {}
SENSOR_REGISTRY: dict[str, type] = {}


def register_guide(name: str):
    """Decorator. Registers a Guide class under `name` in GUIDE_REGISTRY.

    User-defined guides in ~/.pi-harness/guards/*.py use this to make
    themselves visible to GuardRunner via name-based wiring in Topology configs.
    """

    def deco(cls):
        if name in GUIDE_REGISTRY:
            raise ValueError(f"Guide '{name}' already registered")
        GUIDE_REGISTRY[name] = cls
        return cls

    return deco


def register_sensor(name: str):
    """Decorator. Registers a Sensor class under `name` in SENSOR_REGISTRY."""

    def deco(cls):
        if name in SENSOR_REGISTRY:
            raise ValueError(f"Sensor '{name}' already registered")
        SENSOR_REGISTRY[name] = cls
        return cls

    return deco
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/types.py tests/guards/test_types.py
git commit -m "feat(guards): add register_guide/register_sensor registry decorators"
```

---

## Task 5: User guard discovery (load_user_guards)

**Files:**
- Modify: `pi_harness/guards/__init__.py`
- Test: `tests/guards/test_types.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_types.py`:
```python
import textwrap


def test_load_user_guards_imports_files_from_dir(tmp_path):
    from pi_harness.guards import load_user_guards
    from pi_harness.guards.types import GUIDE_REGISTRY, SENSOR_REGISTRY

    GUIDE_REGISTRY.clear()
    SENSOR_REGISTRY.clear()

    guard_file = tmp_path / "my_user_guard.py"
    guard_file.write_text(textwrap.dedent("""
        from pi_harness.guards.types import (
            register_guide, GuardKind, GuardResult
        )

        @register_guide(name="user_x")
        class UserX:
            kind = GuardKind.COMPUTATIONAL_GUIDE
            def __call__(self, intent):
                return GuardResult(allow=True, reason="user")
    """).strip())

    load_user_guards(tmp_path)
    assert "user_x" in GUIDE_REGISTRY


def test_load_user_guards_skips_missing_dir(tmp_path):
    from pi_harness.guards import load_user_guards

    missing = tmp_path / "nope"
    load_user_guards(missing)  # should not raise
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: ImportError for load_user_guards.

- [ ] **Step 3: Wire `__init__.py` and add discovery**

Replace `pi_harness/guards/__init__.py` with:
```python
"""Guides + Sensors — control-system surface for pi-coding-agent tool stream."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from pi_harness.guards.types import (
    ActionIntent,
    ActionResult,
    GUIDE_REGISTRY,
    GuardKind,
    GuardResult,
    Guide,
    Sensor,
    SENSOR_REGISTRY,
    register_guide,
    register_sensor,
)


def load_user_guards(directory: Path) -> None:
    """Import every *.py file in `directory` so its @register_guide / @register_sensor
    side effects populate GUIDE_REGISTRY / SENSOR_REGISTRY.

    Silently no-ops if `directory` does not exist. The convention is
    `~/.pi-harness/guards/` but callers may pass any path (tests do).
    """
    directory = Path(directory)
    if not directory.exists():
        return

    for py in sorted(directory.glob("*.py")):
        module_name = f"pi_harness_user_guards.{py.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)


__all__ = [
    "ActionIntent",
    "ActionResult",
    "GuardKind",
    "GuardResult",
    "Guide",
    "Sensor",
    "GUIDE_REGISTRY",
    "SENSOR_REGISTRY",
    "register_guide",
    "register_sensor",
    "load_user_guards",
]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_types.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/__init__.py tests/guards/test_types.py
git commit -m "feat(guards): add load_user_guards dynamic import discovery"
```

---

## Task 6: AllowlistGuide

**Files:**
- Create: `pi_harness/guards/guides.py`
- Create: `tests/guards/test_guides.py`

- [ ] **Step 1: Write failing test**

Create `tests/guards/test_guides.py`:
```python
from pi_harness.guards.guides import AllowlistGuide
from pi_harness.guards.types import GuardKind


def _intent(tool="bash", **inp):
    return {
        "run_id": "r", "agent_id": "a", "step_id": "s",
        "tool": tool, "input": dict(inp),
    }


def test_allowlist_guide_kind():
    g = AllowlistGuide(allowed_tools=["bash"])
    assert g.kind == GuardKind.COMPUTATIONAL_GUIDE


def test_allowlist_guide_allows_listed_tool():
    g = AllowlistGuide(allowed_tools=["bash", "read"])
    r = g(_intent(tool="bash"))
    assert r.allow is True
    assert "bash" in r.reason


def test_allowlist_guide_denies_unlisted_tool():
    g = AllowlistGuide(allowed_tools=["bash"])
    r = g(_intent(tool="curl"))
    assert r.allow is False
    assert "curl" in r.reason
    assert "not in allowlist" in r.reason
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_guides.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement AllowlistGuide**

Create `pi_harness/guards/guides.py`:
```python
"""Built-in computational Guides (feedforward, deterministic)."""
from __future__ import annotations

from pi_harness.guards.types import ActionIntent, GuardKind, GuardResult


class AllowlistGuide:
    """Deny tool calls whose `tool` name is not in `allowed_tools`."""

    kind = GuardKind.COMPUTATIONAL_GUIDE

    def __init__(self, allowed_tools: list[str]) -> None:
        self.allowed: set[str] = set(allowed_tools)

    def __call__(self, intent: ActionIntent) -> GuardResult:
        tool = intent.get("tool", "")
        if tool in self.allowed:
            return GuardResult(allow=True, reason=f"tool '{tool}' on allowlist")
        return GuardResult(
            allow=False,
            reason=f"tool '{tool}' not in allowlist {sorted(self.allowed)}",
            metadata={"tool": tool, "allowed": sorted(self.allowed)},
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_guides.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/guides.py tests/guards/test_guides.py
git commit -m "feat(guards): add AllowlistGuide"
```

---

## Task 7: PathScopeGuide

**Files:**
- Modify: `pi_harness/guards/guides.py`
- Modify: `tests/guards/test_guides.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_guides.py`:
```python
from pathlib import Path
from pi_harness.guards.guides import PathScopeGuide


def test_path_scope_guide_allows_inside_scope(tmp_path):
    scope = tmp_path / "ws"
    scope.mkdir()
    (scope / "f.txt").write_text("x")

    g = PathScopeGuide(allowed_paths=[scope])
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
           "input": {"path": str(scope / "f.txt")}})
    assert r.allow is True


def test_path_scope_guide_denies_dotdot_escape(tmp_path):
    scope = tmp_path / "ws"
    scope.mkdir()

    g = PathScopeGuide(allowed_paths=[scope])
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
           "input": {"path": str(scope / ".." / "secret.txt")}})
    assert r.allow is False
    assert "outside scope" in r.reason


def test_path_scope_guide_denies_absolute_outside(tmp_path):
    scope = tmp_path / "ws"
    scope.mkdir()

    g = PathScopeGuide(allowed_paths=[scope])
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "write",
           "input": {"path": "/etc/passwd"}})
    assert r.allow is False


def test_path_scope_guide_allows_when_no_path_key():
    """Tools without a 'path' input are passed through; this guard scopes file ops only."""
    g = PathScopeGuide(allowed_paths=[Path("/tmp")])
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
           "input": {"cmd": "ls"}})
    assert r.allow is True
    assert "no path" in r.reason.lower()
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_guides.py -v`
Expected: ImportError for PathScopeGuide.

- [ ] **Step 3: Implement PathScopeGuide**

Append to `pi_harness/guards/guides.py`:
```python
import os
from pathlib import Path


class PathScopeGuide:
    """For file-like tools, deny if the input `path` resolves outside `allowed_paths`.

    Uses os.path.realpath (resolves symlinks AND `..`) so dotdot escapes
    or symlink tricks cannot bypass the check. Tools with no `path` key
    (e.g. plain bash with `cmd`) pass through.
    """

    kind = GuardKind.COMPUTATIONAL_GUIDE

    def __init__(self, allowed_paths: list[Path]) -> None:
        self.allowed: list[str] = [os.path.realpath(str(p)) for p in allowed_paths]

    def __call__(self, intent: ActionIntent) -> GuardResult:
        path_value = intent.get("input", {}).get("path")
        if path_value is None:
            return GuardResult(allow=True, reason="no path in input, skipped")

        real = os.path.realpath(str(path_value))
        for root in self.allowed:
            if real == root or real.startswith(root + os.sep):
                return GuardResult(
                    allow=True,
                    reason=f"path inside scope {root}",
                    metadata={"real": real, "scope": root},
                )

        return GuardResult(
            allow=False,
            reason=f"path '{real}' outside scope {self.allowed}",
            metadata={"real": real, "allowed": self.allowed},
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_guides.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/guides.py tests/guards/test_guides.py
git commit -m "feat(guards): add PathScopeGuide with realpath escape detection"
```

---

## Task 8: SchemaValidatorGuide

**Files:**
- Modify: `pi_harness/guards/guides.py`
- Modify: `tests/guards/test_guides.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_guides.py`:
```python
from pi_harness.guards.guides import SchemaValidatorGuide


def test_schema_validator_allows_valid_input():
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    g = SchemaValidatorGuide(tool_name="read", schema=schema)
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
           "input": {"path": "/x"}})
    assert r.allow is True


def test_schema_validator_denies_invalid_input():
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    g = SchemaValidatorGuide(tool_name="read", schema=schema)
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
           "input": {}})  # missing required 'path'
    assert r.allow is False
    assert "schema" in r.reason.lower()


def test_schema_validator_skips_other_tools():
    """Guard scoped to a tool_name; other tools pass through."""
    g = SchemaValidatorGuide(tool_name="read", schema={"type": "object"})
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
           "input": {"cmd": "ls"}})
    assert r.allow is True
    assert "different tool" in r.reason.lower()
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_guides.py -v`
Expected: ImportError for SchemaValidatorGuide.

- [ ] **Step 3: Implement SchemaValidatorGuide**

Append to `pi_harness/guards/guides.py`:
```python
import jsonschema


class SchemaValidatorGuide:
    """Validate the `input` of a specific tool against a JSON Schema.

    Only fires for `intent["tool"] == tool_name`; other tools pass through.
    On schema failure, returns `allow=False` with the validator's error.
    """

    kind = GuardKind.COMPUTATIONAL_GUIDE

    def __init__(self, tool_name: str, schema: dict) -> None:
        self.tool_name = tool_name
        self.schema = schema
        self._validator = jsonschema.Draft202012Validator(schema)

    def __call__(self, intent: ActionIntent) -> GuardResult:
        if intent.get("tool") != self.tool_name:
            return GuardResult(allow=True, reason=f"different tool, skipped")

        errors = list(self._validator.iter_errors(intent.get("input", {})))
        if not errors:
            return GuardResult(allow=True, reason="schema ok")

        msg = "; ".join(e.message for e in errors)
        return GuardResult(
            allow=False,
            reason=f"schema fail: {msg}",
            metadata={"errors": [e.message for e in errors]},
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_guides.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/guides.py tests/guards/test_guides.py
git commit -m "feat(guards): add SchemaValidatorGuide using jsonschema"
```

---

## Task 9: RateLimitGuide

**Files:**
- Modify: `pi_harness/guards/guides.py`
- Modify: `tests/guards/test_guides.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_guides.py`:
```python
from pi_harness.guards.guides import RateLimitGuide


def test_rate_limit_guide_allows_under_cap(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("pi_harness.guards.guides.time.monotonic", lambda: now[0])

    g = RateLimitGuide(tool_name="bash", max_per_minute=3)
    for i in range(3):
        now[0] = float(i)
        r = g({"run_id": "r", "agent_id": "a", "step_id": f"s{i}", "tool": "bash", "input": {}})
        assert r.allow is True


def test_rate_limit_guide_denies_over_cap(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("pi_harness.guards.guides.time.monotonic", lambda: now[0])

    g = RateLimitGuide(tool_name="bash", max_per_minute=2)
    # Consume the budget
    g({"run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "bash", "input": {}})
    now[0] = 1.0
    g({"run_id": "r", "agent_id": "a", "step_id": "s2", "tool": "bash", "input": {}})
    now[0] = 2.0
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s3", "tool": "bash", "input": {}})
    assert r.allow is False
    assert "rate" in r.reason.lower()


def test_rate_limit_guide_refills_after_window(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("pi_harness.guards.guides.time.monotonic", lambda: now[0])

    g = RateLimitGuide(tool_name="bash", max_per_minute=2)
    g({"run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "bash", "input": {}})
    g({"run_id": "r", "agent_id": "a", "step_id": "s2", "tool": "bash", "input": {}})
    now[0] = 65.0  # past the 60s window
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s3", "tool": "bash", "input": {}})
    assert r.allow is True


def test_rate_limit_guide_skips_other_tools():
    g = RateLimitGuide(tool_name="bash", max_per_minute=1)
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read", "input": {}})
    assert r.allow is True


def test_rate_limit_guide_separates_agents(monkeypatch):
    """The bucket key is (agent_id, tool); two agents should not share quota."""
    now = [0.0]
    monkeypatch.setattr("pi_harness.guards.guides.time.monotonic", lambda: now[0])

    g = RateLimitGuide(tool_name="bash", max_per_minute=1)
    r1 = g({"run_id": "r", "agent_id": "agent1", "step_id": "s", "tool": "bash", "input": {}})
    r2 = g({"run_id": "r", "agent_id": "agent2", "step_id": "s", "tool": "bash", "input": {}})
    assert r1.allow is True
    assert r2.allow is True
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_guides.py -v`
Expected: ImportError for RateLimitGuide.

- [ ] **Step 3: Implement RateLimitGuide**

Append to `pi_harness/guards/guides.py`:
```python
import time
from collections import deque


class RateLimitGuide:
    """Per-(agent_id, tool) token-bucket-style limiter.

    Keeps a sliding 60-second window of call timestamps per key.
    Calls beyond `max_per_minute` in that window are denied.
    Other tools pass through.
    """

    kind = GuardKind.COMPUTATIONAL_GUIDE
    WINDOW_SECONDS = 60.0

    def __init__(self, tool_name: str, max_per_minute: int) -> None:
        self.tool_name = tool_name
        self.max = max_per_minute
        self._buckets: dict[tuple[str, str], deque[float]] = {}

    def __call__(self, intent: ActionIntent) -> GuardResult:
        if intent.get("tool") != self.tool_name:
            return GuardResult(allow=True, reason="different tool, skipped")

        key = (intent.get("agent_id", ""), self.tool_name)
        now = time.monotonic()
        bucket = self._buckets.setdefault(key, deque())

        # Evict timestamps outside the window
        while bucket and bucket[0] < now - self.WINDOW_SECONDS:
            bucket.popleft()

        if len(bucket) >= self.max:
            return GuardResult(
                allow=False,
                reason=f"rate limit: {len(bucket)}/{self.max} per {int(self.WINDOW_SECONDS)}s",
                metadata={"current": len(bucket), "max": self.max},
            )

        bucket.append(now)
        return GuardResult(
            allow=True,
            reason=f"rate ok: {len(bucket)}/{self.max}",
            metadata={"current": len(bucket), "max": self.max},
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_guides.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/guides.py tests/guards/test_guides.py
git commit -m "feat(guards): add RateLimitGuide token-bucket limiter"
```

---

## Task 10: RegexAssertionSensor

**Files:**
- Create: `pi_harness/guards/sensors.py`
- Create: `tests/guards/test_sensors.py`

- [ ] **Step 1: Write failing test**

Create `tests/guards/test_sensors.py`:
```python
from pi_harness.guards.sensors import RegexAssertionSensor
from pi_harness.guards.types import GuardKind


def _result(output_text="hello world", **kw):
    base = {
        "run_id": "r", "agent_id": "a", "step_id": "s",
        "tool": "bash", "input": {}, "output": {"stdout": output_text},
    }
    base.update(kw)
    return base


def test_regex_sensor_kind():
    s = RegexAssertionSensor(pattern=r"hello", must_match=True)
    assert s.kind == GuardKind.COMPUTATIONAL_SENSOR


def test_regex_sensor_must_match_passes():
    s = RegexAssertionSensor(pattern=r"hello", must_match=True)
    r = s(_result("hello world"))
    assert r.allow is True


def test_regex_sensor_must_match_fails():
    s = RegexAssertionSensor(pattern=r"goodbye", must_match=True)
    r = s(_result("hello world"))
    assert r.allow is False
    assert "did not match" in r.reason


def test_regex_sensor_must_not_match_passes():
    s = RegexAssertionSensor(pattern=r"error", must_match=False)
    r = s(_result("hello world"))
    assert r.allow is True


def test_regex_sensor_must_not_match_fails():
    s = RegexAssertionSensor(pattern=r"hello", must_match=False)
    r = s(_result("hello world"))
    assert r.allow is False
    assert "should not match" in r.reason


def test_regex_sensor_handles_non_string_output():
    s = RegexAssertionSensor(pattern=r"x", must_match=True)
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "t",
           "input": {}, "output": {"data": [1, 2]}})
    # Coerces output to str(...) for matching
    assert r.allow is False
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_sensors.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement RegexAssertionSensor**

Create `pi_harness/guards/sensors.py`:
```python
"""Built-in Sensors (feedback, fire after a tool result is observed)."""
from __future__ import annotations

import re

from pi_harness.guards.types import ActionResult, GuardKind, GuardResult


class RegexAssertionSensor:
    """Assert that the stringified tool output matches (or doesn't match) a pattern.

    Computational. Concatenates all values in `result["output"]` with str() and
    runs re.search. `must_match=True` means the pattern MUST be present;
    `must_match=False` means it MUST NOT be present.
    """

    kind = GuardKind.COMPUTATIONAL_SENSOR

    def __init__(self, pattern: str, must_match: bool) -> None:
        self.pattern = pattern
        self.regex = re.compile(pattern)
        self.must_match = must_match

    def __call__(self, result: ActionResult) -> GuardResult:
        text = str(result.get("output", ""))
        hit = self.regex.search(text) is not None

        if self.must_match and hit:
            return GuardResult(allow=True, reason=f"pattern '{self.pattern}' matched")
        if self.must_match and not hit:
            return GuardResult(
                allow=False,
                reason=f"pattern '{self.pattern}' did not match",
                metadata={"pattern": self.pattern, "must_match": True},
            )
        if not self.must_match and hit:
            return GuardResult(
                allow=False,
                reason=f"pattern '{self.pattern}' should not match but did",
                metadata={"pattern": self.pattern, "must_match": False},
            )
        return GuardResult(allow=True, reason=f"pattern '{self.pattern}' absent (ok)")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_sensors.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/sensors.py tests/guards/test_sensors.py
git commit -m "feat(guards): add RegexAssertionSensor"
```

---

## Task 11: ExitCodeSensor

**Files:**
- Modify: `pi_harness/guards/sensors.py`
- Modify: `tests/guards/test_sensors.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_sensors.py`:
```python
from pi_harness.guards.sensors import ExitCodeSensor


def test_exit_code_sensor_allows_expected():
    s = ExitCodeSensor(expected_codes={0})
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
           "input": {}, "output": {}, "exit_code": 0})
    assert r.allow is True


def test_exit_code_sensor_denies_unexpected():
    s = ExitCodeSensor(expected_codes={0})
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
           "input": {}, "output": {}, "exit_code": 1})
    assert r.allow is False
    assert "exit code 1" in r.reason


def test_exit_code_sensor_skips_when_no_exit_code():
    s = ExitCodeSensor(expected_codes={0})
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
           "input": {}, "output": {}})
    assert r.allow is True
    assert "no exit_code" in r.reason
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_sensors.py -v`
Expected: ImportError for ExitCodeSensor.

- [ ] **Step 3: Implement ExitCodeSensor**

Append to `pi_harness/guards/sensors.py`:
```python
class ExitCodeSensor:
    """Assert that the tool's `exit_code` is in `expected_codes`.

    For bash-like tools that include `exit_code` in the result. Tools
    without an `exit_code` key pass through.
    """

    kind = GuardKind.COMPUTATIONAL_SENSOR

    def __init__(self, expected_codes: set[int]) -> None:
        self.expected: set[int] = set(expected_codes)

    def __call__(self, result: ActionResult) -> GuardResult:
        if "exit_code" not in result:
            return GuardResult(allow=True, reason="no exit_code in result, skipped")

        code = result["exit_code"]
        if code in self.expected:
            return GuardResult(allow=True, reason=f"exit code {code} ok")
        return GuardResult(
            allow=False,
            reason=f"exit code {code} not in expected {sorted(self.expected)}",
            metadata={"exit_code": code, "expected": sorted(self.expected)},
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_sensors.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/sensors.py tests/guards/test_sensors.py
git commit -m "feat(guards): add ExitCodeSensor"
```

---

## Task 12: JudgeAgentSensor (with mocked OpenAI client)

**Files:**
- Modify: `pi_harness/guards/sensors.py`
- Modify: `tests/guards/test_sensors.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_sensors.py`:
```python
from unittest.mock import MagicMock, patch
from pi_harness.guards.sensors import JudgeAgentSensor


def _mock_openai_response(verdict: str, confidence: float):
    """Build a mock OpenAI ChatCompletion response."""
    msg = MagicMock()
    msg.content = f'{{"verdict": "{verdict}", "confidence": {confidence}, "reason": "stub"}}'
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@patch("pi_harness.guards.sensors.OpenAI")
def test_judge_agent_sensor_passes(mock_openai_cls):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response("PASS", 0.95)
    mock_openai_cls.return_value = mock_client

    s = JudgeAgentSensor(
        criterion="Output must mention 'success'",
        judge_model="gpt-4o-mini",
        api_key="sk-test",
    )
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
           "input": {}, "output": {"stdout": "task success"}})
    assert r.allow is True
    assert r.confidence == 0.95


@patch("pi_harness.guards.sensors.OpenAI")
def test_judge_agent_sensor_fails(mock_openai_cls):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response("FAIL", 0.8)
    mock_openai_cls.return_value = mock_client

    s = JudgeAgentSensor(
        criterion="Output must mention 'success'",
        judge_model="gpt-4o-mini",
        api_key="sk-test",
    )
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
           "input": {}, "output": {"stdout": "fail"}})
    assert r.allow is False
    assert r.confidence == 0.8


@patch("pi_harness.guards.sensors.OpenAI")
def test_judge_agent_sensor_handles_invalid_json(mock_openai_cls):
    mock_client = MagicMock()
    bad = MagicMock()
    bad.choices = [MagicMock(message=MagicMock(content="not json at all"))]
    mock_client.chat.completions.create.return_value = bad
    mock_openai_cls.return_value = mock_client

    s = JudgeAgentSensor(
        criterion="x",
        judge_model="gpt-4o-mini",
        api_key="sk-test",
    )
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s", "tool": "t",
           "input": {}, "output": {}})
    assert r.allow is False
    assert r.confidence is None
    assert "parse" in r.reason.lower()


@patch("pi_harness.guards.sensors.OpenAI")
def test_judge_agent_sensor_kind_is_inferential(mock_openai_cls):
    from pi_harness.guards.types import GuardKind
    s = JudgeAgentSensor(
        criterion="x", judge_model="gpt-4o-mini", api_key="sk-test",
    )
    assert s.kind == GuardKind.INFERENTIAL_SENSOR
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_sensors.py -v`
Expected: ImportError for JudgeAgentSensor.

- [ ] **Step 3: Implement JudgeAgentSensor**

Append to `pi_harness/guards/sensors.py`:
```python
import json

from openai import OpenAI


JUDGE_SYSTEM_PROMPT = (
    "You are a strict pass/fail judge. Given a criterion and an action result, "
    "decide whether the result satisfies the criterion.\n\n"
    "Respond with ONLY a JSON object of the form:\n"
    '{"verdict": "PASS" | "FAIL", "confidence": <float 0..1>, "reason": "<short>"}'
)


class JudgeAgentSensor:
    """Inferential sensor: an LLM scores tool output against a natural-language criterion.

    Uses the OpenAI client directly (no streaming, single completion). v1 is
    OpenAI-only; multi-provider arrives in v2. Returns confidence from the
    judge's structured JSON. If JSON parse fails, `allow=False`, `confidence=None`.
    """

    kind = GuardKind.INFERENTIAL_SENSOR

    def __init__(self, criterion: str, judge_model: str, api_key: str) -> None:
        self.criterion = criterion
        self.judge_model = judge_model
        self._client = OpenAI(api_key=api_key)

    def __call__(self, result: ActionResult) -> GuardResult:
        user_prompt = (
            f"Criterion: {self.criterion}\n\n"
            f"Action tool: {result.get('tool')}\n"
            f"Action input: {json.dumps(result.get('input', {}))[:500]}\n"
            f"Action output: {json.dumps(result.get('output', {}))[:2000]}"
        )

        response = self._client.chat.completions.create(
            model=self.judge_model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return GuardResult(
                allow=False,
                reason=f"judge response parse error: {content[:120]}",
                confidence=None,
                metadata={"raw": content},
            )

        verdict = data.get("verdict", "FAIL")
        confidence = data.get("confidence")
        reason = data.get("reason", "")

        if isinstance(confidence, (int, float)):
            confidence = float(confidence)
        else:
            confidence = None

        return GuardResult(
            allow=(verdict == "PASS"),
            reason=f"{verdict}: {reason}",
            confidence=confidence,
            metadata={"criterion": self.criterion, "model": self.judge_model},
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_sensors.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/sensors.py tests/guards/test_sensors.py
git commit -m "feat(guards): add JudgeAgentSensor (inferential, OpenAI-backed)"
```

---

## Task 13: TokenBudgetSensor

**Files:**
- Modify: `pi_harness/guards/sensors.py`
- Modify: `tests/guards/test_sensors.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_sensors.py`:
```python
from pi_harness.guards.sensors import TokenBudgetSensor


def test_token_budget_sensor_allows_under_soft():
    s = TokenBudgetSensor(soft_max=1000, hard_max=2000)
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "t",
           "input": {}, "output": {}, "tokens_in": 100, "tokens_out": 200})
    assert r.allow is True
    assert "under soft" in r.reason


def test_token_budget_sensor_warns_above_soft():
    s = TokenBudgetSensor(soft_max=1000, hard_max=2000)
    # Step 1 consumes 800
    s({"run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "t",
       "input": {}, "output": {}, "tokens_in": 400, "tokens_out": 400})
    # Step 2 pushes over soft (now 1100 cumulative)
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s2", "tool": "t",
           "input": {}, "output": {}, "tokens_in": 150, "tokens_out": 150})
    assert r.allow is True   # soft is a warning, not a block
    assert "soft" in r.reason.lower()


def test_token_budget_sensor_denies_above_hard():
    s = TokenBudgetSensor(soft_max=1000, hard_max=2000)
    r = s({"run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "t",
           "input": {}, "output": {}, "tokens_in": 1500, "tokens_out": 600})
    assert r.allow is False
    assert "hard" in r.reason.lower()


def test_token_budget_sensor_per_agent():
    s = TokenBudgetSensor(soft_max=1000, hard_max=2000)
    r1 = s({"run_id": "r", "agent_id": "agent1", "step_id": "s", "tool": "t",
            "input": {}, "output": {}, "tokens_in": 1500, "tokens_out": 0})
    r2 = s({"run_id": "r", "agent_id": "agent2", "step_id": "s", "tool": "t",
            "input": {}, "output": {}, "tokens_in": 100, "tokens_out": 100})
    assert "soft" in r1.reason.lower() or r1.allow is True
    assert r2.allow is True
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_sensors.py -v`
Expected: ImportError for TokenBudgetSensor.

- [ ] **Step 3: Implement TokenBudgetSensor**

Append to `pi_harness/guards/sensors.py`:
```python
class TokenBudgetSensor:
    """Track cumulative tokens per agent across a run; warn at soft, deny at hard.

    Reads `tokens_in` + `tokens_out` from the result (pi-agent records these).
    Soft breach -> allow=True with reason mentioning "soft" (advisory).
    Hard breach -> allow=False (the next step gets a deny signal).
    """

    kind = GuardKind.COMPUTATIONAL_SENSOR

    def __init__(self, soft_max: int, hard_max: int) -> None:
        if hard_max < soft_max:
            raise ValueError("hard_max must be >= soft_max")
        self.soft_max = soft_max
        self.hard_max = hard_max
        self._totals: dict[str, int] = {}

    def __call__(self, result: ActionResult) -> GuardResult:
        agent = result.get("agent_id", "")
        used = int(result.get("tokens_in", 0)) + int(result.get("tokens_out", 0))
        total = self._totals.get(agent, 0) + used
        self._totals[agent] = total

        if total > self.hard_max:
            return GuardResult(
                allow=False,
                reason=f"hard token budget exceeded: {total}/{self.hard_max}",
                metadata={"total": total, "hard_max": self.hard_max},
            )
        if total > self.soft_max:
            return GuardResult(
                allow=True,
                reason=f"soft budget exceeded: {total}/{self.soft_max}",
                metadata={"total": total, "soft_max": self.soft_max},
            )
        return GuardResult(
            allow=True,
            reason=f"under soft budget: {total}/{self.soft_max}",
            metadata={"total": total},
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_sensors.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/sensors.py tests/guards/test_sensors.py
git commit -m "feat(guards): add TokenBudgetSensor with soft/hard caps"
```

---

## Task 14: GuardRunner skeleton (attach + construct)

**Files:**
- Create: `pi_harness/guards/runner.py`
- Create: `tests/guards/test_runner.py`

- [ ] **Step 1: Write failing test**

Create `tests/guards/test_runner.py`:
```python
from pi_harness.guards.runner import GuardRunner
from pi_harness.guards.guides import AllowlistGuide
from pi_harness.guards.sensors import RegexAssertionSensor


def test_guard_runner_construct():
    r = GuardRunner(run_id="run1", agent_id="builder")
    assert r.run_id == "run1"
    assert r.agent_id == "builder"
    assert r.guides == []
    assert r.sensors == []


def test_guard_runner_attach_guides():
    r = GuardRunner(run_id="run1", agent_id="builder")
    g = AllowlistGuide(allowed_tools=["bash"])
    r.attach_guides([g])
    assert r.guides == [g]


def test_guard_runner_attach_sensors():
    r = GuardRunner(run_id="run1", agent_id="builder")
    s = RegexAssertionSensor(pattern=r"x", must_match=True)
    r.attach_sensors([s])
    assert r.sensors == [s]


def test_guard_runner_attach_extends_not_replaces():
    r = GuardRunner(run_id="run1", agent_id="builder")
    g1 = AllowlistGuide(allowed_tools=["a"])
    g2 = AllowlistGuide(allowed_tools=["b"])
    r.attach_guides([g1])
    r.attach_guides([g2])
    assert r.guides == [g1, g2]
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_runner.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement GuardRunner skeleton**

Create `pi_harness/guards/runner.py`:
```python
"""GuardRunner — orchestrates guides + sensors around pi-coding-agent tool calls.

Integration assumption (verify against pi-coding-agent docs):
    pi-coding-agent emits newline-delimited JSON to stdout. Each tool call is
    `{"type": "tool_call", "id": str, "name": str, "input": dict}`. Each tool
    result is `{"type": "tool_result", "id": str, "output": dict,
    "exit_code"?: int}`.

    A Python wrapper subprocess reads these lines, converts them to
    ActionIntent / ActionResult dicts, and calls intercept_tool_call /
    intercept_tool_result. On a denied intercept_tool_call the wrapper writes
    a synthetic `{"type": "tool_result", "id": <same>, "output":
    {"error": <reason>}, "exit_code": 1}` to the agent's stdin, so the agent
    perceives a tool error and can recover.

    THIS WRAPPER IS NOT IMPLEMENTED IN THIS PLAN. Only the Python-side surface
    (this class) is. Wiring is a future integration plan.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from pi_harness.guards.types import (
    ActionIntent,
    ActionResult,
    Guide,
    GuardResult,
    Sensor,
)
from pi_harness.trajectory.schema import TrajectoryEvent
from pi_harness.trajectory.store import write_event


class GuardRunner:
    """Per-(run, agent) container for guides + sensors. Wraps the tool stream."""

    def __init__(self, run_id: str, agent_id: str) -> None:
        self.run_id = run_id
        self.agent_id = agent_id
        self.guides: list[Guide] = []
        self.sensors: list[Sensor] = []

    def attach_guides(self, guides: Iterable[Guide]) -> None:
        """Append guides; existing guides are preserved (order-stable)."""
        self.guides.extend(list(guides))

    def attach_sensors(self, sensors: Iterable[Sensor]) -> None:
        """Append sensors; existing sensors are preserved (order-stable)."""
        self.sensors.extend(list(sensors))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_runner.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/runner.py tests/guards/test_runner.py
git commit -m "feat(guards): add GuardRunner skeleton with attach methods"
```

---

## Task 15: GuardRunner.intercept_tool_call — short-circuit chain + event emission

**Files:**
- Modify: `pi_harness/guards/runner.py`
- Modify: `tests/guards/test_runner.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_runner.py`:
```python
from unittest.mock import patch, MagicMock
from pi_harness.guards.types import GuardKind, GuardResult


class AlwaysAllow:
    kind = GuardKind.COMPUTATIONAL_GUIDE
    def __init__(self):
        self.calls = 0
    def __call__(self, intent):
        self.calls += 1
        return GuardResult(allow=True, reason="allow")


class AlwaysDeny:
    kind = GuardKind.COMPUTATIONAL_GUIDE
    def __init__(self):
        self.calls = 0
    def __call__(self, intent):
        self.calls += 1
        return GuardResult(allow=False, reason="deny", metadata={"why": "test"})


def _intent():
    return {"run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "bash", "input": {}}


@patch("pi_harness.guards.runner.write_event")
def test_intercept_allows_when_all_guides_allow(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    g1, g2 = AlwaysAllow(), AlwaysAllow()
    r.attach_guides([g1, g2])

    result = r.intercept_tool_call(_intent())
    assert result.allow is True
    assert g1.calls == 1 and g2.calls == 1


@patch("pi_harness.guards.runner.write_event")
def test_intercept_short_circuits_on_first_deny(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    deny = AlwaysDeny()
    after = AlwaysAllow()
    r.attach_guides([deny, after])

    result = r.intercept_tool_call(_intent())
    assert result.allow is False
    assert deny.calls == 1
    assert after.calls == 0   # short-circuited


@patch("pi_harness.guards.runner.write_event")
def test_intercept_writes_guide_fired_event_on_deny(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    r.attach_guides([AlwaysDeny()])

    r.intercept_tool_call(_intent())

    assert mock_write.call_count == 1
    event = mock_write.call_args[0][0]
    assert event.classification == "guide_fired"
    assert event.outcome == "deny"
    assert event.run_id == "r"
    assert event.agent_id == "a"


@patch("pi_harness.guards.runner.write_event")
def test_intercept_writes_guide_fired_event_on_allow_too(mock_write):
    """Allow events are still recorded — needed for promote analysis."""
    r = GuardRunner(run_id="r", agent_id="a")
    r.attach_guides([AlwaysAllow()])

    r.intercept_tool_call(_intent())

    assert mock_write.call_count == 1
    event = mock_write.call_args[0][0]
    assert event.classification == "guide_fired"
    assert event.outcome == "allow"
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_runner.py -v`
Expected: AttributeError — `intercept_tool_call` missing.

- [ ] **Step 3: Implement intercept_tool_call**

Append to `pi_harness/guards/runner.py`:
```python
    def intercept_tool_call(self, intent: ActionIntent) -> GuardResult:
        """Run all attached guides on `intent`; first deny short-circuits.

        Every fire (allow or deny) emits a TrajectoryEvent with
        classification="guide_fired". Returns the first deny GuardResult, or
        the last allow GuardResult if all guides allow.
        """
        last_allow: GuardResult = GuardResult(allow=True, reason="no guides attached")

        for guide in self.guides:
            result = guide(intent)
            self._emit_guide_event(intent, guide, result)

            if not result.allow:
                return result
            last_allow = result

        return last_allow

    def _emit_guide_event(
        self,
        intent: ActionIntent,
        guide: Guide,
        result: GuardResult,
    ) -> None:
        kind_value = getattr(getattr(guide, "kind", None), "value", "unknown")
        event = TrajectoryEvent(
            run_id=self.run_id,
            agent_id=self.agent_id,
            step_id=intent.get("step_id", ""),
            ts=datetime.now(timezone.utc),
            tool=intent.get("tool"),
            input=dict(intent.get("input", {})),
            output=None,
            outcome=("allow" if result.allow else "deny"),
            classification="guide_fired",
            metadata={
                "guide": type(guide).__name__,
                "guide_kind": kind_value,
                "reason": result.reason,
                "confidence": result.confidence,
                "guard_metadata": dict(result.metadata),
            },
        )
        write_event(event)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_runner.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/runner.py tests/guards/test_runner.py
git commit -m "feat(guards): GuardRunner.intercept_tool_call with short-circuit + event emit"
```

---

## Task 16: GuardRunner.intercept_tool_result — run all sensors

**Files:**
- Modify: `pi_harness/guards/runner.py`
- Modify: `tests/guards/test_runner.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_runner.py`:
```python
class AlwaysAllowSensor:
    kind = GuardKind.COMPUTATIONAL_SENSOR
    def __init__(self): self.calls = 0
    def __call__(self, result):
        self.calls += 1
        return GuardResult(allow=True, reason="sensor allow")


class AlwaysDenySensor:
    kind = GuardKind.COMPUTATIONAL_SENSOR
    def __init__(self): self.calls = 0
    def __call__(self, result):
        self.calls += 1
        return GuardResult(allow=False, reason="sensor deny")


def _result():
    return {
        "run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "bash",
        "input": {}, "output": {"stdout": "x"},
    }


@patch("pi_harness.guards.runner.write_event")
def test_intercept_tool_result_runs_all_sensors(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    s1, s2 = AlwaysAllowSensor(), AlwaysDenySensor()
    r.attach_sensors([s1, s2])

    results = r.intercept_tool_result(_result())
    assert len(results) == 2
    assert s1.calls == 1 and s2.calls == 1  # all run, no short-circuit


@patch("pi_harness.guards.runner.write_event")
def test_intercept_tool_result_writes_one_event_per_sensor(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    r.attach_sensors([AlwaysAllowSensor(), AlwaysDenySensor()])

    r.intercept_tool_result(_result())

    assert mock_write.call_count == 2
    classifications = [c.args[0].classification for c in mock_write.call_args_list]
    assert classifications == ["sensor_fired", "sensor_fired"]
    outcomes = [c.args[0].outcome for c in mock_write.call_args_list]
    assert outcomes == ["allow", "deny"]


@patch("pi_harness.guards.runner.write_event")
def test_intercept_tool_result_no_sensors_returns_empty(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    results = r.intercept_tool_result(_result())
    assert results == []
    assert mock_write.call_count == 0
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_runner.py -v`
Expected: AttributeError.

- [ ] **Step 3: Implement intercept_tool_result**

Append to `pi_harness/guards/runner.py`:
```python
    def intercept_tool_result(self, action_result: ActionResult) -> list[GuardResult]:
        """Run every attached sensor on `action_result`. No short-circuit.

        Returns the list of GuardResults in attach order. Each fire emits a
        TrajectoryEvent with classification="sensor_fired".
        """
        out: list[GuardResult] = []
        for sensor in self.sensors:
            result = sensor(action_result)
            self._emit_sensor_event(action_result, sensor, result)
            out.append(result)
        return out

    def _emit_sensor_event(
        self,
        action_result: ActionResult,
        sensor: Sensor,
        result: GuardResult,
    ) -> None:
        kind_value = getattr(getattr(sensor, "kind", None), "value", "unknown")
        event = TrajectoryEvent(
            run_id=self.run_id,
            agent_id=self.agent_id,
            step_id=action_result.get("step_id", ""),
            ts=datetime.now(timezone.utc),
            tool=action_result.get("tool"),
            input=dict(action_result.get("input", {})),
            output=dict(action_result.get("output", {})),
            outcome=("allow" if result.allow else "deny"),
            classification="sensor_fired",
            metadata={
                "sensor": type(sensor).__name__,
                "sensor_kind": kind_value,
                "reason": result.reason,
                "confidence": result.confidence,
                "guard_metadata": dict(result.metadata),
            },
        )
        write_event(event)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_runner.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/runner.py tests/guards/test_runner.py
git commit -m "feat(guards): GuardRunner.intercept_tool_result fires all sensors"
```

---

## Task 17: Re-export GuardRunner from guards.__init__

**Files:**
- Modify: `pi_harness/guards/__init__.py`
- Modify: `tests/guards/test_runner.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_runner.py`:
```python
def test_guard_runner_reexported_from_package():
    from pi_harness.guards import GuardRunner as TopLevel
    from pi_harness.guards.runner import GuardRunner as Internal
    assert TopLevel is Internal
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_runner.py::test_guard_runner_reexported_from_package -v`
Expected: ImportError.

- [ ] **Step 3: Add export to `pi_harness/guards/__init__.py`**

Edit `pi_harness/guards/__init__.py`. Add to existing imports block:
```python
from pi_harness.guards.runner import GuardRunner
```

And append `"GuardRunner"` to the `__all__` list.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/ -v`
Expected: all green (32 tests at this point).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/__init__.py tests/guards/test_runner.py
git commit -m "feat(guards): re-export GuardRunner from package root"
```

---

## Task 18: PromotionSuggestion dataclass + promote module skeleton

**Files:**
- Create: `pi_harness/guards/promote.py`
- Create: `tests/guards/test_promote.py`

- [ ] **Step 1: Write failing test**

Create `tests/guards/test_promote.py`:
```python
from pi_harness.guards.promote import PromotionSuggestion


def test_promotion_suggestion_fields():
    s = PromotionSuggestion(
        sensor_name="JudgeAgentSensor",
        sensor_criterion="x",
        fires=25,
        allow_fraction=0.92,
        suggested_stub_code="class FooGuide: ...",
        suggested_kind="computational_guide",
        evidence={"sample_outputs": []},
    )
    assert s.fires == 25
    assert s.allow_fraction == 0.92
    assert "FooGuide" in s.suggested_stub_code
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_promote.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement PromotionSuggestion**

Create `pi_harness/guards/promote.py`:
```python
"""Promote-to-Guide — offline analysis of sensor history.

When an inferential sensor (typically JudgeAgentSensor) fires many times with
low-variance outcomes, the same decision can be cheaply hard-coded. This
module scans the trajectory store for such sensors and produces stub Guide
code the user can review and install at `~/.pi-harness/guards/<name>.py`.

No LLM is involved here. The user's "promote" decision is still manual:
they read the stub, accept it, drop it in the guards directory, and on next
run `load_user_guards` picks it up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PromotionSuggestion:
    """A candidate Guide derived from an oft-firing sensor's history."""

    sensor_name: str
    sensor_criterion: str
    fires: int
    allow_fraction: float
    suggested_stub_code: str
    suggested_kind: str
    evidence: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_promote.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/promote.py tests/guards/test_promote.py
git commit -m "feat(promote): add PromotionSuggestion dataclass"
```

---

## Task 19: suggest_promotions — group events + filter min_fires/variance

**Files:**
- Modify: `pi_harness/guards/promote.py`
- Modify: `tests/guards/test_promote.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_promote.py`:
```python
from unittest.mock import patch
from datetime import datetime, timezone
from pi_harness.guards.promote import suggest_promotions
from pi_harness.trajectory.schema import TrajectoryEvent


def _sensor_event(sensor_name: str, criterion: str, outcome: str, idx: int) -> TrajectoryEvent:
    return TrajectoryEvent(
        run_id="r",
        agent_id="a",
        step_id=f"step{idx}",
        ts=datetime.now(timezone.utc),
        tool="bash",
        input={"cmd": "ls"},
        output={"stdout": "ok"},
        outcome=outcome,
        classification="sensor_fired",
        metadata={
            "sensor": sensor_name,
            "sensor_kind": "inferential_sensor",
            "reason": f"sample {idx}",
            "confidence": 0.9,
            "guard_metadata": {"criterion": criterion, "model": "gpt-4o-mini"},
        },
    )


@patch("pi_harness.guards.promote.query_events")
def test_no_candidates_when_too_few_fires(mock_q):
    mock_q.return_value = [
        _sensor_event("JudgeAgentSensor", "be polite", "allow", i)
        for i in range(5)
    ]
    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert out == []


@patch("pi_harness.guards.promote.query_events")
def test_no_candidates_when_high_variance(mock_q):
    # 50/50 split is high variance
    events = (
        [_sensor_event("JudgeAgentSensor", "be polite", "allow", i) for i in range(13)]
        + [_sensor_event("JudgeAgentSensor", "be polite", "deny", i + 13) for i in range(12)]
    )
    mock_q.return_value = events
    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert out == []


@patch("pi_harness.guards.promote.query_events")
def test_candidate_emitted_with_23_allow_2_deny(mock_q):
    # The acceptance-criteria case: 25 fires, 23 PASS / 2 FAIL, allow_fraction = 0.92
    events = (
        [_sensor_event("JudgeAgentSensor", "must mention success", "allow", i)
         for i in range(23)]
        + [_sensor_event("JudgeAgentSensor", "must mention success", "deny", i + 23)
           for i in range(2)]
    )
    mock_q.return_value = events
    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert len(out) == 1
    sug = out[0]
    assert sug.sensor_name == "JudgeAgentSensor"
    assert sug.fires == 25
    assert abs(sug.allow_fraction - 0.92) < 0.001
    assert "must mention success" in sug.sensor_criterion
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_promote.py -v`
Expected: ImportError for suggest_promotions.

- [ ] **Step 3: Implement suggest_promotions (grouping + filter only; stub gen next task)**

Append to `pi_harness/guards/promote.py`:
```python
from collections import defaultdict

from pi_harness.trajectory.store import query_events


def suggest_promotions(
    min_fires: int = 20,
    low_variance_threshold: float = 0.1,
) -> list[PromotionSuggestion]:
    """Scan sensor history and emit promotion candidates.

    A candidate is produced for each (sensor_name, criterion) group that:
      - has at least `min_fires` events, AND
      - has `min(allow_fraction, 1-allow_fraction) <= low_variance_threshold`
        (i.e. outcomes are lopsided enough to hard-code).

    Stub code generation is delegated to `_render_stub` (filled in Task 20).
    """
    events = query_events({"classification": "sensor_fired"})

    # Group by (sensor_name, criterion); only inferential sensors are candidates.
    groups: dict[tuple[str, str], list[TrajectoryEvent]] = defaultdict(list)
    for ev in events:
        if ev.metadata.get("sensor_kind") != "inferential_sensor":
            continue
        sensor = ev.metadata.get("sensor", "")
        criterion = ev.metadata.get("guard_metadata", {}).get("criterion", "")
        groups[(sensor, criterion)].append(ev)

    out: list[PromotionSuggestion] = []
    for (sensor_name, criterion), bucket in groups.items():
        n = len(bucket)
        if n < min_fires:
            continue

        allow_n = sum(1 for ev in bucket if ev.outcome == "allow")
        allow_frac = allow_n / n
        variance = min(allow_frac, 1.0 - allow_frac)
        if variance > low_variance_threshold:
            continue

        stub_code, stub_kind = _render_stub(sensor_name, criterion, bucket, allow_frac)
        out.append(
            PromotionSuggestion(
                sensor_name=sensor_name,
                sensor_criterion=criterion,
                fires=n,
                allow_fraction=allow_frac,
                suggested_stub_code=stub_code,
                suggested_kind=stub_kind,
                evidence={
                    "allow_count": allow_n,
                    "deny_count": n - allow_n,
                    "sample_reasons": [ev.metadata.get("reason", "") for ev in bucket[:5]],
                },
            )
        )

    return out


def _render_stub(
    sensor_name: str,
    criterion: str,
    events: list[TrajectoryEvent],
    allow_frac: float,
) -> tuple[str, str]:
    """Placeholder; full stub generation in next task."""
    return ("# stub pending", "computational_guide")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_promote.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/promote.py tests/guards/test_promote.py
git commit -m "feat(promote): suggest_promotions groups, filters by fires+variance"
```

---

## Task 20: _render_stub — generate Guide source code

**Files:**
- Modify: `pi_harness/guards/promote.py`
- Modify: `tests/guards/test_promote.py`

- [ ] **Step 1: Write failing test**

Append to `tests/guards/test_promote.py`:
```python
import re


@patch("pi_harness.guards.promote.query_events")
def test_stub_for_regex_extractable_outputs(mock_q):
    """When sensor outputs share a regex-extractable pattern, suggest a RegexAssertionSensor stub."""
    events = []
    for i in range(25):
        ev = _sensor_event("JudgeAgentSensor", "output mentions OK", "allow", i)
        # All these sample outputs contain the literal "STATUS: OK"
        ev.output = {"stdout": f"line {i}\nSTATUS: OK\ndone"}
        events.append(ev)
    mock_q.return_value = events

    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert len(out) == 1
    code = out[0].suggested_stub_code
    # The generated stub should be syntactically Python and reference one of
    # the built-ins it could become.
    assert "class" in code
    assert "Guide" in code or "Sensor" in code
    assert "@register_guide" in code or "@register_sensor" in code
    # And it should be importable as Python source
    compile(code, "<stub>", "exec")


@patch("pi_harness.guards.promote.query_events")
def test_stub_for_schema_extractable_inputs(mock_q):
    """When all allow-fires share an input-key shape, the stub uses SchemaValidatorGuide."""
    events = []
    for i in range(25):
        ev = _sensor_event("JudgeAgentSensor", "input has 'path' key", "allow", i)
        ev.input = {"path": f"/tmp/file{i}.txt", "encoding": "utf-8"}
        events.append(ev)
    mock_q.return_value = events

    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert len(out) == 1
    code = out[0].suggested_stub_code
    assert "SchemaValidatorGuide" in code or "RegexAssertionSensor" in code
    compile(code, "<stub>", "exec")
    assert out[0].suggested_kind in {"computational_guide", "computational_sensor"}


@patch("pi_harness.guards.promote.query_events")
def test_stub_includes_evidence_comment(mock_q):
    events = [_sensor_event("JudgeAgentSensor", "be careful", "allow", i)
              for i in range(23)]
    events += [_sensor_event("JudgeAgentSensor", "be careful", "deny", i + 23)
               for i in range(2)]
    mock_q.return_value = events

    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    code = out[0].suggested_stub_code
    # Stub should comment why it was suggested
    assert "23/25" in code or "0.92" in code or "promoted from" in code.lower()
```

- [ ] **Step 2: Run test (fail)**

Run: `uv run pytest tests/guards/test_promote.py -v`
Expected: the new tests fail — the placeholder stub doesn't compile or doesn't contain required strings.

- [ ] **Step 3: Implement real _render_stub**

In `pi_harness/guards/promote.py` replace the placeholder `_render_stub` with:
```python
def _render_stub(
    sensor_name: str,
    criterion: str,
    events: list[TrajectoryEvent],
    allow_frac: float,
) -> tuple[str, str]:
    """Render a Python source stub for a candidate Guide or Sensor.

    Strategy:
      1. If a common substring is present in every allow-outcome event's output,
         emit a RegexAssertionSensor stub asserting that substring.
      2. Otherwise, if every allow-outcome event's input shares the same set
         of top-level keys, emit a SchemaValidatorGuide stub.
      3. Otherwise, emit a commented-out RegexAssertionSensor scaffold.

    Returns (source_code, suggested_kind).
    """
    safe_name = _slugify(criterion)
    allow_count = sum(1 for ev in events if ev.outcome == "allow")
    total = len(events)
    header = (
        f"# Auto-generated by pi_harness.guards.promote\n"
        f"# Promoted from {sensor_name}({criterion!r})\n"
        f"# Evidence: {allow_count}/{total} allow ({allow_frac:.2f}), low variance\n"
    )

    # Strategy 1: common substring in outputs?
    allow_outputs = [
        str(ev.output) for ev in events
        if ev.outcome == "allow" and ev.output is not None
    ]
    substring = _longest_common_substring(allow_outputs)
    if substring and len(substring) >= 4:
        escaped = re.escape(substring)
        code = header + (
            f"from pi_harness.guards.sensors import RegexAssertionSensor\n"
            f"from pi_harness.guards.types import register_sensor\n\n"
            f"@register_sensor(name='{safe_name}')\n"
            f"class {_pascal(safe_name)}Sensor(RegexAssertionSensor):\n"
            f"    def __init__(self):\n"
            f"        super().__init__(pattern=r'{escaped}', must_match=True)\n"
        )
        return code, "computational_sensor"

    # Strategy 2: shared input key shape?
    allow_inputs = [ev.input or {} for ev in events if ev.outcome == "allow"]
    shared_keys = _shared_top_level_keys(allow_inputs)
    if shared_keys:
        tool_name = events[0].tool or "unknown"
        schema_props = {k: {"type": "string"} for k in sorted(shared_keys)}
        code = header + (
            f"from pi_harness.guards.guides import SchemaValidatorGuide\n"
            f"from pi_harness.guards.types import register_guide\n\n"
            f"@register_guide(name='{safe_name}')\n"
            f"class {_pascal(safe_name)}Guide(SchemaValidatorGuide):\n"
            f"    def __init__(self):\n"
            f"        super().__init__(\n"
            f"            tool_name={tool_name!r},\n"
            f"            schema={{\n"
            f"                'type': 'object',\n"
            f"                'properties': {schema_props!r},\n"
            f"                'required': {sorted(shared_keys)!r},\n"
            f"            }},\n"
            f"        )\n"
        )
        return code, "computational_guide"

    # Strategy 3: scaffold (always compiles)
    code = header + (
        f"from pi_harness.guards.sensors import RegexAssertionSensor\n"
        f"from pi_harness.guards.types import register_sensor\n\n"
        f"# TODO: replace 'PATTERN' below with a regex extracted from your outputs\n"
        f"@register_sensor(name='{safe_name}')\n"
        f"class {_pascal(safe_name)}Sensor(RegexAssertionSensor):\n"
        f"    def __init__(self):\n"
        f"        super().__init__(pattern=r'PATTERN', must_match=True)\n"
    )
    return code, "computational_sensor"


def _slugify(text: str) -> str:
    """Lowercase alphanumeric + underscores, falls back to 'promoted'."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return cleaned or "promoted"


def _pascal(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_") if part)


def _longest_common_substring(strings: list[str]) -> str:
    """Return the longest substring that appears in every input string.

    Naive O(n*m^2) but sufficient: we cap inputs at the first 25 events
    and snippets at the first 500 chars.
    """
    if not strings:
        return ""
    strings = [s[:500] for s in strings[:25]]
    shortest = min(strings, key=len)
    best = ""
    for i in range(len(shortest)):
        for j in range(i + len(best) + 1, len(shortest) + 1):
            candidate = shortest[i:j]
            if all(candidate in s for s in strings):
                if len(candidate) > len(best):
                    best = candidate
            else:
                break
    return best


def _shared_top_level_keys(dicts: list[dict]) -> set[str]:
    """Intersection of top-level keys across all dicts (empty if list is empty)."""
    if not dicts:
        return set()
    keys = set(dicts[0].keys())
    for d in dicts[1:]:
        keys &= set(d.keys())
    return keys
```

Also import `re` at the top of `promote.py` if not already.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/guards/test_promote.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/promote.py tests/guards/test_promote.py
git commit -m "feat(promote): generate compilable Guide/Sensor stubs from sensor history"
```

---

## Task 21: Final integration sweep

**Files:**
- Modify: `pi_harness/guards/__init__.py`
- Verify: all `pi_harness/guards/*.py` and `tests/guards/*.py`

- [ ] **Step 1: Add remaining exports**

Edit `pi_harness/guards/__init__.py` so `__all__` includes the public surface needed by Plan 5 (Topology) and Plan 8 (Dashboard).

The file should re-export, at minimum:
- `GuardKind`, `GuardResult`, `Guide`, `Sensor`, `ActionIntent`, `ActionResult`
- `register_guide`, `register_sensor`, `GUIDE_REGISTRY`, `SENSOR_REGISTRY`, `load_user_guards`
- `GuardRunner`
- Built-ins: `AllowlistGuide`, `PathScopeGuide`, `SchemaValidatorGuide`, `RateLimitGuide`, `RegexAssertionSensor`, `ExitCodeSensor`, `JudgeAgentSensor`, `TokenBudgetSensor`
- `PromotionSuggestion`, `suggest_promotions`

Add to `pi_harness/guards/__init__.py`:
```python
from pi_harness.guards.guides import (
    AllowlistGuide,
    PathScopeGuide,
    RateLimitGuide,
    SchemaValidatorGuide,
)
from pi_harness.guards.sensors import (
    ExitCodeSensor,
    JudgeAgentSensor,
    RegexAssertionSensor,
    TokenBudgetSensor,
)
from pi_harness.guards.promote import PromotionSuggestion, suggest_promotions
```

Append the corresponding names to `__all__`.

- [ ] **Step 2: Verify the full guards test suite is green**

Run: `uv run pytest tests/guards/ -v`
Expected: all tests pass (~40 tests across the five test files).

- [ ] **Step 3: Verify package can be imported flat**

Run:
```bash
uv run python -c "from pi_harness.guards import GuardRunner, AllowlistGuide, JudgeAgentSensor, suggest_promotions; print('ok')"
```

Expected: prints `ok`, no ImportError.

- [ ] **Step 4: Run the wider test suite to make sure nothing else broke**

Run: `uv run pytest -v`
Expected: all green (Plans 1, 2, 3, 4 tests included if they exist; otherwise just guards).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/guards/__init__.py
git commit -m "feat(guards): finalize public surface re-exports for Plans 5 + 8"
```

---

## Self-Review Summary

- **Spec coverage:**
  - Acceptance 1 (AllowlistGuide denies non-allowlisted + logs event) — Task 6 + Task 15.
  - Acceptance 2 (PathScopeGuide denies `..`/absolute escape, realpath) — Task 7.
  - Acceptance 3 (JudgeAgentSensor returns confidence, LLM mocked) — Task 12.
  - Acceptance 4 (GuardRunner.intercept_tool_call short-circuits) — Task 15.
  - Acceptance 5 (suggest_promotions on 23/2 split emits stub) — Task 19 + 20.
  - Acceptance 6 (all firings write TrajectoryEvent with classification) — Tasks 15 + 16.
- **Cross-plan references:**
  - Plan 1: `Config` for the OpenAI API key passed into `JudgeAgentSensor`.
  - Plan 2: `TrajectoryEvent`, `write_event`, `query_events` used in `runner.py` and `promote.py`.
  - Plan 5: `Coordinator.launch(..., guides=[...], sensors=[...])` consumes `GuardRunner.attach_*`.
  - Plan 8: imports `GuardKind`, `Guide`, `Sensor`, `GuardResult`, `PromotionSuggestion` for the inspector.
- **Unresolved decision flagged in `runner.py` docstring:** pi-coding-agent's actual stdout protocol shape — verify against the pi-coding-agent monorepo before wiring the subprocess layer.
