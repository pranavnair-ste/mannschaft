# Spec Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the design-first critical path: a spec editor with linter and LLM-backed decomposer that converts versioned spec files into ClawTeam task DAGs, exposes them over HTTP for Plan 8's dashboard, AND provides a `pi-harness` command-line entry point that drives the full spec→lint→decompose→launch pipeline from the terminal. The CLI is the canonical headless invocation surface; the slash-command skill in Claude Code is a thin Bash wrapper over it.

**Architecture:** Specs live as `~/.pi-harness/specs/<spec_id>.md` files (YAML frontmatter + markdown body) for git-friendliness. A pluggable linter auto-discovers rule modules under `pi_harness/spec/lints/` and emits errors/warnings with a normalized 0-1 score. A Decomposer calls the OpenAI reasoning tier with a strict pydantic JSON schema, returns `DecomposedTask` entries that map one-to-one to ClawTeam tasks (carrying `blocked_by` chains). A FastAPI HTTP surface exposes CRUD + `/lint` + `/decompose` + `/launch` so Plan 8's dashboard can consume the layer over HTTP at `localhost:8800`. A `typer`-based CLI (`pi-harness`) calls the same `Spec`/`Linter`/`Decomposer` modules in-process (no server required) and shells out to Plan 5's `Coordinator.launch` for execution. A Claude Code skill at `skills/pi-harness/SKILL.md` registers `/pi-harness <spec-path>` as a one-keystroke wrapper that invokes the CLI via Bash.

**Tech Stack:** Python 3.11+ (matches Plan 1's bump for stdlib `tomllib`), uv, pytest, FastAPI, uvicorn, pydantic, pyyaml, httpx (for `fastapi.testclient`), OpenAI SDK (already a Plan 5/Plan 4 dependency), **typer>=0.12** for the CLI (already a transitive dep via ClawTeam; pinned explicitly so the CLI surface is stable independent of ClawTeam version bumps).

---

## File Structure (locked in before tasks)

Files you will create (all under `/Users/pranavnair/Desktop/Personal/mannschaft/`):

```
pi_harness/spec/__init__.py                        # public exports: Spec, LintResult, DecomposedTask
pi_harness/spec/format.py                          # Spec dataclass + parse_spec / serialize_spec
pi_harness/spec/lints/__init__.py                  # rule registry + auto-discovery
pi_harness/spec/lints/required_acceptance.py       # rule
pi_harness/spec/lints/vague_terms.py               # rule
pi_harness/spec/lints/scope_bounded.py             # rule
pi_harness/spec/lints/measurable_criteria.py       # rule
pi_harness/spec/linter.py                          # Linter class, LintResult, LintViolation
pi_harness/spec/decomposer.py                      # Decomposer class, DecomposedTask
pi_harness/spec/prompts/decompose_prompt.md        # versioned prompt
pi_harness/spec/editor.py                          # FastAPI app (uvicorn.run guarded by __main__)
pi_harness/cli.py                                  # Typer entry point — `pi-harness` binary
pi_harness/spec/scaffold.md                        # template body used by `pi-harness spec new`
skills/pi-harness/SKILL.md                         # Claude Code skill — `/pi-harness <spec>` wrapper
tests/spec/__init__.py
tests/spec/test_format.py
tests/spec/test_linter.py
tests/spec/test_decomposer.py
tests/spec/test_editor.py
tests/test_cli.py                                  # CLI unit tests via Typer's CliRunner
tests/test_skill.py                                # skill-file frontmatter + body shape
```

Responsibilities:
- `format.py` — pure I/O: parse + serialize. No business logic.
- `lints/*.py` — each rule exports `check(spec: Spec) -> list[LintViolation]` and `RULE_NAME: str`. No I/O.
- `linter.py` — discovery + aggregation + scoring. No file I/O.
- `decomposer.py` — LLM call + pydantic validation + retry. Reads prompt file at module load.
- `editor.py` — HTTP only. Delegates to format / linter / decomposer / Plan 5 Coordinator.
- `cli.py` — Typer entry point. In-process calls to format/linter/decomposer/Coordinator. NEVER duplicates business logic — every code path is a thin shim over an existing module. The CLI is what the slash-command skill shells out to, and what a CI job would invoke for headless launches.
- `scaffold.md` — single template string interpolated by `pi-harness spec new <id>`.

Cross-plan boundaries:
- Imports `pi_harness.config.Config` (Plan 1).
- Imports `pi_harness.topology.coordinator.Coordinator`, `RunSpec`, `AgentSpec` (Plan 5).
- Optionally imports `pi_harness.trajectory.store.subscribe` (Plan 2) for live event streaming in `pi-harness launch --watch`; falls back to polling `clawteam --json task list` when Plan 2 isn't installed.
- Exports `Spec`, `LintResult`, `LintViolation`, `DecomposedTask` for Plan 8 dashboard.
- Exposes the `pi-harness` console script via `[project.scripts]` in `pyproject.toml` — Plan 8's dashboard CLI (`pi-harness dashboard`) registers a subcommand on the same Typer `app` from `pi_harness.cli`.

Storage layout (created lazily by `format.serialize_spec`):
```
~/.pi-harness/specs/<spec_id>.md
```

---

## Pre-Task Setup

Before Task 1, verify dependencies are present in `pyproject.toml`. If Plan 1 has not added them yet, add them now.

- [ ] **Setup Step 1: Confirm cwd is repo root**

Run: `pwd`
Expected: `/Users/pranavnair/Desktop/Personal/mannschaft`

- [ ] **Setup Step 2: Add Plan 7 dependencies**

Run:
```bash
uv add fastapi 'uvicorn[standard]' pyyaml pydantic httpx 'typer>=0.12,<1.0'
uv add --dev pytest pytest-asyncio
```

Expected: `pyproject.toml` lists `fastapi`, `uvicorn`, `pyyaml`, `pydantic`, `httpx`, `typer` and dev `pytest`, `pytest-asyncio`.

If a Plan 1-6 task has already added any of these, `uv add` is idempotent — no action needed. (`typer` is already a transitive dep via ClawTeam, but pin it explicitly here so the CLI doesn't break if ClawTeam unpins it.)

Also add the console script entry in `pyproject.toml` (paste under `[project]`, adjacent to `dependencies = [...]`):

```toml
[project.scripts]
pi-harness = "pi_harness.cli:app"
```

After editing, run `uv sync --extra dev` so the script is installed into `.venv/bin/pi-harness`. Verify:

```bash
uv run pi-harness --help
```

Expected: a typer-style help banner. (Will fail until Task 13 lands `pi_harness/cli.py`, which is fine — this setup step is just registering the entry point so later tasks can iterate.)

- [ ] **Setup Step 3: Confirm Plan 1 and Plan 5 modules exist**

Run: `ls pi_harness/config.py pi_harness/topology/coordinator.py`
Expected: both files print without error.

If either is missing, STOP — this plan depends on Plan 1 (`Config`) and Plan 5 (`Coordinator`, `RunSpec`, `AgentSpec`). Surface the missing dependency to the orchestrator.

- [ ] **Setup Step 4: Make directories**

Run:
```bash
mkdir -p pi_harness/spec/lints pi_harness/spec/prompts tests/spec skills/pi-harness
touch pi_harness/spec/__init__.py pi_harness/spec/lints/__init__.py tests/spec/__init__.py
```

Expected: no errors.

---

## Task 1: Spec dataclass and round-trip parser

**Files:**
- Create: `pi_harness/spec/format.py`
- Test: `tests/spec/test_format.py`

This task implements the on-disk format: YAML frontmatter delimited by `---` lines, followed by a markdown body. The body holds the human-readable goal/criteria; the frontmatter holds the typed metadata. Round-trip must be lossless for any spec the linter or decomposer might handle.

- [ ] **Step 1: Write the failing round-trip test**

Create `tests/spec/test_format.py`:

```python
"""Tests for spec format: parse/serialize round-trip and storage location."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pi_harness.spec.format import (
    Spec,
    parse_spec,
    serialize_spec,
    spec_storage_dir,
    spec_path,
)


@pytest.fixture
def tmp_specs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    d = tmp_path / "specs"
    d.mkdir()
    return d


def test_storage_dir_uses_env(tmp_specs_dir: Path) -> None:
    assert spec_storage_dir() == tmp_specs_dir


def test_round_trip_preserves_all_fields(tmp_specs_dir: Path) -> None:
    spec = Spec(
        id="spec-001",
        title="Add cancel button",
        goal="Users can cancel an in-flight upload.",
        acceptance_criteria=[
            "Clicking Cancel during upload aborts the request within 200ms",
            "Cancelled upload leaves no partial file on the server",
        ],
        constraints=["Must not break resumable uploads"],
        non_goals=["Resuming after cancel is out of scope"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=None,
        status="draft",
    )

    path = spec_path(spec.id)
    serialize_spec(spec, path)
    parsed = parse_spec(path)

    assert parsed == spec


def test_parse_rejects_missing_frontmatter(tmp_specs_dir: Path) -> None:
    bad = tmp_specs_dir / "bad.md"
    bad.write_text("# no frontmatter here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frontmatter"):
        parse_spec(bad)


def test_serialize_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    spec = Spec(
        id="spec-002",
        title="t",
        goal="g",
        acceptance_criteria=["one two three four"],
        constraints=[],
        non_goals=["nope"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=None,
        status="draft",
    )
    # `specs/` directory does not exist yet — serialize must create it.
    serialize_spec(spec, spec_path(spec.id))
    assert (tmp_path / "specs" / "spec-002.md").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/spec/test_format.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pi_harness.spec.format'`.

- [ ] **Step 3: Implement `format.py`**

Create `pi_harness/spec/format.py`:

```python
"""On-disk spec format: YAML frontmatter + markdown body.

Storage layout:
    <PI_HARNESS_HOME or ~/.pi-harness>/specs/<spec_id>.md

The body is whatever markdown the author wants (rendered as the goal +
acceptance-criteria narrative); the frontmatter is the typed metadata the
linter and decomposer read.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import yaml

SpecStatus = Literal["draft", "linted", "decomposed", "running", "complete"]

FRONTMATTER_DELIM = "---"


@dataclass
class Spec:
    id: str
    title: str
    goal: str
    acceptance_criteria: list[str]
    constraints: list[str]
    non_goals: list[str]
    created_at: str
    updated_at: str
    linter_score: float | None
    status: SpecStatus


def _home_dir() -> Path:
    raw = os.environ.get("PI_HARNESS_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".pi-harness"


def spec_storage_dir() -> Path:
    return _home_dir() / "specs"


def spec_path(spec_id: str) -> Path:
    return spec_storage_dir() / f"{spec_id}.md"


def _build_body(spec: Spec) -> str:
    lines: list[str] = [f"# {spec.title}", "", "## Goal", "", spec.goal, ""]
    if spec.acceptance_criteria:
        lines += ["## Acceptance Criteria", ""]
        lines += [f"- {item}" for item in spec.acceptance_criteria]
        lines.append("")
    if spec.constraints:
        lines += ["## Constraints", ""]
        lines += [f"- {item}" for item in spec.constraints]
        lines.append("")
    if spec.non_goals:
        lines += ["## Non-Goals", ""]
        lines += [f"- {item}" for item in spec.non_goals]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def serialize_spec(spec: Spec, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = asdict(spec)
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=True, default_flow_style=False)
    body = _build_body(spec)
    contents = f"{FRONTMATTER_DELIM}\n{yaml_block}{FRONTMATTER_DELIM}\n\n{body}"
    path.write_text(contents, encoding="utf-8")


def parse_spec(path: Path) -> Spec:
    text = path.read_text(encoding="utf-8")
    if not text.startswith(FRONTMATTER_DELIM):
        raise ValueError(f"Spec file {path} is missing YAML frontmatter")
    # Split off the frontmatter block.
    parts = text.split(f"\n{FRONTMATTER_DELIM}\n", 2)
    if len(parts) < 2:
        raise ValueError(f"Spec file {path} has malformed frontmatter")
    yaml_block = parts[0][len(FRONTMATTER_DELIM) :].lstrip("\n")
    data = yaml.safe_load(yaml_block) or {}
    # Defaults for back-compat with hand-edited files.
    data.setdefault("constraints", [])
    data.setdefault("non_goals", [])
    data.setdefault("linter_score", None)
    data.setdefault("status", "draft")
    return Spec(**data)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/spec/test_format.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/__init__.py pi_harness/spec/format.py tests/spec/__init__.py tests/spec/test_format.py
git commit -m "feat(spec): add Spec dataclass with round-trip parser"
```

---

## Task 2: LintViolation, Linter, and rule registry skeleton

**Files:**
- Create: `pi_harness/spec/linter.py`
- Modify: `pi_harness/spec/lints/__init__.py` (auto-discovery)
- Test: `tests/spec/test_linter.py`

Goal: a `Linter()` that imports every module under `pi_harness.spec.lints`, calls each module's `check(spec)`, aggregates `LintViolation` instances, and returns a `LintResult` with a 0-1 score.

Scoring: `score = 1.0 if no errors and no warnings; 1.0 - 0.5 * has_errors - 0.1 * min(warning_count, 5) / 5`. Errors hard-cap score below 1.0; warnings degrade up to -0.1 total. Status `linted` requires `errors == []` (not `score == 1.0`); the editor's `/decompose` route is the gate that requires `score == 1.0`.

- [ ] **Step 1: Write failing tests for Linter aggregation and scoring**

Create `tests/spec/test_linter.py`:

```python
"""Tests for the linter aggregation, scoring, and per-rule behavior."""
from __future__ import annotations

import pytest

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import Linter, LintResult, LintViolation


def _spec(**overrides) -> Spec:
    defaults = dict(
        id="spec-x",
        title="t",
        goal="g",
        acceptance_criteria=["one two three four", "five six seven eight"],
        constraints=[],
        non_goals=["explicit non-goal one"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=None,
        status="draft",
    )
    defaults.update(overrides)
    return Spec(**defaults)


def test_clean_spec_scores_one() -> None:
    result = Linter().lint(_spec())
    assert result.errors == []
    assert result.warnings == []
    assert result.score == 1.0


def test_lint_result_shape() -> None:
    result = Linter().lint(_spec())
    assert isinstance(result, LintResult)
    assert isinstance(result.errors, list)
    assert isinstance(result.warnings, list)
    assert 0.0 <= result.score <= 1.0


def test_violation_carries_rule_name_and_location() -> None:
    bad = _spec(acceptance_criteria=[])
    result = Linter().lint(bad)
    assert any(v.rule_name == "required_acceptance" for v in result.errors)
    v = next(v for v in result.errors if v.rule_name == "required_acceptance")
    assert isinstance(v, LintViolation)
    assert v.severity == "error"
    assert v.message
    assert v.location  # may be a field name or "acceptance_criteria[0]"


def test_error_drops_score_below_one() -> None:
    result = Linter().lint(_spec(acceptance_criteria=[]))
    assert result.score < 1.0


def test_warnings_only_keeps_score_above_threshold() -> None:
    # Vague-terms is warning-only; introduce one occurrence.
    result = Linter().lint(_spec(goal="a simple and easy thing"))
    assert result.errors == []
    assert any(v.severity == "warning" for v in result.warnings)
    assert result.score < 1.0
    assert result.score >= 0.9


def test_linter_discovers_all_four_rules() -> None:
    # Sanity: the registry surfaces the four rules this plan ships.
    rules = {r for r in Linter().rule_names()}
    assert {
        "required_acceptance",
        "vague_terms",
        "scope_bounded",
        "measurable_criteria",
    } <= rules
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/spec/test_linter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pi_harness.spec.linter'`.

- [ ] **Step 3: Implement `lints/__init__.py` registry**

Replace `pi_harness/spec/lints/__init__.py`:

```python
"""Auto-discovery registry for lint rules.

Each rule module under this package must expose:
  - `RULE_NAME: str`     # stable identifier, also the module file stem
  - `check(spec) -> list[LintViolation]`

The registry imports every non-underscore module on first access.
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

_CACHED: dict[str, ModuleType] | None = None


def _discover() -> dict[str, ModuleType]:
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    out: dict[str, ModuleType] = {}
    package = importlib.import_module(__name__)
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        rule_name = getattr(mod, "RULE_NAME", info.name)
        if not callable(getattr(mod, "check", None)):
            raise RuntimeError(
                f"Lint rule {info.name!r} missing required `check(spec)` function"
            )
        out[rule_name] = mod
    _CACHED = out
    return out


def all_rules() -> dict[str, ModuleType]:
    return dict(_discover())


def reset_cache_for_testing() -> None:
    global _CACHED
    _CACHED = None
```

- [ ] **Step 4: Implement `linter.py`**

Create `pi_harness/spec/linter.py`:

```python
"""Linter: runs every discovered rule, aggregates violations, computes score."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pi_harness.spec.format import Spec
from pi_harness.spec.lints import all_rules

Severity = Literal["error", "warning"]


@dataclass
class LintViolation:
    rule_name: str
    severity: Severity
    message: str
    location: str  # e.g. "acceptance_criteria[0]" or "goal:line=3"


@dataclass
class LintResult:
    errors: list[LintViolation] = field(default_factory=list)
    warnings: list[LintViolation] = field(default_factory=list)
    score: float = 1.0


class Linter:
    """Aggregates discovered lint rules into a LintResult."""

    def __init__(self) -> None:
        self._rules = all_rules()

    def rule_names(self) -> list[str]:
        return sorted(self._rules)

    def lint(self, spec: Spec) -> LintResult:
        errors: list[LintViolation] = []
        warnings: list[LintViolation] = []
        for _, mod in self._rules.items():
            for v in mod.check(spec):
                if v.severity == "error":
                    errors.append(v)
                else:
                    warnings.append(v)
        score = self._score(errors, warnings)
        return LintResult(errors=errors, warnings=warnings, score=score)

    @staticmethod
    def _score(errors: list[LintViolation], warnings: list[LintViolation]) -> float:
        score = 1.0
        if errors:
            score -= 0.5
        # Up to -0.1 from warnings, saturating at 5 warnings.
        score -= 0.1 * (min(len(warnings), 5) / 5.0)
        return max(0.0, round(score, 4))
```

- [ ] **Step 5: Add a placeholder rule so discovery has something to find**

The four real rules ship in Tasks 3-6. To make Task 2 tests pass standalone, create a temporary `_noop.py` rule. We will delete it in Task 7's wiring step.

Create `pi_harness/spec/lints/_noop.py`:

```python
"""Internal placeholder. Skipped by discovery (leading underscore)."""
RULE_NAME = "_noop"


def check(spec):  # noqa: ARG001
    return []
```

(File starts with `_` so discovery skips it — but the file's existence proves the iter_modules path works. It will be deleted at the end of Task 6.)

- [ ] **Step 6: Run the tests — expect partial pass / partial fail**

Run: `uv run pytest tests/spec/test_linter.py -v`
Expected:
- `test_clean_spec_scores_one` — PASS (no rules loaded yet → no violations)
- `test_lint_result_shape` — PASS
- `test_violation_carries_rule_name_and_location` — FAIL (no `required_acceptance` rule yet)
- `test_error_drops_score_below_one` — FAIL
- `test_warnings_only_keeps_score_above_threshold` — FAIL
- `test_linter_discovers_all_four_rules` — FAIL

This is the intended TDD state. Tasks 3-6 implement the four rules and turn these red.

- [ ] **Step 7: Commit**

```bash
git add pi_harness/spec/linter.py pi_harness/spec/lints/__init__.py pi_harness/spec/lints/_noop.py tests/spec/test_linter.py
git commit -m "feat(spec): add Linter, LintResult, and rule registry"
```

---

## Task 3: Rule — `required_acceptance`

**Files:**
- Create: `pi_harness/spec/lints/required_acceptance.py`
- Modify: `tests/spec/test_linter.py` (append rule-specific tests)

Rule: emits an error if `acceptance_criteria` is empty OR if every item is shorter than 3 whitespace-separated tokens.

- [ ] **Step 1: Append failing rule-specific tests**

Append to `tests/spec/test_linter.py`:

```python
def test_required_acceptance_fails_on_empty() -> None:
    result = Linter().lint(_spec(acceptance_criteria=[]))
    rule_errors = [v for v in result.errors if v.rule_name == "required_acceptance"]
    assert len(rule_errors) == 1
    assert "empty" in rule_errors[0].message.lower()


def test_required_acceptance_fails_when_all_too_short() -> None:
    result = Linter().lint(_spec(acceptance_criteria=["one two", "ok"]))
    rule_errors = [v for v in result.errors if v.rule_name == "required_acceptance"]
    assert len(rule_errors) == 1
    assert "3" in rule_errors[0].message or "three" in rule_errors[0].message.lower()


def test_required_acceptance_passes_with_one_long_enough() -> None:
    result = Linter().lint(_spec(acceptance_criteria=["one two three four", "ok"]))
    rule_errors = [v for v in result.errors if v.rule_name == "required_acceptance"]
    assert rule_errors == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_linter.py::test_required_acceptance_fails_on_empty -v`
Expected: FAIL (rule does not exist yet).

- [ ] **Step 3: Implement the rule**

Create `pi_harness/spec/lints/required_acceptance.py`:

```python
"""Rule: spec must have at least one acceptance criterion >= 3 words."""
from __future__ import annotations

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import LintViolation

RULE_NAME = "required_acceptance"
MIN_WORDS = 3


def check(spec: Spec) -> list[LintViolation]:
    if not spec.acceptance_criteria:
        return [
            LintViolation(
                rule_name=RULE_NAME,
                severity="error",
                message="acceptance_criteria is empty; at least one criterion required",
                location="acceptance_criteria",
            )
        ]
    has_long_enough = any(
        len(item.split()) >= MIN_WORDS for item in spec.acceptance_criteria
    )
    if not has_long_enough:
        return [
            LintViolation(
                rule_name=RULE_NAME,
                severity="error",
                message=f"every acceptance criterion is shorter than {MIN_WORDS} words",
                location="acceptance_criteria",
            )
        ]
    return []
```

Note: this module imports `LintViolation` from `pi_harness.spec.linter`. That creates a tight cycle only if `linter.py` imports rule modules at module-load time. It does not — `linter.py` calls `all_rules()` lazily from `__init__`, which imports the rule modules, which then import `LintViolation` from a fully-loaded `linter` module. Safe.

If you hit a circular-import error at runtime, move `LintViolation` to a new `pi_harness/spec/violation.py` and have both `linter.py` and the rules import from there. We're betting the lazy-discovery path avoids it.

- [ ] **Step 4: Reset registry cache and run tests**

Run: `uv run pytest tests/spec/test_linter.py -v`
Expected: the three `required_acceptance` tests PASS; `test_linter_discovers_all_four_rules` still FAILS (3 of 4 rules present).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/lints/required_acceptance.py tests/spec/test_linter.py
git commit -m "feat(spec): add required_acceptance lint rule"
```

---

## Task 4: Rule — `vague_terms`

**Files:**
- Create: `pi_harness/spec/lints/vague_terms.py`
- Modify: `tests/spec/test_linter.py`

Rule: emits one warning per occurrence of a vague term in `goal`, any `acceptance_criteria` entry, any `constraints` entry, or any `non_goals` entry. The wordlist is configurable via the `PI_HARNESS_VAGUE_WORDS` env var (comma-separated, overrides the default). Default list: `simple, easy, fast, should, robust, scalable, smooth, intuitive`. Matching is case-insensitive, whole-word (`\bword\b`).

Locations are formatted as `<field>:line=<N>` where N is the 1-indexed line within the field's serialized form (each list item is a separate line; `goal` is line 1).

- [ ] **Step 1: Append failing tests**

Append to `tests/spec/test_linter.py`:

```python
def test_vague_terms_flags_each_occurrence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PI_HARNESS_VAGUE_WORDS", raising=False)
    s = _spec(
        goal="It should be simple and fast",
        acceptance_criteria=["The UI feels intuitive when scrolling smoothly enough"],
    )
    result = Linter().lint(s)
    vague = [v for v in result.warnings if v.rule_name == "vague_terms"]
    # goal contains: "should", "simple", "fast" -> 3
    # ac[0] contains: "intuitive" -> 1  (note: "smoothly" is not a whole-word match for "smooth")
    assert len(vague) == 4


def test_vague_terms_is_case_insensitive() -> None:
    result = Linter().lint(_spec(goal="Make it ROBUST"))
    vague = [v for v in result.warnings if v.rule_name == "vague_terms"]
    assert len(vague) == 1
    assert vague[0].severity == "warning"


def test_vague_terms_configurable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_HARNESS_VAGUE_WORDS", "fluffy,kinda")
    # Default words should now NOT fire; "fluffy" should.
    s = _spec(goal="A fluffy and robust system", acceptance_criteria=["one two three four"])
    result = Linter().lint(s)
    vague = [v for v in result.warnings if v.rule_name == "vague_terms"]
    assert len(vague) == 1
    assert "fluffy" in vague[0].message.lower()


def test_vague_terms_location_carries_field_and_line() -> None:
    result = Linter().lint(
        _spec(acceptance_criteria=["one two three four", "this should be measurable"])
    )
    vague = [v for v in result.warnings if v.rule_name == "vague_terms"]
    assert len(vague) == 1
    assert "acceptance_criteria" in vague[0].location
    assert "line=2" in vague[0].location
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_linter.py::test_vague_terms_flags_each_occurrence -v`
Expected: FAIL (rule does not exist).

- [ ] **Step 3: Implement the rule**

Create `pi_harness/spec/lints/vague_terms.py`:

```python
"""Rule: warn on vague language. Wordlist configurable via env var."""
from __future__ import annotations

import os
import re

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import LintViolation

RULE_NAME = "vague_terms"

_DEFAULT_WORDS = (
    "simple",
    "easy",
    "fast",
    "should",
    "robust",
    "scalable",
    "smooth",
    "intuitive",
)


def _active_wordlist() -> tuple[str, ...]:
    raw = os.environ.get("PI_HARNESS_VAGUE_WORDS")
    if raw is None:
        return _DEFAULT_WORDS
    return tuple(w.strip().lower() for w in raw.split(",") if w.strip())


def _scan(field_name: str, lines: list[str], words: tuple[str, ...]) -> list[LintViolation]:
    if not words:
        return []
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)
    out: list[LintViolation] = []
    for idx, line in enumerate(lines, start=1):
        for m in pattern.finditer(line):
            term = m.group(1).lower()
            out.append(
                LintViolation(
                    rule_name=RULE_NAME,
                    severity="warning",
                    message=f"vague term '{term}' — replace with a measurable phrase",
                    location=f"{field_name}:line={idx}",
                )
            )
    return out


def check(spec: Spec) -> list[LintViolation]:
    words = _active_wordlist()
    violations: list[LintViolation] = []
    violations += _scan("goal", [spec.goal], words)
    violations += _scan("acceptance_criteria", list(spec.acceptance_criteria), words)
    violations += _scan("constraints", list(spec.constraints), words)
    violations += _scan("non_goals", list(spec.non_goals), words)
    return violations
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/spec/test_linter.py -v -k "vague_terms or warnings_only"`
Expected: all `vague_terms` tests PASS plus `test_warnings_only_keeps_score_above_threshold` PASSES.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/lints/vague_terms.py tests/spec/test_linter.py
git commit -m "feat(spec): add vague_terms lint rule with env-configurable wordlist"
```

---

## Task 5: Rule — `scope_bounded`

**Files:**
- Create: `pi_harness/spec/lints/scope_bounded.py`
- Modify: `tests/spec/test_linter.py`

Rule: emits an error if `non_goals` is empty. Forces every spec author to declare what's out of scope.

- [ ] **Step 1: Append failing tests**

Append to `tests/spec/test_linter.py`:

```python
def test_scope_bounded_fails_on_empty_non_goals() -> None:
    result = Linter().lint(_spec(non_goals=[]))
    rule_errors = [v for v in result.errors if v.rule_name == "scope_bounded"]
    assert len(rule_errors) == 1
    assert rule_errors[0].location == "non_goals"


def test_scope_bounded_passes_with_non_goal() -> None:
    result = Linter().lint(_spec(non_goals=["resuming after cancel"]))
    rule_errors = [v for v in result.errors if v.rule_name == "scope_bounded"]
    assert rule_errors == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_linter.py::test_scope_bounded_fails_on_empty_non_goals -v`
Expected: FAIL.

- [ ] **Step 3: Implement the rule**

Create `pi_harness/spec/lints/scope_bounded.py`:

```python
"""Rule: every spec must declare at least one non-goal (explicit scope edge)."""
from __future__ import annotations

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import LintViolation

RULE_NAME = "scope_bounded"


def check(spec: Spec) -> list[LintViolation]:
    if not spec.non_goals:
        return [
            LintViolation(
                rule_name=RULE_NAME,
                severity="error",
                message="non_goals is empty; declare at least one out-of-scope item",
                location="non_goals",
            )
        ]
    return []
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/spec/test_linter.py -v -k scope_bounded`
Expected: both `scope_bounded` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/lints/scope_bounded.py tests/spec/test_linter.py
git commit -m "feat(spec): add scope_bounded lint rule"
```

---

## Task 6: Rule — `measurable_criteria`

**Files:**
- Create: `pi_harness/spec/lints/measurable_criteria.py`
- Modify: `tests/spec/test_linter.py`
- Delete: `pi_harness/spec/lints/_noop.py`

Rule: warns when an acceptance-criterion line has no measurable signal. Measurable signals (any one passes the heuristic):
- Contains a digit (`\d`) — covers latency, counts, percentages, dates, sizes.
- Contains a unit token (`ms|s|sec|seconds|minutes|hours|kb|mb|gb|%|px|req/s`) case-insensitive.
- Contains a test-shell hint: a backticked span, or the substrings `pytest `, `npm test`, `uv run`, `bash $`, `curl `.
- Contains an observable-state verb (`returns`, `exits`, `responds`, `writes`, `creates`, `deletes`, `produces`).

Severity = warning (not error) because a human may judge the criterion measurable through context.

- [ ] **Step 1: Append failing tests**

Append to `tests/spec/test_linter.py`:

```python
def test_measurable_criteria_warns_on_unmeasurable() -> None:
    result = Linter().lint(
        _spec(acceptance_criteria=["the experience is delightful and clean"])
    )
    warn = [v for v in result.warnings if v.rule_name == "measurable_criteria"]
    assert len(warn) == 1
    assert "measurable" in warn[0].message.lower()


def test_measurable_criteria_accepts_digit() -> None:
    result = Linter().lint(_spec(acceptance_criteria=["cancellation aborts within 200ms"]))
    warn = [v for v in result.warnings if v.rule_name == "measurable_criteria"]
    assert warn == []


def test_measurable_criteria_accepts_observable_verb() -> None:
    result = Linter().lint(
        _spec(acceptance_criteria=["pressing cancel returns the user to the upload screen"])
    )
    warn = [v for v in result.warnings if v.rule_name == "measurable_criteria"]
    assert warn == []


def test_measurable_criteria_accepts_test_command() -> None:
    result = Linter().lint(
        _spec(acceptance_criteria=["`pytest tests/upload/test_cancel.py` passes"])
    )
    warn = [v for v in result.warnings if v.rule_name == "measurable_criteria"]
    assert warn == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_linter.py::test_measurable_criteria_warns_on_unmeasurable -v`
Expected: FAIL.

- [ ] **Step 3: Implement the rule**

Create `pi_harness/spec/lints/measurable_criteria.py`:

```python
"""Rule: each acceptance criterion should be measurable (digit, unit, or verb)."""
from __future__ import annotations

import re

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import LintViolation

RULE_NAME = "measurable_criteria"

_DIGIT_RE = re.compile(r"\d")
_UNIT_RE = re.compile(
    r"\b(ms|s|sec|seconds|minutes|hours|kb|mb|gb|%|px|req/s)\b", re.IGNORECASE
)
_TEST_HINT_RE = re.compile(r"`[^`]+`|\bpytest\b|\bnpm test\b|\buv run\b|\bbash \$|\bcurl\b")
_OBSERVABLE_RE = re.compile(
    r"\b(returns?|exits?|responds?|writes?|creates?|deletes?|produces?)\b", re.IGNORECASE
)


def _is_measurable(line: str) -> bool:
    if _DIGIT_RE.search(line):
        return True
    if _UNIT_RE.search(line):
        return True
    if _TEST_HINT_RE.search(line):
        return True
    if _OBSERVABLE_RE.search(line):
        return True
    return False


def check(spec: Spec) -> list[LintViolation]:
    out: list[LintViolation] = []
    for idx, item in enumerate(spec.acceptance_criteria, start=1):
        if not _is_measurable(item):
            out.append(
                LintViolation(
                    rule_name=RULE_NAME,
                    severity="warning",
                    message=(
                        "criterion has no measurable signal "
                        "(no number, unit, test command, or observable verb)"
                    ),
                    location=f"acceptance_criteria[{idx - 1}]",
                )
            )
    return out
```

- [ ] **Step 4: Delete the placeholder**

```bash
rm pi_harness/spec/lints/_noop.py
```

- [ ] **Step 5: Run the full linter test file**

Run: `uv run pytest tests/spec/test_linter.py -v`
Expected: every test passes, including `test_linter_discovers_all_four_rules`.

- [ ] **Step 6: Commit**

```bash
git add pi_harness/spec/lints/measurable_criteria.py tests/spec/test_linter.py
git rm pi_harness/spec/lints/_noop.py
git commit -m "feat(spec): add measurable_criteria lint rule"
```

---

## Task 7: Decomposer prompt and `DecomposedTask` pydantic model

**Files:**
- Create: `pi_harness/spec/prompts/decompose_prompt.md`
- Create: `pi_harness/spec/decomposer.py` (model + stubs only — LLM call comes in Task 8)
- Test: `tests/spec/test_decomposer.py`

Lock the data shape and prompt before wiring the LLM.

- [ ] **Step 1: Write the prompt**

Create `pi_harness/spec/prompts/decompose_prompt.md`:

```markdown
<!-- prompt-version: 1 -->
You are the Pi-Agent Harness decomposition assistant. Your job: break a software spec
into the smallest set of parallelizable tasks that, executed together, satisfy every
acceptance criterion. Each task must be assignable to exactly one role:

- `orchestrator` — coordinates, never writes code
- `builder` — writes code and tests
- `scout` — gathers context, reads docs, surveys the codebase
- `reviewer` — reads code and emits findings, never writes
- `synthesizer` — combines outputs from parallel branches

Rules:
1. Every acceptance criterion in the spec must be covered by at least one task whose
   `acceptance_criterion` field repeats that criterion verbatim.
2. If criterion B depends on criterion A's output, the task for B lists the task id
   for A in `blocked_by`. Otherwise `blocked_by` is `[]`.
3. Task ids are stable kebab-case strings prefixed with `t-`, e.g. `t-add-cancel-button`.
4. Prefer parallelism. Only add a dependency when there is a real artifact handoff.
5. Do NOT invent acceptance criteria. Do NOT split a single criterion across multiple
   tasks unless the split has independent artifacts.

Output STRICTLY the JSON schema you were given. No prose, no markdown fences, no
trailing commentary.
```

- [ ] **Step 2: Write failing tests for the pydantic model**

Create `tests/spec/test_decomposer.py`:

```python
"""Tests for Decomposer model shape and prompt loading.

LLM-call tests live further down and mock the OpenAI client.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from pi_harness.spec.decomposer import (
    DecomposedTask,
    Decomposer,
    DecompositionResult,
    PROMPT_PATH,
)
from pi_harness.spec.format import Spec


def _spec() -> Spec:
    return Spec(
        id="spec-cancel",
        title="Cancel button",
        goal="Users can cancel an in-flight upload",
        acceptance_criteria=[
            "Clicking Cancel during upload aborts the request within 200ms",
            "Cancelled upload leaves no partial file on the server",
        ],
        constraints=[],
        non_goals=["Resuming after cancel"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=1.0,
        status="linted",
    )


def test_prompt_file_exists_and_versioned() -> None:
    assert PROMPT_PATH.exists()
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "prompt-version" in text


def test_decomposed_task_validates_role() -> None:
    with pytest.raises(ValidationError):
        DecomposedTask(
            id="t-1",
            name="bad",
            description="d",
            acceptance_criterion="x",
            blocked_by=[],
            assigned_role="wizard",  # not in the literal set
        )


def test_decomposed_task_round_trip() -> None:
    t = DecomposedTask(
        id="t-cancel",
        name="Add cancel button",
        description="Wire the button to abort the upload",
        acceptance_criterion="Clicking Cancel during upload aborts the request within 200ms",
        blocked_by=[],
        assigned_role="builder",
    )
    data = t.model_dump()
    again = DecomposedTask.model_validate(data)
    assert again == t


def test_decomposition_result_holds_tasks() -> None:
    res = DecompositionResult(
        tasks=[
            DecomposedTask(
                id="t-1",
                name="n",
                description="d",
                acceptance_criterion="abc",
                blocked_by=[],
                assigned_role="builder",
            )
        ]
    )
    assert len(res.tasks) == 1


def test_decomposer_init_loads_prompt(tmp_path: Path) -> None:
    cfg = MagicMock()
    cfg.openai_api_key = "sk-test"
    cfg.reasoning_model = "o-test"
    d = Decomposer(cfg)
    assert "decomposition assistant" in d.prompt.lower()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_decomposer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pi_harness.spec.decomposer'`.

- [ ] **Step 4: Implement `decomposer.py` (model + skeleton, no LLM call yet)**

Create `pi_harness/spec/decomposer.py`:

```python
"""Decomposer: turns a linted Spec into a list of DecomposedTask via the LLM.

Task 8 wires the LLM call. This file ships the data model + prompt loader so the
shape is locked before networking is introduced.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from pi_harness.spec.format import Spec

PROMPT_PATH = Path(__file__).parent / "prompts" / "decompose_prompt.md"

Role = Literal["orchestrator", "builder", "scout", "reviewer", "synthesizer"]


class DecomposedTask(BaseModel):
    id: str
    name: str
    description: str
    acceptance_criterion: str
    blocked_by: list[str] = Field(default_factory=list)
    assigned_role: Role


class DecompositionResult(BaseModel):
    tasks: list[DecomposedTask]


class DecomposerError(RuntimeError):
    pass


class Decomposer:
    """Calls the OpenAI reasoning tier with structured outputs.

    Implementation of the network call is added in Task 8. This constructor
    loads the versioned prompt and validates config.
    """

    MAX_RETRIES = 2

    def __init__(self, config) -> None:
        if not getattr(config, "openai_api_key", None):
            raise DecomposerError("config.openai_api_key is required")
        if not getattr(config, "reasoning_model", None):
            raise DecomposerError("config.reasoning_model is required")
        self.config = config
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def decompose(self, spec: Spec) -> list[DecomposedTask]:  # pragma: no cover (Task 8)
        raise NotImplementedError("Decomposer.decompose is wired in Task 8")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/spec/test_decomposer.py -v`
Expected: 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pi_harness/spec/decomposer.py pi_harness/spec/prompts/decompose_prompt.md tests/spec/test_decomposer.py
git commit -m "feat(spec): add DecomposedTask model and decomposition prompt"
```

---

## Task 8: Decomposer LLM call with retry

**Files:**
- Modify: `pi_harness/spec/decomposer.py`
- Modify: `tests/spec/test_decomposer.py`

Wire the OpenAI structured-output call. Retry up to twice on malformed output (pydantic `ValidationError` or JSON parse error). On the third failure, raise `DecomposerError`.

Use OpenAI's responses API with `response_format={"type": "json_schema", "json_schema": ...}`. The `Decomposer` constructs the client itself (`from openai import OpenAI; OpenAI(api_key=config.openai_api_key)`) — Plan 1's `Config` provides the key, but the SDK client is local to the decomposer.

- [ ] **Step 1: Append failing tests with mocked client**

Append to `tests/spec/test_decomposer.py`:

```python
import json
from unittest.mock import MagicMock, patch

from pi_harness.spec.decomposer import DecomposerError


def _mock_openai_response(payload: dict | str) -> MagicMock:
    """Build a fake OpenAI Responses-API result whose .output_text is the payload."""
    fake = MagicMock()
    fake.output_text = payload if isinstance(payload, str) else json.dumps(payload)
    return fake


def _fake_config():
    cfg = MagicMock()
    cfg.openai_api_key = "sk-test"
    cfg.reasoning_model = "o-test"
    return cfg


def test_decomposer_returns_tasks_on_valid_response() -> None:
    payload = {
        "tasks": [
            {
                "id": "t-cancel",
                "name": "Wire cancel button",
                "description": "Hook the cancel button up to abort the upload",
                "acceptance_criterion": "Clicking Cancel during upload aborts the request within 200ms",
                "blocked_by": [],
                "assigned_role": "builder",
            },
            {
                "id": "t-cleanup",
                "name": "Server cleanup",
                "description": "Delete partial file on cancel",
                "acceptance_criterion": "Cancelled upload leaves no partial file on the server",
                "blocked_by": ["t-cancel"],
                "assigned_role": "builder",
            },
        ]
    }
    fake_client = MagicMock()
    fake_client.responses.create.return_value = _mock_openai_response(payload)

    with patch("pi_harness.spec.decomposer.OpenAI", return_value=fake_client):
        d = Decomposer(_fake_config())
        tasks = d.decompose(_spec())

    assert len(tasks) == 2
    assert tasks[0].id == "t-cancel"
    assert tasks[1].blocked_by == ["t-cancel"]
    fake_client.responses.create.assert_called_once()


def test_decomposer_retries_on_malformed_then_succeeds() -> None:
    good = {
        "tasks": [
            {
                "id": "t-only",
                "name": "n",
                "description": "d",
                "acceptance_criterion": "Clicking Cancel during upload aborts the request within 200ms",
                "blocked_by": [],
                "assigned_role": "builder",
            }
        ]
    }
    fake_client = MagicMock()
    fake_client.responses.create.side_effect = [
        _mock_openai_response("not json"),       # attempt 1 -> json parse error
        _mock_openai_response({"tasks": [{}]}),  # attempt 2 -> pydantic error
        _mock_openai_response(good),             # attempt 3 -> success
    ]
    with patch("pi_harness.spec.decomposer.OpenAI", return_value=fake_client):
        tasks = Decomposer(_fake_config()).decompose(_spec())
    assert len(tasks) == 1
    assert fake_client.responses.create.call_count == 3


def test_decomposer_raises_after_max_retries() -> None:
    fake_client = MagicMock()
    fake_client.responses.create.return_value = _mock_openai_response("still broken")
    with patch("pi_harness.spec.decomposer.OpenAI", return_value=fake_client):
        with pytest.raises(DecomposerError, match="failed after"):
            Decomposer(_fake_config()).decompose(_spec())
    assert fake_client.responses.create.call_count == 3  # 1 initial + 2 retries
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_decomposer.py -v -k "valid_response or retries or max_retries"`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Wire the LLM call**

Replace the body of `decompose` in `pi_harness/spec/decomposer.py` (and add the `OpenAI` import + `_call_llm` + JSON-schema builder):

```python
"""Decomposer: turns a linted Spec into a list of DecomposedTask via the LLM."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from pi_harness.spec.format import Spec

PROMPT_PATH = Path(__file__).parent / "prompts" / "decompose_prompt.md"

Role = Literal["orchestrator", "builder", "scout", "reviewer", "synthesizer"]


class DecomposedTask(BaseModel):
    id: str
    name: str
    description: str
    acceptance_criterion: str
    blocked_by: list[str] = Field(default_factory=list)
    assigned_role: Role


class DecompositionResult(BaseModel):
    tasks: list[DecomposedTask]


class DecomposerError(RuntimeError):
    pass


_RESPONSE_SCHEMA = {
    "name": "decomposition",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["tasks"],
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id",
                        "name",
                        "description",
                        "acceptance_criterion",
                        "blocked_by",
                        "assigned_role",
                    ],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "acceptance_criterion": {"type": "string"},
                        "blocked_by": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "assigned_role": {
                            "type": "string",
                            "enum": [
                                "orchestrator",
                                "builder",
                                "scout",
                                "reviewer",
                                "synthesizer",
                            ],
                        },
                    },
                },
            }
        },
    },
    "strict": True,
}


def _spec_to_user_message(spec: Spec) -> str:
    return json.dumps(
        {
            "id": spec.id,
            "title": spec.title,
            "goal": spec.goal,
            "acceptance_criteria": spec.acceptance_criteria,
            "constraints": spec.constraints,
            "non_goals": spec.non_goals,
        },
        indent=2,
    )


class Decomposer:
    MAX_RETRIES = 2  # in addition to the first attempt

    def __init__(self, config) -> None:
        if not getattr(config, "openai_api_key", None):
            raise DecomposerError("config.openai_api_key is required")
        if not getattr(config, "reasoning_model", None):
            raise DecomposerError("config.reasoning_model is required")
        self.config = config
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self._client = OpenAI(api_key=config.openai_api_key)

    def decompose(self, spec: Spec) -> list[DecomposedTask]:
        attempts = self.MAX_RETRIES + 1
        last_err: Exception | None = None
        for _ in range(attempts):
            try:
                raw = self._call_llm(spec)
                data = json.loads(raw)
                return DecompositionResult.model_validate(data).tasks
            except (json.JSONDecodeError, ValidationError) as e:
                last_err = e
                continue
        raise DecomposerError(
            f"decomposition failed after {attempts} attempts: {last_err}"
        )

    def _call_llm(self, spec: Spec) -> str:
        result = self._client.responses.create(
            model=self.config.reasoning_model,
            input=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": _spec_to_user_message(spec)},
            ],
            response_format={"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
        )
        return result.output_text
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/spec/test_decomposer.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/decomposer.py tests/spec/test_decomposer.py
git commit -m "feat(spec): wire Decomposer LLM call with structured outputs and retry"
```

---

## Task 9: Public package exports

**Files:**
- Modify: `pi_harness/spec/__init__.py`

Plan 8's dashboard and any other consumer should import `Spec`, `LintResult`, `LintViolation`, `DecomposedTask`, `Linter`, `Decomposer` from `pi_harness.spec` directly.

- [ ] **Step 1: Write the failing test**

Append to `tests/spec/test_format.py`:

```python
def test_public_exports() -> None:
    from pi_harness.spec import (
        DecomposedTask,
        Decomposer,
        LintResult,
        LintViolation,
        Linter,
        Spec,
    )
    assert all(
        x is not None
        for x in (DecomposedTask, Decomposer, LintResult, LintViolation, Linter, Spec)
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/spec/test_format.py::test_public_exports -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Wire the exports**

Replace `pi_harness/spec/__init__.py`:

```python
"""Public surface of the spec layer."""
from pi_harness.spec.decomposer import DecomposedTask, Decomposer, DecomposerError
from pi_harness.spec.format import (
    Spec,
    SpecStatus,
    parse_spec,
    serialize_spec,
    spec_path,
    spec_storage_dir,
)
from pi_harness.spec.linter import LintResult, LintViolation, Linter, Severity

__all__ = [
    "DecomposedTask",
    "Decomposer",
    "DecomposerError",
    "LintResult",
    "LintViolation",
    "Linter",
    "Severity",
    "Spec",
    "SpecStatus",
    "parse_spec",
    "serialize_spec",
    "spec_path",
    "spec_storage_dir",
]
```

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/spec/test_format.py::test_public_exports -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/__init__.py tests/spec/test_format.py
git commit -m "feat(spec): expose public Spec layer API"
```

---

## Task 10: FastAPI editor — CRUD routes

**Files:**
- Create: `pi_harness/spec/editor.py`
- Test: `tests/spec/test_editor.py`

Routes implemented in this task:
- `GET /specs` — list all spec ids in `spec_storage_dir()`.
- `GET /specs/{id}` — return the parsed Spec as JSON (404 if missing).
- `POST /specs` — body: `{title, goal, acceptance_criteria, constraints, non_goals}`. Server generates `id` (slug of title + timestamp), `created_at`, `updated_at`, defaults `linter_score=None`, `status="draft"`. Returns the created Spec.
- `PUT /specs/{id}` — body: any subset of editable fields. Server updates `updated_at`. Returns the updated Spec. 404 if missing.

`/lint`, `/decompose`, and `/launch` ship in Tasks 11 and 12.

- [ ] **Step 1: Write failing CRUD tests**

Create `tests/spec/test_editor.py`:

```python
"""HTTP tests for the spec editor FastAPI app."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    # Force any cached spec_storage_dir consumers to recompute.
    from pi_harness.spec import editor
    return TestClient(editor.app)


def _payload(**overrides) -> dict:
    base = dict(
        title="Cancel button",
        goal="Users can cancel an in-flight upload",
        acceptance_criteria=[
            "Clicking Cancel during upload aborts the request within 200ms",
            "Cancelled upload leaves no partial file on the server",
        ],
        constraints=[],
        non_goals=["Resuming after cancel"],
    )
    base.update(overrides)
    return base


def test_list_empty(client: TestClient) -> None:
    r = client.get("/specs")
    assert r.status_code == 200
    assert r.json() == {"specs": []}


def test_create_spec(client: TestClient) -> None:
    r = client.post("/specs", json=_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Cancel button"
    assert body["status"] == "draft"
    assert body["id"].startswith("spec-")
    assert body["created_at"]
    assert body["updated_at"] == body["created_at"]


def test_get_spec(client: TestClient) -> None:
    created = client.post("/specs", json=_payload()).json()
    r = client.get(f"/specs/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_get_spec_missing(client: TestClient) -> None:
    r = client.get("/specs/spec-does-not-exist")
    assert r.status_code == 404


def test_update_spec(client: TestClient) -> None:
    created = client.post("/specs", json=_payload()).json()
    r = client.put(
        f"/specs/{created['id']}",
        json={"title": "Renamed", "non_goals": ["explicit non-goal"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Renamed"
    assert body["non_goals"] == ["explicit non-goal"]
    assert body["updated_at"] >= created["updated_at"]


def test_update_spec_missing(client: TestClient) -> None:
    r = client.put("/specs/spec-nope", json={"title": "x"})
    assert r.status_code == 404


def test_list_after_create(client: TestClient) -> None:
    a = client.post("/specs", json=_payload(title="A")).json()
    b = client.post("/specs", json=_payload(title="B")).json()
    r = client.get("/specs")
    ids = {s["id"] for s in r.json()["specs"]}
    assert {a["id"], b["id"]} <= ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_editor.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the editor (CRUD only)**

Create `pi_harness/spec/editor.py`:

```python
"""FastAPI HTTP surface for the spec layer.

Default port: 8800 (ClawTeam's `board serve --port 8080` uses 8080 — do NOT collide).
Run directly: `uv run python -m pi_harness.spec.editor`.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from pi_harness.spec.format import (
    Spec,
    parse_spec,
    serialize_spec,
    spec_path,
    spec_storage_dir,
)

app = FastAPI(title="Pi-Harness Spec Editor", version="0.1.0")


# ---------- request / response models ----------


class CreateSpecBody(BaseModel):
    title: str
    goal: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)


class UpdateSpecBody(BaseModel):
    title: str | None = None
    goal: str | None = None
    acceptance_criteria: list[str] | None = None
    constraints: list[str] | None = None
    non_goals: list[str] | None = None


class SpecList(BaseModel):
    specs: list[Spec]


# ---------- helpers ----------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "untitled"


def _new_spec_id(title: str) -> str:
    return f"spec-{_slugify(title)[:32]}-{uuid.uuid4().hex[:6]}"


def _load(spec_id: str) -> Spec:
    path = spec_path(spec_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")
    return parse_spec(path)


# ---------- routes ----------


@app.get("/specs", response_model=SpecList)
def list_specs() -> SpecList:
    storage = spec_storage_dir()
    if not storage.exists():
        return SpecList(specs=[])
    specs: list[Spec] = []
    for path in sorted(storage.glob("*.md")):
        try:
            specs.append(parse_spec(path))
        except ValueError:
            # Skip malformed files; don't take the whole list down.
            continue
    return SpecList(specs=specs)


@app.get("/specs/{spec_id}", response_model=Spec)
def get_spec(spec_id: str) -> Spec:
    return _load(spec_id)


@app.post("/specs", response_model=Spec, status_code=status.HTTP_201_CREATED)
def create_spec(body: CreateSpecBody) -> Spec:
    now = _now()
    spec = Spec(
        id=_new_spec_id(body.title),
        title=body.title,
        goal=body.goal,
        acceptance_criteria=list(body.acceptance_criteria),
        constraints=list(body.constraints),
        non_goals=list(body.non_goals),
        created_at=now,
        updated_at=now,
        linter_score=None,
        status="draft",
    )
    serialize_spec(spec, spec_path(spec.id))
    return spec


@app.put("/specs/{spec_id}", response_model=Spec)
def update_spec(spec_id: str, body: UpdateSpecBody) -> Spec:
    spec = _load(spec_id)
    data = spec.__dict__.copy()
    patch = body.model_dump(exclude_unset=True)
    data.update(patch)
    data["updated_at"] = _now()
    updated = Spec(**data)
    serialize_spec(updated, spec_path(spec_id))
    return updated


def main() -> None:  # pragma: no cover
    import uvicorn

    port = int(os.environ.get("PI_HARNESS_SPEC_PORT", "8800"))
    uvicorn.run("pi_harness.spec.editor:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/spec/test_editor.py -v`
Expected: all CRUD tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/editor.py tests/spec/test_editor.py
git commit -m "feat(spec): add FastAPI editor with CRUD routes"
```

---

## Task 11: Editor — `/lint` and `/decompose` routes

**Files:**
- Modify: `pi_harness/spec/editor.py`
- Modify: `tests/spec/test_editor.py`

- `POST /specs/{id}/lint` — runs `Linter().lint(spec)`, persists `linter_score` and `status="linted"` if `errors == []`, returns `LintResult` JSON.
- `POST /specs/{id}/decompose` — requires `linter_score == 1.0` (no errors AND no warnings). Returns 409 with a list of remediation strings otherwise. On success, calls `Decomposer(config).decompose(spec)`, persists `status="decomposed"`, returns `{"tasks": [...]}`.

The `Decomposer` and `Config` are wired via a small `get_config()` / `get_decomposer()` dependency-injection pair so tests can override them with FastAPI's `app.dependency_overrides`.

- [ ] **Step 1: Write failing tests**

Append to `tests/spec/test_editor.py`:

```python
from unittest.mock import MagicMock

from pi_harness.spec.decomposer import DecomposedTask
from pi_harness.spec.editor import app, get_config, get_decomposer


@pytest.fixture
def linted_client(client: TestClient) -> TestClient:
    # No overrides needed for /lint.
    return client


def test_lint_route_returns_result(linted_client: TestClient) -> None:
    created = linted_client.post("/specs", json=_payload()).json()
    r = linted_client.post(f"/specs/{created['id']}/lint")
    assert r.status_code == 200
    body = r.json()
    assert "errors" in body
    assert "warnings" in body
    assert "score" in body


def test_lint_persists_status_when_no_errors(linted_client: TestClient) -> None:
    created = linted_client.post("/specs", json=_payload()).json()
    linted_client.post(f"/specs/{created['id']}/lint")
    fetched = linted_client.get(f"/specs/{created['id']}").json()
    assert fetched["status"] == "linted"
    assert fetched["linter_score"] is not None


def test_lint_does_not_promote_on_errors(linted_client: TestClient) -> None:
    bad = _payload(acceptance_criteria=[])
    created = linted_client.post("/specs", json=bad).json()
    linted_client.post(f"/specs/{created['id']}/lint")
    fetched = linted_client.get(f"/specs/{created['id']}").json()
    assert fetched["status"] == "draft"


def test_decompose_requires_perfect_score(client: TestClient) -> None:
    # Use a spec that lints clean of errors but has warnings (score < 1.0).
    payload = _payload(goal="Make it simple and fast")
    created = client.post("/specs", json=payload).json()
    client.post(f"/specs/{created['id']}/lint")
    r = client.post(f"/specs/{created['id']}/decompose")
    assert r.status_code == 409
    assert "score" in r.text.lower() or "1.0" in r.text


def test_decompose_invokes_decomposer_on_clean(client: TestClient) -> None:
    fake_decomposer = MagicMock()
    fake_decomposer.decompose.return_value = [
        DecomposedTask(
            id="t-a",
            name="A",
            description="d",
            acceptance_criterion="Clicking Cancel during upload aborts the request within 200ms",
            blocked_by=[],
            assigned_role="builder",
        )
    ]
    app.dependency_overrides[get_decomposer] = lambda: fake_decomposer
    try:
        created = client.post("/specs", json=_payload()).json()
        client.post(f"/specs/{created['id']}/lint")
        r = client.post(f"/specs/{created['id']}/decompose")
        assert r.status_code == 200, r.text
        assert r.json()["tasks"][0]["id"] == "t-a"

        fetched = client.get(f"/specs/{created['id']}").json()
        assert fetched["status"] == "decomposed"
    finally:
        app.dependency_overrides.clear()


def test_decompose_404_on_unknown_spec(client: TestClient) -> None:
    r = client.post("/specs/nope/decompose")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_editor.py -v -k "lint or decompose"`
Expected: FAIL — routes do not exist.

- [ ] **Step 3: Add the routes and DI shims**

Append to `pi_harness/spec/editor.py` (above the `main()` block):

```python
# ---------- dependencies (override-able in tests) ----------


def get_config():
    """Lazy import to avoid circular dependency at module load.

    Plan 1 exposes `load_config(env_file: str | Path | None = ".env") -> Config`
    (NOT a `Config.load()` classmethod).
    """
    from pi_harness.config import load_config

    return load_config()


def get_decomposer():
    from pi_harness.spec.decomposer import Decomposer

    return Decomposer(get_config())


# ---------- linter + decomposer routes ----------


from fastapi import Depends  # noqa: E402  (kept local to make import survey easy)

from pi_harness.spec.decomposer import DecomposedTask  # noqa: E402
from pi_harness.spec.linter import Linter, LintResult  # noqa: E402


class DecomposeResponse(BaseModel):
    tasks: list[DecomposedTask]


@app.post("/specs/{spec_id}/lint", response_model=LintResult)
def lint_spec(spec_id: str) -> LintResult:
    spec = _load(spec_id)
    result = Linter().lint(spec)

    # Persist the score + promoted status.
    data = spec.__dict__.copy()
    data["linter_score"] = result.score
    data["updated_at"] = _now()
    if not result.errors:
        data["status"] = "linted"
    serialize_spec(Spec(**data), spec_path(spec_id))
    return result


@app.post("/specs/{spec_id}/decompose", response_model=DecomposeResponse)
def decompose_spec(
    spec_id: str,
    decomposer=Depends(get_decomposer),
) -> DecomposeResponse:
    spec = _load(spec_id)
    if spec.linter_score is None or spec.linter_score < 1.0:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "spec must lint to score 1.0 before decomposition",
                "current_score": spec.linter_score,
                "remediation": [
                    "POST /specs/{id}/lint to re-run the linter after edits",
                    "fix every error and warning until score == 1.0",
                ],
            },
        )
    tasks = decomposer.decompose(spec)

    data = spec.__dict__.copy()
    data["status"] = "decomposed"
    data["updated_at"] = _now()
    serialize_spec(Spec(**data), spec_path(spec_id))
    return DecomposeResponse(tasks=tasks)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/spec/test_editor.py -v`
Expected: all editor tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/editor.py tests/spec/test_editor.py
git commit -m "feat(spec): add /lint and /decompose editor routes"
```

---

## Task 12: Editor — `/launch` route bridges to Plan 5 Coordinator

**Files:**
- Modify: `pi_harness/spec/editor.py`
- Modify: `tests/spec/test_editor.py`

`POST /specs/{id}/launch`:
1. Requires `status == "decomposed"`. Re-decomposes if not (so the route is idempotent from a `linted` state). Stores the most recent `DecomposedTask` list on the spec request lifecycle (not persisted — the linter still considers it stateless).
2. Builds a `RunSpec` from Plan 5:
   - `RunSpec.run_id = f"run-{spec.id}-{uuid4 hex[:8]}"`
   - `RunSpec.spec_id = spec.id`
   - `RunSpec.agents = [AgentSpec(id=t.id, role=t.assigned_role, blocked_by=t.blocked_by, prompt=t.description, acceptance_criterion=t.acceptance_criterion) for t in tasks]`
   - `RunSpec.topology = "sequential"` (default; Plan 5 owns the enum)
3. Calls `coordinator.launch(run_spec)` and returns `{"run_id": ...}`.
4. Persists `spec.status = "running"`.

Plan 5's exact `RunSpec` / `AgentSpec` field names are the authoritative source. This task assumes the field names listed above; if Plan 5 lands with different names, update the field map in `_run_spec_from_tasks` here only — that is the single mapping point.

- [ ] **Step 1: Write failing tests**

Append to `tests/spec/test_editor.py`:

```python
from pi_harness.spec.editor import get_coordinator


def test_launch_requires_decomposed(client: TestClient) -> None:
    created = client.post("/specs", json=_payload()).json()
    # Skip /lint and /decompose entirely.
    r = client.post(f"/specs/{created['id']}/launch")
    assert r.status_code == 409


def test_launch_builds_run_spec_and_returns_run_id(client: TestClient) -> None:
    fake_decomposer = MagicMock()
    fake_decomposer.decompose.return_value = [
        DecomposedTask(
            id="t-cancel",
            name="Cancel",
            description="Wire cancel button",
            acceptance_criterion="Clicking Cancel during upload aborts the request within 200ms",
            blocked_by=[],
            assigned_role="builder",
        ),
        DecomposedTask(
            id="t-cleanup",
            name="Cleanup",
            description="Delete partial file",
            acceptance_criterion="Cancelled upload leaves no partial file on the server",
            blocked_by=["t-cancel"],
            assigned_role="builder",
        ),
    ]
    fake_coordinator = MagicMock()
    fake_coordinator.launch.return_value = "run-spec-cancel-abcdef"

    app.dependency_overrides[get_decomposer] = lambda: fake_decomposer
    app.dependency_overrides[get_coordinator] = lambda: fake_coordinator
    try:
        created = client.post("/specs", json=_payload()).json()
        client.post(f"/specs/{created['id']}/lint")
        client.post(f"/specs/{created['id']}/decompose")
        r = client.post(f"/specs/{created['id']}/launch")
        assert r.status_code == 200, r.text
        assert r.json() == {"run_id": "run-spec-cancel-abcdef"}

        # Coordinator received a RunSpec built from the decomposed tasks.
        fake_coordinator.launch.assert_called_once()
        run_spec_arg = fake_coordinator.launch.call_args.args[0]
        assert run_spec_arg.spec_id == created["id"]
        assert len(run_spec_arg.agents) == 2
        assert run_spec_arg.agents[1].blocked_by == ["t-cancel"]

        fetched = client.get(f"/specs/{created['id']}").json()
        assert fetched["status"] == "running"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/spec/test_editor.py -v -k launch`
Expected: FAIL — `get_coordinator` does not exist yet.

- [ ] **Step 3: Implement the `/launch` route**

Append to `pi_harness/spec/editor.py` (above `main()`):

```python
# ---------- launch route ----------


def get_coordinator():
    from pi_harness.topology.coordinator import Coordinator

    return Coordinator(get_config())


def _run_spec_from_tasks(spec: Spec, tasks: list[DecomposedTask]):
    """Single mapping point between DecomposedTask and Plan 5 RunSpec/AgentSpec.

    If Plan 5's field names change, only this function needs to update.
    """
    from pi_harness.topology.coordinator import AgentSpec, RunSpec

    agents = [
        AgentSpec(
            id=t.id,
            role=t.assigned_role,
            blocked_by=list(t.blocked_by),
            prompt=t.description,
            acceptance_criterion=t.acceptance_criterion,
        )
        for t in tasks
    ]
    return RunSpec(
        run_id=f"run-{spec.id}-{uuid.uuid4().hex[:8]}",
        spec_id=spec.id,
        agents=agents,
        topology="sequential",
    )


class LaunchResponse(BaseModel):
    run_id: str


@app.post("/specs/{spec_id}/launch", response_model=LaunchResponse)
def launch_spec(
    spec_id: str,
    decomposer=Depends(get_decomposer),
    coordinator=Depends(get_coordinator),
) -> LaunchResponse:
    spec = _load(spec_id)
    if spec.status != "decomposed":
        raise HTTPException(
            status_code=409,
            detail=f"spec status is {spec.status!r}; expected 'decomposed'. "
            "POST /specs/{id}/decompose first.",
        )
    tasks = decomposer.decompose(spec)
    run_spec = _run_spec_from_tasks(spec, tasks)
    run_id = coordinator.launch(run_spec)

    data = spec.__dict__.copy()
    data["status"] = "running"
    data["updated_at"] = _now()
    serialize_spec(Spec(**data), spec_path(spec_id))
    return LaunchResponse(run_id=run_id)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/spec/test_editor.py -v`
Expected: all editor tests PASS, including both `/launch` tests.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/editor.py tests/spec/test_editor.py
git commit -m "feat(spec): add /launch route bridging spec to Plan 5 Coordinator"
```

---

## Task 13: CLI scaffold — `pi-harness` Typer app

**Files:**
- Create: `pi_harness/cli.py`
- Test: `tests/test_cli.py`

The CLI is one Typer `app` that other plans can extend (Plan 8 registers a `dashboard` subcommand on it). Task 13 lands ONLY the scaffold + `--help` + `--version`. Later tasks (14-17) wire subcommands.

- [ ] **Step 1: Write the failing test** at `/Users/pranavnair/Desktop/Personal/mannschaft/tests/test_cli.py`:

```python
"""Smoke tests for the pi-harness CLI."""
from __future__ import annotations

from typer.testing import CliRunner

runner = CliRunner()


def test_app_imports():
    """Importable as `pi_harness.cli.app`."""
    from pi_harness.cli import app
    assert app is not None


def test_help_runs_cleanly():
    from pi_harness.cli import app

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pi-harness" in result.stdout.lower()


def test_version_flag():
    from pi_harness.cli import app

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    # Plan 1 exports __version__; the CLI should print it.
    from pi_harness import __version__
    assert __version__ in result.stdout
```

Run: `uv run pytest tests/test_cli.py -v` → expect `ModuleNotFoundError`.

- [ ] **Step 2: Implement** `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/cli.py`:

```python
"""pi-harness command-line entry point.

Subcommands land in Tasks 14-17:

  pi-harness launch <spec>      — lint → decompose → Coordinator.launch
  pi-harness lint <spec>        — pure linter; exits 0/1/2 by severity
  pi-harness decompose <spec>   — print JSON task list; gated on lint score 1.0
  pi-harness spec new|edit|     — manage `~/.pi-harness/specs/*.md`
              show|rm|ls
  pi-harness serve              — boot the FastAPI editor (was `python -m
                                  pi_harness.spec.editor`)

Plan 8 registers `pi-harness dashboard` on the same Typer `app`.
"""
from __future__ import annotations

import typer

from pi_harness import __version__

app = typer.Typer(
    name="pi-harness",
    help="Pi-Agent Harness — spec-driven multi-agent run launcher.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the pi-harness version and exit.",
    ),
) -> None:
    """Root callback — owns `--version` so all subcommands inherit it."""


# Subcommands are registered in Tasks 14-17 via app.command() decorators below.
# Keep this module short — the per-subcommand logic lives in dedicated handlers.


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8800, "--port", help="Bind port (default 8800; 8080 is ClawTeam's board)."),
) -> None:
    """Boot the FastAPI spec editor (same as `python -m pi_harness.spec.editor`)."""
    import uvicorn
    from pi_harness.spec.editor import app as fastapi_app
    uvicorn.run(fastapi_app, host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    app()
```

- [ ] **Step 3: Re-run** `uv run pytest tests/test_cli.py -v` — expect 3 passed.

- [ ] **Step 4: Smoke the installed binary.** Re-sync so the `[project.scripts]` entry from Pre-Task Setup actually points at the new module:

```bash
uv sync --extra dev
uv run pi-harness --version
uv run pi-harness --help
```

Expected: version prints `0.1.0` (matches `pi_harness.__version__`); `--help` shows the banner.

- [ ] **Step 5: Commit.**

```bash
git add pi_harness/cli.py tests/test_cli.py pyproject.toml uv.lock
git commit -m "feat(cli): add pi-harness Typer scaffold with --help and --version"
```

---

## Task 14: `pi-harness launch <spec>` — direct-mode in-process launch

The headline use case: point `pi-harness` at a spec file and have it lint → decompose → launch through Plan 5's Coordinator without standing up a server.

**Flags:**
- `--allow-warnings` — proceed even if lint reports warnings (errors always block).
- `--detach` — return the run_id immediately; don't watch.
- `--watch` (default when not `--detach`) — tail trajectory events from Plan 2 if installed, else poll `clawteam --json task list <team>` every 2s. Print status + step transitions to stdout.
- `--timeout <seconds>` — passed to `Coordinator.wait_for_completion`; default 1800.
- `--api-url <url>` — instead of in-process launch, POST to `<url>/specs/<id>/launch`. Useful when the FastAPI editor is already running and you want the dashboard to see the run.

**Files:**
- Edit: `pi_harness/cli.py` (add `launch` subcommand)
- Test: `tests/test_cli.py` (extend)

- [ ] **Step 1: Append failing tests** to `tests/test_cli.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def good_spec(tmp_path: Path) -> Path:
    """A spec that lints cleanly. Reuses the linter test fixture."""
    body = (
        "---\n"
        "spec_id: cli-smoke\n"
        "title: Add dark mode toggle\n"
        "topology: sequential\n"
        "sync_mode: per_agent\n"
        "agents:\n"
        "  - { name: lead, role: orchestrator, model_tier: reasoning }\n"
        "  - { name: builder-a, role: builder, model_tier: fast }\n"
        "acceptance_criteria:\n"
        "  - Toggle persists across loads.\n"
        "  - WCAG AAA contrast in dark mode.\n"
        "---\n"
        "# Goal\nAdd a dark mode toggle to settings.\n"
    )
    p = tmp_path / "cli-smoke.md"
    p.write_text(body)
    return p


def test_launch_calls_coordinator_with_decomposed_tasks(good_spec, monkeypatch):
    """`pi-harness launch <spec>` lints, decomposes, then invokes Coordinator.launch."""
    from pi_harness.cli import app

    fake_handle = MagicMock(run_id="run-abc", team_name="team-abc")
    fake_coord = MagicMock()
    fake_coord.launch.return_value = fake_handle
    fake_coord.wait_for_completion.return_value = MagicMock(success=True)

    monkeypatch.setattr(
        "pi_harness.cli._make_coordinator", lambda cfg: fake_coord
    )
    # Avoid hitting OpenAI: pre-canned decomposed tasks.
    monkeypatch.setattr(
        "pi_harness.cli._decompose_or_die",
        lambda spec, cfg: [
            MagicMock(id="t1", description="d1", blocked_by=[], assigned_role="builder"),
        ],
    )

    result = runner.invoke(app, ["launch", str(good_spec), "--detach"])
    assert result.exit_code == 0, result.stdout
    assert "run-abc" in result.stdout
    fake_coord.launch.assert_called_once()


def test_launch_blocks_on_lint_errors(tmp_path, monkeypatch):
    """A spec with empty acceptance_criteria must exit non-zero before calling Coordinator."""
    from pi_harness.cli import app

    bad = tmp_path / "bad.md"
    bad.write_text(
        "---\nspec_id: bad\ntitle: t\ntopology: sequential\n"
        "sync_mode: per_agent\nagents: []\nacceptance_criteria: []\n---\n"
    )

    fake_coord = MagicMock()
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)

    result = runner.invoke(app, ["launch", str(bad)])
    assert result.exit_code != 0
    assert "lint" in result.stdout.lower() or "error" in result.stdout.lower()
    fake_coord.launch.assert_not_called()


def test_launch_allow_warnings_bypasses_warnings_only(good_spec, monkeypatch):
    """`--allow-warnings` lets a warning-only spec through."""
    from pi_harness.cli import app
    from pi_harness.spec.linter import LintResult, LintViolation

    fake_lint = LintResult(
        score=0.8,
        violations=[LintViolation(rule_name="vague_terms", severity="warning",
                                  message="vague", location="body:line=3")],
    )
    monkeypatch.setattr("pi_harness.cli._lint_or_die",
                        lambda spec, allow_warnings: fake_lint if allow_warnings else None)
    monkeypatch.setattr("pi_harness.cli._decompose_or_die",
                        lambda spec, cfg: [])
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-warn")
    monkeypatch.setattr("pi_harness.cli._make_coordinator", lambda cfg: fake_coord)

    result = runner.invoke(app, ["launch", str(good_spec), "--allow-warnings", "--detach"])
    assert result.exit_code == 0
```

Run: `uv run pytest tests/test_cli.py -v` → 3 prior pass, 3 new fail.

- [ ] **Step 2: Implement `launch`** by appending to `pi_harness/cli.py`:

```python
# ---- added in Task 14 ----------------------------------------------------- #
from pathlib import Path
from typing import Optional

# Lazy imports inside functions keep `pi-harness --help` fast and avoid
# pulling OpenAI / Coordinator deps unless needed.


def _load_spec_or_die(spec_path: Path):
    from pi_harness.spec.format import parse_spec_file
    if not spec_path.exists():
        typer.echo(f"error: spec file not found: {spec_path}", err=True)
        raise typer.Exit(code=2)
    return parse_spec_file(spec_path)


def _lint_or_die(spec, *, allow_warnings: bool):
    """Run the linter; exit non-zero on errors. Returns LintResult (or None
    if the test monkeypatch wants to short-circuit)."""
    from pi_harness.spec.linter import Linter

    result = Linter().lint(spec)
    if any(v.severity == "error" for v in result.violations):
        typer.echo("error: spec has lint errors:", err=True)
        for v in result.violations:
            if v.severity == "error":
                typer.echo(f"  [{v.rule_name}] {v.message} ({v.location})", err=True)
        raise typer.Exit(code=1)
    if not allow_warnings and any(v.severity == "warning" for v in result.violations):
        typer.echo("error: spec has lint warnings (use --allow-warnings to proceed):", err=True)
        for v in result.violations:
            if v.severity == "warning":
                typer.echo(f"  [{v.rule_name}] {v.message} ({v.location})", err=True)
        raise typer.Exit(code=2)
    return result


def _decompose_or_die(spec, cfg):
    from pi_harness.spec.decomposer import Decomposer
    return Decomposer(cfg).decompose(spec)


def _make_coordinator(cfg):
    """Wire Plan 5's Coordinator with stub corpus reader / improve runner.

    Plans 3 and 4 may not be installed yet; if their imports fail we fall back
    to no-op shims. The CLI still runs the team — corpus prime and improve
    just don't happen until those plans land.
    """
    from pi_harness.clawteam import ClawTeamClient
    from pi_harness.topology.coordinator import Coordinator

    client = ClawTeamClient(cfg)
    try:
        from pi_harness.corpus.reader import CorpusReader  # type: ignore
        reader = CorpusReader(cfg.corpus_root)
    except ImportError:
        reader = _NoopReader()
    try:
        from pi_harness.improve.runner import run_for_completed_run  # type: ignore

        class _ImproveRunner:
            def run_for_completed_run(self, handle):
                return run_for_completed_run(handle)
        improve = _ImproveRunner()
    except ImportError:
        improve = _NoopImprove()

    return Coordinator(
        config=cfg, clawteam_client=client,
        corpus_reader=reader, improve_runner=improve,
    )


class _NoopReader:
    def prime(self, *, classifications, session_id=None):
        return []


class _NoopImprove:
    def run_for_completed_run(self, handle):
        return None


def _watch_run(handle, *, timeout: float) -> int:
    """Tail trajectory events (Plan 2) or poll task list. Returns process exit code."""
    try:
        from pi_harness.trajectory.store import subscribe  # type: ignore
        import asyncio

        async def _tail() -> None:
            async for ev in subscribe(handle.run_id):
                typer.echo(f"[{ev.ts:%H:%M:%S}] {ev.agent_id} {ev.classification}: {ev.tool or ''}")

        asyncio.run(_tail())
        return 0
    except ImportError:
        # Fallback: poll task list. Crude but works without Plan 2.
        import time
        from pi_harness.clawteam import ClawTeamClient
        from pi_harness.config import load_config
        client = ClawTeamClient(load_config())
        deadline = time.monotonic() + timeout
        seen_status: dict[str, str] = {}
        while time.monotonic() < deadline:
            for t in client.list_tasks(handle.team_name):
                tid = t.get("task_id", "?")
                status = t.get("status", "?")
                if seen_status.get(tid) != status:
                    typer.echo(f"  task={tid} status={status}")
                    seen_status[tid] = status
            if all(s == "completed" for s in seen_status.values()) and seen_status:
                return 0
            time.sleep(2.0)
        typer.echo("error: watch timed out", err=True)
        return 1


@app.command()
def launch(
    spec_path: Path = typer.Argument(..., exists=False, help="Path to a spec .md file."),
    allow_warnings: bool = typer.Option(False, "--allow-warnings", help="Don't block on lint warnings."),
    detach: bool = typer.Option(False, "--detach", "-d", help="Return run_id and exit; don't watch."),
    timeout: float = typer.Option(1800.0, "--timeout", help="wait_for_completion timeout (seconds)."),
    api_url: Optional[str] = typer.Option(
        None, "--api-url",
        help="If set, POST to <url>/specs/<id>/launch instead of launching in-process.",
    ),
) -> None:
    """Launch a Pi-Agent Harness run from a spec file."""
    from pi_harness.config import load_config

    spec = _load_spec_or_die(spec_path)
    _lint_or_die(spec, allow_warnings=allow_warnings)
    cfg = load_config()

    if api_url:
        # API mode: defer launch to the running spec-editor server.
        import httpx
        r = httpx.post(f"{api_url.rstrip('/')}/specs/{spec.spec_id}/launch", timeout=30.0)
        r.raise_for_status()
        typer.echo(r.json().get("run_id", ""))
        return

    tasks = _decompose_or_die(spec, cfg)
    coord = _make_coordinator(cfg)
    handle = coord.launch(_spec_to_runspec(spec, tasks))
    typer.echo(handle.run_id)

    if detach:
        return

    exit_code = _watch_run(handle, timeout=timeout)
    result = coord.wait_for_completion(handle, timeout=timeout)
    coord.on_completion(handle)
    if not result.success:
        raise typer.Exit(code=exit_code or 1)


def _spec_to_runspec(spec, tasks):
    """Bridge `Spec` + decomposed tasks → Plan 5 RunSpec. Pulls field names
    from Plan 5; if Plan 5 renames fields, edit this function only."""
    from pi_harness.topology.base import (
        AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
    )
    return RunSpec(
        goal=spec.title,
        agents=[
            AgentSpec(
                name=a["name"],
                role=Role(a["role"]),
                model_tier=ModelTier(a["model_tier"]),
                task_prompt=None,
            )
            for a in spec.agents
        ],
        mode=TopologyMode(spec.topology),
        sync_mode=SyncMode(spec.sync_mode),
        corpus_classifications=getattr(spec, "corpus_classifications", []),
        session_id=getattr(spec, "session_id", None),
    )
```

- [ ] **Step 3: Re-run** `uv run pytest tests/test_cli.py -v` — expect 6 passed.

- [ ] **Step 4: Commit.**

```bash
git add pi_harness/cli.py tests/test_cli.py
git commit -m "feat(cli): add pi-harness launch <spec> with lint+decompose+coordinator"
```

---

## Task 15: `pi-harness lint` and `pi-harness decompose`

These are introspection subcommands that let an engineer iterate on spec quality without launching. `lint` exits with severity-based codes (0 = clean, 1 = error, 2 = warning). `decompose` requires lint score 1.0 and prints the JSON task list to stdout.

**Files:**
- Edit: `pi_harness/cli.py` (add `lint` + `decompose`)
- Test: `tests/test_cli.py` (extend)

- [ ] **Step 1: Append failing tests** to `tests/test_cli.py`:

```python
def test_lint_clean_exits_zero(good_spec):
    from pi_harness.cli import app
    result = runner.invoke(app, ["lint", str(good_spec)])
    assert result.exit_code == 0
    assert "score" in result.stdout.lower() or "ok" in result.stdout.lower()


def test_lint_errors_exit_one(tmp_path):
    from pi_harness.cli import app
    bad = tmp_path / "bad.md"
    bad.write_text(
        "---\nspec_id: bad\ntitle: t\ntopology: sequential\nsync_mode: per_agent\n"
        "agents: []\nacceptance_criteria: []\n---\n"
    )
    result = runner.invoke(app, ["lint", str(bad)])
    assert result.exit_code == 1


def test_decompose_emits_json_task_list(good_spec, monkeypatch):
    from pi_harness.cli import app

    fake_task = MagicMock()
    fake_task.model_dump.return_value = {
        "id": "t1", "name": "n", "description": "d",
        "acceptance_criterion": "ac", "blocked_by": [], "assigned_role": "builder",
    }
    monkeypatch.setattr(
        "pi_harness.cli._decompose_or_die",
        lambda spec, cfg: [fake_task],
    )

    result = runner.invoke(app, ["decompose", str(good_spec)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert payload[0]["id"] == "t1"


def test_decompose_refuses_imperfect_lint(tmp_path):
    """Decompose must refuse when lint score < 1.0 (matches /decompose API behavior)."""
    from pi_harness.cli import app
    warn = tmp_path / "warn.md"
    # Spec missing acceptance criteria → lint error → decompose blocks.
    warn.write_text(
        "---\nspec_id: warn\ntitle: t\ntopology: sequential\nsync_mode: per_agent\n"
        "agents: []\nacceptance_criteria: []\n---\n"
    )
    result = runner.invoke(app, ["decompose", str(warn)])
    assert result.exit_code != 0
```

- [ ] **Step 2: Implement** by appending to `pi_harness/cli.py`:

```python
@app.command()
def lint(
    spec_path: Path = typer.Argument(..., help="Path to a spec .md file."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of pretty text."),
) -> None:
    """Lint a spec file. Exit code: 0 clean, 1 errors, 2 warnings."""
    spec = _load_spec_or_die(spec_path)
    from pi_harness.spec.linter import Linter
    result = Linter().lint(spec)

    if json_output:
        import json as _json
        typer.echo(_json.dumps({
            "score": result.score,
            "violations": [
                {"rule": v.rule_name, "severity": v.severity,
                 "message": v.message, "location": v.location}
                for v in result.violations
            ],
        }))
    else:
        typer.echo(f"score: {result.score:.2f}")
        for v in result.violations:
            typer.echo(f"  [{v.severity}] {v.rule_name}: {v.message} ({v.location})")

    if any(v.severity == "error" for v in result.violations):
        raise typer.Exit(code=1)
    if any(v.severity == "warning" for v in result.violations):
        raise typer.Exit(code=2)


@app.command()
def decompose(
    spec_path: Path = typer.Argument(..., help="Path to a spec .md file."),
) -> None:
    """Decompose a clean spec into ClawTeam-ready tasks. Refuses if lint < 1.0."""
    import json as _json
    from pi_harness.config import load_config
    from pi_harness.spec.linter import Linter

    spec = _load_spec_or_die(spec_path)
    lint_result = Linter().lint(spec)
    if lint_result.score < 1.0:
        typer.echo(
            f"error: lint score is {lint_result.score:.2f}; decomposer requires 1.0",
            err=True,
        )
        raise typer.Exit(code=1)

    cfg = load_config()
    tasks = _decompose_or_die(spec, cfg)
    typer.echo(_json.dumps([t.model_dump() for t in tasks], indent=2))
```

- [ ] **Step 3: Re-run** `uv run pytest tests/test_cli.py -v` — expect 10 passed.

- [ ] **Step 4: Commit.**

```bash
git add pi_harness/cli.py tests/test_cli.py
git commit -m "feat(cli): add pi-harness lint and pi-harness decompose"
```

---

## Task 16: `pi-harness spec` subcommands — new / edit / show / rm / ls

Manages spec files at `~/.pi-harness/specs/<id>.md`. The `spec new` template lives at `pi_harness/spec/scaffold.md` so engineers can edit it without touching code.

**Files:**
- Edit: `pi_harness/cli.py` (add `spec` Typer sub-app)
- Create: `pi_harness/spec/scaffold.md`
- Test: `tests/test_cli.py` (extend)

- [ ] **Step 1: Write the scaffold template** at `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/spec/scaffold.md`:

```markdown
---
spec_id: __SPEC_ID__
title: __TITLE__
topology: sequential
sync_mode: per_agent
session_id: null
corpus_classifications: []
agents:
  - { name: lead,      role: orchestrator, model_tier: reasoning }
  - { name: builder-a, role: builder,      model_tier: fast }
acceptance_criteria:
  - "Replace this with a concrete, measurable acceptance criterion."
---

# Goal

(Write the user-facing goal in 1-3 sentences. The decomposer will use this to seed tasks.)

# Non-goals

- (Optional list of out-of-scope items the agents should refuse.)

# Notes

(Anything else the agents should know — domain facts, conventions, prior art.)
```

- [ ] **Step 2: Append failing tests** to `tests/test_cli.py`:

```python
def test_spec_new_creates_file(tmp_path, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    result = runner.invoke(app, ["spec", "new", "my-new-spec", "--title", "Test feature"])
    assert result.exit_code == 0, result.stdout
    target = tmp_path / "specs" / "my-new-spec.md"
    assert target.exists()
    body = target.read_text()
    assert "spec_id: my-new-spec" in body
    assert "title: Test feature" in body


def test_spec_new_refuses_existing(tmp_path, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    runner.invoke(app, ["spec", "new", "dup", "--title", "x"])
    result = runner.invoke(app, ["spec", "new", "dup", "--title", "x"])
    assert result.exit_code != 0


def test_spec_ls_lists_existing(tmp_path, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    runner.invoke(app, ["spec", "new", "a", "--title", "A"])
    runner.invoke(app, ["spec", "new", "b", "--title", "B"])
    result = runner.invoke(app, ["spec", "ls"])
    assert result.exit_code == 0
    assert "a" in result.stdout
    assert "b" in result.stdout


def test_spec_show_prints_file(tmp_path, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    runner.invoke(app, ["spec", "new", "showme", "--title", "Show me"])
    result = runner.invoke(app, ["spec", "show", "showme"])
    assert result.exit_code == 0
    assert "Show me" in result.stdout


def test_spec_rm_force_deletes(tmp_path, monkeypatch):
    from pi_harness.cli import app
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    runner.invoke(app, ["spec", "new", "doomed", "--title", "Doomed"])
    target = tmp_path / "specs" / "doomed.md"
    assert target.exists()
    result = runner.invoke(app, ["spec", "rm", "doomed", "--force"])
    assert result.exit_code == 0
    assert not target.exists()
```

- [ ] **Step 3: Implement** by appending to `pi_harness/cli.py`:

```python
spec_app = typer.Typer(help="Manage spec files under ~/.pi-harness/specs/.")
app.add_typer(spec_app, name="spec")


def _specs_dir() -> Path:
    import os
    home = Path(os.environ.get("PI_HARNESS_HOME", str(Path.home() / ".pi-harness")))
    d = home / "specs"
    d.mkdir(parents=True, exist_ok=True)
    return d


@spec_app.command("new")
def spec_new(
    spec_id: str = typer.Argument(..., help="Slug (e.g. dark-mode-toggle)."),
    title: str = typer.Option(..., "--title", "-t", help="Human-readable title."),
    force: bool = typer.Option(False, "--force", help="Overwrite if exists."),
) -> None:
    target = _specs_dir() / f"{spec_id}.md"
    if target.exists() and not force:
        typer.echo(f"error: {target} already exists (pass --force to overwrite)", err=True)
        raise typer.Exit(code=1)
    template = (Path(__file__).parent / "spec" / "scaffold.md").read_text()
    body = template.replace("__SPEC_ID__", spec_id).replace("__TITLE__", title)
    target.write_text(body)
    typer.echo(str(target))


@spec_app.command("ls")
def spec_ls() -> None:
    for f in sorted(_specs_dir().glob("*.md")):
        typer.echo(f.stem)


@spec_app.command("show")
def spec_show(spec_id: str) -> None:
    target = _specs_dir() / f"{spec_id}.md"
    if not target.exists():
        typer.echo(f"error: {target} not found", err=True)
        raise typer.Exit(code=1)
    typer.echo(target.read_text())


@spec_app.command("rm")
def spec_rm(
    spec_id: str,
    force: bool = typer.Option(False, "--force", help="Skip confirmation."),
) -> None:
    target = _specs_dir() / f"{spec_id}.md"
    if not target.exists():
        typer.echo(f"error: {target} not found", err=True)
        raise typer.Exit(code=1)
    if not force:
        confirm = typer.confirm(f"Delete {target}?", default=False)
        if not confirm:
            typer.echo("aborted")
            raise typer.Exit(code=0)
    target.unlink()
    typer.echo(f"removed {target}")


@spec_app.command("edit")
def spec_edit(spec_id: str) -> None:
    """Open the spec in $EDITOR (falls back to `vi`)."""
    import os
    import subprocess
    target = _specs_dir() / f"{spec_id}.md"
    if not target.exists():
        typer.echo(f"error: {target} not found", err=True)
        raise typer.Exit(code=1)
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(target)], check=False)
```

- [ ] **Step 4: Re-run** `uv run pytest tests/test_cli.py -v` — expect 15 passed.

- [ ] **Step 5: Commit.**

```bash
git add pi_harness/cli.py pi_harness/spec/scaffold.md tests/test_cli.py
git commit -m "feat(cli): add pi-harness spec new/ls/show/rm/edit"
```

---

## Task 17: Claude Code skill wrapper

Registers `/pi-harness` as a slash command inside Claude Code. The skill body is a thin instruction file that tells Claude to shell out to the `pi-harness` CLI via Bash.

**Files:**
- Create: `skills/pi-harness/SKILL.md`
- Test: `tests/test_skill.py`

- [ ] **Step 1: Write the failing test** at `/Users/pranavnair/Desktop/Personal/mannschaft/tests/test_skill.py`:

```python
"""Validate the Claude Code skill file shape."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "pi-harness" / "SKILL.md"


def test_skill_file_exists():
    assert SKILL_PATH.exists(), f"missing {SKILL_PATH}"


def test_skill_has_frontmatter():
    text = SKILL_PATH.read_text()
    assert text.startswith("---\n")
    end = text.find("\n---\n", 4)
    assert end > 0, "frontmatter not terminated"
    front = yaml.safe_load(text[4:end])
    # Required Claude Code skill keys.
    assert front["name"] == "pi-harness"
    assert front.get("description"), "description required"


def test_skill_body_mentions_bash_invocation():
    """The skill must instruct Claude to shell out to `pi-harness` via Bash."""
    text = SKILL_PATH.read_text()
    assert "Bash" in text or "bash" in text
    assert "pi-harness launch" in text
```

Run: `uv run pytest tests/test_skill.py -v` → expect failure (file missing).

- [ ] **Step 2: Write the skill file** at `/Users/pranavnair/Desktop/Personal/mannschaft/skills/pi-harness/SKILL.md`:

````markdown
---
name: pi-harness
description: Launch a Pi-Agent Harness run from a spec file. Use when the user types `/pi-harness <spec-id-or-path>` to kick off a multi-agent build via the pi-harness CLI; this skill shells out to `pi-harness launch` via Bash and surfaces the output so the user can watch the run.
---

# pi-harness

**Use when:** The user invokes `/pi-harness <arg>` where `<arg>` is either
- A spec file path (`/path/to/spec.md`), or
- A spec ID (resolved to `~/.pi-harness/specs/<id>.md`).

## What to do

1. **Resolve the spec path.** If the argument is an absolute or relative path that exists, use it. Otherwise, treat it as a spec_id and resolve to `~/.pi-harness/specs/<id>.md`. Verify the file exists with `ls -la <path>` before launching; if it doesn't, ask the user to clarify or offer to scaffold one via `pi-harness spec new`.

2. **Lint first.** Run `pi-harness lint <path>` via Bash. If exit code is non-zero, surface the output to the user and STOP. Offer to help them fix the violations rather than auto-launching a flawed spec.

3. **Launch.** If lint passes, run `pi-harness launch <path>` via Bash. The CLI streams events to stdout — the user sees agent activity in real time. The skill's job is just to start it and pass through.

4. **Don't add flags the user didn't ask for.** No `--detach` (default is watch). No `--allow-warnings` (let the linter block warning-spec by default). If the user explicitly asks for either, pass it through.

5. **On non-zero exit,** report the run_id (if printed) and the tail of the output. The user may want to inspect the trajectory store or branch from a partial run.

## What NOT to do

- Don't try to fix a failing spec by editing it yourself; ask the user.
- Don't run `pi-harness decompose` first — `pi-harness launch` already does that, and running it twice burns OpenAI credit unnecessarily.
- Don't run `pi-harness spec new` without the user asking; that's a separate intent.
- Don't shell out to `clawteam` directly — the whole point of this CLI is that the agentic orchestration is hidden behind one command.

## Installation

To register this skill with Claude Code, symlink the directory into your plugins cache:

```bash
mkdir -p ~/.claude/plugins/local
ln -sfn /Users/pranavnair/Desktop/Personal/mannschaft/skills/pi-harness ~/.claude/plugins/local/pi-harness
```

Then restart Claude Code; `/pi-harness <arg>` should appear in the slash-command menu.
````

- [ ] **Step 3: Re-run** `uv run pytest tests/test_skill.py -v` — expect 3 passed.

- [ ] **Step 4: Commit.**

```bash
git add skills/pi-harness/SKILL.md tests/test_skill.py
git commit -m "feat(skill): add /pi-harness Claude Code slash-command wrapper"
```

---

## Task 18: Full suite + smoke check

- [ ] **Step 1: Run the entire spec test suite + CLI + skill tests**

Run: `uv run pytest tests/spec/ tests/test_cli.py tests/test_skill.py -v`
Expected: every test in `test_format.py`, `test_linter.py`, `test_decomposer.py`, `test_editor.py`, `test_cli.py` (15), `test_skill.py` (3) PASSES. Track count — should be roughly 50+.

- [ ] **Step 2: Manual smoke — open the OpenAPI doc**

Run (in one terminal): `uv run pi-harness serve &` then `sleep 1 && curl -s http://127.0.0.1:8800/openapi.json | head -40`. Stop the server with `kill %1`.
Expected: JSON OpenAPI document lists `/specs`, `/specs/{spec_id}`, `/specs/{spec_id}/lint`, `/specs/{spec_id}/decompose`, `/specs/{spec_id}/launch`.

(If `pi-harness serve` isn't wired yet because Task 13 only landed the scaffold, fall back to `uv run python -m pi_harness.spec.editor &`. Adding `serve` as a thin command on `app` is a follow-up — note it in the commit log.)

- [ ] **Step 3: Manual smoke — CLI end-to-end on a fixture spec**

```bash
export PI_HARNESS_HOME=/tmp/pi-harness-smoke-$$
uv run pi-harness spec new smoke-cli --title "Smoke CLI test"
# Edit the scaffold's acceptance_criteria to have at least one real bullet
# (the default scaffold has a placeholder; the linter will warn until you fix it)
sed -i '' 's|Replace this with a concrete.*|hello.txt exists at the worktree root.|' "$PI_HARNESS_HOME/specs/smoke-cli.md"
uv run pi-harness lint smoke-cli                # should exit 0
uv run pi-harness decompose smoke-cli > /tmp/smoke-decomp.json  # should produce JSON
cat /tmp/smoke-decomp.json | head -20
```

Expected: `pi-harness lint smoke-cli` exits 0, `decompose` writes a JSON array of `DecomposedTask` objects. (Skip the actual `pi-harness launch` step here; that's covered by Plan 5's smoke test.)

- [ ] **Step 4: Final commit (only if any uncommitted changes remain)**

Run: `git status`
If clean, skip. Otherwise:

```bash
git add -A
git commit -m "chore(spec): wrap up spec layer plan"
```

---

## Self-Review (already performed during planning)

- **Spec coverage:** Every acceptance criterion in the source brief maps to a task:
  - AC1 (round-trip) → Task 1.
  - AC2 (`required_acceptance` blocks empty) → Task 3.
  - AC3 (vague terms with line numbers) → Task 4 (`location="<field>:line=<N>"`).
  - AC4 (decomposer produces tasks per criterion + `blocked_by` chains) → Task 8 (LLM call) + Task 12 test (`blocked_by` carries through).
  - AC5 (`/lint` returns `LintResult`; `/decompose` requires score 1.0) → Task 11 (both routes + `test_decompose_requires_perfect_score`).
  - AC6 (`/launch` builds `RunSpec` and returns `run_id`) → Task 12.
  - AC7 (CLI invokes the spec→launch pipeline headlessly) → Task 14 (`pi-harness launch`).
  - AC8 (Claude Code slash-command wrapper) → Task 17 (`/pi-harness <spec>`).
- **Placeholder scan:** every step has full code; no TODOs. The single `pragma: no cover` block on `main()` is intentional (uvicorn boot can't be unit-tested cleanly) and is not a placeholder for missing logic.
- **Type consistency:** `Spec` field names are identical across `format.py`, `linter.py` (reads `spec.acceptance_criteria` etc.), `decomposer.py` (`_spec_to_user_message`), and `editor.py` (CRUD + lint + decompose + launch all use the same dict expansion). `LintViolation(rule_name, severity, message, location)` matches in `linter.py` and every rule under `lints/`. `DecomposedTask(id, name, description, acceptance_criterion, blocked_by, assigned_role)` matches in `decomposer.py` (definition), `editor.py` (consumer), `cli.py` (`decompose` subcommand serializer), and every test. The CLI's `_spec_to_runspec` is the single mapping point between spec field names and Plan 5's `RunSpec` shape — if Plan 5 renames a field, edit only this function.

---

## Notes for the engineer

- **Linter rule list is configurable at two levels.** (1) Per-rule wordlists via env var — currently only `vague_terms` uses `PI_HARNESS_VAGUE_WORDS`. (2) Rule enable/disable is NOT configurable in this plan; every module in `pi_harness/spec/lints/` runs. If a future plan adds a `PI_HARNESS_LINT_DISABLE` env var (comma-separated rule names), the filter point is `Linter.__init__` — drop the matching keys from `self._rules`. Surfacing this decision to Plan 1's `Config` is a follow-up, not part of Plan 7.
- **Port choice.** Default port is 8800 to avoid ClawTeam's `board serve --port 8080`. Override with `PI_HARNESS_SPEC_PORT`. Plan 8's dashboard must hit `localhost:8800`.
- **Storage location.** `~/.pi-harness/specs/` by default; `PI_HARNESS_HOME` overrides the parent. Tests rely on the env var for isolation.
- **CLI vs HTTP parity.** `pi-harness launch <spec>` and `POST /specs/{id}/launch` MUST produce identical `RunSpec` objects from the same spec file. The shared helper is `_spec_to_runspec` in `pi_harness/cli.py`; the editor route should `from pi_harness.cli import _spec_to_runspec` rather than re-implementing the mapping. If they drift, the dashboard and the CLI will launch differently-shaped runs from the same spec, which silently breaks branch/replay.
- **Slash-command installation.** The skill file at `skills/pi-harness/SKILL.md` is shipped in the repo but NOT auto-installed into Claude Code's plugins cache. The skill body documents the symlink command (`ln -sfn .../skills/pi-harness ~/.claude/plugins/local/pi-harness`); Plan 8 may later add `pi-harness install-skill` as a convenience, but it's intentionally out of scope here.
- **CLI direct vs API mode.** `pi-harness launch` runs in-process by default — no FastAPI server required. Pass `--api-url http://localhost:8800` if you want the dashboard to see the run (it talks to the same `/launch` endpoint Plan 8's "Launch" button uses). Direct mode is the right default for CI / headless / scripting; API mode is for "I'm watching the dashboard and want this run to show up there."
- **OpenAI client.** `Decomposer` instantiates its own `OpenAI` client. Plan 1's `Config` only supplies the API key + reasoning-model name. If Plan 4 introduces a shared client factory, refactor `Decomposer.__init__` to consume it then.
