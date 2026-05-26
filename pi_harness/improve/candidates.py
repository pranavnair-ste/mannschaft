"""Improve-agent candidate dataclasses + pydantic validation.

The improve-agent emits two flavors of candidate per completed run:

- :class:`CandidateUpdate` — propose adding a new corpus entry.
- :class:`CandidatePrune` — flag an existing entry for pruning (the curator
  decides the actual graduated action).

These are the LLM-emitted, JSON-serializable shapes. Plan 4's
:mod:`pi_harness.improve.runner` converts them to the curator-input shapes
(``pi_harness.corpus.curator.CandidateUpdate`` /
``pi_harness.corpus.curator.CandidatePrune``) before forwarding to the
Curator. The naming collision is deliberate-but-scoped: the LLM-facing
contract is independent from the curator-input contract.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

import pydantic

from pi_harness.corpus.format import Classification, RecordType

__all__ = [
    "CandidatePrune",
    "CandidateUpdate",
    "PruneTrigger",
    "parse_agent_response",
]


class PruneTrigger(str, Enum):
    """Why the improve-agent thinks an existing corpus entry should be pruned.

    The actual graduated action (ARCHIVE / DEMOTE / MERGE / DELETE) is the
    curator's call — the agent only flags the trigger.
    """

    COUNTER = "counter"
    CONTRADICTION = "contradiction"
    STALENESS = "staleness"
    BUDGET = "budget"
    DEDUP = "dedup"


def _default(obj: Any) -> Any:
    """JSON-encoder hook that coerces ``Enum`` instances to their values."""
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable"
    )


@dataclass(frozen=True)
class CandidateUpdate:
    """A proposed new corpus entry.

    Attributes:
        record_type: One of the 6 Mulch record types.
        classification: One of the 3 corpus tiers.
        body: Markdown content for the new entry.
        source_run_id: The run that produced this candidate.
        source_step_ids: Step ids that evidence the candidate (required —
            without specific steps the candidate is too vague).
        confidence: Float in [0.0, 1.0]; the agent's confidence the
            candidate is worth adding.
        rationale: 1-3 sentence justification (logged in the audit trail).
    """

    record_type: RecordType
    classification: Classification
    body: str
    source_run_id: str
    source_step_ids: list[str]
    confidence: float
    rationale: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence!r}"
            )

    def to_json(self) -> str:
        """Serialize to a JSON string (enum values are flattened)."""
        return json.dumps(asdict(self), default=_default, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "CandidateUpdate":
        """Deserialize from a JSON string (enum values are re-hydrated)."""
        data = json.loads(s)
        return cls(
            record_type=RecordType(data["record_type"]),
            classification=Classification(data["classification"]),
            body=str(data["body"]),
            source_run_id=str(data["source_run_id"]),
            source_step_ids=list(data["source_step_ids"]),
            confidence=float(data["confidence"]),
            rationale=str(data["rationale"]),
        )


@dataclass(frozen=True)
class CandidatePrune:
    """A flag asking the curator to prune an existing entry.

    Attributes:
        entry_id: Id of the existing corpus entry.
        trigger: Why the agent thinks the entry should be pruned.
        rationale: 1-3 sentence justification.
    """

    entry_id: str
    trigger: PruneTrigger
    rationale: str

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(asdict(self), default=_default, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "CandidatePrune":
        """Deserialize from a JSON string."""
        data = json.loads(s)
        return cls(
            entry_id=str(data["entry_id"]),
            trigger=PruneTrigger(data["trigger"]),
            rationale=str(data["rationale"]),
        )


# ---------------------------------------------------------------------------
# Pydantic validators for raw LLM payloads
# ---------------------------------------------------------------------------


class _CandidateUpdateModel(pydantic.BaseModel):
    """Pydantic mirror of :class:`CandidateUpdate`; rejects unknown fields."""

    model_config = pydantic.ConfigDict(use_enum_values=False, extra="forbid")

    record_type: RecordType
    classification: Classification
    body: str
    source_run_id: str
    source_step_ids: list[str]
    confidence: float
    rationale: str

    @pydantic.field_validator("confidence")
    @classmethod
    def _confidence_in_unit_interval(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {v!r}")
        return v


class _CandidatePruneModel(pydantic.BaseModel):
    """Pydantic mirror of :class:`CandidatePrune`; rejects unknown fields."""

    model_config = pydantic.ConfigDict(use_enum_values=False, extra="forbid")

    entry_id: str
    trigger: PruneTrigger
    rationale: str


class _AgentResponseModel(pydantic.BaseModel):
    """Top-level wrapper for an improve-agent JSON response."""

    model_config = pydantic.ConfigDict(extra="forbid")

    updates: list[_CandidateUpdateModel]
    prunes: list[_CandidatePruneModel]


def parse_agent_response(
    payload: dict | str,
) -> tuple[list[CandidateUpdate], list[CandidatePrune]]:
    """Validate a raw agent payload and convert to frozen dataclasses.

    Args:
        payload: Either a parsed dict or a raw JSON string.

    Returns:
        Tuple of (updates, prunes) as frozen dataclass lists.

    Raises:
        pydantic.ValidationError: If the payload fails schema validation.
        json.JSONDecodeError: If ``payload`` is a string and not valid JSON.
    """
    if isinstance(payload, str):
        payload = json.loads(payload)
    model = _AgentResponseModel.model_validate(payload)
    updates = [
        CandidateUpdate(
            record_type=u.record_type,
            classification=u.classification,
            body=u.body,
            source_run_id=u.source_run_id,
            source_step_ids=list(u.source_step_ids),
            confidence=u.confidence,
            rationale=u.rationale,
        )
        for u in model.updates
    ]
    prunes = [
        CandidatePrune(
            entry_id=p.entry_id,
            trigger=p.trigger,
            rationale=p.rationale,
        )
        for p in model.prunes
    ]
    return updates, prunes
