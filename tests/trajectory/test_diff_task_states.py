"""Unit test for the shared task-state diff helper (sync; no asyncio mark)."""
from __future__ import annotations

from datetime import datetime, timezone

from pi_harness.trajectory.capture import diff_task_states


def test_diff_task_states_emits_only_on_change():
    now = datetime.now(timezone.utc)
    state: dict[str, str] = {}

    first = diff_task_states(
        state,
        [{"task_id": "t1", "owner": "builder", "status": "pending"}],
        run_id="run-x",
        now=now,
    )
    assert len(first) == 1
    assert first[0].classification == "task_transition"
    assert first[0].output["status"] == "pending"
    assert first[0].input["prev_status"] is None
    assert state == {"t1": "pending"}

    # No change -> no events.
    same = diff_task_states(
        state,
        [{"task_id": "t1", "owner": "builder", "status": "pending"}],
        run_id="run-x",
        now=now,
    )
    assert same == []

    # Change -> one event, state updated.
    changed = diff_task_states(
        state,
        [{"task_id": "t1", "owner": "builder", "status": "completed"}],
        run_id="run-x",
        now=now,
    )
    assert len(changed) == 1
    assert changed[0].output["status"] == "completed"
    assert state["t1"] == "completed"
