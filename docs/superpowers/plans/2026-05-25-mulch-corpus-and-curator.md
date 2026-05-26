# Mulch Corpus + Curator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the Mulch-format corpus and a deterministic (LLM-free) Python curator that applies improve-agent candidate updates and prunes entries per the rules in `HARNESS_ARCHITECTURE.md` §2.

**Architecture:** The corpus lives at `~/.pi-harness/corpus/` as its own git repo with per-classification subdirs holding YAML-frontmatter markdown files. A `Curator` is the sole gateway permitted to write entries (enforced via a context manager) — it applies candidate updates, runs every prune rule, then commits one summary commit per pass. All counter writes go through `counters.py` to keep the file format consistent.

**Tech Stack:** Python 3.10+, uv, pytest, `tiktoken` (cl100k_base for token sizing), `pyyaml` (frontmatter parse/serialize), `freezegun` (time-dependent prune tests), `gitpython` (corpus repo commits), stdlib `dataclasses` / `enum` / `hashlib` / `pathlib`.

---

## Dependencies — read these from prior plans

You depend on two upstream plans. Skim their public surface before starting:

- **Plan 1** provides `pi_harness.config.Config` with `Config.corpus_root: pathlib.Path` (defaults to `~/.pi-harness/corpus`). Tests construct a `Config` pointed at a `tmp_path` to keep filesystem effects isolated.
- **Plan 2** provides `pi_harness.trajectory.schema.TrajectoryEvent` (fields include `run_id: str`, `corpus_refs: list[str]`, `corpus_cited: list[str]`) and `pi_harness.trajectory.store.query_events(run_id=None, since_ts=None, limit=None) -> list[TrajectoryEvent]`. Counter updates in this plan read these but never write trajectory rows.

If either is not yet implemented when you start, stub them locally in `tests/conftest.py` as needed — the curator code itself imports `Config` only via constructor injection (don't hard-code paths).

You provide downstream:

- `CorpusEntry`, `Classification`, `RecordType` (consumed by Plans 4, 6, 8).
- `Curator.apply_candidates(...)` (called by Plan 4's improve-agent runner).
- `reader.prime(...)` (used by Plans 6 and 8 to inject corpus context into agents).

---

## Conventions (apply to every task)

- **TDD always:** write failing tests first, then code. Run `uv run pytest tests/corpus/<file>.py -v` after each task.
- **Type hints everywhere:** all public functions get full annotations. `from __future__ import annotations` at the top of every module.
- **Conventional commits:** prefix `feat(corpus):`, `test(corpus):`, `chore(corpus):`. One commit per completed task (checkbox group).
- **No placeholders.** If a value is missing, stop and resolve it in `## Unresolved decisions` rather than emitting `# TODO`.
- **Pure code curator.** No LLM calls in `pi_harness/corpus/`. Similarity uses shingled-hash, never embeddings.
- **Frozen time for prune tests.** Every staleness/recency assertion must wrap `freeze_time(...)` so tests are reproducible.

---

## Task 0 — Project bootstrap

- [x] **0.1** Confirm `pi_harness/` package exists at repo root with `__init__.py`. If not, create it.
  - Run: `ls /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/__init__.py`
  - Expected: file exists. If not, `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness && touch /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/__init__.py`.
- [x] **0.2** Add dependencies via `uv`.
  - Run: `cd /Users/pranavnair/Desktop/Personal/mannschaft && uv add tiktoken pyyaml gitpython && uv add --dev freezegun pytest`
  - Expected: `pyproject.toml` gains `tiktoken`, `pyyaml`, `gitpython` in main deps and `freezegun`, `pytest` in dev deps.
- [x] **0.3** Create the corpus package skeleton.
  - Run: `mkdir -p /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/corpus /Users/pranavnair/Desktop/Personal/mannschaft/tests/corpus && touch /Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/corpus/__init__.py /Users/pranavnair/Desktop/Personal/mannschaft/tests/corpus/__init__.py`
  - Expected: both `__init__.py` files exist and are empty.
- [x] **0.4** Add a `tests/conftest.py` (or extend existing) providing a `tmp_corpus_root` fixture.
  - File: `/Users/pranavnair/Desktop/Personal/mannschaft/tests/conftest.py`
  - Contents:
    ```python
    from __future__ import annotations
    from pathlib import Path
    import pytest

    @pytest.fixture
    def tmp_corpus_root(tmp_path: Path) -> Path:
        root = tmp_path / "corpus"
        root.mkdir()
        for sub in ("foundational", "tactical", "observational", "archived"):
            (root / sub).mkdir()
        return root
    ```
  - Run: `uv run pytest --collect-only tests/corpus -q`
  - Expected: collection succeeds (zero tests yet).
- [x] **0.5** Commit. `git add pi_harness/corpus tests/corpus tests/conftest.py pyproject.toml uv.lock && git commit -m "chore(corpus): bootstrap package and dev deps"`

---

## Task 1 — `format.py` (data model + YAML frontmatter roundtrip)

- [x] **1.1** Write failing tests for the enums and dataclass in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/corpus/test_format.py`:
  - One parametrized test that roundtrips ALL 6 `RecordType` values (`convention`, `pattern`, `failure`, `decision`, `reference`, `guide`) and all 3 `Classification` values (`foundational`, `tactical`, `observational`) through `serialize_entry → parse_entry`, asserting every field is preserved including counters, timestamps (use `freeze_time("2026-05-25T12:00:00Z")`), and the body text.
  - A test that asserts `CorpusEntry.id` matches `r"^(convention|pattern|failure|decision|reference|guide)-[0-9a-f]{12}$"`.
  - A test that asserts `size_tokens` is computed from the body using `tiktoken.get_encoding("cl100k_base")` — assert it equals `len(enc.encode(body))` for a known string.
  - A test that asserts unknown enum values raise `ValueError` on parse.
  - Run: `uv run pytest tests/corpus/test_format.py -v` → expected: tests fail (module not yet implemented).
- [x] **1.2** Implement `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/corpus/format.py`:
  - Module imports: `from __future__ import annotations`, `dataclasses`, `enum`, `datetime`, `hashlib`, `pathlib.Path`, `yaml`, `tiktoken`.
  - `class RecordType(str, Enum)` with members `CONVENTION = "convention"`, `PATTERN = "pattern"`, `FAILURE = "failure"`, `DECISION = "decision"`, `REFERENCE = "reference"`, `GUIDE = "guide"`.
  - `class Classification(str, Enum)` with `FOUNDATIONAL = "foundational"`, `TACTICAL = "tactical"`, `OBSERVATIONAL = "observational"`.
  - `_ENCODER = tiktoken.get_encoding("cl100k_base")` (module-level).
  - `def _hash_body(record_type: RecordType, body: str) -> str` returns `f"{record_type.value}-{hashlib.sha256((record_type.value + body).encode()).hexdigest()[:12]}"`.
  - `def count_tokens(text: str) -> int` returns `len(_ENCODER.encode(text))`.
  - `@dataclass class CorpusEntry` with the exact fields listed in the scope spec. Provide `@classmethod def new(cls, *, record_type, classification, body, now: datetime) -> CorpusEntry` that auto-computes `id` and `size_tokens` and sets `created_at = last_updated_at = now`.
  - `def serialize_entry(entry: CorpusEntry) -> str` returns YAML frontmatter (between `---` lines) + `\n` + `entry.body`. Frontmatter keys (order preserved): `id`, `record_type`, `classification`, `helpful_count`, `harmful_count`, `contradiction_count`, `created_at` (ISO 8601 UTC), `last_updated_at`, `last_referenced_run_id`, `size_tokens`. Use `yaml.safe_dump(..., sort_keys=False)`.
  - `def parse_entry(path: pathlib.Path) -> CorpusEntry` reads the file, splits on the first two `---` lines, parses frontmatter with `yaml.safe_load`, coerces enums (`RecordType(value)`, `Classification(value)`) — letting `ValueError` propagate for unknowns — and parses ISO timestamps via `datetime.fromisoformat`.
  - Run: `uv run pytest tests/corpus/test_format.py -v`
  - Expected: all tests pass.
- [x] **1.3** Commit. `git add pi_harness/corpus/format.py tests/corpus/test_format.py && git commit -m "feat(corpus): record/classification enums + YAML frontmatter format with roundtrip"`

---

## Task 2 — `counters.py` (utility, recency decay, counter writes)

- [x] **2.1** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/corpus/test_counters.py`:
  - `test_recency_decay_half_life_14_days`: with `freeze_time("2026-05-25T00:00:00Z")`, an entry whose `last_updated_at = now - 14 days` returns `recency_decay(entry, now) == pytest.approx(0.5, rel=1e-3)`.
  - `test_recency_decay_today_is_one`: an entry just updated at `now` returns `1.0`.
  - `test_utility_score_formula`: `utility_score = helpful_count / max(size_tokens, 1) * recency_decay`; assert that doubling `helpful_count` doubles the score; assert `size_tokens=0` is handled (uses `max(1, size_tokens)`).
  - `test_update_helpful_increments_and_stamps_last_updated_at`: with frozen time, after `update_helpful(entry, now)` returns a new entry, `helpful_count` is +1 and `last_updated_at == now`.
  - Symmetric tests for `update_harmful` and `update_contradiction`.
  - `test_counter_update_writes_through_format`: with a temp corpus root, write an entry via `Writer` (this test uses the curator context manager from Task 5; if writing this test before Task 5, stub by direct `serialize_entry` write — then re-validate after Task 5), call counter update, parse back, assert counter changed.
  - Run: `uv run pytest tests/corpus/test_counters.py -v` → expected: fails.
- [x] **2.2** Implement `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/corpus/counters.py`:
  - Functions: `update_helpful(entry: CorpusEntry, now: datetime) -> CorpusEntry`, `update_harmful(...)`, `update_contradiction(...)`. Each returns a `dataclasses.replace(entry, <counter>=<+1>, last_updated_at=now)`.
  - `def recency_decay(entry: CorpusEntry, now: datetime, half_life_days: float = 14.0) -> float`: `age_days = (now - entry.last_updated_at).total_seconds() / 86400`; `return 0.5 ** (age_days / half_life_days)`.
  - `def utility_score(entry: CorpusEntry, now: datetime) -> float`: `return entry.helpful_count / max(entry.size_tokens, 1) * recency_decay(entry, now)`.
  - The mutation functions return new entries — they don't write to disk. Disk writes go through `Curator → writer.write_entry`. Document this explicitly in the module docstring.
  - Run: `uv run pytest tests/corpus/test_counters.py -v`
  - Expected: all tests pass (except the `Writer`-coupled one which can be xfail-skipped until Task 5).
- [x] **2.3** Commit. `git add pi_harness/corpus/counters.py tests/corpus/test_counters.py && git commit -m "feat(corpus): counter mutations, recency decay, utility score"`

---

## Task 3 — `writer.py` (gated, append-only)

- [x] **3.1** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/corpus/test_writer.py`:
  - `test_write_entry_outside_curator_raises_writer_access_error`: calling `writer.write_entry(entry, root)` directly raises `WriterAccessError`.
  - `test_write_entry_inside_curator_context_succeeds`: using `with writer.curator_context():` block, call writes succeed and the file lands at `<root>/<classification>/<id>.md`.
  - `test_write_entry_updates_last_updated_at`: with `freeze_time`, after `write_entry(entry)` parses-back-equal except `last_updated_at == now`.
  - `test_write_entry_is_idempotent_overwrite`: writing the same entry twice does not raise; second write replaces first.
  - `test_concurrent_writes_use_file_lock`: open the same path twice via the lock helper (use `fcntl.flock`); assert second blocks/raises immediately (use `LOCK_NB`).
  - Run: `uv run pytest tests/corpus/test_writer.py -v` → fail.
- [x] **3.2** Implement `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/corpus/writer.py`:
  - `class WriterAccessError(RuntimeError): ...`
  - Module-level `_CURATOR_CONTEXT_ACTIVE: bool = False` and `_LOCK = threading.Lock()` for the flag toggling.
  - `@contextlib.contextmanager def curator_context()`: toggles `_CURATOR_CONTEXT_ACTIVE` True on enter, False on exit (with try/finally). Reentrant: nested calls bump a counter.
  - `def write_entry(entry: CorpusEntry, root: pathlib.Path, now: datetime) -> pathlib.Path`:
    - If not `_CURATOR_CONTEXT_ACTIVE`, raise `WriterAccessError("write_entry must be called via Curator")`.
    - `target = root / entry.classification.value / f"{entry.id}.md"`.
    - Acquire `fcntl.flock(LOCK_EX)` on a sidecar `.{id}.lock` file.
    - Replace `entry.last_updated_at = now` (via `dataclasses.replace`).
    - Write via `serialize_entry(entry)` atomically: write to `<target>.tmp` then `os.replace`.
    - Return `target`.
  - `def archive_entry(entry, root, now) -> Path`: move/copy the file to `<root>/archived/<classification>/<id>.md` (still gated by curator context).
  - Run: `uv run pytest tests/corpus/test_writer.py -v`
  - Expected: pass.
- [x] **3.3** Commit. `git add pi_harness/corpus/writer.py tests/corpus/test_writer.py && git commit -m "feat(corpus): gated append-only writer with file lock"`

---

## Task 4 — `reader.py` (prime + expand + classification queries)

- [x] **4.1** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/corpus/test_reader.py`:
  - `test_prime_returns_metadata_only_under_budget`: write 5 entries with known `size_tokens` (e.g. 100 each by padding bodies); `prime(token_budget=250)` returns ≤ 3 entries summing ≤ 250 metadata tokens. Metadata-tier means body is replaced by a 1-line summary slice (first markdown heading or first 80 chars) — assert the returned entries have a `body` shorter than the full body.
  - `test_prime_orders_by_classification_then_recency`: write 2 foundational + 2 tactical + 2 observational, all same size; `prime(budget=large)` returns foundational first, then tactical, then observational — and within each tier, more-recently-updated first.
  - `test_prime_filters_by_classifications_arg`: `prime(budget, classifications=[Classification.TACTICAL])` returns only tactical.
  - `test_expand_loads_full_body`: `expand(entry_id)` returns the full body, not the metadata slice.
  - `test_find_by_classification`: returns every entry with the given classification.
  - `test_find_unreferenced_since_days`: with frozen time, entries whose `last_referenced_run_id is None` AND `last_updated_at <= now - timedelta(days=N)` are returned.
  - `test_find_unreferenced_since_run_uses_trajectory`: parametrize with a fake `query_events` returning a list of `corpus_refs` strings — entries not in that union are returned.
  - Run: `uv run pytest tests/corpus/test_reader.py -v` → fail.
- [x] **4.2** Implement `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/corpus/reader.py`:
  - `class CorpusReader`:
    - `def __init__(self, root: Path, query_events=None)`: `query_events` is an injected callable matching Plan 2's signature; default to a lazy import to avoid hard coupling.
    - `def prime(self, token_budget: int, classifications: list[Classification] | None = None, now: datetime | None = None) -> list[CorpusEntry]`:
      - Gather all entries via filesystem walk of `<root>/<classification>/*.md` (skip `archived/`).
      - Filter by `classifications` if provided.
      - Sort key: `(classification_rank, -recency_decay(now))` where `FOUNDATIONAL=0, TACTICAL=1, OBSERVATIONAL=2`.
      - Build metadata-tier entry by replacing `body` with a one-line summary (first non-empty markdown line, truncated to 80 chars).
      - Accumulate until adding next would exceed `token_budget` (use `count_tokens(metadata_body)`).
    - `def expand(self, entry_id: str) -> CorpusEntry`: walk to find the file by ID, return full `parse_entry`.
    - `def find_by_classification(self, classification: Classification) -> list[CorpusEntry]`.
    - `def find_unreferenced(self, since_run: str | None = None, days: int | None = None, now: datetime | None = None) -> list[CorpusEntry]`:
      - If `days` is set: filter to entries where `(now - last_updated_at).days >= days` AND `last_referenced_run_id is None`.
      - If `since_run` is set: call `self.query_events(run_id=since_run)`, union all `corpus_refs`, return entries not in that set.
      - If both, intersect.
  - Run: `uv run pytest tests/corpus/test_reader.py -v`
  - Expected: pass.
- [x] **4.3** Commit. `git add pi_harness/corpus/reader.py tests/corpus/test_reader.py && git commit -m "feat(corpus): reader with metadata-tier prime, expand, and pruning queries"`

---

## Task 5 — `prune.py` (every trigger from the architecture doc)

This task is the heart of the plan. Each rule gets its own test and its own function. All five triggers from `HARNESS_ARCHITECTURE.md` §2 must be implemented.

- [x] **5.1** Add the `PruneAction` enum and dataclass to a new module `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/corpus/prune.py`:
  - `class PruneActionType(str, Enum)`: `ARCHIVE`, `DEMOTE`, `MERGE`, `DELETE`.
  - `@dataclass class PruneAction`: `action: PruneActionType`, `entry_id: str`, `reason: str`, `target_classification: Classification | None = None` (for DEMOTE), `merge_with: str | None = None` (for MERGE), `merged_counters: dict[str, int] | None = None`.
  - No tests yet — just the enum + dataclass.
- [x] **5.2** Write failing test `test_prune_by_counter_demotes_when_harmful_exceeds_helpful` in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/corpus/test_prune.py`:
  - Tactical entry with `helpful_count=2, harmful_count=5` → returns one `PruneAction(action=DEMOTE, target_classification=OBSERVATIONAL, reason="harmful_count > helpful_count")`.
  - Foundational entry with `helpful_count=2, harmful_count=5` → returns `DEMOTE` to `TACTICAL`.
  - Observational entry with `helpful_count=2, harmful_count=5` → returns `ARCHIVE` (can't demote below observational).
  - Entry with `harmful_count <= helpful_count` → returns `[]`.
- [x] **5.3** Implement `def prune_by_counter(entry: CorpusEntry) -> list[PruneAction]`.
- [x] **5.4** Write failing test `test_prune_by_contradiction_removes_at_3`:
  - `contradiction_count == 2` → `[]`.
  - `contradiction_count == 3` → `[PruneAction(ARCHIVE, reason="contradiction_count >= 3")]`.
  - `contradiction_count == 10` → same archive action.
  - Architecture doc says "remove" — interpret as `ARCHIVE` (Delete is gated to 90-day rule).
- [x] **5.5** Implement `def prune_by_contradiction(entry: CorpusEntry) -> list[PruneAction]`.
- [x] **5.6** Write failing test suite `test_prune_by_staleness`:
  - Use `freeze_time("2026-05-25T00:00:00Z")` throughout.
  - Foundational entry with `last_referenced_run_id=None` and `last_updated_at = now - 365 days` → `[]` (never auto-prune).
  - Tactical entry referenced in 0 of last K=50 runs → `[ARCHIVE]`. Mock `recent_runs: list[str]` argument so test is hermetic. Tactical entry referenced in any of last 50 runs → `[]`.
  - Observational entry, `last_referenced_run_id=None`, age=6 days → `[]`.
  - Observational entry, `last_referenced_run_id=None`, age=8 days → `[ARCHIVE, reason="observational unreferenced 7d"]`.
  - Observational entry already archived, archived_at=now-31 days, `restored=False` → `[DELETE, reason="observational archived 30d unreferenced"]`. (Track archive state via the file living in `<root>/archived/observational/`.)
  - Observational entry archived but `restored=True` → `[]`.
- [x] **5.7** Implement `def prune_by_staleness(entry: CorpusEntry, now: datetime, recent_run_ids: list[str], archive_age_days: int | None = None, restored: bool = False) -> list[PruneAction]`. `archive_age_days` is None for active entries.
- [x] **5.8** Write failing test `test_prune_by_budget_archives_lowest_utility_until_under_cap`:
  - Build a corpus of entries summing to 60k `size_tokens` across all three active classifications. Vary `helpful_count` and `last_updated_at` to produce a spread of utility scores.
  - Call `prune_by_budget(entries, soft_cap=50_000, now=...)`.
  - Assert: returned `PruneAction(ARCHIVE)` list, when removed from the corpus, drops total tokens ≤ 50,000. Assert that the entries archived are the LOWEST `utility_score`. Assert foundational entries are NEVER in the action list (foundational is excluded from token budget cap per architecture doc; only foundational+tactical+observational total counts — but foundational is preserved, so the function archives from tactical/observational only).
  - Edge case: if foundational alone exceeds the cap, the function returns `[]` and emits a structured warning (use `logging.warning`).
- [x] **5.9** Implement `def prune_by_budget(entries: list[CorpusEntry], soft_cap: int, now: datetime) -> list[PruneAction]`.
- [x] **5.10** Write failing test `test_prune_by_dedup_merges_near_duplicates`:
  - Two entries with 90%-overlapping bodies (shared shingles), differing only in a stray sentence. Assert one `PruneAction(MERGE)` is emitted. Assert `merge_with` points to the higher-utility entry's id. Assert `merged_counters` contains summed helpful/harmful/contradiction.
  - Two entries with <50% overlap → no MERGE action.
  - Threshold parameter `similarity_threshold=0.85` defaults exposed.
- [x] **5.11** Implement `def _shingles(text: str, k: int = 5) -> set[int]`: lowercase, split on whitespace, sliding window of k tokens, hash via `hash()` (or `hashlib.blake2b(digest_size=8).intdigest()` for stability across runs). `def _jaccard(a: set[int], b: set[int]) -> float`. `def prune_by_dedup(entries: list[CorpusEntry], similarity_threshold: float = 0.85, now: datetime) -> list[PruneAction]`.
- [x] **5.12** Run: `uv run pytest tests/corpus/test_prune.py -v` — expected: all prune tests pass.
- [x] **5.13** Commit. `git add pi_harness/corpus/prune.py tests/corpus/test_prune.py && git commit -m "feat(corpus): every prune trigger (counter, contradiction, staleness, budget, dedup)"`

---

## Task 6 — `curator.py` (entry point; the only thing that may call writer)

- [x] **6.1** Define candidate types in the same module (or a tiny `candidates.py` if you prefer separation):
  - `@dataclass class CandidateUpdate`: `entry: CorpusEntry`, `kind: Literal["new", "append", "date"]`, `reason: str`.
    - `new` = create entry; `append` = append body to existing; `date` = stamp `last_updated_at`.
  - `@dataclass class CandidatePrune`: `entry_id: str`, `actions: list[PruneAction]`, `reason: str`.
  - `@dataclass class CuratorReport`: `run_id: str`, `updates_applied: int`, `archives: int`, `demotes: int`, `merges: int`, `deletes: int`, `actions: list[PruneAction]`, `git_sha: str`.
- [x] **6.2** Write failing tests in `/Users/pranavnair/Desktop/Personal/mannschaft/tests/corpus/test_curator.py`:
  - `test_curator_initializes_git_repo_on_first_use`: empty `tmp_corpus_root` — first `apply_candidates` call results in `(root / ".git").exists()`.
  - `test_curator_creates_one_commit_per_apply_candidates_call`: with two updates + one prune candidate, assert `git -C <root> log --oneline | wc -l == 1` after first call, `== 2` after second.
  - `test_curator_commit_message_format`: parse `HEAD` commit message → title matches `curator: <run_id> applied <N> updates, <M> archives, <K> deletes` (use a regex). Body lists each action with its reason on its own line.
  - `test_curator_runs_all_prune_rules`: after applying updates, the curator internally calls `prune_by_counter`, `prune_by_contradiction`, `prune_by_staleness`, `prune_by_budget`, `prune_by_dedup` over the resulting corpus and includes their actions in the commit. Use `unittest.mock.patch` to assert each module-level function is invoked once.
  - `test_writer_access_error_outside_curator`: calling `writer.write_entry` from outside `Curator.apply_candidates` raises `WriterAccessError`.
  - `test_60k_corpus_pruned_under_50k`: build 60k-token corpus (acceptance criterion 5), run curator with no updates and no candidate prunes (let `prune_by_budget` do the work). Assert total active tokens ≤ 50_000 post-call.
  - `test_foundational_never_archived` (acceptance 6): a foundational entry with `harmful_count=99, contradiction_count=99, last_referenced_run_id=None` for 365 days → ends up at most demoted to TACTICAL; never archived by the curator.
  - `test_hard_delete_requires_90_day_archive` (acceptance 7): observational entry archived 89 days → DELETE not emitted. 91 days + `restored=False` → DELETE emitted. 91 days + `restored=True` → DELETE not emitted.
  - Run: `uv run pytest tests/corpus/test_curator.py -v` → fail.
- [x] **6.3** Implement `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/corpus/curator.py`:
  - `class Curator`:
    - `def __init__(self, config: "Config")`: takes the Plan 1 config; stores `self.root = config.corpus_root`.
    - `def _ensure_git(self)`: if `(self.root / ".git").exists()` skip; else `git.Repo.init(self.root)` and create a `.gitignore` excluding `*.tmp` and `*.lock`. Make an initial empty commit on a fresh repo.
    - `def apply_candidates(self, run_id: str, updates: list[CandidateUpdate], prunes: list[CandidatePrune], now: datetime | None = None) -> CuratorReport`:
      1. `self._ensure_git()`.
      2. `now = now or datetime.now(timezone.utc)`.
      3. Enter `writer.curator_context()`.
      4. Apply `updates` in order — for `new`, call `writer.write_entry`; for `append`, parse existing, concat body, recompute `size_tokens`, rewrite; for `date`, replace `last_updated_at`, rewrite.
      5. Run prune rules in order on the now-current corpus: counter → contradiction → staleness → budget → dedup. Combine candidate prunes from the input with internally-derived ones.
      6. Resolve actions: `ARCHIVE` → `writer.archive_entry`; `DEMOTE` → `dataclasses.replace(classification=…)` and move file between subdirs (via writer); `MERGE` → write the surviving entry with summed counters, archive the loser; `DELETE` → only if archived ≥90 days AND `restored=False`, then `pathlib.unlink`.
      7. Exit context.
      8. `git -C <root> add -A`; `git commit -m <structured message>`.
      9. Return `CuratorReport` with `git_sha = repo.head.commit.hexsha`.
  - Commit message helper: title `curator: {run_id} applied {len(updates_applied)} updates, {archive_count} archives, {delete_count} deletes`, body: one bullet per action: `- {action.type.value} {entry_id}: {reason}`.
  - Run: `uv run pytest tests/corpus/test_curator.py -v`
  - Expected: pass.
- [x] **6.4** Commit. `git add pi_harness/corpus/curator.py tests/corpus/test_curator.py && git commit -m "feat(corpus): curator entry point with git audit trail and all prune rules"`

---

## Task 7 — Public API + final acceptance sweep

- [x] **7.1** Populate `/Users/pranavnair/Desktop/Personal/mannschaft/pi_harness/corpus/__init__.py`:
  ```python
  from __future__ import annotations
  from pi_harness.corpus.format import (
      Classification,
      CorpusEntry,
      RecordType,
      parse_entry,
      serialize_entry,
      count_tokens,
  )
  from pi_harness.corpus.reader import CorpusReader
  from pi_harness.corpus.writer import WriterAccessError, write_entry, archive_entry, curator_context
  from pi_harness.corpus.counters import (
      update_helpful,
      update_harmful,
      update_contradiction,
      recency_decay,
      utility_score,
  )
  from pi_harness.corpus.prune import (
      PruneAction,
      PruneActionType,
      prune_by_counter,
      prune_by_contradiction,
      prune_by_staleness,
      prune_by_budget,
      prune_by_dedup,
  )
  from pi_harness.corpus.curator import (
      CandidateUpdate,
      CandidatePrune,
      CuratorReport,
      Curator,
  )
  __all__ = [
      "Classification", "CorpusEntry", "RecordType", "parse_entry", "serialize_entry", "count_tokens",
      "CorpusReader",
      "WriterAccessError", "write_entry", "archive_entry", "curator_context",
      "update_helpful", "update_harmful", "update_contradiction", "recency_decay", "utility_score",
      "PruneAction", "PruneActionType",
      "prune_by_counter", "prune_by_contradiction", "prune_by_staleness", "prune_by_budget", "prune_by_dedup",
      "CandidateUpdate", "CandidatePrune", "CuratorReport", "Curator",
  ]
  ```
- [x] **7.2** Run the full test suite for this plan.
  - Run: `uv run pytest tests/corpus -v --tb=short`
  - Expected: every test passes, no warnings other than known ones (deprecation in third-party libs is fine).
- [x] **7.3** Acceptance-criteria walkthrough — explicitly re-run each as a checklist:
  - [x] AC1 Roundtrip all 6 RecordType values: `uv run pytest tests/corpus/test_format.py::test_roundtrip_all_record_types -v`
  - [x] AC2 Each prune trigger has its own test: `uv run pytest tests/corpus/test_prune.py -v` → 5+ tests.
  - [x] AC3 Curator commits to git: `uv run pytest tests/corpus/test_curator.py::test_curator_creates_one_commit_per_apply_candidates_call -v`
  - [x] AC4 `WriterAccessError` outside curator: `uv run pytest tests/corpus/test_writer.py::test_write_entry_outside_curator_raises_writer_access_error -v`
  - [x] AC5 60k → ≤50k: `uv run pytest tests/corpus/test_curator.py::test_60k_corpus_pruned_under_50k -v`
  - [x] AC6 Foundational never auto-archived: `uv run pytest tests/corpus/test_curator.py::test_foundational_never_archived -v`
  - [x] AC7 Hard delete only after 90-day archive + not restored: `uv run pytest tests/corpus/test_curator.py::test_hard_delete_requires_90_day_archive -v`
- [x] **7.4** Commit. `git add pi_harness/corpus/__init__.py && git commit -m "feat(corpus): public API surface + acceptance sweep"`

---

## Unresolved decisions

None — the architecture doc and scope spec lock every value. The following defaults are explicit and tunable via constructor kwargs (not magic numbers):

- Recency half-life: 14 days (counters.py)
- Tactical staleness threshold K: 50 runs (prune.py `prune_by_staleness`)
- Observational unreferenced archive: 7 days; hard-delete: 30 days
- Dedup similarity threshold: 0.85 Jaccard over 5-shingles
- Token budget soft cap: 50,000 (curator caller may override per-pass)
- 90-day archive grace before hard delete

---

## Cross-plan consumer notes (for Plans 4, 6, 8)

- Plan 4 (improve-agent) creates `CandidateUpdate` and `CandidatePrune` instances and hands them to `Curator(config).apply_candidates(run_id, updates, prunes)`. It does NOT touch `writer.py` directly.
- Plan 6 (agent runtime) instantiates `CorpusReader(config.corpus_root)` and calls `reader.prime(token_budget=config.prime_token_budget)` at the start of each agent turn. The returned `CorpusEntry` list goes into the agent's system prompt under a `<corpus_primer>` section. Each step then logs `corpus_refs=[e.id for e in primed]` via Plan 2's trajectory store.
- Plan 8 (dashboard) reads the corpus filesystem via `CorpusReader.find_by_classification` and `find_unreferenced` to render the corpus health view; it also surfaces `last archive commit` from `git log` on the corpus repo.
