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
