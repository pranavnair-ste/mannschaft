"""Unit tests for capture pipelines. No real subprocesses; streams are mocked."""
from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import patch

import pytest

from pi_harness.trajectory.capture import (
    capture_clawteam_transitions,
    capture_pi_agent_stream,
    normalize_pi_agent_event,
)
from pi_harness.trajectory.schema import TrajectoryEvent
from pi_harness.trajectory.store import init_db, query_events


pytestmark = pytest.mark.asyncio


async def _async_iter(lines: list[str]) -> AsyncIterator[str]:
    for line in lines:
        yield line


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "trajectory.db"
    init_db(path)
    return path


# --- normalize_pi_agent_event -------------------------------------------------

def test_normalize_tool_call_event():
    raw = {
        "type": "tool_call",
        "tool": "bash",
        "input": {"cmd": "ls"},
        "output": None,
        "duration_ms": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "step_id": "step-001",
        "ts": "2026-05-25T12:00:00+00:00",
        "model": "gpt-x-fast",
    }
    ev = normalize_pi_agent_event(
        raw, run_id="run-1", agent_id="builder", fallback_step_seq=0
    )
    assert isinstance(ev, TrajectoryEvent)
    assert ev.classification == "tool_call"
    assert ev.tool == "bash"
    assert ev.input == {"cmd": "ls"}
    assert ev.output == {}
    assert ev.run_id == "run-1"
    assert ev.agent_id == "builder"
    assert ev.step_id == "step-001"


def test_normalize_tool_result_event():
    raw = {
        "type": "tool_result",
        "tool": "bash",
        "output": {"stdout": "hi\n", "exit_code": 0},
        "duration_ms": 12,
        "outcome": "success",
        "ts": "2026-05-25T12:00:01+00:00",
        "model": "gpt-x-fast",
    }
    ev = normalize_pi_agent_event(
        raw, run_id="run-1", agent_id="builder", fallback_step_seq=1
    )
    assert ev.classification == "tool_result"
    assert ev.outcome == "success"
    assert ev.duration_ms == 12

def test_normalize_message_event_has_empty_tool():
    raw = {
        "type": "message",
        "content": "Hello world",
        "ts": "2026-05-25T12:00:02+00:00",
        "model": "gpt-x-fast",
        "tokens_in": 5,
        "tokens_out": 7,
    }
    ev = normalize_pi_agent_event(
        raw, run_id="run-1", agent_id="builder", fallback_step_seq=2
    )
    assert ev.classification == "message"
    assert ev.tool == ""
    assert ev.tokens_in == 5
    assert ev.tokens_out == 7


def test_normalize_unknown_outcome_falls_back_to_success():
    raw = {
        "type": "tool_result",
        "tool": "bash",
        "ts": "2026-05-25T12:00:00+00:00",
        "model": "m",
        # no outcome field
    }
    ev = normalize_pi_agent_event(
        raw, run_id="r", agent_id="a", fallback_step_seq=0
    )
    assert ev.outcome == "success"


def test_normalize_error_outcome_passes_through():
    raw = {
        "type": "tool_result",
        "tool": "bash",
        "ts": "2026-05-25T12:00:00+00:00",
        "model": "m",
        "outcome": "error",
    }
    ev = normalize_pi_agent_event(
        raw, run_id="r", agent_id="a", fallback_step_seq=0
    )
    assert ev.outcome == "error"


def test_normalize_uses_fallback_step_id_when_missing():
    raw = {
        "type": "message",
        "content": "no step id",
        "ts": "2026-05-25T12:00:00+00:00",
        "model": "m",
    }
    ev = normalize_pi_agent_event(
        raw, run_id="r", agent_id="a", fallback_step_seq=42
    )
    assert ev.step_id == "step-000042"


# --- capture_pi_agent_stream --------------------------------------------------

async def test_capture_pi_agent_stream_writes_events(db_path: Path):
    lines = [
        json.dumps(
            {
                "type": "tool_call",
                "tool": "bash",
                "input": {"cmd": "ls"},
                "ts": "2026-05-25T12:00:00+00:00",
                "model": "gpt-x-fast",
                "step_id": "step-001",
            }
        ),
        json.dumps(
            {
                "type": "tool_result",
                "tool": "bash",
                "output": {"stdout": "a\nb\n"},
                "duration_ms": 7,
                "outcome": "success",
                "ts": "2026-05-25T12:00:01+00:00",
                "model": "gpt-x-fast",
                "step_id": "step-001",
            }
        ),
    ]
    await capture_pi_agent_stream(
        run_id="run-1",
        agent_id="builder",
        stream=_async_iter(lines),
        db_path=db_path,
    )
    events = query_events(run_id="run-1", db_path=db_path)
    assert len(events) == 2
    assert events[0].classification == "tool_call"
    assert events[1].classification == "tool_result"


async def test_capture_pi_agent_stream_skips_blank_and_invalid_lines(
    db_path: Path,
):
    lines = [
        "",
        "   ",
        "not valid json {{",
        json.dumps(
            {
                "type": "message",
                "content": "ok",
                "ts": "2026-05-25T12:00:00+00:00",
                "model": "m",
            }
        ),
    ]
    await capture_pi_agent_stream(
        run_id="run-1",
        agent_id="builder",
        stream=_async_iter(lines),
        db_path=db_path,
    )
    events = query_events(run_id="run-1", db_path=db_path)
    assert len(events) == 1
    assert events[0].classification == "message"


# --- capture_clawteam_transitions ---------------------------------------------

async def test_capture_clawteam_transitions_emits_on_state_change(
    db_path: Path,
):
    # Real ClawTeam 0.2.x task JSON uses `task_id` and `status` (not `id`/`state`),
    # with status values pending|in_progress|completed|blocked (no `done`/`failed`).
    polls = [
        # poll 0
        [
            {"task_id": "t1", "owner": "builder", "status": "pending"},
            {"task_id": "t2", "owner": "reviewer", "status": "pending"},
        ],
        # poll 1: t1 moves to in_progress
        [
            {"task_id": "t1", "owner": "builder", "status": "in_progress"},
            {"task_id": "t2", "owner": "reviewer", "status": "pending"},
        ],
        # poll 2: t1 completed, t2 in_progress
        [
            {"task_id": "t1", "owner": "builder", "status": "completed"},
            {"task_id": "t2", "owner": "reviewer", "status": "in_progress"},
        ],
    ]

    call_idx = {"i": 0}

    async def fake_list_tasks(team_name: str) -> list[dict]:
        i = call_idx["i"]
        call_idx["i"] += 1
        if i >= len(polls):
            raise asyncio.CancelledError()
        return polls[i]

    with patch(
        "pi_harness.trajectory.capture._clawteam_list_tasks",
        side_effect=fake_list_tasks,
    ):
        task = asyncio.create_task(
            capture_clawteam_transitions(
                run_id="run-1",
                team_name="demo",
                db_path=db_path,
                poll_interval_s=0.0,
            )
        )
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            task.cancel()

    events = query_events(run_id="run-1", db_path=db_path)
    # Expect baseline (2) + transitions across polls 1 & 2 (3 transitions)
    assert len(events) >= 3
    transitions = [
        e for e in events if e.classification == "task_transition"
    ]
    # At least t1: pending -> in_progress -> completed, t2: pending -> in_progress
    states_for_t1 = [
        e.output["status"]
        for e in transitions
        if e.output.get("task_id") == "t1"
    ]
    assert "in_progress" in states_for_t1
    assert "completed" in states_for_t1
