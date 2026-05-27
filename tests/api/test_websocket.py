from __future__ import annotations

import time

import pytest
from starlette.websockets import WebSocketDisconnect


def test_websocket_streams_events_for_run(client, seed_run):
    client.app.state.ws_poll_interval = 0.01
    seed_run("r-1")  # writes a tool_call + guide_fired event; run is succeeded
    msgs = []
    with client.websocket_connect("/ws/runs/r-1") as ws:
        try:
            while True:
                msgs.append(ws.receive_json())
        except WebSocketDisconnect:
            pass
    assert len(msgs) == 2
    assert {m["classification"] for m in msgs} == {"tool_call", "guide_fired"}


def test_websocket_unknown_run_closes_4404(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/runs/nope") as ws:
            ws.receive_json()
    assert exc.value.code == 4404


def test_websocket_first_event_under_500ms(client, seed_run):
    client.app.state.ws_poll_interval = 0.01
    seed_run("r-1")
    start = time.perf_counter()
    with client.websocket_connect("/ws/runs/r-1") as ws:
        ws.receive_json()
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5
