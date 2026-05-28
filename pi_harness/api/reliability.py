"""Derived reliability scores for a run's events.

Plan 2 emits no per-agent reliability scores, so the dashboard derives four
dimensions heuristically from event stats. These are a first pass (see the
adapted plan's Unresolved decisions) -- each is a fraction in [0, 1] or None
when there's no signal for it.
"""
from __future__ import annotations

from typing import Any, Iterable

Scores = dict[str, float | None]


def compute_reliability(events: Iterable[Any]) -> Scores:
    events = list(events)
    if not events:
        return {"consistency": None, "robustness": None, "predictability": None, "safety": None}

    # safety: fraction of guide/sensor firings that allowed the action
    firings = [e for e in events if e.classification in ("guide_fired", "sensor_fired")]
    if firings:
        allowed = sum(
            1 for e in firings if (e.output or {}).get("_guard_meta", {}).get("allow") is True
        )
        safety: float | None = allowed / len(firings)
    else:
        safety = None

    # robustness: 1 - fraction of events with an error outcome
    errors = sum(1 for e in events if e.outcome == "error")
    robustness = 1.0 - errors / len(events)

    # predictability: fraction of tool calls that produced a matching tool_result
    calls = [e for e in events if e.classification == "tool_call"]
    result_steps = {e.step_id for e in events if e.classification == "tool_result"}
    if calls:
        matched = sum(1 for e in calls if e.step_id in result_steps)
        predictability: float | None = matched / len(calls)
    else:
        predictability = None

    # consistency: 1 - (distinct tools / total tool calls), i.e. repeated tool use
    tool_calls = [e for e in events if e.classification == "tool_call" and e.tool]
    if tool_calls:
        distinct = len({e.tool for e in tool_calls})
        consistency: float | None = max(0.0, min(1.0, 1.0 - distinct / len(tool_calls)))
    else:
        consistency = None

    return {
        "consistency": consistency,
        "robustness": robustness,
        "predictability": predictability,
        "safety": safety,
    }
