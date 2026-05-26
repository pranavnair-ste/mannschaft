"""Tests for pi_harness.trajectory.schema."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pi_harness.trajectory.schema import TrajectoryEvent


def _sample_event(**overrides) -> TrajectoryEvent:
    base = dict(
        run_id="run-1",
        agent_id="builder",
        step_id="step-001",
        ts=datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc),
        model="gpt-x-fast",
        tool="bash",
        input={"cmd": "ls"},
        output={"stdout": "a\nb\n"},
        duration_ms=42,
        tokens_in=10,
        tokens_out=5,
        outcome="success",
        classification="tool_call",
        corpus_refs=["entry-a", "entry-b"],
        corpus_cited=["entry-a"],
    )
    base.update(overrides)
    return TrajectoryEvent(**base)


def test_event_defaults_empty_corpus_lists():
    ev = TrajectoryEvent(
        run_id="r",
        agent_id="a",
        step_id="s",
        ts=datetime(2026, 5, 25, tzinfo=timezone.utc),
        model="m",
        tool="",
        input={},
        output={},
        duration_ms=0,
        tokens_in=0,
        tokens_out=0,
        outcome="success",
        classification="message",
    )
    assert ev.corpus_refs == []
    assert ev.corpus_cited == []


def test_to_row_serializes_dicts_and_lists_as_json():
    ev = _sample_event()
    row = ev.to_row()
    assert row["run_id"] == "run-1"
    assert json.loads(row["input"]) == {"cmd": "ls"}
    assert json.loads(row["output"]) == {"stdout": "a\nb\n"}
    assert json.loads(row["corpus_refs"]) == ["entry-a", "entry-b"]
    assert json.loads(row["corpus_cited"]) == ["entry-a"]
    # ts must be ISO-8601 with timezone
    assert row["ts"] == "2026-05-25T12:00:00+00:00"


def test_from_row_round_trips():
    original = _sample_event()
    row = original.to_row()
    restored = TrajectoryEvent.from_row(row)
    assert restored == original


def test_from_row_round_trips_with_empty_corpus_refs():
    original = _sample_event(corpus_refs=[], corpus_cited=[])
    restored = TrajectoryEvent.from_row(original.to_row())
    assert restored.corpus_refs == []
    assert restored.corpus_cited == []


def test_outcome_rejects_invalid_literal():
    with pytest.raises(ValueError):
        TrajectoryEvent(
            run_id="r",
            agent_id="a",
            step_id="s",
            ts=datetime(2026, 5, 25, tzinfo=timezone.utc),
            model="m",
            tool="",
            input={},
            output={},
            duration_ms=0,
            tokens_in=0,
            tokens_out=0,
            outcome="oopsie",  # not in the allowed set
            classification="message",
        )


def test_ts_must_be_timezone_aware():
    with pytest.raises(ValueError):
        TrajectoryEvent(
            run_id="r",
            agent_id="a",
            step_id="s",
            ts=datetime(2026, 5, 25, 12, 0, 0),  # naive
            model="m",
            tool="",
            input={},
            output={},
            duration_ms=0,
            tokens_in=0,
            tokens_out=0,
            outcome="success",
            classification="message",
        )
