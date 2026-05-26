"""TrajectoryEvent dataclass + SQLite row serialization."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

Outcome = Literal["success", "error", "blocked", "timeout"]

_VALID_OUTCOMES: frozenset[str] = frozenset(
    {"success", "error", "blocked", "timeout"}
)

# Classification is a free-form string in storage so the harness can add new
# event kinds without a migration, but v1 emitters MUST pick from this set.
# Capture pipelines and guards reuse these constants to avoid typos.
CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "tool_call",
        "tool_result",
        "message",
        "task_transition",
        "guide_fired",
        "sensor_fired",
    }
)


@dataclass
class TrajectoryEvent:
    """A single point in a run's trajectory.

    One row per: tool call, tool result, agent message, ClawTeam task
    transition, guide firing, or sensor firing. See `CLASSIFICATIONS` for the
    canonical v1 event kinds.

    `corpus_refs` / `corpus_cited` are populated by Plan 3 (corpus); Plan 2
    stores them as empty lists.
    """

    run_id: str
    agent_id: str
    step_id: str
    ts: datetime
    model: str
    tool: str  # "" for non-tool events
    input: Mapping[str, Any]
    output: Mapping[str, Any]
    duration_ms: int
    tokens_in: int
    tokens_out: int
    outcome: Outcome
    classification: str
    corpus_refs: list[str] = field(default_factory=list)
    corpus_cited: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.outcome not in _VALID_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {sorted(_VALID_OUTCOMES)}, "
                f"got {self.outcome!r}"
            )
        if self.ts.tzinfo is None:
            raise ValueError("ts must be timezone-aware (use UTC)")

    def to_row(self) -> dict[str, Any]:
        """Serialize for SQLite. List/dict fields become JSON strings."""
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "step_id": self.step_id,
            "ts": self.ts.isoformat(),
            "model": self.model,
            "tool": self.tool,
            "input": json.dumps(dict(self.input), sort_keys=True),
            "output": json.dumps(dict(self.output), sort_keys=True),
            "duration_ms": self.duration_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "outcome": self.outcome,
            "classification": self.classification,
            "corpus_refs": json.dumps(list(self.corpus_refs)),
            "corpus_cited": json.dumps(list(self.corpus_cited)),
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "TrajectoryEvent":
        """Deserialize a SQLite row (mapping or sqlite3.Row) back to an event."""
        return cls(
            run_id=row["run_id"],
            agent_id=row["agent_id"],
            step_id=row["step_id"],
            ts=datetime.fromisoformat(row["ts"]),
            model=row["model"],
            tool=row["tool"],
            input=json.loads(row["input"]) if row["input"] else {},
            output=json.loads(row["output"]) if row["output"] else {},
            duration_ms=int(row["duration_ms"]),
            tokens_in=int(row["tokens_in"]),
            tokens_out=int(row["tokens_out"]),
            outcome=row["outcome"],
            classification=row["classification"],
            corpus_refs=json.loads(row["corpus_refs"]) if row["corpus_refs"] else [],
            corpus_cited=json.loads(row["corpus_cited"]) if row["corpus_cited"] else [],
        )
