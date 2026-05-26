"""Tests for ``pi_harness.corpus.counters`` — recency decay, utility, counter mutations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time


def _make_entry(**overrides):
    """Helper: build a CorpusEntry with sensible defaults."""
    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
    )

    defaults = dict(
        record_type=RecordType.PATTERN,
        classification=Classification.TACTICAL,
        body="example body",
        now=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return CorpusEntry.new(**defaults)


# ---------------------------------------------------------------------------
# Recency decay
# ---------------------------------------------------------------------------


def test_recency_decay_half_life_14_days() -> None:
    """An entry updated 14 days ago has a recency decay of 0.5."""
    from pi_harness.corpus.counters import recency_decay

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(now=now - timedelta(days=14))
        # The entry's own ``last_updated_at`` is ``now-14d``
        assert recency_decay(entry, now) == pytest.approx(0.5, rel=1e-3)


def test_recency_decay_today_is_one() -> None:
    """An entry just updated at ``now`` has recency decay 1.0."""
    from pi_harness.corpus.counters import recency_decay

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(now=now)
        assert recency_decay(entry, now) == pytest.approx(1.0, rel=1e-9)


def test_recency_decay_28_days_is_quarter() -> None:
    """Two half-lives = quarter."""
    from pi_harness.corpus.counters import recency_decay

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(now=now - timedelta(days=28))
        assert recency_decay(entry, now) == pytest.approx(0.25, rel=1e-3)


def test_recency_decay_custom_half_life() -> None:
    """``half_life_days`` argument is honored."""
    from pi_harness.corpus.counters import recency_decay

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(now=now - timedelta(days=7))
        assert recency_decay(entry, now, half_life_days=7.0) == pytest.approx(0.5, rel=1e-3)


# ---------------------------------------------------------------------------
# Utility score
# ---------------------------------------------------------------------------


def test_utility_score_doubles_when_helpful_count_doubles() -> None:
    """Doubling helpful_count doubles the utility score."""
    from pi_harness.corpus.counters import utility_score

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        e1 = _make_entry(now=now).with_counters(helpful_count=2)
        e2 = _make_entry(now=now).with_counters(helpful_count=4)
        s1 = utility_score(e1, now)
        s2 = utility_score(e2, now)
        assert s2 == pytest.approx(2 * s1, rel=1e-9)


def test_utility_score_handles_zero_size_tokens() -> None:
    """``size_tokens=0`` must not divide-by-zero (we use ``max(1, size_tokens)``)."""
    from dataclasses import replace

    from pi_harness.corpus.counters import utility_score

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(now=now).with_counters(helpful_count=3)
        entry = replace(entry, size_tokens=0)
        # No exception, sensible value
        score = utility_score(entry, now)
        assert score == pytest.approx(3.0, rel=1e-9)


def test_utility_score_formula_is_explicit() -> None:
    """Sanity-check the formula: helpful / max(size,1) * recency_decay."""
    from dataclasses import replace

    from pi_harness.corpus.counters import recency_decay, utility_score

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(now=now - timedelta(days=14)).with_counters(helpful_count=10)
        entry = replace(entry, size_tokens=100)
        expected = (10 / 100) * recency_decay(entry, now)
        assert utility_score(entry, now) == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# Counter mutations (pure data, no disk writes)
# ---------------------------------------------------------------------------


def test_update_helpful_increments_and_stamps_last_updated_at() -> None:
    from pi_harness.corpus.counters import update_helpful

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        # Build an entry that was last updated yesterday, then bump.
        original = _make_entry(now=now - timedelta(days=1))
        updated = update_helpful(original, now)
        assert updated.helpful_count == original.helpful_count + 1
        assert updated.last_updated_at == now
        # Other counters untouched.
        assert updated.harmful_count == original.harmful_count
        assert updated.contradiction_count == original.contradiction_count
        # Originals immutable.
        assert original.helpful_count == 0


def test_update_harmful_increments_and_stamps_last_updated_at() -> None:
    from pi_harness.corpus.counters import update_harmful

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        original = _make_entry(now=now - timedelta(days=1))
        updated = update_harmful(original, now)
        assert updated.harmful_count == original.harmful_count + 1
        assert updated.last_updated_at == now


def test_update_contradiction_increments_and_stamps_last_updated_at() -> None:
    from pi_harness.corpus.counters import update_contradiction

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        original = _make_entry(now=now - timedelta(days=1))
        updated = update_contradiction(original, now)
        assert updated.contradiction_count == original.contradiction_count + 1
        assert updated.last_updated_at == now


def test_counter_mutations_do_not_write_to_disk(tmp_corpus_root) -> None:
    """Smoke check: counter funcs are pure — no files appear on disk."""
    from pi_harness.corpus.counters import (
        update_contradiction,
        update_harmful,
        update_helpful,
    )

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(now=now)
        update_helpful(entry, now)
        update_harmful(entry, now)
        update_contradiction(entry, now)
        # No new files in the corpus root.
        files = [p for p in tmp_corpus_root.rglob("*") if p.is_file()]
        assert files == []
