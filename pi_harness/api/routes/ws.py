"""WebSocket event tailer.

Plan 2 has no live event bus, so this polls the trajectory db. Each tick it
fetches only events whose rowid is greater than the last one streamed (the
rowid is the only monotonic append cursor — (ts, step_id) is not monotonic
across concurrent writers, so a count-based index silently skips out-of-order
inserts). The db read runs in a threadpool so it never blocks the event loop,
and a poll-count cap guarantees a non-terminal run eventually disconnects
rather than tailing forever. It closes once a poll yields no new events AND the
run has reached a terminal status. Once the live-capture wrapper (Phase 6)
writes events faster, this same loop streams them.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from pi_harness.api.models import TrajectoryEventDTO
from pi_harness.trajectory.runs import get_run
from pi_harness.trajectory.store import query_events_after

logger = logging.getLogger(__name__)

router = APIRouter()

_TERMINAL = {"succeeded", "failed", "cancelled"}

# Cap on how many polls a single connection will run before disconnecting, so a
# stuck non-terminal run can't keep a socket + poll loop alive indefinitely.
_DEFAULT_MAX_POLLS = 3600


@router.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str) -> None:
    db = websocket.app.state.config.trajectory_db_path
    if await run_in_threadpool(get_run, run_id, db_path=db) is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    poll = getattr(websocket.app.state, "ws_poll_interval", 1.0)
    max_polls = getattr(websocket.app.state, "ws_max_polls", _DEFAULT_MAX_POLLS)
    last_id = 0
    polls = 0
    try:
        while True:
            # Threadpool so the sync sqlite read never blocks the event loop;
            # cursor on rowid so we fetch only new rows, not the whole run.
            rows = await run_in_threadpool(
                query_events_after, run_id, last_id, db_path=db
            )
            for ev_id, event in rows:
                await websocket.send_json(
                    TrajectoryEventDTO(**vars(event)).model_dump(mode="json")
                )
                last_id = ev_id
            run = await run_in_threadpool(get_run, run_id, db_path=db)
            terminal = run is not None and run["status"] in _TERMINAL
            if not rows and terminal:
                await websocket.close()
                return
            polls += 1
            if polls >= max_polls:
                await websocket.close(code=4408)  # tailer aged out
                return
            await asyncio.sleep(poll)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001 — DB/send error: close cleanly, don't leak the socket
        logger.warning("ws_run: closing run %s after error", run_id, exc_info=True)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        return
