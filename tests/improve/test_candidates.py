"""Tests for pi_harness.improve.candidates."""

from __future__ import annotations

import pydantic
import pytest

from pi_harness.corpus.format import Classification, RecordType
from pi_harness.improve.candidates import (
    ProposedPrune,
    ProposedUpdate,
    PruneTrigger,
    parse_agent_response,
)


_VALID_PAYLOAD = {
    "updates": [
        {
            "record_type": "pattern",
            "classification": "tactical",
            "body": "Prefer select_related for N+1",
            "source_run_id": "run-1",
            "source_step_ids": ["step-1"],
            "confidence": 0.7,
            "rationale": "Observed twice.",
        }
    ],
    "prunes": [
        {
            "entry_id": "entry-1",
            "trigger": "counter",
            "rationale": "harmful > helpful",
        }
    ],
}


def test_candidate_update_roundtrip() -> None:
    """A ProposedUpdate must roundtrip cleanly through to_json/from_json."""
    original = ProposedUpdate(
        record_type=RecordType.PATTERN,
        classification=Classification.TACTICAL,
        body="Always use async for IO",
        source_run_id="run-abc",
        source_step_ids=["step-1", "step-2"],
        confidence=0.85,
        rationale="Observed 3 successes",
    )
    blob = original.to_json()
    restored = ProposedUpdate.from_json(blob)

    assert restored.record_type == original.record_type
    assert restored.classification == original.classification
    assert restored.body == original.body
    assert restored.source_run_id == original.source_run_id
    assert restored.source_step_ids == original.source_step_ids
    assert restored.confidence == pytest.approx(original.confidence)
    assert restored.rationale == original.rationale


def test_candidate_prune_roundtrip() -> None:
    """A ProposedPrune must roundtrip cleanly through to_json/from_json."""
    original = ProposedPrune(
        entry_id="entry-xyz",
        trigger=PruneTrigger.COUNTER,
        rationale="harmful > helpful",
    )
    blob = original.to_json()
    restored = ProposedPrune.from_json(blob)

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
        ProposedUpdate(confidence=-0.1, **common)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ProposedUpdate(confidence=1.5, **common)  # type: ignore[arg-type]
    # Boundary values are valid.
    ProposedUpdate(confidence=0.0, **common)  # type: ignore[arg-type]
    ProposedUpdate(confidence=1.0, **common)  # type: ignore[arg-type]


def test_prune_trigger_enum_values() -> None:
    """PruneTrigger contains exactly the 5 documented triggers."""
    assert {t.value for t in PruneTrigger} == {
        "counter",
        "contradiction",
        "staleness",
        "budget",
        "dedup",
    }


def test_validator_accepts_valid_payload() -> None:
    """A schema-compliant payload returns (list[ProposedUpdate], list[ProposedPrune])."""
    updates, prunes = parse_agent_response(_VALID_PAYLOAD)
    assert len(updates) == 1
    assert len(prunes) == 1
    assert isinstance(updates[0], ProposedUpdate)
    assert isinstance(prunes[0], ProposedPrune)
    assert updates[0].record_type == RecordType.PATTERN
    assert updates[0].classification == Classification.TACTICAL
    assert prunes[0].trigger == PruneTrigger.COUNTER


def test_validator_rejects_missing_field() -> None:
    """Missing required field raises pydantic.ValidationError."""
    bad = {
        "updates": [
            {
                "record_type": "pattern",
                "classification": "tactical",
                "body": "x",
                "source_run_id": "r",
                "source_step_ids": ["s"],
                # confidence omitted
                "rationale": "x",
            }
        ],
        "prunes": [],
    }
    with pytest.raises(pydantic.ValidationError):
        parse_agent_response(bad)


def test_validator_rejects_unknown_record_type() -> None:
    """An unknown record_type value raises validation error."""
    bad = {
        "updates": [
            {
                "record_type": "not-a-type",
                "classification": "tactical",
                "body": "x",
                "source_run_id": "r",
                "source_step_ids": ["s"],
                "confidence": 0.5,
                "rationale": "x",
            }
        ],
        "prunes": [],
    }
    with pytest.raises(pydantic.ValidationError):
        parse_agent_response(bad)


def test_validator_accepts_json_string() -> None:
    """A JSON string payload is parsed before validation."""
    import json as _json

    updates, prunes = parse_agent_response(_json.dumps(_VALID_PAYLOAD))
    assert len(updates) == 1
    assert len(prunes) == 1
