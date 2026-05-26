"""Gated, atomic corpus writer.

The corpus is an append-only knowledge base: only the :class:`Curator` may
write to it, and only via the :func:`curator_context` context manager. Direct
``write_entry`` / ``archive_entry`` calls outside that context raise
:class:`WriterAccessError`.

Implementation notes
--------------------

- A module-level counter (guarded by a :class:`threading.Lock`) toggles the
  gate; the context manager is reentrant so nested ``apply_candidates`` calls
  remain safe.
- Each write acquires an exclusive ``fcntl.flock`` on a sidecar
  ``.{id}.lock`` file in the classification subdir.
- Writes are atomic: serialize → write to ``<target>.tmp`` → ``os.replace``.
- ``archive_entry`` moves the entry into ``<root>/archived/<classification>/<id>.md``.

This module is intentionally tiny — all policy (when to write, what to write)
lives in :mod:`pi_harness.corpus.curator`.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Iterator

from pi_harness.corpus.format import CorpusEntry, serialize_entry

__all__ = [
    "WriterAccessError",
    "archive_entry",
    "curator_context",
    "write_entry",
]


class WriterAccessError(RuntimeError):
    """Raised when a write is attempted outside a ``curator_context``."""


# Reentrant counter: 0 = gate closed, >0 = inside one or more curator contexts.
_GATE_LOCK = threading.Lock()
_GATE_DEPTH = 0


def _assert_inside_curator() -> None:
    """Raise :class:`WriterAccessError` unless we're inside a curator context."""
    with _GATE_LOCK:
        depth = _GATE_DEPTH
    if depth <= 0:
        raise WriterAccessError(
            "write_entry / archive_entry must be called via "
            "Curator.apply_candidates (inside curator_context())"
        )


@contextlib.contextmanager
def curator_context() -> Iterator[None]:
    """Open the writer gate for the duration of the ``with`` block.

    Reentrant: nested ``with`` blocks bump a depth counter; the gate only
    closes when the outermost context exits.
    """
    global _GATE_DEPTH
    with _GATE_LOCK:
        _GATE_DEPTH += 1
    try:
        yield
    finally:
        with _GATE_LOCK:
            _GATE_DEPTH -= 1


def _classification_dir(root: Path, entry: CorpusEntry) -> Path:
    """Return ``<root>/<classification.value>/`` (created if missing)."""
    target_dir = root / entry.classification.value
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _archive_dir(root: Path, entry: CorpusEntry) -> Path:
    """Return ``<root>/archived/<classification.value>/`` (created if missing)."""
    target_dir = root / "archived" / entry.classification.value
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


@contextlib.contextmanager
def _file_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an exclusive ``fcntl.flock`` on ``lock_path``.

    The lock file is created if missing. On exit the lock is released and
    the file is left in place (cleanup is the curator's responsibility, but
    in practice it's harmless to leave).
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def write_entry(entry: CorpusEntry, root: Path, now: datetime) -> Path:
    """Write ``entry`` to ``<root>/<classification>/<id>.md`` atomically.

    Updates ``entry.last_updated_at`` to ``now`` before serializing. Holds
    an exclusive flock on a sidecar lock file for the duration of the write.

    Returns:
        The final on-disk path.

    Raises:
        WriterAccessError: If called outside :func:`curator_context`.
    """
    _assert_inside_curator()
    target_dir = _classification_dir(root, entry)
    target = target_dir / f"{entry.id}.md"
    lock_path = target_dir / f".{entry.id}.lock"

    stamped = replace(entry, last_updated_at=now)

    with _file_lock(lock_path):
        tmp = target.with_suffix(".md.tmp")
        tmp.write_text(serialize_entry(stamped), encoding="utf-8")
        os.replace(tmp, target)
    return target


def archive_entry(entry: CorpusEntry, root: Path, now: datetime) -> Path:
    """Move ``entry`` to ``<root>/archived/<classification>/<id>.md``.

    The original file at ``<root>/<classification>/<id>.md`` is removed (if
    present). ``last_updated_at`` is stamped to ``now``.

    Returns:
        The archive path.

    Raises:
        WriterAccessError: If called outside :func:`curator_context`.
    """
    _assert_inside_curator()
    active_dir = _classification_dir(root, entry)
    archive_dir = _archive_dir(root, entry)
    active_path = active_dir / f"{entry.id}.md"
    archive_path = archive_dir / f"{entry.id}.md"
    lock_path = active_dir / f".{entry.id}.lock"

    stamped = replace(entry, last_updated_at=now)

    with _file_lock(lock_path):
        tmp = archive_path.with_suffix(".md.tmp")
        tmp.write_text(serialize_entry(stamped), encoding="utf-8")
        os.replace(tmp, archive_path)
        if active_path.exists():
            active_path.unlink()
    return archive_path
