"""Tests for pi_harness.guards.runner.GuardRunner — the per-(run, agent)
orchestrator that wraps pi-coding-agent's tool stream.
"""

from __future__ import annotations

from unittest.mock import patch

from pi_harness.guards.guides import AllowlistGuide
from pi_harness.guards.runner import GuardRunner
from pi_harness.guards.sensors import RegexAssertionSensor
from pi_harness.guards.types import GuardKind, GuardResult


# ---------------------------------------------------------------------------
# Skeleton: construct + attach
# ---------------------------------------------------------------------------


def test_guard_runner_construct():
    r = GuardRunner(run_id="run1", agent_id="builder")
    assert r.run_id == "run1"
    assert r.agent_id == "builder"
    assert r.guides == []
    assert r.sensors == []


def test_guard_runner_attach_guides():
    r = GuardRunner(run_id="run1", agent_id="builder")
    g = AllowlistGuide(allowed_tools=["bash"])
    r.attach_guides([g])
    assert r.guides == [g]


def test_guard_runner_attach_sensors():
    r = GuardRunner(run_id="run1", agent_id="builder")
    s = RegexAssertionSensor(pattern=r"x", must_match=True)
    r.attach_sensors([s])
    assert r.sensors == [s]


def test_guard_runner_attach_extends_not_replaces():
    r = GuardRunner(run_id="run1", agent_id="builder")
    g1 = AllowlistGuide(allowed_tools=["a"])
    g2 = AllowlistGuide(allowed_tools=["b"])
    r.attach_guides([g1])
    r.attach_guides([g2])
    assert r.guides == [g1, g2]


# ---------------------------------------------------------------------------
# Test fixtures: simple guide / sensor stubs that record calls
# ---------------------------------------------------------------------------


class AlwaysAllow:
    kind = GuardKind.COMPUTATIONAL_GUIDE

    def __init__(self):
        self.calls = 0

    def __call__(self, intent):
        self.calls += 1
        return GuardResult(allow=True, reason="allow")


class AlwaysDeny:
    kind = GuardKind.COMPUTATIONAL_GUIDE

    def __init__(self):
        self.calls = 0

    def __call__(self, intent):
        self.calls += 1
        return GuardResult(allow=False, reason="deny", metadata={"why": "test"})


def _intent():
    return {
        "run_id": "r", "agent_id": "a", "step_id": "s1",
        "tool": "bash", "input": {},
    }


# ---------------------------------------------------------------------------
# intercept_tool_call — short-circuit chain + event emission
# ---------------------------------------------------------------------------


@patch("pi_harness.guards.runner.write_event")
def test_intercept_allows_when_all_guides_allow(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    g1, g2 = AlwaysAllow(), AlwaysAllow()
    r.attach_guides([g1, g2])

    result = r.intercept_tool_call(_intent())
    assert result.allow is True
    assert g1.calls == 1 and g2.calls == 1


@patch("pi_harness.guards.runner.write_event")
def test_intercept_short_circuits_on_first_deny(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    deny = AlwaysDeny()
    after = AlwaysAllow()
    r.attach_guides([deny, after])

    result = r.intercept_tool_call(_intent())
    assert result.allow is False
    assert deny.calls == 1
    assert after.calls == 0   # short-circuited


@patch("pi_harness.guards.runner.write_event")
def test_intercept_writes_guide_fired_event_on_deny(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    r.attach_guides([AlwaysDeny()])

    r.intercept_tool_call(_intent())

    assert mock_write.call_count == 1
    # write_event(event, db_path=None) — event is positional[0]
    event = mock_write.call_args.args[0]
    assert event.classification == "guide_fired"
    assert event.outcome == "blocked"
    assert event.output["_guard_meta"]["allow"] is False
    assert event.output["_guard_meta"]["guide"] == "AlwaysDeny"
    assert event.run_id == "r"
    assert event.agent_id == "a"


@patch("pi_harness.guards.runner.write_event")
def test_intercept_writes_guide_fired_event_on_allow_too(mock_write):
    """Allow events are still recorded — needed for promote analysis."""
    r = GuardRunner(run_id="r", agent_id="a")
    r.attach_guides([AlwaysAllow()])

    r.intercept_tool_call(_intent())

    assert mock_write.call_count == 1
    event = mock_write.call_args.args[0]
    assert event.classification == "guide_fired"
    assert event.outcome == "success"
    assert event.output["_guard_meta"]["allow"] is True
    assert event.output["_guard_meta"]["guide"] == "AlwaysAllow"


@patch("pi_harness.guards.runner.write_event")
def test_intercept_with_no_guides_returns_allow(mock_write):
    """A runner with no guides allows everything through."""
    r = GuardRunner(run_id="r", agent_id="a")
    result = r.intercept_tool_call(_intent())
    assert result.allow is True
    assert mock_write.call_count == 0


# ---------------------------------------------------------------------------
# intercept_tool_result — all sensors run, no short-circuit
# ---------------------------------------------------------------------------


class AlwaysAllowSensor:
    kind = GuardKind.COMPUTATIONAL_SENSOR

    def __init__(self):
        self.calls = 0

    def __call__(self, result):
        self.calls += 1
        return GuardResult(allow=True, reason="sensor allow")


class AlwaysDenySensor:
    kind = GuardKind.COMPUTATIONAL_SENSOR

    def __init__(self):
        self.calls = 0

    def __call__(self, result):
        self.calls += 1
        return GuardResult(allow=False, reason="sensor deny")


def _result():
    return {
        "run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "bash",
        "input": {}, "output": {"stdout": "x"},
    }


@patch("pi_harness.guards.runner.write_event")
def test_intercept_tool_result_runs_all_sensors(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    s1, s2 = AlwaysAllowSensor(), AlwaysDenySensor()
    r.attach_sensors([s1, s2])

    results = r.intercept_tool_result(_result())
    assert len(results) == 2
    assert s1.calls == 1 and s2.calls == 1  # all run, no short-circuit


@patch("pi_harness.guards.runner.write_event")
def test_intercept_tool_result_writes_one_event_per_sensor(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    r.attach_sensors([AlwaysAllowSensor(), AlwaysDenySensor()])

    r.intercept_tool_result(_result())

    assert mock_write.call_count == 2
    classifications = [c.args[0].classification for c in mock_write.call_args_list]
    assert classifications == ["sensor_fired", "sensor_fired"]
    outcomes = [c.args[0].outcome for c in mock_write.call_args_list]
    assert outcomes == ["success", "blocked"]
    allows = [
        c.args[0].output["_guard_meta"]["allow"]
        for c in mock_write.call_args_list
    ]
    assert allows == [True, False]
    sensors = [
        c.args[0].output["_guard_meta"]["sensor"]
        for c in mock_write.call_args_list
    ]
    assert sensors == ["AlwaysAllowSensor", "AlwaysDenySensor"]
    # Real tool output preserved alongside _guard_meta
    real_outputs = [c.args[0].output.get("stdout") for c in mock_write.call_args_list]
    assert real_outputs == ["x", "x"]


@patch("pi_harness.guards.runner.write_event")
def test_intercept_tool_result_no_sensors_returns_empty(mock_write):
    r = GuardRunner(run_id="r", agent_id="a")
    results = r.intercept_tool_result(_result())
    assert results == []
    assert mock_write.call_count == 0


# ---------------------------------------------------------------------------
# Public re-export
# ---------------------------------------------------------------------------


def test_guard_runner_reexported_from_package():
    from pi_harness.guards import GuardRunner as TopLevel
    from pi_harness.guards.runner import GuardRunner as Internal
    assert TopLevel is Internal
