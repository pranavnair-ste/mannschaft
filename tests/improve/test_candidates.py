"""Tests for pi_harness.improve.candidates."""

from __future__ import annotations

import pytest

from pi_harness.corpus.format import Classification, RecordType
from pi_harness.improve.candidates import (
    CandidatePrune,
    CandidateUpdate,
    PruneTrigger,
)


def test_candidate_update_roundtrip() -> None:
    """A CandidateUpdate must roundtrip cleanly through to_json/from_json."""
    original = CandidateUpdate(
        record_type=RecordType.PATTERN,
        classification=Classification.TACTICAL,
        body="Always use async for IO",
        source_run_id="run-abc",
        source_step_ids=["step-1", "step-2"],
        confidence=0.85,
        rationale="Observed 3 successes",
    )
    blob = original.to_json()
    restored = CandidateUpdate.from_json(blob)

    assert restored.record_type == original.record_type
    assert restored.classification == original.classification
    assert restored.body == original.body
    assert restored.source_run_id == original.source_run_id
    assert restored.source_step_ids == original.source_step_ids
    assert restored.confidence == pytest.approx(original.confidence)
    assert restored.rationale == original.rationale


def test_candidate_prune_roundtrip() -> None:
    """A CandidatePrune must roundtrip cleanly through to_json/from_json."""
    original = CandidatePrune(
        entry_id="entry-xyz",
        trigger=PruneTrigger.COUNTER,
        rationale="harmful > helpful",
    )
    blob = original.to_json()
    restored = CandidatePrune.from_json(blob)

    assert restored.entry_id == original.entry_id
    assert restored.trigger == original.trigger
    assert restored.rationale == original.rationale


def test_candidate_update_confidence_validation() -> None:
    """Confidence outside [0, 1] must raise ValueError on construction."""
    common = dict(
        record_type=RecordType.PATTERN,
        classification=Classification.TACTICAL,
        body="b",
        source_run_id="r",
        source_step_ids=["s"],
        rationale="x",
    )
    with pytest.raises(ValueError):
        CandidateUpdate(confidence=-0.1, **common)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CandidateUpdate(confidence=1.5, **common)  # type: ignore[arg-type]
    # Boundary values are valid.
    CandidateUpdate(confidence=0.0, **common)  # type: ignore[arg-type]
    CandidateUpdate(confidence=1.0, **common)  # type: ignore[arg-type]


def test_prune_trigger_enum_values() -> None:
    """PruneTrigger contains exactly the 5 documented triggers."""
    assert {t.value for t in PruneTrigger} == {
        "counter",
        "contradiction",
        "staleness",
        "budget",
        "dedup",
    }
