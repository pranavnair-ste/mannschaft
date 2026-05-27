"""Tests for ``pi_harness.corpus.reader`` — prime + expand + classification queries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest
from freezegun import freeze_time


def _write(root, entry, now):
    """Helper: write ``entry`` under the curator gate (tests need real files)."""
    from pi_harness.corpus import writer

    with writer.curator_context():
        return writer.write_entry(entry, root, now)


def _make_entry(body, classification=None, record_type=None, now=None):
    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
    )

    return CorpusEntry.new(
        record_type=record_type or RecordType.PATTERN,
        classification=classification or Classification.TACTICAL,
        body=body,
        now=now or datetime(2026, 5, 25, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# prime: metadata-tier under token budget
# ---------------------------------------------------------------------------


def test_prime_returns_metadata_only_under_budget(tmp_corpus_root: Path) -> None:
    """``prime`` returns at most as many entries as fit under the token budget."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    # 5 entries with chunky bodies (each ~50+ tokens)
    bodies = [
        f"# Heading {i}\n\nLong body with many tokens used for sizing checks. " * 5
        for i in range(5)
    ]
    for body in bodies:
        entry = _make_entry(body, classification=Classification.TACTICAL, now=now)
        _write(tmp_corpus_root, entry, now)

    reader = CorpusReader(tmp_corpus_root)
    # Each entry's full size_tokens is large; metadata is the first heading line
    # (~3-5 tokens). Budget=20 metadata tokens — should still admit several
    # because metadata-tier is tiny.
    primed = reader.prime(token_budget=20, now=now)
    # Sum of metadata sizes must fit
    from pi_harness.corpus.format import count_tokens

    total = sum(count_tokens(e.body) for e in primed)
    assert total <= 20
    # Metadata body must be a slice — shorter than the original
    for p in primed:
        assert len(p.body) < len(bodies[0])


def test_prime_orders_foundational_then_tactical_then_observational(
    tmp_corpus_root: Path,
) -> None:
    """Within budget, foundational entries appear first, then tactical, then observational."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    classifications = [
        Classification.FOUNDATIONAL,
        Classification.TACTICAL,
        Classification.OBSERVATIONAL,
    ]
    for tier in classifications:
        for j in range(2):
            body = f"# {tier.value} {j}\n\nbody {tier.value} {j}"
            entry = _make_entry(body, classification=tier, now=now)
            _write(tmp_corpus_root, entry, now)

    reader = CorpusReader(tmp_corpus_root)
    primed = reader.prime(token_budget=10_000, now=now)
    # Six entries total, all fit
    assert len(primed) == 6
    tiers = [p.classification for p in primed]
    # foundational entries appear before tactical entries which appear before observational
    f_indices = [i for i, t in enumerate(tiers) if t == Classification.FOUNDATIONAL]
    t_indices = [i for i, t in enumerate(tiers) if t == Classification.TACTICAL]
    o_indices = [i for i, t in enumerate(tiers) if t == Classification.OBSERVATIONAL]
    assert max(f_indices) < min(t_indices)
    assert max(t_indices) < min(o_indices)


def test_prime_orders_within_tier_by_recency(tmp_corpus_root: Path) -> None:
    """Within a classification, more-recently-updated entries appear first."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    # Create three foundational entries with staggered last_updated_at
    older = _make_entry(
        "# older\nbody older",
        classification=Classification.FOUNDATIONAL,
        now=now - timedelta(days=10),
    )
    middle = _make_entry(
        "# middle\nbody middle",
        classification=Classification.FOUNDATIONAL,
        now=now - timedelta(days=5),
    )
    newer = _make_entry(
        "# newer\nbody newer",
        classification=Classification.FOUNDATIONAL,
        now=now - timedelta(days=1),
    )
    # Write at their respective times (write_entry stamps last_updated_at = ``now`` argument)
    _write(tmp_corpus_root, older, now - timedelta(days=10))
    _write(tmp_corpus_root, middle, now - timedelta(days=5))
    _write(tmp_corpus_root, newer, now - timedelta(days=1))

    reader = CorpusReader(tmp_corpus_root)
    primed = reader.prime(token_budget=10_000, now=now)
    ids_in_order = [p.id for p in primed]
    # newer first
    assert ids_in_order.index(newer.id) < ids_in_order.index(middle.id)
    assert ids_in_order.index(middle.id) < ids_in_order.index(older.id)


def test_prime_filters_by_classifications_arg(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    for tier in [
        Classification.FOUNDATIONAL,
        Classification.TACTICAL,
        Classification.OBSERVATIONAL,
    ]:
        body = f"# {tier.value}\nbody"
        entry = _make_entry(body, classification=tier, now=now)
        _write(tmp_corpus_root, entry, now)

    reader = CorpusReader(tmp_corpus_root)
    primed = reader.prime(
        token_budget=10_000, classifications=[Classification.TACTICAL], now=now
    )
    assert len(primed) == 1
    assert primed[0].classification == Classification.TACTICAL


# ---------------------------------------------------------------------------
# expand: returns full body
# ---------------------------------------------------------------------------


def test_expand_loads_full_body(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    body = "# heading\n\nthis is a very long body with multiple paragraphs.\n\nAnother para."
    entry = _make_entry(body, classification=Classification.TACTICAL, now=now)
    _write(tmp_corpus_root, entry, now)

    reader = CorpusReader(tmp_corpus_root)
    expanded = reader.expand(entry.id)
    assert expanded.body == body


def test_expand_unknown_id_raises(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus.reader import CorpusReader

    reader = CorpusReader(tmp_corpus_root)
    with pytest.raises(FileNotFoundError):
        reader.expand("pattern-deadbeefcafe")


# ---------------------------------------------------------------------------
# find_by_classification
# ---------------------------------------------------------------------------


def test_find_by_classification(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    f_entry = _make_entry(
        "# foundational\nbody", classification=Classification.FOUNDATIONAL, now=now
    )
    t_entries = [
        _make_entry(
            f"# tactical {i}\nbody {i}",
            classification=Classification.TACTICAL,
            now=now,
        )
        for i in range(3)
    ]
    _write(tmp_corpus_root, f_entry, now)
    for e in t_entries:
        _write(tmp_corpus_root, e, now)

    reader = CorpusReader(tmp_corpus_root)
    found = reader.find_by_classification(Classification.TACTICAL)
    assert len(found) == 3
    assert {e.id for e in found} == {e.id for e in t_entries}


# ---------------------------------------------------------------------------
# find_unreferenced — by age (days)
# ---------------------------------------------------------------------------


def test_find_unreferenced_since_days(tmp_corpus_root: Path) -> None:
    """Entries with last_referenced_run_id=None AND age >= days are returned."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        # Old + unreferenced — should match
        old_unref = _make_entry(
            "# old unref\nbody",
            classification=Classification.OBSERVATIONAL,
            now=now - timedelta(days=30),
        )
        _write(tmp_corpus_root, old_unref, now - timedelta(days=30))

        # Recent + unreferenced — should NOT match (too young)
        new_unref = _make_entry(
            "# new unref\nbody",
            classification=Classification.OBSERVATIONAL,
            now=now - timedelta(days=2),
        )
        _write(tmp_corpus_root, new_unref, now - timedelta(days=2))

        # Old + referenced — should NOT match
        old_ref_entry = _make_entry(
            "# old ref\nbody",
            classification=Classification.OBSERVATIONAL,
            now=now - timedelta(days=30),
        )
        old_ref_entry = old_ref_entry.with_counters(last_referenced_run_id="run-1")
        _write(tmp_corpus_root, old_ref_entry, now - timedelta(days=30))

        reader = CorpusReader(tmp_corpus_root)
        results = reader.find_unreferenced(days=7, now=now)
        ids = {r.id for r in results}
        assert old_unref.id in ids
        assert new_unref.id not in ids
        assert old_ref_entry.id not in ids


# ---------------------------------------------------------------------------
# find_unreferenced — by trajectory run
# ---------------------------------------------------------------------------


def test_find_unreferenced_since_run_uses_trajectory(tmp_corpus_root: Path) -> None:
    """Entries not present in any trajectory event's corpus_refs are returned."""
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    a = _make_entry("# a\nA body", classification=Classification.TACTICAL, now=now)
    b = _make_entry("# b\nB body", classification=Classification.TACTICAL, now=now)
    c = _make_entry("# c\nC body", classification=Classification.TACTICAL, now=now)
    for e in (a, b, c):
        _write(tmp_corpus_root, e, now)

    # Fake query_events that says only entry ``a`` was referenced in run-XYZ.
    class _FakeEvent:
        def __init__(self, refs):
            self.corpus_refs = refs
            self.corpus_cited = []

    def fake_query(run_id=None, since_ts=None, limit=None):
        return [_FakeEvent([a.id]), _FakeEvent([])]

    reader = CorpusReader(tmp_corpus_root, query_events=fake_query)
    results = reader.find_unreferenced(since_run="run-XYZ", now=now)
    ids = {r.id for r in results}
    assert a.id not in ids
    assert b.id in ids
    assert c.id in ids


def test_find_unreferenced_skips_archived(tmp_corpus_root: Path) -> None:
    """Archived entries are not returned by find_unreferenced."""
    from pi_harness.corpus import writer
    from pi_harness.corpus.format import Classification
    from pi_harness.corpus.reader import CorpusReader

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        entry = _make_entry(
            "# archived\nbody",
            classification=Classification.OBSERVATIONAL,
            now=now - timedelta(days=60),
        )
        with writer.curator_context():
            writer.write_entry(entry, tmp_corpus_root, now - timedelta(days=60))
            writer.archive_entry(entry, tmp_corpus_root, now - timedelta(days=60))

        reader = CorpusReader(tmp_corpus_root)
        results = reader.find_unreferenced(days=7, now=now)
        assert entry.id not in {r.id for r in results}


# ---------------------------------------------------------------------------
# prime: session_id filtering
# ---------------------------------------------------------------------------


def _make_entry_with_session(body, session_id=None, classification=None, now=None):
    """Like _make_entry but forwards session_id to CorpusEntry.new."""
    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
    )

    return CorpusEntry.new(
        record_type=RecordType.PATTERN,
        classification=classification or Classification.TACTICAL,
        body=body,
        now=now or datetime(2026, 5, 25, tzinfo=timezone.utc),
        session_id=session_id,
    )


def _make_session_corpus(tmp_corpus_root):
    """Write three entries: session_id=None, 'A', 'B'. Returns (none_entry, a_entry, b_entry)."""
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    none_entry = _make_entry_with_session("# global entry\nglobal body", session_id=None, now=now)
    a_entry = _make_entry_with_session("# session A entry\nA body", session_id="A", now=now)
    b_entry = _make_entry_with_session("# session B entry\nB body", session_id="B", now=now)
    for e in (none_entry, a_entry, b_entry):
        _write(tmp_corpus_root, e, now)
    return none_entry, a_entry, b_entry


def test_prime_session_none_returns_all(tmp_corpus_root: Path) -> None:
    """session_id=None (default) returns all entries regardless of their session_id."""
    from pi_harness.corpus.reader import CorpusReader

    none_entry, a_entry, b_entry = _make_session_corpus(tmp_corpus_root)
    reader = CorpusReader(tmp_corpus_root)
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)

    primed = reader.prime(token_budget=10_000, session_id=None, now=now)
    ids = {e.id for e in primed}
    assert len(primed) == 3
    assert none_entry.id in ids
    assert a_entry.id in ids
    assert b_entry.id in ids


def test_prime_session_filters_to_matching_plus_global(tmp_corpus_root: Path) -> None:
    """session_id='A' returns entries where entry.session_id == 'A' or is None."""
    from pi_harness.corpus.reader import CorpusReader

    none_entry, a_entry, b_entry = _make_session_corpus(tmp_corpus_root)
    reader = CorpusReader(tmp_corpus_root)
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)

    primed = reader.prime(token_budget=10_000, session_id="A", now=now)
    ids = {e.id for e in primed}
    assert len(primed) == 2
    assert none_entry.id in ids
    assert a_entry.id in ids
    assert b_entry.id not in ids


def test_prime_session_excludes_other_sessions(tmp_corpus_root: Path) -> None:
    """A B-only entry must not appear in prime(session_id='A') results."""
    from pi_harness.corpus.reader import CorpusReader

    _none_entry, _a_entry, b_entry = _make_session_corpus(tmp_corpus_root)
    reader = CorpusReader(tmp_corpus_root)
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)

    primed = reader.prime(token_budget=10_000, session_id="A", now=now)
    ids = {e.id for e in primed}
    assert b_entry.id not in ids


def test_module_prime_forwards_session_id(tmp_corpus_root: Path) -> None:
    """Module-level prime() must forward session_id to CorpusReader.prime."""
    import pi_harness.corpus.reader as reader_mod

    none_entry, a_entry, b_entry = _make_session_corpus(tmp_corpus_root)
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)

    primed = reader_mod.prime(tmp_corpus_root, token_budget=10_000, session_id="A", now=now)
    ids = {e.id for e in primed}
    assert len(primed) == 2
    assert none_entry.id in ids
    assert a_entry.id in ids
    assert b_entry.id not in ids
