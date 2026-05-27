from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from pi_harness.api.reliability import compute_reliability


@dataclass
class _Ev:
    classification: str
    outcome: str = "success"
    step_id: str = "s"
    tool: str = ""
    output: dict[str, Any] | None = None


def test_empty_events_all_none():
    assert compute_reliability([]) == {
        "consistency": None, "robustness": None, "predictability": None, "safety": None,
    }


def test_mixed_events_scores():
    events = [
        _Ev("tool_call", "success", "s1", "edit"),
        _Ev("tool_result", "success", "s1"),
        _Ev("tool_call", "error", "s2", "edit"),
        _Ev("guide_fired", "success", "g1", output={"_guard_meta": {"allow": True}}),
        _Ev("sensor_fired", "blocked", "x1", output={"_guard_meta": {"allow": False}}),
    ]
    scores = compute_reliability(events)
    assert scores["safety"] == pytest.approx(0.5)  # 1 of 2 firings allowed
    assert scores["robustness"] == pytest.approx(0.8)  # 1 error / 5 events
    assert scores["predictability"] == pytest.approx(0.5)  # s1 matched, s2 not
    assert scores["consistency"] == pytest.approx(0.5)  # 2 calls, 1 distinct tool


def test_no_firings_safety_none():
    scores = compute_reliability([_Ev("tool_call", "success", "s1", "edit")])
    assert scores["safety"] is None
    assert scores["robustness"] == pytest.approx(1.0)


def test_reliability_route(client, seed_run):
    seed_run("r-1")  # 1 tool_call + 1 guide_fired (allow=True)
    r = client.get("/runs/r-1/reliability")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"consistency", "robustness", "predictability", "safety"}
    assert body["safety"] == pytest.approx(1.0)  # the one guide_fired allowed


def test_reliability_404(client):
    assert client.get("/runs/nope/reliability").status_code == 404
