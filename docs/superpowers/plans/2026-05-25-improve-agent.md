# Improve-agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the post-hoc improve-agent that analyzes a completed run's trajectory + git diffs and emits validated candidate corpus updates and prune candidates to the Curator — strictly post-run, never during.

**Architecture:** A single LLM agent (OpenAI reasoning model) reads a summarized trajectory + corpus metadata index + git diff summary, returns structured JSON candidates parsed via pydantic. A runner module assembles inputs, invokes the agent (with retry-on-malformed up to 2 retries), validates output, and forwards candidates to the Curator from Plan 3. Execution-Learning Separation is enforced architecturally: there is no write API exposed during a run — the runner entrypoint is only called by the topology coordinator (Plan 5) after a run terminates.

**Tech Stack:** Python 3.10+, `openai>=1.0.0` SDK, `pydantic>=2.0` for schema validation, `pytest` + `pytest-mock` for tests, `uv` for dependency + test execution.

---

## Context for the engineer (zero-context onboarding)

You are implementing one module of the Pi-Agent Harness (project `mannschaft`). Read `/Users/pranavnair/Desktop/Personal/mannschaft/HARNESS_ARCHITECTURE.md` first — specifically the **Improve-agent + Curator** section and the **Execution-Learning Separation** principle (line 57: *"agents read corpus during runs, never write. Only the improve-agent writes, and only post-hoc"*).

Your module lives at `pi_harness/improve/`. You depend on three earlier plans:

- **Plan 1** provides `pi_harness.config.Config` with attributes `openai_api_key: str` and `reasoning_model: str` (e.g. `"o1"` or whatever OpenAI's current reasoning-tier name is).
- **Plan 2** provides `pi_harness.trajectory.store.query_events(run_id: str) -> list[TrajectoryEvent]` and `pi_harness.trajectory.store.query_runs(run_id: str) -> RunRecord` plus the `TrajectoryEvent` dataclass with fields documented in `HARNESS_ARCHITECTURE.md` line 49.
- **Plan 3** provides `pi_harness.corpus.curator.Curator` with method `apply_candidates(updates: list[CandidateUpdate], prunes: list[CandidatePrune]) -> CuratorReport`. Also provides the enums `Classification` (`foundational | tactical | observational`) and `RecordType` (`convention | pattern | failure | decision | reference | guide`), and the `CorpusEntry` dataclass.

You provide:

- `CandidateUpdate`, `CandidatePrune` (consumed by Plan 5 only indirectly — they pass through the runner)
- `runner.run_for_completed_run(run_id: str) -> ImproveReport` (called by Plan 5's topology coordinator at run completion)

You do **not** depend on Plan 5 — your runner is the contract surface Plan 5 calls into.

---

## Module layout

```
pi_harness/improve/
  __init__.py
  candidates.py
  agent.py
  runner.py
  prompts/
    improve_prompt.md
tests/improve/
  __init__.py
  test_candidates.py
  test_agent.py
  test_runner.py
  fixtures/
    sample_trajectory.json
    sample_corpus_index.json
    sample_git_diff.txt
    sample_agent_response.json
```

---

## Tasks

### Task 1 — Project skeleton and dependency bump

- [ ] Verify `pyproject.toml` declares Python 3.10+, `openai>=1.0.0`, `pydantic>=2.0`, `pytest>=7.0`, `pytest-mock>=3.10`. If any are missing, add them under `[project.dependencies]` (runtime) and `[project.optional-dependencies.dev]` (test). Run `uv sync` to install.
- [ ] Create empty `pi_harness/improve/__init__.py`. Add a module docstring: `"""Post-hoc improve-agent: analyzes completed runs, emits curator candidates."""`.
- [ ] Create `pi_harness/improve/prompts/` directory with an empty `__init__.py` (so it's importable for fixture loading in tests if needed).
- [ ] Create `tests/improve/__init__.py` (empty).
- [ ] Create `tests/improve/fixtures/` directory.
- [ ] Run `uv run pytest tests/ -v` to confirm the test harness still works (should pass with zero collected tests in `tests/improve/`).
- [ ] Commit: `chore(improve): scaffold improve module and test directories`.

### Task 2 — `candidates.py`: dataclasses + JSON roundtrip (TDD)

Write the test first.

- [ ] Create `tests/improve/test_candidates.py` with these test functions:
  - `test_candidate_update_roundtrip()`: construct a `CandidateUpdate` with all fields populated (record_type=`RecordType.PATTERN`, classification=`Classification.TACTICAL`, body=`"Always use async for IO"`, source_run_id=`"run-abc"`, source_step_ids=`["step-1", "step-2"]`, confidence=`0.85`, rationale=`"Observed 3 successes"`). Call `.to_json()`, then `CandidateUpdate.from_json(...)`. Assert equality field-by-field.
  - `test_candidate_prune_roundtrip()`: construct a `CandidatePrune` with `entry_id="entry-xyz"`, `trigger=PruneTrigger.COUNTER`, `rationale="harmful > helpful"`. Roundtrip and assert.
  - `test_candidate_update_confidence_validation()`: assert that confidence outside [0, 1] raises `ValueError` at construction.
  - `test_prune_trigger_enum_values()`: assert `PruneTrigger` contains exactly `COUNTER`, `CONTRADICTION`, `STALENESS`, `BUDGET`, `DEDUP`.
- [ ] Run the test, confirm it fails (`uv run pytest tests/improve/test_candidates.py -v`).
- [ ] Create `pi_harness/improve/candidates.py`:
  - Import `Classification`, `RecordType` from `pi_harness.corpus.curator` (or whichever module Plan 3 exports them from — check Plan 3 deliverables; assume `pi_harness.corpus.format`).
  - Define `class PruneTrigger(str, Enum)` with members `COUNTER = "counter"`, `CONTRADICTION = "contradiction"`, `STALENESS = "staleness"`, `BUDGET = "budget"`, `DEDUP = "dedup"`.
  - Define `@dataclass(frozen=True) class CandidateUpdate` with fields exactly: `record_type: RecordType`, `classification: Classification`, `body: str`, `source_run_id: str`, `source_step_ids: list[str]`, `confidence: float`, `rationale: str`. Add `__post_init__` validating `0.0 <= confidence <= 1.0` (raise `ValueError` with descriptive message if not).
  - Define `@dataclass(frozen=True) class CandidatePrune` with fields exactly: `entry_id: str`, `trigger: PruneTrigger`, `rationale: str`.
  - Implement `to_json(self) -> str` on both: use `json.dumps` with enum-to-value coercion (write a small `_default` helper).
  - Implement `@classmethod from_json(cls, s: str) -> Self` on both: `json.loads`, then construct.
- [ ] Run `uv run pytest tests/improve/test_candidates.py -v`. All 4 tests pass.
- [ ] Commit: `feat(improve): add CandidateUpdate and CandidatePrune dataclasses with JSON roundtrip`.

### Task 3 — Pydantic validation models (TDD)

The LLM returns JSON; pydantic validates it before we trust it.

- [ ] Extend `tests/improve/test_candidates.py` with:
  - `test_validator_accepts_valid_payload()`: feed a dict matching the expected agent output schema (see Task 6 prompt schema) to `parse_agent_response(payload)`; assert it returns `(list[CandidateUpdate], list[CandidatePrune])`.
  - `test_validator_rejects_missing_field()`: feed a dict with `confidence` missing from an update entry; assert `pydantic.ValidationError` is raised.
  - `test_validator_rejects_unknown_record_type()`: feed `record_type="not-a-type"`; assert validation fails.
- [ ] Run, confirm tests fail.
- [ ] In `pi_harness/improve/candidates.py`, add:
  - `class _CandidateUpdateModel(pydantic.BaseModel)` mirroring `CandidateUpdate` fields. Use `pydantic.ConfigDict(use_enum_values=False, extra="forbid")`.
  - `class _CandidatePruneModel(pydantic.BaseModel)` mirroring `CandidatePrune`.
  - `class _AgentResponseModel(pydantic.BaseModel)`: `updates: list[_CandidateUpdateModel]`, `prunes: list[_CandidatePruneModel]`.
  - Function `parse_agent_response(payload: dict | str) -> tuple[list[CandidateUpdate], list[CandidatePrune]]`. If `payload` is `str`, `json.loads` it first. Validate via `_AgentResponseModel`, then convert pydantic models to the frozen dataclasses.
- [ ] Run tests; all pass.
- [ ] Commit: `feat(improve): add pydantic validation for agent response payloads`.

### Task 4 — Prompt template file

- [ ] Create `pi_harness/improve/prompts/improve_prompt.md` with the following content (this is the v1 prompt — it is *expected* to iterate, so it lives as a file, not a constant):

```markdown
# Improve-Agent System Prompt (v1)

You analyze a completed multi-agent run and propose updates to the team's expertise corpus.

## Your inputs

1. **Run summary** — high-level shape of the run (agents, tools used, outcomes).
2. **Per-agent step summaries** — what each agent did, no raw I/O.
3. **Current corpus metadata index** — every existing entry with id, classification, record_type, helpful_count, harmful_count, last_referenced_run_id, body_preview (first 120 chars).
4. **Git diff summary** — which files changed in the working tree during this run.

## Your outputs

You return a SINGLE JSON object with exactly two top-level keys: `updates` and `prunes`.

### `updates`: list of new corpus candidates

Each entry has fields:
- `record_type`: one of `convention | pattern | failure | decision | reference | guide`
- `classification`: one of `foundational | tactical | observational`
- `body`: the actual content to add to the corpus (markdown allowed, keep under 500 tokens)
- `source_run_id`: the run_id you were given
- `source_step_ids`: list of step_ids that evidence this candidate
- `confidence`: float in [0.0, 1.0] — your confidence the candidate is worth adding
- `rationale`: 1-3 sentences explaining why this belongs in the corpus

### `prunes`: list of existing corpus entries to remove or demote

Each entry has fields:
- `entry_id`: id of the existing corpus entry
- `trigger`: one of `counter | contradiction | staleness | budget | dedup`
- `rationale`: 1-3 sentences explaining why

## The 6 RecordTypes — what belongs in each

- **convention**: team-agreed style/format rules. ("Branch names use kebab-case.")
- **pattern**: a recurring solution shape that worked. ("For N+1 queries, prefer `select_related`.")
- **failure**: a documented anti-pattern with evidence. ("Calling `asyncio.run` inside an existing loop crashes.")
- **decision**: an architectural choice with rationale. ("We use SQLite over Postgres for v1 because single-machine.")
- **reference**: an external link or canonical doc pointer. ("OpenAI Responses API: https://...")
- **guide**: step-by-step procedural knowledge. ("To add a new agent profile: 1. ... 2. ...")

## The 3 Classifications — when to use each

- **foundational**: durable, project-wide truths. Rarely change. Pruned only via human review.
- **tactical**: useful procedures and patterns. Auto-archived after K=50 unreferenced runs.
- **observational**: short-lived observations from a single run. Auto-archived after 7 days.

## Rules

- Be selective. Empty `updates` and `prunes` lists are valid — only emit when you have evidence.
- Cite specific `source_step_ids` for every update; if you cannot, the candidate is too vague.
- Never propose a foundational update with confidence < 0.7.
- Never propose deleting an entry — the curator handles graduated demotion; you only flag triggers.
- If two existing entries duplicate each other, emit a `dedup` prune candidate on the weaker one.

## Output format

Return ONLY a JSON object matching this exact schema. No prose, no markdown fences.

```json
{
  "updates": [
    {
      "record_type": "pattern",
      "classification": "tactical",
      "body": "...",
      "source_run_id": "<run_id>",
      "source_step_ids": ["step-1", "step-2"],
      "confidence": 0.8,
      "rationale": "..."
    }
  ],
  "prunes": [
    {
      "entry_id": "entry-abc",
      "trigger": "counter",
      "rationale": "..."
    }
  ]
}
```
```

- [ ] Commit: `feat(improve): add v1 improve-agent prompt template`.

### Task 5 — Input assembly helpers (TDD)

The agent does not see raw trajectory dumps — we summarize first to stay in token budget.

- [ ] Add to `tests/improve/test_agent.py`:
  - `test_summarize_trajectory_shape()`: feed a list of fake `TrajectoryEvent` objects (3 agents, 5 steps each) to `summarize_trajectory(events)`. Assert the returned dict has keys `run_shape` (with `agents: list[str]`, `tools_used: list[str]`, `outcomes: dict[str, str]`) and `per_agent_steps` (with one entry per agent_id, each a list of step dicts containing `step_id`, `tool`, `outcome`, `duration_ms` — NOT `input` or `output`).
  - `test_summarize_corpus_metadata()`: feed a list of fake `CorpusEntry` objects to `summarize_corpus_metadata(entries)`. Assert each returned dict has `id`, `classification`, `record_type`, `helpful_count`, `harmful_count`, `last_referenced_run_id`, `body_preview` (first 120 chars of body), and that no full `body` field is present.
  - `test_summarize_git_diff()`: feed a fake git diff string (multi-file, ~200 lines); assert `summarize_git_diff(diff_text)` returns a string under 2000 chars with a per-file `+N -M` summary plus first/last 3 hunks per file.
- [ ] Run, confirm fail.
- [ ] Create `pi_harness/improve/agent.py`. Add three functions:
  - `summarize_trajectory(events: list[TrajectoryEvent]) -> dict`. Group events by `agent_id`, collect distinct `tool` values, pull the final `outcome` per agent. Return the shape the test expects.
  - `summarize_corpus_metadata(entries: list[CorpusEntry]) -> list[dict]`. Drop `body`, keep metadata + first-120-char preview.
  - `summarize_git_diff(diff_text: str) -> str`. Parse `diff --git` headers, count `+`/`-` lines per file, retain first 3 + last 3 hunks per file separated by `... <N lines elided> ...`. Cap total at 2000 chars (truncate with `[truncated]` marker if needed).
- [ ] Run tests; all pass.
- [ ] Commit: `feat(improve): add trajectory/corpus/diff summarization helpers`.

### Task 6 — Prompt assembly (TDD)

- [ ] Add to `tests/improve/test_agent.py`:
  - `test_build_messages_includes_all_inputs()`: call `build_messages(run_id, trajectory_summary, corpus_summary, git_diff_summary, prompt_template_text)` and assert the returned `list[dict]` has a system message containing the loaded prompt template and a user message containing the run_id, all four summaries serialized as JSON, and the literal phrase `"Return ONLY a JSON object"`.
  - `test_load_prompt_template_reads_file()`: assert `load_prompt_template()` reads `pi_harness/improve/prompts/improve_prompt.md` and returns the content non-empty.
- [ ] Run, confirm fail.
- [ ] In `pi_harness/improve/agent.py`:
  - `def load_prompt_template() -> str`: use `importlib.resources.files("pi_harness.improve.prompts").joinpath("improve_prompt.md").read_text(encoding="utf-8")`. If that fails (e.g. namespace package issues), fall back to `pathlib.Path(__file__).parent / "prompts" / "improve_prompt.md"`.
  - `def build_messages(run_id: str, trajectory_summary: dict, corpus_summary: list[dict], git_diff_summary: str, prompt_template_text: str) -> list[dict]`. Returns `[{"role": "system", "content": prompt_template_text}, {"role": "user", "content": <serialized JSON envelope>}]`. The envelope is a JSON object with keys `run_id`, `trajectory_summary`, `corpus_metadata`, `git_diff_summary`, plus a closing string `"Return ONLY a JSON object matching the schema in the system prompt."`.
- [ ] Run tests; pass.
- [ ] Commit: `feat(improve): add prompt template loader and message assembly`.

### Task 7 — `ImproveAgent` class with OpenAI call + retry (TDD)

This is the agent itself. The LLM call is mocked in tests via `pytest-mock`.

- [ ] Add to `tests/improve/test_agent.py`:
  - `test_analyze_returns_parsed_candidates(mocker)`: create a fake `OpenAI` client whose `chat.completions.create` returns an object with `.choices[0].message.content` = a JSON string matching the schema, with one update and one prune. Inject it into `ImproveAgent(config, client=fake_client)`. Call `agent.analyze(run_id="run-1", events=[...], corpus_entries=[...], git_diff_text="...")`. Assert the result is a tuple `(updates, prunes)` with one item each, correctly typed.
  - `test_analyze_retries_on_malformed_json(mocker)`: fake client returns `"not json"` on first call, `"{\"updates\": [], \"prunes\": []}"` on second. Assert `analyze(...)` succeeds and the client was called exactly 2 times.
  - `test_analyze_retries_on_schema_violation(mocker)`: fake client returns valid JSON missing required fields on first call, valid full JSON on second. Same behavior — succeeds on retry.
  - `test_analyze_raises_after_max_retries(mocker)`: fake client returns malformed JSON 3 times. Assert `ImproveError` is raised. Assert the client was called exactly 3 times.
- [ ] Run; confirm fail.
- [ ] In `pi_harness/improve/agent.py`:
  - `class ImproveError(Exception): pass`
  - `MAX_RETRIES = 2` (so 3 total attempts including the initial call).
  - `class ImproveAgent`:
    - `__init__(self, config: Config, client: OpenAI | None = None)`. If `client` is None, instantiate `OpenAI(api_key=config.openai_api_key)`.
    - `def analyze(self, run_id: str, events: list[TrajectoryEvent], corpus_entries: list[CorpusEntry], git_diff_text: str) -> tuple[list[CandidateUpdate], list[CandidatePrune]]`:
      1. Build summaries via helpers.
      2. Load prompt template.
      3. Build messages.
      4. Loop up to `MAX_RETRIES + 1` times:
         - Call `self._client.chat.completions.create(model=self._config.reasoning_model, messages=messages, response_format={"type": "json_object"})`. (Note: we use `json_object` mode for v1, not strict `json_schema`, because reasoning-tier models' strict-schema support is inconsistent — see "Unresolved decisions" below.)
         - Extract `content = response.choices[0].message.content`.
         - Try `parse_agent_response(content)`. On success, return.
         - On `json.JSONDecodeError` or `pydantic.ValidationError`, log a warning, append a corrective user message to `messages` (e.g. `{"role": "user", "content": "Your previous response was invalid: <error>. Re-emit ONLY valid JSON matching the schema."}`), and loop.
      5. After the loop exhausts, raise `ImproveError(f"Agent produced invalid output after {MAX_RETRIES + 1} attempts")`.
- [ ] Run tests; all 4 pass.
- [ ] Commit: `feat(improve): add ImproveAgent with retry-on-malformed and ImproveError`.

### Task 8 — Test fixtures

- [ ] Create `tests/improve/fixtures/sample_trajectory.json` — a JSON list of 5-8 fake `TrajectoryEvent` dicts (matching Plan 2's schema). Cover 2 agents, ~3 tools, mixed outcomes.
- [ ] Create `tests/improve/fixtures/sample_corpus_index.json` — a JSON list of 3-5 fake `CorpusEntry` dicts (matching Plan 3's schema). Mix classifications.
- [ ] Create `tests/improve/fixtures/sample_git_diff.txt` — a realistic multi-file git diff (~150 lines).
- [ ] Create `tests/improve/fixtures/sample_agent_response.json` — a valid agent response (2 updates, 1 prune) matching the prompt schema.
- [ ] Add a `tests/improve/conftest.py` with fixture loaders:

```python
import json
from pathlib import Path
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_trajectory():
    return json.loads((FIXTURE_DIR / "sample_trajectory.json").read_text())

@pytest.fixture
def sample_corpus_index():
    return json.loads((FIXTURE_DIR / "sample_corpus_index.json").read_text())

@pytest.fixture
def sample_git_diff():
    return (FIXTURE_DIR / "sample_git_diff.txt").read_text()

@pytest.fixture
def sample_agent_response():
    return (FIXTURE_DIR / "sample_agent_response.json").read_text()
```

- [ ] Add one acceptance-criterion test in `tests/improve/test_agent.py`:
  - `test_analyze_with_sample_fixtures(mocker, sample_trajectory, sample_corpus_index, sample_git_diff, sample_agent_response)`: convert fixture dicts to `TrajectoryEvent` / `CorpusEntry` instances, fake the OpenAI client to return `sample_agent_response`, call `agent.analyze(...)`, assert updates and prunes parse cleanly and match expected counts (2 and 1).
- [ ] Run; passes.
- [ ] Commit: `test(improve): add fixtures and fixture-driven agent test`.

### Task 9 — `runner.py`: `run_for_completed_run` end-to-end (TDD)

- [ ] Create `tests/improve/test_runner.py`:
  - `test_run_for_completed_run_end_to_end(mocker, tmp_path, sample_agent_response)`:
    1. Set up a temp git repo at `tmp_path/corpus`. Initialize git (`subprocess.run(["git", "init"], cwd=...)`), seed it with a Plan-3 `Corpus` instance (write one entry, commit).
    2. Set up a temp SQLite trajectory store at `tmp_path/trajectory.db`. Seed it with one run + several events for `run_id="run-test-1"` (use Plan 2's writer API; if Plan 2 exposes `record_event`, use it).
    3. Build a `Config` instance with `openai_api_key="fake"`, `reasoning_model="fake-model"`, `corpus_path=tmp_path/"corpus"`, `trajectory_db_path=tmp_path/"trajectory.db"`.
    4. Mock `ImproveAgent.analyze` to return parsed candidates from `sample_agent_response`.
    5. Call `run_for_completed_run("run-test-1", config=config)`.
    6. Assert returned `ImproveReport` has the right counts (candidates_emitted, candidates_applied).
    7. Assert the corpus directory has new git commits (`git log --oneline` shows > 1 commit).
    8. Assert no writes occurred to the corpus *before* `run_for_completed_run` was called (regression guard against accidental in-run writes — verify by checking commit count was 1 before the call).
  - `test_run_for_completed_run_propagates_improve_error(mocker, ...)`: mock `ImproveAgent.analyze` to raise `ImproveError`; assert `run_for_completed_run` re-raises (does NOT swallow — Plan 5 needs to know).
- [ ] Run, confirm fail.
- [ ] Create `pi_harness/improve/runner.py`:
  - `@dataclass class ImproveReport`: `run_id: str`, `candidates_emitted: int`, `prunes_emitted: int`, `curator_actions: int` (sum of applied updates + applied prunes from the `CuratorReport` returned by `Curator.apply_candidates`).
  - `def run_for_completed_run(run_id: str, config: Config | None = None, *, agent: ImproveAgent | None = None, curator: Curator | None = None) -> ImproveReport`:
    1. If `config is None`, load via `Config.load()` (Plan 1).
    2. Query `events = query_events(run_id, db_path=config.trajectory_db_path)`. If empty, raise `ImproveError(f"No events for run {run_id}")`.
    3. Query `run_record = query_runs(run_id, db_path=config.trajectory_db_path)`. Capture `run_record.start_ts` as `run_start_ts`.
    4. Read corpus entries via Plan 3's reader: `corpus_entries = CorpusReader(config.corpus_path).all_entries()`.
    5. Read git diff: `git_diff_text = _git_diff_since(config.corpus_path, run_start_ts)`. Implementation uses `subprocess.run(["git", "log", "--since", iso_ts, "-p", "--no-color"], cwd=config.corpus_path, capture_output=True, text=True)`. (We diff the corpus git, not the project git — corpus changes during a run would indicate a bug, but we still inspect them. For project-code changes during a run, the topology coordinator passes them in separately; v1 reads corpus diff only and leaves project-diff plumbing as a v2 hook.)
    6. If `agent is None`, instantiate `ImproveAgent(config)`.
    7. Call `updates, prunes = agent.analyze(run_id, events, corpus_entries, git_diff_text)`.
    8. If `curator is None`, instantiate `Curator(config.corpus_path)` (Plan 3).
    9. Call `curator_report = curator.apply_candidates(updates, prunes)`.
    10. Return `ImproveReport(run_id=run_id, candidates_emitted=len(updates), prunes_emitted=len(prunes), curator_actions=curator_report.applied_count)`.
  - Helper `def _git_diff_since(repo_path: Path, since_ts: datetime) -> str`: as described.
- [ ] Run tests; both pass.
- [ ] Commit: `feat(improve): add runner.run_for_completed_run with end-to-end orchestration`.

### Task 10 — Execution-Learning Separation guard test

This is an acceptance-criterion test (#4) — it's worth its own task because it's the defining architectural invariant.

- [ ] Add `tests/improve/test_runner.py::test_no_writes_during_run`:
  - Build the same temp corpus + trajectory setup as Task 9.
  - Run a fake "live run" path: call `query_events`, instantiate `ImproveAgent`, but do NOT call `run_for_completed_run`. After this simulated run, assert the corpus git log is unchanged (commit count + HEAD SHA both stable).
  - Now call `run_for_completed_run`. Assert the corpus git log grew.
  - Rationale: confirms there is no code path inside `ImproveAgent.__init__` or summarization helpers that mutates the corpus.
- [ ] Run; passes.
- [ ] Commit: `test(improve): add execution-learning separation guard test`.

### Task 11 — Public exports + module docstring polish

- [ ] In `pi_harness/improve/__init__.py`, export the public API:

```python
"""Post-hoc improve-agent: analyzes completed runs, emits curator candidates."""

from pi_harness.improve.candidates import (
    CandidateUpdate,
    CandidatePrune,
    PruneTrigger,
    parse_agent_response,
)
from pi_harness.improve.agent import ImproveAgent, ImproveError
from pi_harness.improve.runner import run_for_completed_run, ImproveReport

__all__ = [
    "CandidateUpdate",
    "CandidatePrune",
    "PruneTrigger",
    "ImproveAgent",
    "ImproveError",
    "ImproveReport",
    "run_for_completed_run",
    "parse_agent_response",
]
```

- [ ] Run the full module test suite: `uv run pytest tests/improve/ -v`. All tests pass.
- [ ] Run a smoke import: `uv run python -c "from pi_harness.improve import run_for_completed_run, CandidateUpdate, ImproveAgent; print('ok')"`. Output is `ok`.
- [ ] Commit: `feat(improve): expose public API via __init__`.

### Task 12 — Acceptance-criteria verification pass

Walk through the 5 acceptance criteria and confirm each maps to a passing test. Document the mapping in the commit message.

- [ ] AC1 (CandidateUpdate/CandidatePrune JSON roundtrip) → `test_candidate_update_roundtrip`, `test_candidate_prune_roundtrip`.
- [ ] AC2 (sample trajectory + corpus produces validator-accepted candidates) → `test_analyze_with_sample_fixtures`.
- [ ] AC3 (end-to-end: trajectory → agent → curator → corpus updated, commits in temp git) → `test_run_for_completed_run_end_to_end`.
- [ ] AC4 (no writes during live run) → `test_no_writes_during_run`.
- [ ] AC5 (retries up to 2 times, fails on 3rd with `ImproveError`) → `test_analyze_retries_on_malformed_json`, `test_analyze_retries_on_schema_violation`, `test_analyze_raises_after_max_retries`.
- [ ] Run `uv run pytest tests/improve/ -v` one more time. All tests green.
- [ ] Run `uv run pytest tests/ -v` (full project suite) to confirm no regressions in Plans 1-3.
- [ ] Commit: `test(improve): verify all 5 acceptance criteria mapped to passing tests`.

---

## Self-review checklist (run before declaring done)

- [ ] No `TODO`, `FIXME`, `XXX`, or `pass  # placeholder` in shipped code.
- [ ] Every public function has a type hint on every parameter and the return value.
- [ ] Every dataclass is `frozen=True`.
- [ ] All filenames match the layout exactly: `candidates.py`, `agent.py`, `runner.py`, `prompts/improve_prompt.md`.
- [ ] All cross-plan imports use the exact symbol names from Plan 1/2/3 (`Config`, `TrajectoryEvent`, `query_events`, `query_runs`, `Curator`, `CorpusEntry`, `Classification`, `RecordType`). If any symbol turns out to be named differently in the upstream plan, **stop and reconcile** — do not invent local aliases.
- [ ] `ImproveAgent.analyze` is the ONLY place that calls `openai.OpenAI.chat.completions.create` — no scattered SDK calls.
- [ ] `run_for_completed_run` is the only public entrypoint that writes to the corpus.
- [ ] Test count: ≥ 13 tests in `tests/improve/`. Confirm via `uv run pytest tests/improve/ -v --co -q | wc -l`.

---

## Unresolved decisions (flag to Pranav before / during build)

1. **OpenAI API shape** — Plan brief says "OpenAI Responses API (or `openai` SDK chat completions)". I lock in **`chat.completions.create` with `response_format={"type": "json_object"}`** for v1 because:
   - The Responses API (`client.responses.create`) is newer and its structured-output story for reasoning-tier models (o1/o3 family) was still rolling out as of late 2025; strict `json_schema` mode may or may not be supported depending on the specific model name configured.
   - `chat.completions` with `json_object` mode is universally supported and pairs cleanly with our pydantic-validation + retry loop.
   - **If Pranav prefers Responses API**: swap the body of `_call_llm` in `ImproveAgent`; the rest of the module is API-shape-agnostic. Recommend deciding once after Plan 1 lands and we know the exact `reasoning_model` value in `Config`.
2. **Reasoning-tier streaming** — none in v1. Improve-agent runs post-hoc and is allowed to be slow.
3. **Project-code diff** — v1 reads corpus-repo diff only. Plan 5 may want to pass in a project-code diff at `run_for_completed_run` call time; if so, add `project_diff_text: str | None = None` as a keyword arg in v2 and thread it into `agent.analyze`.
4. **Token budget** — no hard cap on the assembled user message in v1. Add a guard in v2 once we have telemetry on real run sizes.

---

## Provides (for Plan 5)

- `pi_harness.improve.run_for_completed_run(run_id: str, config: Config | None = None) -> ImproveReport`. Plan 5's topology coordinator calls this exactly once at the end of every run.
- `pi_harness.improve.ImproveReport` dataclass for surfacing improve-agent results in the dashboard.
- `pi_harness.improve.ImproveError` for failure handling.
