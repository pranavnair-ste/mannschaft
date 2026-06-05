"""Tests for ``pi_harness.corpus.prune`` — all five pruning triggers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import logging

import pytest
from freezegun import freeze_time


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


# ---------------------------------------------------------------------------
# Counter-based pruning
# ---------------------------------------------------------------------------


def test_prune_by_counter_demotes_tactical_when_harmful_exceeds_helpful() -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_counter,
    )

    entry = _make_entry(
        classification=Classification.TACTICAL,
        helpful_count=2,
        harmful_count=5,
    )
    actions = prune_by_counter(entry)
    assert len(actions) == 1
    a = actions[0]
    assert a.action == PruneActionType.DEMOTE
    assert a.target_classification == Classification.OBSERVATIONAL
    assert "harmful" in a.reason.lower()
    assert a.entry_id == entry.id


def test_prune_by_counter_demotes_foundational_to_tactical() -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_counter,
    )

    entry = _make_entry(
        classification=Classification.FOUNDATIONAL,
        helpful_count=2,
        harmful_count=5,
    )
    actions = prune_by_counter(entry)
    assert len(actions) == 1
    a = actions[0]
    assert a.action == PruneActionType.DEMOTE
    assert a.target_classification == Classification.TACTICAL


def test_prune_by_counter_archives_observational() -> None:
    """Observational can't demote further — archive instead."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_counter,
    )

    entry = _make_entry(
        classification=Classification.OBSERVATIONAL,
        helpful_count=2,
        harmful_count=5,
    )
    actions = prune_by_counter(entry)
    assert len(actions) == 1
    assert actions[0].action == PruneActionType.ARCHIVE


def test_prune_by_counter_noop_when_helpful_meets_or_exceeds_harmful() -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import prune_by_counter

    entry = _make_entry(
        classification=Classification.TACTICAL,
        helpful_count=5,
        harmful_count=5,
    )
    assert prune_by_counter(entry) == []

    entry = _make_entry(
        classification=Classification.TACTICAL,
        helpful_count=10,
        harmful_count=3,
    )
    assert prune_by_counter(entry) == []


# ---------------------------------------------------------------------------
# Contradiction-based pruning
# ---------------------------------------------------------------------------


def test_prune_by_contradiction_noop_below_3() -> None:
    from pi_harness.corpus.prune import prune_by_contradiction

    entry = _make_entry(contradiction_count=2)
    assert prune_by_contradiction(entry) == []


def test_prune_by_contradiction_archives_at_3() -> None:
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_contradiction,
    )

    entry = _make_entry(contradiction_count=3)
    actions = prune_by_contradiction(entry)
    assert len(actions) == 1
    a = actions[0]
    assert a.action == PruneActionType.ARCHIVE
    assert "contradiction" in a.reason.lower()


def test_prune_by_contradiction_archives_at_higher_counts() -> None:
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_contradiction,
    )

    entry = _make_entry(contradiction_count=10)
    actions = prune_by_contradiction(entry)
    assert len(actions) == 1
    assert actions[0].action == PruneActionType.ARCHIVE


# ---------------------------------------------------------------------------
# Staleness-based pruning
# ---------------------------------------------------------------------------


def test_prune_by_staleness_foundational_never_pruned() -> None:
    """Foundational entries never auto-prune, regardless of age."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import prune_by_staleness

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(
            classification=Classification.FOUNDATIONAL,
            last_updated_at=now - timedelta(days=365),
            last_referenced_run_id=None,
        )
        assert prune_by_staleness(entry, now, recent_run_ids=[]) == []


def test_prune_by_staleness_tactical_unreferenced_in_recent_runs() -> None:
    """Tactical entry referenced in 0 of last K=50 runs → ARCHIVE."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_staleness,
    )

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(
            classification=Classification.TACTICAL,
            last_updated_at=now - timedelta(days=30),
            last_referenced_run_id="run-OLD",
        )
        recent_runs = [f"run-{i}" for i in range(50)]
        actions = prune_by_staleness(entry, now, recent_run_ids=recent_runs)
        assert len(actions) == 1
        assert actions[0].action == PruneActionType.ARCHIVE


def test_prune_by_staleness_tactical_referenced_in_recent_runs_noop() -> None:
    """Tactical entry referenced within the recent window → no action."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import prune_by_staleness

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(
            classification=Classification.TACTICAL,
            last_updated_at=now - timedelta(days=30),
            last_referenced_run_id="run-7",
        )
        recent_runs = [f"run-{i}" for i in range(50)]
        assert prune_by_staleness(entry, now, recent_run_ids=recent_runs) == []


def test_prune_by_staleness_observational_under_7_days_noop() -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import prune_by_staleness

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(
            classification=Classification.OBSERVATIONAL,
            last_updated_at=now - timedelta(days=6),
            last_referenced_run_id=None,
        )
        assert prune_by_staleness(entry, now, recent_run_ids=[]) == []


def test_prune_by_staleness_observational_over_7_days_archives() -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_staleness,
    )

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(
            classification=Classification.OBSERVATIONAL,
            last_updated_at=now - timedelta(days=8),
            last_referenced_run_id=None,
        )
        actions = prune_by_staleness(entry, now, recent_run_ids=[])
        assert len(actions) == 1
        a = actions[0]
        assert a.action == PruneActionType.ARCHIVE
        assert "7" in a.reason or "observational" in a.reason.lower()


def test_prune_by_staleness_observational_archived_31_days_deletes() -> None:
    """Observational archived ≥30 days + not restored → DELETE."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_staleness,
    )

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(
            classification=Classification.OBSERVATIONAL,
            last_updated_at=now - timedelta(days=31),
            last_referenced_run_id=None,
        )
        actions = prune_by_staleness(
            entry,
            now,
            recent_run_ids=[],
            archive_age_days=31,
            restored=False,
        )
        kinds = [a.action for a in actions]
        assert PruneActionType.DELETE in kinds


def test_prune_by_staleness_observational_archived_restored_no_delete() -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_staleness,
    )

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(
            classification=Classification.OBSERVATIONAL,
            last_updated_at=now - timedelta(days=31),
            last_referenced_run_id=None,
        )
        actions = prune_by_staleness(
            entry,
            now,
            recent_run_ids=[],
            archive_age_days=31,
            restored=True,
        )
        kinds = [a.action for a in actions]
        assert PruneActionType.DELETE not in kinds


# ---------------------------------------------------------------------------
# Token-budget-based pruning
# ---------------------------------------------------------------------------


def test_prune_by_budget_archives_lowest_utility_until_under_cap() -> None:
    """Archive lowest-utility tactical/observational entries until tokens ≤ cap."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_budget,
    )

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        # Build a mix of foundational (5k each x2 = 10k), tactical (5k each x4 = 20k),
        # observational (5k each x6 = 30k) — total 60k.
        entries = []
        for i in range(2):
            entries.append(
                _make_entry(
                    classification=Classification.FOUNDATIONAL,
                    body=f"foundational {i}",
                    helpful_count=10,  # high utility
                    last_updated_at=now,
                    size_tokens=5_000,
                )
            )
        for i in range(4):
            entries.append(
                _make_entry(
                    classification=Classification.TACTICAL,
                    body=f"tactical {i}",
                    helpful_count=5,  # medium utility
                    last_updated_at=now,
                    size_tokens=5_000,
                )
            )
        for i in range(6):
            entries.append(
                _make_entry(
                    classification=Classification.OBSERVATIONAL,
                    body=f"observational {i}",
                    helpful_count=1,  # low utility
                    last_updated_at=now,
                    size_tokens=5_000,
                )
            )
        total_before = sum(e.size_tokens for e in entries)
        assert total_before == 60_000

        actions = prune_by_budget(entries, soft_cap=50_000, now=now)
        archived_ids = {a.entry_id for a in actions if a.action == PruneActionType.ARCHIVE}
        # No foundational entries archived
        for e in entries:
            if e.classification == Classification.FOUNDATIONAL:
                assert e.id not in archived_ids
        # Total post-archive tokens ≤ cap
        remaining = sum(e.size_tokens for e in entries if e.id not in archived_ids)
        assert remaining <= 50_000

        # Among archived, all should be observational (lowest utility) first
        archived_entries = [e for e in entries if e.id in archived_ids]
        assert all(
            e.classification == Classification.OBSERVATIONAL for e in archived_entries
        )


def test_prune_by_budget_warns_when_foundational_alone_exceeds_cap(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If foundational ≥ cap, return [] and emit a warning."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import prune_by_budget

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entries = [
            _make_entry(
                classification=Classification.FOUNDATIONAL,
                body="huge foundational",
                helpful_count=10,
                last_updated_at=now,
                size_tokens=60_000,
            )
        ]
        with caplog.at_level(logging.WARNING):
            actions = prune_by_budget(entries, soft_cap=50_000, now=now)
        assert actions == []
        assert any(
            "foundational" in rec.message.lower() for rec in caplog.records
        )


def test_prune_by_budget_under_cap_noop() -> None:
    """If total tokens already under cap, no actions emitted."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import prune_by_budget

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entries = [
            _make_entry(
                classification=Classification.TACTICAL,
                body="small",
                helpful_count=5,
                last_updated_at=now,
                size_tokens=100,
            ),
            _make_entry(
                classification=Classification.OBSERVATIONAL,
                body="also small",
                helpful_count=2,
                last_updated_at=now,
                size_tokens=100,
            ),
        ]
        actions = prune_by_budget(entries, soft_cap=10_000, now=now)
        assert actions == []


# ---------------------------------------------------------------------------
# Semantic dedup
# ---------------------------------------------------------------------------


def test_prune_by_dedup_merges_near_duplicates() -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import (
        PruneActionType,
        prune_by_dedup,
    )

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        # Two entries with ~90% overlapping content — only a single short
        # trailing clause differs. With 5-shingles, ~90% overlap → jaccard
        # above the default 0.85 threshold.
        common = (
            "we always use absolute paths in pi_harness tests because relative "
            "paths break when the worker changes cwd between bash calls and the "
            "harness reset trips up coverage collectors and pytest discovery alike "
            "and the curator must always run inside the writer gate and the "
            "trajectory store is the substrate for every improvement loop in v1 "
            "and the dashboard renders runs as cards in a kanban-style board"
        )
        a_body = common + " plus a stray sentence."
        b_body = common + " plus a stray clause."
        a = _make_entry(
            classification=Classification.TACTICAL,
            body=a_body,
            helpful_count=10,  # higher utility — should survive
            harmful_count=1,
            contradiction_count=0,
            last_updated_at=now,
        )
        b = _make_entry(
            classification=Classification.TACTICAL,
            body=b_body,
            helpful_count=2,
            harmful_count=0,
            contradiction_count=1,
            last_updated_at=now,
        )

        actions = prune_by_dedup([a, b], now=now)
        merges = [act for act in actions if act.action == PruneActionType.MERGE]
        assert len(merges) == 1
        merge = merges[0]
        # loser is the lower-utility entry, target merge_with is the higher
        assert merge.entry_id == b.id
        assert merge.merge_with == a.id
        # Counters summed
        assert merge.merged_counters is not None
        assert merge.merged_counters["helpful_count"] == 12
        assert merge.merged_counters["harmful_count"] == 1
        assert merge.merged_counters["contradiction_count"] == 1


def test_prune_by_dedup_no_action_for_distinct_entries() -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import prune_by_dedup

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        a = _make_entry(
            classification=Classification.TACTICAL,
            body="completely unique sentence about apples and orchards",
            helpful_count=5,
            last_updated_at=now,
        )
        b = _make_entry(
            classification=Classification.TACTICAL,
            body="totally different topic involving spaceships and engines",
            helpful_count=5,
            last_updated_at=now,
        )
        assert prune_by_dedup([a, b], now=now) == []


def test_prune_by_dedup_never_merges_empty_or_short_bodies() -> None:
    """Empty/whitespace/near-empty bodies are non-comparable and must never be
    auto-merged (which would archive one of them) — they previously scored
    jaccard=1.0 (audit #34)."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import prune_by_dedup

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        empty1 = _make_entry(classification=Classification.TACTICAL, body="   ", last_updated_at=now)
        empty2 = _make_entry(classification=Classification.TACTICAL, body="", last_updated_at=now)
        short1 = _make_entry(classification=Classification.TACTICAL, body="two words", last_updated_at=now)
        short2 = _make_entry(classification=Classification.TACTICAL, body="two words", last_updated_at=now)
        assert prune_by_dedup([empty1, empty2, short1, short2], now=now) == []


def test_prune_by_staleness_keeps_entry_referenced_by_newest_run() -> None:
    """recent_run_ids is newest-first; an entry referenced by the NEWEST run
    must stay, while one referenced only by a run outside the window archives
    (audit #11 — the window was inverted, archiving live knowledge)."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.prune import PruneActionType, prune_by_staleness

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    runs_desc = ["run-new", "run-mid", "run-old1", "run-old2"]  # newest-first

    fresh = _make_entry(
        classification=Classification.TACTICAL,
        last_referenced_run_id="run-new",
        last_updated_at=now,
    )
    assert prune_by_staleness(fresh, now, recent_run_ids=runs_desc, tactical_recent_k=2) == []

    stale = _make_entry(
        classification=Classification.TACTICAL,
        last_referenced_run_id="run-old2",  # outside the 2-run window
        last_updated_at=now,
    )
    actions = prune_by_staleness(stale, now, recent_run_ids=runs_desc, tactical_recent_k=2)
    assert any(a.action == PruneActionType.ARCHIVE for a in actions)
