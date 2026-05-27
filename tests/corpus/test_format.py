"""Tests for ``pi_harness.corpus.format`` — enums + YAML frontmatter roundtrip."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time


# ---------------------------------------------------------------------------
# Roundtrip across every RecordType x Classification combination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record_type_value",
    ["convention", "pattern", "failure", "decision", "reference", "guide"],
)
@pytest.mark.parametrize(
    "classification_value",
    ["foundational", "tactical", "observational"],
)
def test_roundtrip_all_record_types(
    tmp_corpus_root: Path, record_type_value: str, classification_value: str
) -> None:
    """Every record type and classification must roundtrip without loss."""
    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
        parse_entry,
        serialize_entry,
    )

    record_type = RecordType(record_type_value)
    classification = Classification(classification_value)

    with freeze_time("2026-05-25T12:00:00Z"):
        now = datetime.now(timezone.utc)
        body = (
            f"# {record_type.value} entry\n\n"
            "This is the body. It has multiple paragraphs.\n\n"
            "Second paragraph with details."
        )
        original = CorpusEntry.new(
            record_type=record_type,
            classification=classification,
            body=body,
            now=now,
        )
        # Bump counters so they actually exercise serialization
        bumped = original.with_counters(
            helpful_count=3,
            harmful_count=1,
            contradiction_count=2,
            last_referenced_run_id="run-abc",
        )

        serialized = serialize_entry(bumped)

        # Write to a temp file under classification subdir, then parse back
        target = tmp_corpus_root / classification.value / f"{bumped.id}.md"
        target.write_text(serialized, encoding="utf-8")
        parsed = parse_entry(target)

    assert parsed.id == bumped.id
    assert parsed.record_type == record_type
    assert parsed.classification == classification
    assert parsed.helpful_count == 3
    assert parsed.harmful_count == 1
    assert parsed.contradiction_count == 2
    assert parsed.last_referenced_run_id == "run-abc"
    assert parsed.created_at == bumped.created_at
    assert parsed.last_updated_at == bumped.last_updated_at
    assert parsed.size_tokens == bumped.size_tokens
    assert parsed.body == body


# ---------------------------------------------------------------------------
# ID format
# ---------------------------------------------------------------------------


def test_corpus_entry_id_matches_required_pattern() -> None:
    """``id`` must be ``<record_type>-<12 hex chars>``."""
    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
    )

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    entry = CorpusEntry.new(
        record_type=RecordType.PATTERN,
        classification=Classification.TACTICAL,
        body="some body",
        now=now,
    )
    assert re.match(r"^(convention|pattern|failure|decision|reference|guide)-[0-9a-f]{12}$", entry.id)


# ---------------------------------------------------------------------------
# size_tokens via tiktoken cl100k_base
# ---------------------------------------------------------------------------


def test_size_tokens_uses_cl100k_base_encoder() -> None:
    """``size_tokens`` must equal ``len(cl100k_base.encode(body))``."""
    import tiktoken

    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
    )

    body = "The quick brown fox jumps over the lazy dog. " * 5
    enc = tiktoken.get_encoding("cl100k_base")
    expected = len(enc.encode(body))

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    entry = CorpusEntry.new(
        record_type=RecordType.CONVENTION,
        classification=Classification.FOUNDATIONAL,
        body=body,
        now=now,
    )
    assert entry.size_tokens == expected


# ---------------------------------------------------------------------------
# Unknown enum values raise ValueError on parse
# ---------------------------------------------------------------------------


def test_parse_unknown_record_type_raises(tmp_corpus_root: Path) -> None:
    """Unknown record_type in frontmatter must raise ValueError."""
    from pi_harness.corpus.format import parse_entry

    target = tmp_corpus_root / "foundational" / "bogus.md"
    target.write_text(
        """---
id: bogus-000000000000
record_type: not_a_real_type
classification: foundational
helpful_count: 0
harmful_count: 0
contradiction_count: 0
created_at: '2026-05-25T12:00:00+00:00'
last_updated_at: '2026-05-25T12:00:00+00:00'
last_referenced_run_id: null
size_tokens: 1
---
body
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        parse_entry(target)


def test_parse_unknown_classification_raises(tmp_corpus_root: Path) -> None:
    from pi_harness.corpus.format import parse_entry

    target = tmp_corpus_root / "foundational" / "bogus2.md"
    target.write_text(
        """---
id: convention-000000000000
record_type: convention
classification: ultra_critical
helpful_count: 0
harmful_count: 0
contradiction_count: 0
created_at: '2026-05-25T12:00:00+00:00'
last_updated_at: '2026-05-25T12:00:00+00:00'
last_referenced_run_id: null
size_tokens: 1
---
body
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        parse_entry(target)


# ---------------------------------------------------------------------------
# Frontmatter key order (auditable, deterministic)
# ---------------------------------------------------------------------------


def test_frontmatter_key_order_is_deterministic() -> None:
    """Frontmatter keys must serialize in the documented order (sort_keys=False)."""
    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
        serialize_entry,
    )

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    entry = CorpusEntry.new(
        record_type=RecordType.GUIDE,
        classification=Classification.OBSERVATIONAL,
        body="body",
        now=now,
    )
    out = serialize_entry(entry)
    expected_order = [
        "id:",
        "record_type:",
        "classification:",
        "helpful_count:",
        "harmful_count:",
        "contradiction_count:",
        "created_at:",
        "last_updated_at:",
        "last_referenced_run_id:",
        "session_id:",
        "size_tokens:",
    ]
    indices = [out.index(k) for k in expected_order]
    assert indices == sorted(indices), f"Keys not in expected order: {out}"


# ---------------------------------------------------------------------------
# session_id field
# ---------------------------------------------------------------------------


def test_session_id_defaults_none() -> None:
    """CorpusEntry.new() without session_id must produce session_id=None."""
    from pi_harness.corpus.format import Classification, CorpusEntry, RecordType

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    entry = CorpusEntry.new(
        record_type=RecordType.PATTERN,
        classification=Classification.TACTICAL,
        body="some body",
        now=now,
    )
    assert entry.session_id is None


def test_session_id_set() -> None:
    """CorpusEntry.new(session_id=...) must propagate the value."""
    from pi_harness.corpus.format import Classification, CorpusEntry, RecordType

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    entry = CorpusEntry.new(
        record_type=RecordType.PATTERN,
        classification=Classification.TACTICAL,
        body="some body",
        now=now,
        session_id="sess-1",
    )
    assert entry.session_id == "sess-1"


def test_session_id_roundtrips(tmp_path: Path) -> None:
    """session_id must survive a serialize_entry → parse_entry roundtrip."""
    from pi_harness.corpus.format import (
        Classification,
        CorpusEntry,
        RecordType,
        parse_entry,
        serialize_entry,
    )

    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    entry = CorpusEntry.new(
        record_type=RecordType.PATTERN,
        classification=Classification.TACTICAL,
        body="roundtrip body",
        now=now,
        session_id="sess-1",
    )
    target = tmp_path / "entry.md"
    target.write_text(serialize_entry(entry), encoding="utf-8")
    parsed = parse_entry(target)
    assert parsed.session_id == "sess-1"


def test_missing_session_id_parses_as_none(tmp_path: Path) -> None:
    """Pre-existing entries without a session_id key must parse as session_id=None."""
    from pi_harness.corpus.format import parse_entry

    # Craft minimal frontmatter without session_id to simulate a pre-existing entry.
    content = """\
---
id: pattern-000000000000
record_type: pattern
classification: tactical
helpful_count: 0
harmful_count: 0
contradiction_count: 0
created_at: '2026-05-25T12:00:00+00:00'
last_updated_at: '2026-05-25T12:00:00+00:00'
last_referenced_run_id: null
size_tokens: 3
---
legacy body
"""
    target = tmp_path / "legacy.md"
    target.write_text(content, encoding="utf-8")
    parsed = parse_entry(target)
    assert parsed.session_id is None
