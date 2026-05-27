"""Corpus entry data model + YAML-frontmatter serialization.

A corpus entry is a single markdown file with YAML frontmatter::

    ---
    id: pattern-9f86d081884c
    record_type: pattern
    classification: tactical
    helpful_count: 3
    harmful_count: 0
    contradiction_count: 0
    created_at: '2026-05-25T12:00:00+00:00'
    last_updated_at: '2026-05-25T12:00:00+00:00'
    last_referenced_run_id: run-abc
    size_tokens: 42
    ---
    # Optional markdown body
    ...

Counter mutations live in :mod:`pi_harness.corpus.counters`; disk writes live
in :mod:`pi_harness.corpus.writer`. This module is pure data + (de)serialization.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import tiktoken
import yaml

__all__ = [
    "Classification",
    "CorpusEntry",
    "RecordType",
    "count_tokens",
    "parse_entry",
    "serialize_entry",
]


class RecordType(str, Enum):
    """The 6 Mulch record types (per ``HARNESS_ARCHITECTURE.md`` §1.2)."""

    CONVENTION = "convention"
    PATTERN = "pattern"
    FAILURE = "failure"
    DECISION = "decision"
    REFERENCE = "reference"
    GUIDE = "guide"


class Classification(str, Enum):
    """The 3 corpus tiers; pruning rules differ per tier."""

    FOUNDATIONAL = "foundational"
    TACTICAL = "tactical"
    OBSERVATIONAL = "observational"


# Module-level encoder. ``tiktoken.get_encoding`` is cached internally but we
# cache the handle ourselves to avoid the lookup on every call.
_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Token count for ``text`` using cl100k_base.

    Used for ``size_tokens`` on every entry and for the metadata-tier budget
    in :meth:`pi_harness.corpus.reader.CorpusReader.prime`.
    """
    return len(_ENCODER.encode(text))


def _hash_body(record_type: RecordType, body: str) -> str:
    """Deterministic 12-char hash id derived from ``record_type`` + ``body``.

    Returns ``<record_type.value>-<12 hex chars>``. Collisions are improbable
    because we mix the record type into the digest input.
    """
    digest = hashlib.sha256(
        (record_type.value + body).encode("utf-8")
    ).hexdigest()[:12]
    return f"{record_type.value}-{digest}"


def _iso(dt: datetime) -> str:
    """ISO 8601 UTC string suitable for YAML frontmatter.

    We force tz-aware datetimes; a naive datetime is treated as UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string back to a tz-aware ``datetime`` (UTC)."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class CorpusEntry:
    """A single Mulch-format corpus entry.

    Instances are frozen; mutations return a new entry via :func:`dataclasses.replace`.
    Disk writes are gated by :mod:`pi_harness.corpus.writer.curator_context`.
    """

    id: str
    record_type: RecordType
    classification: Classification
    body: str
    helpful_count: int
    harmful_count: int
    contradiction_count: int
    created_at: datetime
    last_updated_at: datetime
    last_referenced_run_id: Optional[str]
    session_id: Optional[str]
    size_tokens: int

    @classmethod
    def new(
        cls,
        *,
        record_type: RecordType,
        classification: Classification,
        body: str,
        now: datetime,
        session_id: Optional[str] = None,
    ) -> "CorpusEntry":
        """Construct a fresh entry with derived id + size_tokens + timestamps."""
        return cls(
            id=_hash_body(record_type, body),
            record_type=record_type,
            classification=classification,
            body=body,
            helpful_count=0,
            harmful_count=0,
            contradiction_count=0,
            created_at=now,
            last_updated_at=now,
            last_referenced_run_id=None,
            session_id=session_id,
            size_tokens=count_tokens(body),
        )

    def with_counters(
        self,
        *,
        helpful_count: Optional[int] = None,
        harmful_count: Optional[int] = None,
        contradiction_count: Optional[int] = None,
        last_referenced_run_id: Optional[str] = None,
    ) -> "CorpusEntry":
        """Return a copy with overridden counters (helper for tests + curator)."""
        return replace(
            self,
            helpful_count=self.helpful_count if helpful_count is None else helpful_count,
            harmful_count=self.harmful_count if harmful_count is None else harmful_count,
            contradiction_count=(
                self.contradiction_count
                if contradiction_count is None
                else contradiction_count
            ),
            last_referenced_run_id=(
                last_referenced_run_id
                if last_referenced_run_id is not None
                else self.last_referenced_run_id
            ),
        )


def serialize_entry(entry: CorpusEntry) -> str:
    """Serialize ``entry`` to a ``---``-delimited frontmatter + body string.

    Key order is preserved for auditability via ``yaml.safe_dump(sort_keys=False)``.
    The output always ends with a single newline after the body.
    """
    frontmatter = {
        "id": entry.id,
        "record_type": entry.record_type.value,
        "classification": entry.classification.value,
        "helpful_count": entry.helpful_count,
        "harmful_count": entry.harmful_count,
        "contradiction_count": entry.contradiction_count,
        "created_at": _iso(entry.created_at),
        "last_updated_at": _iso(entry.last_updated_at),
        "last_referenced_run_id": entry.last_referenced_run_id,
        "session_id": entry.session_id,
        "size_tokens": entry.size_tokens,
    }
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    body = entry.body if entry.body.endswith("\n") else entry.body + "\n"
    return f"---\n{yaml_block}---\n{body}"


def parse_entry(path: Path) -> CorpusEntry:
    """Read a corpus entry file from disk.

    Raises:
        ValueError: If frontmatter is malformed or contains unknown enum values.
        FileNotFoundError: If ``path`` does not exist.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing leading '---' frontmatter delimiter")

    # Split at the second ``---`` line.
    remainder = text[4:]  # drop leading ``---\n``
    closing = remainder.find("\n---\n")
    if closing == -1:
        raise ValueError(f"{path}: missing closing '---' frontmatter delimiter")

    yaml_block = remainder[:closing]
    body = remainder[closing + len("\n---\n") :]
    # Strip exactly one trailing newline we added in serialize_entry, but leave
    # any inner whitespace alone.
    if body.endswith("\n"):
        body = body[:-1]

    data = yaml.safe_load(yaml_block) or {}

    # Coerce enums — ValueError propagates on unknown values.
    record_type = RecordType(data["record_type"])
    classification = Classification(data["classification"])

    return CorpusEntry(
        id=str(data["id"]),
        record_type=record_type,
        classification=classification,
        body=body,
        helpful_count=int(data["helpful_count"]),
        harmful_count=int(data["harmful_count"]),
        contradiction_count=int(data["contradiction_count"]),
        created_at=_parse_iso(data["created_at"]),
        last_updated_at=_parse_iso(data["last_updated_at"]),
        last_referenced_run_id=(
            None
            if data.get("last_referenced_run_id") in (None, "")
            else str(data["last_referenced_run_id"])
        ),
        session_id=(
            None
            if data.get("session_id") in (None, "")
            else str(data["session_id"])
        ),
        size_tokens=int(data["size_tokens"]),
    )
