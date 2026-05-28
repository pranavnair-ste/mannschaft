"""WebSocket event tailer.

Plan 2 has no live event bus, so this polls the trajectory db: each tick it
queries events for the run and pushes any not yet sent. It closes once a poll
yields no new events AND the run has reached a terminal status -- which keeps
the synchronous TestClient bounded and lets the browser reconnect (via the
TanStack refetch on the timeline) for still-running runs. Once the live-capture
wrapper (Phase 6) writes events faster, this same loop streams them.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pi_harness.api.models import TrajectoryEventDTO
from pi_harness.trajectory.runs import get_run
from pi_harness.trajectory.store import query_events

router = APIRouter()

_TERMINAL = {"succeeded", "failed", "cancelled"}


@router.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str) -> None:
    db = websocket.app.state.config.trajectory_db_path
    if get_run(run_id, db_path=db) is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    poll = getattr(websocket.app.state, "ws_poll_interval", 1.0)
    sent = 0
    try:
        while True:
            events = query_events(run_id=run_id, db_path=db)
            new = events[sent:]
            for event in new:
                await websocket.send_json(
                    TrajectoryEventDTO(**vars(event)).model_dump(mode="json")
                )
            sent += len(new)
            run = get_run(run_id, db_path=db)
            terminal = run is not None and run["status"] in _TERMINAL
            if not new and terminal:
                await websocket.close()
                return
            await asyncio.sleep(poll)
    except WebSocketDisconnect:
        return
