"""Pydantic DTOs for the dashboard API.

These mirror the REAL upstream shapes: trajectory ``RunSummary`` and
``TrajectoryEvent`` (note: events have NO inline guide/sensor firing arrays --
firings are separate events with classification guide_fired/sensor_fired;
``outcome``/``classification`` are open strings; input/output are dicts).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RunSummaryDTO(BaseModel):
    run_id: str
    status: str
    topology: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    agent_count: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    event_count: int
    parent_run_id: str | None = None
    branch_from_step: str | None = None
    goal: str | None = None
    spec_id: str | None = None
    wall_clock_s: float | None = None
    sovereign: bool = False


class TrajectoryEventDTO(BaseModel):
    run_id: str
    agent_id: str
    step_id: str
    ts: datetime
    model: str
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int
    tokens_in: int
    tokens_out: int
    outcome: str
    classification: str
    corpus_refs: list[str] = Field(default_factory=list)
    corpus_cited: list[str] = Field(default_factory=list)


class RunDetailDTO(BaseModel):
    summary: RunSummaryDTO
    events: list[TrajectoryEventDTO]


class AgentTimelineRowDTO(BaseModel):
    agent_id: str
    events: list[TrajectoryEventDTO]


class TimelineDTO(BaseModel):
    run_id: str
    agents: list[AgentTimelineRowDTO]


class ReliabilityDTO(BaseModel):
    consistency: float | None = None
    robustness: float | None = None
    predictability: float | None = None
    safety: float | None = None


class BranchRequest(BaseModel):
    step_id: str
    overrides: dict[str, Any] = Field(default_factory=dict)


class BranchResponse(BaseModel):
    run_id: str
    parent_run_id: str
    branched_from_step: str


class CorpusEntryDTO(BaseModel):
    id: str
    record_type: str
    classification: str
    helpful_count: int
    harmful_count: int
    contradiction_count: int
    created_at: datetime
    last_updated_at: datetime
    last_referenced_run_id: str | None = None
    session_id: str | None = None
    size_tokens: int
    archived: bool = False
    body_preview: str


class CorpusHealthDTO(BaseModel):
    total_active_tokens: int
    soft_cap_tokens: int
    pct_of_cap: float
    foundational_count: int
    tactical_count: int
    observational_count: int
    archived_count: int
    prune_candidates: dict[str, int]
    stale_entries: list[CorpusEntryDTO]
    recently_archived: list[CorpusEntryDTO]


class PromotionCandidateDTO(BaseModel):
    sensor_name: str
    sensor_criterion: str
    fires: int
    allow_fraction: float
    suggested_kind: str
    suggested_stub_code: str
    evidence: dict[str, Any] = Field(default_factory=dict)
