"""Tests for pi_harness.guards.promote — the offline analysis pass that
turns oft-firing inferential sensors into stub Guides.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from pi_harness.guards.promote import PromotionSuggestion, suggest_promotions
from pi_harness.trajectory.schema import TrajectoryEvent


# ---------------------------------------------------------------------------
# PromotionSuggestion dataclass
# ---------------------------------------------------------------------------


def test_promotion_suggestion_fields():
    s = PromotionSuggestion(
        sensor_name="JudgeAgentSensor",
        sensor_criterion="x",
        fires=25,
        allow_fraction=0.92,
        suggested_stub_code="class FooGuide: ...",
        suggested_kind="computational_guide",
        evidence={"sample_outputs": []},
    )
    assert s.fires == 25
    assert s.allow_fraction == 0.92
    assert "FooGuide" in s.suggested_stub_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sensor_event(
    sensor_name: str,
    criterion: str,
    allow: bool,
    idx: int,
    *,
    input_payload: dict | None = None,
    output_payload: dict | None = None,
) -> TrajectoryEvent:
    """Build a sensor_fired TrajectoryEvent matching what GuardRunner emits.

    ``allow`` -> ``outcome="success"``, deny -> ``outcome="blocked"`` (this is
    the mapping the runner applies; promote reads ``_guard_meta.allow`` so
    that's the authoritative flag).
    """
    base_output = dict(output_payload or {"stdout": "ok"})
    base_output["_guard_meta"] = {
        "sensor": sensor_name,
        "sensor_kind": "inferential_sensor",
        "reason": f"sample {idx}",
        "confidence": 0.9,
        "guard_metadata": {"criterion": criterion, "model": "gpt-4o-mini"},
        "allow": allow,
    }
    return TrajectoryEvent(
        run_id="r",
        agent_id="a",
        step_id=f"step{idx}",
        ts=datetime.now(timezone.utc),
        model="",
        tool="bash",
        input=dict(input_payload or {"cmd": "ls"}),
        output=base_output,
        duration_ms=0,
        tokens_in=0,
        tokens_out=0,
        outcome="success" if allow else "blocked",
        classification="sensor_fired",
    )


# ---------------------------------------------------------------------------
# Group + filter behaviour
# ---------------------------------------------------------------------------


@patch("pi_harness.guards.promote.query_events")
def test_no_candidates_when_too_few_fires(mock_q):
    mock_q.return_value = [
        _sensor_event("JudgeAgentSensor", "be polite", True, i)
        for i in range(5)
    ]
    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert out == []


@patch("pi_harness.guards.promote.query_events")
def test_no_candidates_when_high_variance(mock_q):
    # 13 allow / 12 deny = ~52% / 48% -> variance ~0.48 > 0.1
    events = (
        [_sensor_event("JudgeAgentSensor", "be polite", True, i) for i in range(13)]
        + [_sensor_event("JudgeAgentSensor", "be polite", False, i + 13) for i in range(12)]
    )
    mock_q.return_value = events
    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert out == []


@patch("pi_harness.guards.promote.query_events")
def test_candidate_emitted_with_23_allow_2_deny(mock_q):
    # Acceptance-criteria case: 25 fires, 23 PASS / 2 FAIL, allow_fraction = 0.92
    events = (
        [_sensor_event("JudgeAgentSensor", "must mention success", True, i)
         for i in range(23)]
        + [_sensor_event("JudgeAgentSensor", "must mention success", False, i + 23)
           for i in range(2)]
    )
    mock_q.return_value = events
    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert len(out) == 1
    sug = out[0]
    assert sug.sensor_name == "JudgeAgentSensor"
    assert sug.fires == 25
    assert abs(sug.allow_fraction - 0.92) < 0.001
    assert "must mention success" in sug.sensor_criterion


@patch("pi_harness.guards.promote.query_events")
def test_skips_non_sensor_events(mock_q):
    """Events with classification != sensor_fired must be ignored."""
    sensor_events = [
        _sensor_event("JudgeAgentSensor", "x", True, i) for i in range(25)
    ]
    # Pollute with a guide_fired event with the same metadata shape
    guide_event = TrajectoryEvent(
        run_id="r", agent_id="a", step_id="g1",
        ts=datetime.now(timezone.utc),
        model="", tool="bash",
        input={}, output={"_guard_meta": {"sensor_kind": "inferential_sensor"}},
        duration_ms=0, tokens_in=0, tokens_out=0,
        outcome="success",
        classification="guide_fired",
    )
    mock_q.return_value = sensor_events + [guide_event]
    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert len(out) == 1
    assert out[0].fires == 25


@patch("pi_harness.guards.promote.query_events")
def test_skips_computational_sensors(mock_q):
    """Only inferential sensors are promotion candidates — computational
    sensors are already deterministic and need no upgrade.
    """
    events = []
    for i in range(25):
        ev = _sensor_event("RegexAssertionSensor", "x", True, i)
        ev.output["_guard_meta"]["sensor_kind"] = "computational_sensor"
        events.append(ev)
    mock_q.return_value = events
    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert out == []


# ---------------------------------------------------------------------------
# Stub generation
# ---------------------------------------------------------------------------


@patch("pi_harness.guards.promote.query_events")
def test_stub_for_regex_extractable_outputs(mock_q):
    """When sensor outputs share a substring, suggest a RegexAssertionSensor stub."""
    events = []
    for i in range(25):
        # All these sample outputs contain the literal "STATUS: OK"
        ev = _sensor_event(
            "JudgeAgentSensor", "output mentions OK", True, i,
            output_payload={"stdout": f"line {i}\nSTATUS: OK\ndone"},
        )
        events.append(ev)
    mock_q.return_value = events

    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert len(out) == 1
    code = out[0].suggested_stub_code
    # The generated stub should be syntactically valid Python and reference one
    # of the built-ins it could become.
    assert "class" in code
    assert "Guide" in code or "Sensor" in code
    assert "@register_guide" in code or "@register_sensor" in code
    # And it should be importable as Python source
    compile(code, "<stub>", "exec")


@patch("pi_harness.guards.promote.query_events")
def test_stub_for_schema_extractable_inputs(mock_q):
    """When all allow-fires share an input-key shape, the stub uses
    SchemaValidatorGuide.
    """
    events = []
    for i in range(25):
        ev = _sensor_event(
            "JudgeAgentSensor", "input has path key", True, i,
            input_payload={"path": f"/tmp/file{i}.txt", "encoding": "utf-8"},
            # Diverse outputs so the regex strategy doesn't pick first
            output_payload={"stdout": f"random text {i} differently every time"},
        )
        events.append(ev)
    mock_q.return_value = events

    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    assert len(out) == 1
    code = out[0].suggested_stub_code
    assert "SchemaValidatorGuide" in code or "RegexAssertionSensor" in code
    compile(code, "<stub>", "exec")
    assert out[0].suggested_kind in {"computational_guide", "computational_sensor"}


@patch("pi_harness.guards.promote.query_events")
def test_stub_includes_evidence_comment(mock_q):
    events = [
        _sensor_event("JudgeAgentSensor", "be careful", True, i)
        for i in range(23)
    ]
    events += [
        _sensor_event("JudgeAgentSensor", "be careful", False, i + 23)
        for i in range(2)
    ]
    mock_q.return_value = events

    out = suggest_promotions(min_fires=20, low_variance_threshold=0.1)
    code = out[0].suggested_stub_code
    # Stub should comment why it was suggested
    assert "23/25" in code or "0.92" in code or "promoted from" in code.lower()
