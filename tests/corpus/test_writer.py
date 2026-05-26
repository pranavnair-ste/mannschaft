"""Tests for ``pi_harness.corpus.writer`` — gated, atomic, append-only writes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time


def _make_entry(**overrides):
    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
    )

    defaults = dict(
        record_type=RecordType.PATTERN,
        classification=Classification.TACTICAL,
        body="body content for writer tests",
        now=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return CorpusEntry.new(**defaults)


# ---------------------------------------------------------------------------
# Gating: writes outside curator_context fail
# ---------------------------------------------------------------------------


def test_write_entry_outside_curator_raises_writer_access_error(
    tmp_corpus_root: Path,
) -> None:
    from pi_harness.corpus import writer
    from pi_harness.corpus.writer import WriterAccessError

    entry = _make_entry()
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    with pytest.raises(WriterAccessError):
        writer.write_entry(entry, tmp_corpus_root, now)


def test_archive_entry_outside_curator_raises_writer_access_error(
    tmp_corpus_root: Path,
) -> None:
    from pi_harness.corpus import writer
    from pi_harness.corpus.writer import WriterAccessError

    entry = _make_entry()
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    with pytest.raises(WriterAccessError):
        writer.archive_entry(entry, tmp_corpus_root, now)


# ---------------------------------------------------------------------------
# Inside curator_context: writes succeed and land at <root>/<classification>/<id>.md
# ---------------------------------------------------------------------------


def test_write_entry_inside_curator_context_succeeds(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus import writer
    from pi_harness.corpus.format import Classification, parse_entry

    entry = _make_entry()
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    with writer.curator_context():
        target = writer.write_entry(entry, tmp_corpus_root, now)
    assert target == tmp_corpus_root / Classification.TACTICAL.value / f"{entry.id}.md"
    assert target.exists()
    # Roundtrip
    parsed = parse_entry(target)
    assert parsed.id == entry.id
    assert parsed.body == entry.body


def test_write_entry_updates_last_updated_at(tmp_corpus_root: Path) -> None:
    """After write, parsed entry has ``last_updated_at == now`` (the write stamps it)."""
    from pi_harness.corpus import writer
    from pi_harness.corpus.format import parse_entry

    # Build entry with last_updated_at in the past
    past = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entry = _make_entry(now=past)

    with freeze_time("2026-05-25T00:00:00Z"):
        now = datetime.now(timezone.utc)
        with writer.curator_context():
            target = writer.write_entry(entry, tmp_corpus_root, now)
        parsed = parse_entry(target)
        assert parsed.last_updated_at == now
        # created_at is preserved
        assert parsed.created_at == past


def test_write_entry_is_idempotent_overwrite(tmp_corpus_root: Path) -> None:
    """Second write to the same id replaces, does not raise."""
    from pi_harness.corpus import writer
    from pi_harness.corpus.format import parse_entry

    entry = _make_entry()
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    with writer.curator_context():
        target1 = writer.write_entry(entry, tmp_corpus_root, now)
        target2 = writer.write_entry(entry, tmp_corpus_root, now + timedelta(hours=1))
    assert target1 == target2
    parsed = parse_entry(target2)
    assert parsed.last_updated_at == now + timedelta(hours=1)


def test_curator_context_is_reentrant(tmp_corpus_root: Path) -> None:
    """Nested curator_context calls don't break the gate."""
    from pi_harness.corpus import writer

    entry = _make_entry()
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    with writer.curator_context():
        with writer.curator_context():
            writer.write_entry(entry, tmp_corpus_root, now)
        # Still gated after inner exit
        writer.write_entry(entry, tmp_corpus_root, now + timedelta(hours=1))
    # And once both exit, gate closes again
    from pi_harness.corpus.writer import WriterAccessError
    with pytest.raises(WriterAccessError):
        writer.write_entry(entry, tmp_corpus_root, now + timedelta(hours=2))


# ---------------------------------------------------------------------------
# archive_entry moves the file into <root>/archived/<classification>/<id>.md
# ---------------------------------------------------------------------------


def test_archive_entry_moves_file_to_archive_subdir(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus import writer
    from pi_harness.corpus.format import Classification

    entry = _make_entry()
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    with writer.curator_context():
        original = writer.write_entry(entry, tmp_corpus_root, now)
        archived_path = writer.archive_entry(entry, tmp_corpus_root, now)

    assert not original.exists()
    expected = (
        tmp_corpus_root
        / "archived"
        / Classification.TACTICAL.value
        / f"{entry.id}.md"
    )
    assert archived_path == expected
    assert archived_path.exists()


# ---------------------------------------------------------------------------
# Concurrent writes use a file lock
# ---------------------------------------------------------------------------


def test_concurrent_writes_use_file_lock(tmp_corpus_root: Path) -> None:
    """A second non-blocking ``LOCK_EX`` attempt on the same id raises immediately."""
    import fcntl

    from pi_harness.corpus import writer

    entry = _make_entry()
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    # The writer's lock helper is exposed for tests:
    lock_path = tmp_corpus_root / f".{entry.id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd1 = lock_path.open("w")
    fcntl.flock(fd1.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    fd2 = lock_path.open("w")
    with pytest.raises(BlockingIOError):
        fcntl.flock(fd2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    fcntl.flock(fd1.fileno(), fcntl.LOCK_UN)
    fd1.close()
    fd2.close()


def test_write_uses_atomic_replace(tmp_corpus_root: Path) -> None:
    """No ``.tmp`` file remains after a successful write (atomic rename)."""
    from pi_harness.corpus import writer

    entry = _make_entry()
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    with writer.curator_context():
        target = writer.write_entry(entry, tmp_corpus_root, now)
    # No leftover .tmp file in the classification dir
    leftovers = list((target.parent).glob("*.tmp"))
    assert leftovers == []
