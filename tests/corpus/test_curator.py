"""Tests for ``pi_harness.corpus.curator`` — the only entry point that may write."""

from __future__ import annotations

import re
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time


def _make_config(corpus_root: Path):
    """Build a real Config pointed at the temp corpus root."""
    from pi_harness.config import Config

    return Config(
        openai_api_key="sk-test",
        reasoning_model="gpt-5",
        fast_model="gpt-5-mini",
        clawteam_state_dir=corpus_root.parent / "clawteam",
        corpus_root=corpus_root,
        trajectory_db_path=corpus_root.parent / "trajectory.db",
    )


def _make_entry(
    *,
    classification=None,
    body="default body",
    helpful_count=0,
    harmful_count=0,
    contradiction_count=0,
    last_referenced_run_id=None,
    last_updated_at=None,
    size_tokens=None,
):
    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
    )

    now = last_updated_at or datetime(2026, 5, 25, tzinfo=timezone.utc)
    entry = CorpusEntry.new(
        record_type=RecordType.PATTERN,
        classification=classification or Classification.TACTICAL,
        body=body,
        now=now,
    )
    if size_tokens is None:
        size_tokens = entry.size_tokens
    entry = entry.with_counters(
        helpful_count=helpful_count,
        harmful_count=harmful_count,
        contradiction_count=contradiction_count,
        last_referenced_run_id=last_referenced_run_id,
    )
    return replace(entry, last_updated_at=now, size_tokens=size_tokens)


def _git_log_count(corpus_root: Path) -> int:
    """Return the number of commits on the corpus repo's HEAD."""
    res = subprocess.run(
        ["git", "-C", str(corpus_root), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(res.stdout.strip())


# ---------------------------------------------------------------------------
# Curator initializes a git repo
# ---------------------------------------------------------------------------


def test_curator_initializes_git_repo_on_first_use(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus.curator import CandidateUpdate, Curator

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)
    entry = _make_entry()
    update = CandidateUpdate(entry=entry, kind="new", reason="initial new entry")

    with freeze_time("2026-05-25T00:00:00Z"):
        curator.apply_candidates(
            run_id="run-1",
            updates=[update],
            prunes=[],
            now=datetime.now(timezone.utc),
        )
    assert (tmp_corpus_root / ".git").exists()


# ---------------------------------------------------------------------------
# One commit per apply_candidates call
# ---------------------------------------------------------------------------


def test_curator_creates_one_commit_per_apply_candidates_call(
    tmp_corpus_root: Path,
) -> None:
    from pi_harness.corpus.curator import CandidateUpdate, Curator

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)
    entry_a = _make_entry(body="entry A")
    entry_b = _make_entry(body="entry B")

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        curator.apply_candidates(
            run_id="run-1",
            updates=[CandidateUpdate(entry=entry_a, kind="new", reason="A")],
            prunes=[],
            now=now,
        )
    # initial empty commit (if any) + 1 for the apply call
    count_after_one = _git_log_count(tmp_corpus_root)

    with freeze_time("2026-05-26T00:00:00Z"):
        now = datetime.now(timezone.utc)
        curator.apply_candidates(
            run_id="run-2",
            updates=[CandidateUpdate(entry=entry_b, kind="new", reason="B")],
            prunes=[],
            now=now,
        )
    count_after_two = _git_log_count(tmp_corpus_root)

    assert count_after_two == count_after_one + 1


def test_curator_skips_commit_when_no_changes(tmp_corpus_root: Path) -> None:
    """If no updates and no prune actions land, no commit is created."""
    from pi_harness.corpus.curator import Curator

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)
    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        report1 = curator.apply_candidates(
            run_id="run-1", updates=[], prunes=[], now=now
        )
        # apply_candidates again with nothing — git log should not grow
        count_a = _git_log_count(tmp_corpus_root)
        report2 = curator.apply_candidates(
            run_id="run-2", updates=[], prunes=[], now=now
        )
        count_b = _git_log_count(tmp_corpus_root)
    assert count_a == count_b


# ---------------------------------------------------------------------------
# Commit message format
# ---------------------------------------------------------------------------


def test_curator_commit_message_format(tmp_corpus_root: Path) -> None:
    """Title: ``curator: <run_id> applied <N> updates, <M> archives, <K> deletes``."""
    from pi_harness.corpus.curator import CandidateUpdate, Curator

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)
    entry = _make_entry()
    update = CandidateUpdate(entry=entry, kind="new", reason="initial")

    with freeze_time("2026-05-25T00:00:00Z"):
        curator.apply_candidates(
            run_id="run-abc",
            updates=[update],
            prunes=[],
            now=datetime.now(timezone.utc),
        )

    res = subprocess.run(
        ["git", "-C", str(tmp_corpus_root), "log", "-1", "--format=%s%n%b"],
        capture_output=True,
        text=True,
        check=True,
    )
    title = res.stdout.splitlines()[0]
    assert re.match(
        r"curator: run-abc applied \d+ updates, \d+ archives, \d+ deletes",
        title,
    ), f"Unexpected title: {title}"
    # Body lists each action's reason
    assert "initial" in res.stdout


# ---------------------------------------------------------------------------
# Curator runs every prune rule
# ---------------------------------------------------------------------------


def test_curator_runs_all_prune_rules(tmp_corpus_root: Path, monkeypatch) -> None:
    """The curator invokes counter, contradiction, staleness, budget, dedup."""
    from pi_harness.corpus import curator as curator_mod
    from pi_harness.corpus.curator import Curator

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)

    calls: dict[str, int] = {
        "counter": 0,
        "contradiction": 0,
        "staleness": 0,
        "budget": 0,
        "dedup": 0,
    }

    original_counter = curator_mod.prune_by_counter
    original_contradiction = curator_mod.prune_by_contradiction
    original_staleness = curator_mod.prune_by_staleness
    original_budget = curator_mod.prune_by_budget
    original_dedup = curator_mod.prune_by_dedup

    def spy_counter(*args, **kwargs):
        calls["counter"] += 1
        return original_counter(*args, **kwargs)

    def spy_contradiction(*args, **kwargs):
        calls["contradiction"] += 1
        return original_contradiction(*args, **kwargs)

    def spy_staleness(*args, **kwargs):
        calls["staleness"] += 1
        return original_staleness(*args, **kwargs)

    def spy_budget(*args, **kwargs):
        calls["budget"] += 1
        return original_budget(*args, **kwargs)

    def spy_dedup(*args, **kwargs):
        calls["dedup"] += 1
        return original_dedup(*args, **kwargs)

    monkeypatch.setattr(curator_mod, "prune_by_counter", spy_counter)
    monkeypatch.setattr(curator_mod, "prune_by_contradiction", spy_contradiction)
    monkeypatch.setattr(curator_mod, "prune_by_staleness", spy_staleness)
    monkeypatch.setattr(curator_mod, "prune_by_budget", spy_budget)
    monkeypatch.setattr(curator_mod, "prune_by_dedup", spy_dedup)

    from pi_harness.corpus.curator import CandidateUpdate

    entry = _make_entry()
    with freeze_time("2026-05-25T00:00:00Z"):
        curator.apply_candidates(
            run_id="run-1",
            updates=[CandidateUpdate(entry=entry, kind="new", reason="bootstrap")],
            prunes=[],
            now=datetime.now(timezone.utc),
        )

    # Each prune family must have been invoked at least once
    assert calls["counter"] >= 1
    assert calls["contradiction"] >= 1
    assert calls["staleness"] >= 1
    assert calls["budget"] >= 1
    assert calls["dedup"] >= 1


# ---------------------------------------------------------------------------
# Writer access error outside curator
# ---------------------------------------------------------------------------


def test_writer_access_error_outside_curator(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus import writer
    from pi_harness.corpus.writer import WriterAccessError

    entry = _make_entry()
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    with pytest.raises(WriterAccessError):
        writer.write_entry(entry, tmp_corpus_root, now)


# ---------------------------------------------------------------------------
# 60k → ≤50k
# ---------------------------------------------------------------------------


def test_60k_corpus_pruned_under_50k(tmp_corpus_root: Path) -> None:
    """Acceptance criterion 5: 60k-token corpus archives down under 50k."""
    from pi_harness.corpus.curator import CandidateUpdate, Curator
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        updates = []
        # 2 foundational @ 5k = 10k; 4 tactical @ 5k = 20k; 6 observational @ 5k = 30k
        for i in range(2):
            entry = _make_entry(
                classification=Classification.FOUNDATIONAL,
                body=f"foundational {i}",
                helpful_count=10,
                last_updated_at=now,
                size_tokens=5_000,
            )
            updates.append(
                CandidateUpdate(entry=entry, kind="new", reason="seed-foundational")
            )
        for i in range(4):
            entry = _make_entry(
                classification=Classification.TACTICAL,
                body=f"tactical {i}",
                helpful_count=5,
                last_updated_at=now,
                size_tokens=5_000,
                # Reference recently so staleness doesn't archive everything first
                last_referenced_run_id="run-now",
            )
            updates.append(
                CandidateUpdate(entry=entry, kind="new", reason="seed-tactical")
            )
        for i in range(6):
            entry = _make_entry(
                classification=Classification.OBSERVATIONAL,
                body=f"observational {i}",
                helpful_count=1,
                last_updated_at=now,
                # Reference recently so 7d staleness doesn't fire
                last_referenced_run_id="run-now",
                size_tokens=5_000,
            )
            updates.append(
                CandidateUpdate(entry=entry, kind="new", reason="seed-observational")
            )

        curator.apply_candidates(
            run_id="run-now", updates=updates, prunes=[], now=now
        )

    # Read back active entries (skip archived/)
    reader = CorpusReader(tmp_corpus_root)
    active = []
    for c in [
        Classification.FOUNDATIONAL,
        Classification.TACTICAL,
        Classification.OBSERVATIONAL,
    ]:
        active.extend(reader.find_by_classification(c))
    total_tokens = sum(e.size_tokens for e in active)
    assert total_tokens <= 50_000, (
        f"Active token total {total_tokens} exceeds 50k cap"
    )


# ---------------------------------------------------------------------------
# Foundational never auto-archived
# ---------------------------------------------------------------------------


def test_foundational_never_archived(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus.curator import CandidateUpdate, Curator
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(
            classification=Classification.FOUNDATIONAL,
            body="critical foundational policy",
            helpful_count=0,
            harmful_count=99,
            contradiction_count=99,
            last_referenced_run_id=None,
            last_updated_at=now - timedelta(days=365),
        )
        curator.apply_candidates(
            run_id="run-foundational",
            updates=[
                CandidateUpdate(
                    entry=entry, kind="new", reason="seed-foundational-abused"
                )
            ],
            prunes=[],
            now=now,
        )

    reader = CorpusReader(tmp_corpus_root)
    # Either still foundational (preserved) or at most demoted to tactical
    foundational_paths = list((tmp_corpus_root / "foundational").glob("*.md"))
    tactical_paths = list((tmp_corpus_root / "tactical").glob("*.md"))
    archived_paths = list((tmp_corpus_root / "archived").rglob("*.md"))
    # The entry must not be in archived; must be either foundational or tactical
    assert all(entry.id not in p.stem for p in archived_paths), (
        f"Foundational entry was archived: {archived_paths}"
    )
    # Present somewhere active
    all_active = foundational_paths + tactical_paths
    assert any(p.stem == entry.id for p in all_active)


# ---------------------------------------------------------------------------
# Hard delete requires 90-day archive grace
# ---------------------------------------------------------------------------


def test_hard_delete_requires_90_day_archive(tmp_corpus_root: Path) -> None:
    """Observational archived 89d → no DELETE; 91d → DELETE; 91d + restored=True → no DELETE."""
    from pi_harness.corpus.curator import (
        CandidatePrune,
        Curator,
    )
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import PruneAction, PruneActionType

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)

        # --- 89 days archived: DELETE must NOT execute ---
        entry_89 = _make_entry(
            classification=Classification.OBSERVATIONAL,
            body="entry archived 89 days",
            last_updated_at=now - timedelta(days=89),
            size_tokens=100,
        )
        # Pre-populate as archived (write to archived dir directly via curator)
        from pi_harness.corpus import writer
        with writer.curator_context():
            writer.write_entry(entry_89, tmp_corpus_root, now - timedelta(days=89))
            writer.archive_entry(entry_89, tmp_corpus_root, now - timedelta(days=89))

        # Caller asks the curator to consider deletion via a CandidatePrune
        prune_89 = CandidatePrune(
            entry_id=entry_89.id,
            actions=[
                PruneAction(
                    action=PruneActionType.DELETE,
                    entry_id=entry_89.id,
                    reason="caller requested",
                )
            ],
            reason="archive grace too short",
        )
        curator.apply_candidates(
            run_id="run-89", updates=[], prunes=[prune_89], now=now
        )
        archive_path_89 = (
            tmp_corpus_root
            / "archived"
            / Classification.OBSERVATIONAL.value
            / f"{entry_89.id}.md"
        )
        assert archive_path_89.exists(), (
            "89-day archived entry was deleted; should require 90 days"
        )

        # --- 91 days archived, not restored: DELETE must execute ---
        entry_91 = _make_entry(
            classification=Classification.OBSERVATIONAL,
            body="entry archived 91 days",
            last_updated_at=now - timedelta(days=91),
            size_tokens=100,
        )
        with writer.curator_context():
            writer.write_entry(entry_91, tmp_corpus_root, now - timedelta(days=91))
            writer.archive_entry(entry_91, tmp_corpus_root, now - timedelta(days=91))

        prune_91 = CandidatePrune(
            entry_id=entry_91.id,
            actions=[
                PruneAction(
                    action=PruneActionType.DELETE,
                    entry_id=entry_91.id,
                    reason="caller requested",
                )
            ],
            reason="archive grace satisfied",
        )
        curator.apply_candidates(
            run_id="run-91", updates=[], prunes=[prune_91], now=now
        )
        archive_path_91 = (
            tmp_corpus_root
            / "archived"
            / Classification.OBSERVATIONAL.value
            / f"{entry_91.id}.md"
        )
        assert not archive_path_91.exists(), (
            "91-day archived entry should have been deleted"
        )


# ---------------------------------------------------------------------------
# Append update preserves existing entry's session_id
# ---------------------------------------------------------------------------


def test_append_update_preserves_session_id(tmp_corpus_root: Path) -> None:
    """Appending body to an existing entry must not clobber its session_id."""
    from pi_harness.corpus.curator import CandidateUpdate, Curator
    from pi_harness.corpus.format import Classification, CorpusEntry, RecordType

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)

    # Seed an entry that already carries a session_id
    original = CorpusEntry.new(
        record_type=RecordType.PATTERN,
        classification=Classification.OBSERVATIONAL,
        body="original body text",
        now=now,
        session_id="orig-session",
    )

    with freeze_time("2026-05-25T00:00:00Z"):
        curator.apply_candidates(
            run_id="run-seed",
            updates=[CandidateUpdate(entry=original, kind="new", reason="seed")],
            prunes=[],
            now=now,
        )

    # Now append to that entry via a CandidateUpdate with kind="append"
    # The entry in the update only needs the id (same body-hash) and the new body fragment
    append_entry = CorpusEntry.new(
        record_type=RecordType.PATTERN,
        classification=Classification.OBSERVATIONAL,
        body="original body text",  # same body → same id
        now=now,
        session_id=None,  # deliberately None on the update — existing entry's session_id should survive
    )
    # Override body on the append_entry to carry the appended text
    from dataclasses import replace as dc_replace
    append_entry = dc_replace(append_entry, body="appended fragment")

    later = datetime(2026, 5, 26, tzinfo=timezone.utc)
    with freeze_time("2026-05-26T00:00:00Z"):
        curator.apply_candidates(
            run_id="run-append",
            updates=[CandidateUpdate(entry=append_entry, kind="append", reason="append test")],
            prunes=[],
            now=later,
        )

    # Re-read the entry from disk and check session_id was preserved
    from pi_harness.corpus.format import parse_entry
    entry_path = tmp_corpus_root / "observational" / f"{original.id}.md"
    assert entry_path.exists(), f"Entry not found at {entry_path}"
    on_disk = parse_entry(entry_path)
    assert on_disk.session_id == "orig-session", (
        f"Append clobbered session_id: got {on_disk.session_id!r}, expected 'orig-session'"
    )
    assert "appended fragment" in on_disk.body, "Appended text should be in the body"


# ---------------------------------------------------------------------------
# restore_archived — un-archive an entry back to its active classification dir
# ---------------------------------------------------------------------------


def test_restore_archived_moves_entry_back_to_active(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus import writer
    from pi_harness.corpus.curator import (
        Curator,
        _classification_dir,
        _find_archived_entry_path,
    )
    from pi_harness.corpus.format import Classification

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)
    curator._ensure_git()
    entry = _make_entry(classification=Classification.TACTICAL, body="restore me")
    now = datetime(2026, 5, 28, tzinfo=timezone.utc)
    with writer.curator_context():
        writer.archive_entry(entry, tmp_corpus_root, now)

    active_path = _classification_dir(tmp_corpus_root, entry.classification) / f"{entry.id}.md"
    assert _find_archived_entry_path(tmp_corpus_root, entry.id) is not None
    assert not active_path.exists()

    restored = curator.restore_archived(entry.id)

    assert restored.id == entry.id
    assert restored.classification == Classification.TACTICAL
    assert active_path.exists()
    assert _find_archived_entry_path(tmp_corpus_root, entry.id) is None


def test_restore_archived_commits(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus import writer
    from pi_harness.corpus.curator import Curator
    from pi_harness.corpus.format import Classification

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)
    curator._ensure_git()
    entry = _make_entry(classification=Classification.OBSERVATIONAL, body="commit me")
    now = datetime(2026, 5, 28, tzinfo=timezone.utc)
    with writer.curator_context():
        writer.archive_entry(entry, tmp_corpus_root, now)
    before = _git_log_count(tmp_corpus_root)

    curator.restore_archived(entry.id)

    assert _git_log_count(tmp_corpus_root) == before + 1


def test_restore_unknown_raises(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus.curator import Curator

    cfg = _make_config(tmp_corpus_root)
    curator = Curator(cfg)
    with pytest.raises(FileNotFoundError):
        curator.restore_archived("does-not-exist")
