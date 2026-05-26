"""Tests for pi_harness.guards.types — GuardKind, GuardResult,
ActionIntent / ActionResult typed dicts, Guide / Sensor protocols, and the
register_guide / register_sensor decorators.
"""

from __future__ import annotations

import textwrap

import pytest

from pi_harness.guards.types import (
    ActionIntent,
    ActionResult,
    GUIDE_REGISTRY,
    GuardKind,
    GuardResult,
    Guide,
    SENSOR_REGISTRY,
    Sensor,
    register_guide,
    register_sensor,
)


# ---------------------------------------------------------------------------
# GuardKind
# ---------------------------------------------------------------------------


def test_guardkind_has_four_quadrants():
    assert GuardKind.COMPUTATIONAL_GUIDE.value == "computational_guide"
    assert GuardKind.INFERENTIAL_GUIDE.value == "inferential_guide"
    assert GuardKind.COMPUTATIONAL_SENSOR.value == "computational_sensor"
    assert GuardKind.INFERENTIAL_SENSOR.value == "inferential_sensor"


# ---------------------------------------------------------------------------
# GuardResult
# ---------------------------------------------------------------------------


def test_guardresult_allow_default_metadata_empty():
    r = GuardResult(allow=True, reason="ok")
    assert r.allow is True
    assert r.reason == "ok"
    assert r.confidence is None
    assert r.metadata == {}


def test_guardresult_deny_with_confidence_and_metadata():
    r = GuardResult(
        allow=False,
        reason="schema fail",
        confidence=0.92,
        metadata={"path": "/x"},
    )
    assert r.allow is False
    assert r.confidence == 0.92
    assert r.metadata["path"] == "/x"


# ---------------------------------------------------------------------------
# ActionIntent / ActionResult typed dicts
# ---------------------------------------------------------------------------


def test_action_intent_required_keys():
    intent: ActionIntent = {
        "run_id": "r1",
        "agent_id": "builder",
        "step_id": "s1",
        "tool": "bash",
        "input": {"cmd": "ls"},
    }
    assert intent["tool"] == "bash"
    assert intent["input"]["cmd"] == "ls"


def test_action_result_required_keys():
    result: ActionResult = {
        "run_id": "r1",
        "agent_id": "builder",
        "step_id": "s1",
        "tool": "bash",
        "input": {"cmd": "ls"},
        "output": {"stdout": "a\nb"},
        "exit_code": 0,
        "duration_ms": 42,
    }
    assert result["exit_code"] == 0


# ---------------------------------------------------------------------------
# Guide / Sensor protocols
# ---------------------------------------------------------------------------


def test_guide_protocol_accepts_callable():
    def my_guide(intent: ActionIntent) -> GuardResult:
        return GuardResult(allow=True, reason="ok")

    g: Guide = my_guide  # type-check only; runtime: assigns
    out = g({
        "run_id": "r", "agent_id": "a", "step_id": "s",
        "tool": "bash", "input": {},
    })
    assert out.allow is True


def test_sensor_protocol_accepts_callable():
    def my_sensor(result: ActionResult) -> GuardResult:
        return GuardResult(allow=True, reason="ok")

    s: Sensor = my_sensor
    out = s({
        "run_id": "r", "agent_id": "a", "step_id": "s",
        "tool": "bash", "input": {}, "output": {},
    })
    assert out.allow is True


def test_guide_must_expose_kind_attribute():
    """Concrete guides/sensors expose .kind; the Protocol does not require it,
    but the GuardRunner inspects it. Verify it's discoverable on a stub."""

    class StubGuide:
        kind = GuardKind.COMPUTATIONAL_GUIDE

        def __call__(self, intent):
            return GuardResult(allow=True, reason="ok")

    s = StubGuide()
    assert s.kind == GuardKind.COMPUTATIONAL_GUIDE


# ---------------------------------------------------------------------------
# register_guide / register_sensor decorators + GUIDE_REGISTRY / SENSOR_REGISTRY
# ---------------------------------------------------------------------------


def test_register_guide_adds_to_registry():
    GUIDE_REGISTRY.clear()

    @register_guide(name="my_guide")
    class MyGuide:
        kind = GuardKind.COMPUTATIONAL_GUIDE

        def __call__(self, intent):
            return GuardResult(allow=True, reason="ok")

    assert "my_guide" in GUIDE_REGISTRY
    assert GUIDE_REGISTRY["my_guide"] is MyGuide


def test_register_sensor_adds_to_registry():
    SENSOR_REGISTRY.clear()

    @register_sensor(name="my_sensor")
    class MySensor:
        kind = GuardKind.COMPUTATIONAL_SENSOR

        def __call__(self, result):
            return GuardResult(allow=True, reason="ok")

    assert "my_sensor" in SENSOR_REGISTRY
    assert SENSOR_REGISTRY["my_sensor"] is MySensor


def test_register_guide_rejects_duplicate_name():
    GUIDE_REGISTRY.clear()

    @register_guide(name="dup")
    class A:
        kind = GuardKind.COMPUTATIONAL_GUIDE

        def __call__(self, intent):
            return GuardResult(allow=True, reason="")

    with pytest.raises(ValueError, match="already registered"):
        @register_guide(name="dup")
        class B:
            kind = GuardKind.COMPUTATIONAL_GUIDE

            def __call__(self, intent):
                return GuardResult(allow=True, reason="")


# ---------------------------------------------------------------------------
# load_user_guards dynamic import discovery
# ---------------------------------------------------------------------------


def test_load_user_guards_imports_files_from_dir(tmp_path):
    from pi_harness.guards import load_user_guards

    GUIDE_REGISTRY.clear()
    SENSOR_REGISTRY.clear()

    guard_file = tmp_path / "my_user_guard.py"
    guard_file.write_text(textwrap.dedent("""
        from pi_harness.guards.types import (
            register_guide, GuardKind, GuardResult
        )

        @register_guide(name="user_x")
        class UserX:
            kind = GuardKind.COMPUTATIONAL_GUIDE
            def __call__(self, intent):
                return GuardResult(allow=True, reason="user")
    """).strip())

    load_user_guards(tmp_path)
    assert "user_x" in GUIDE_REGISTRY


def test_load_user_guards_skips_missing_dir(tmp_path):
    from pi_harness.guards import load_user_guards

    missing = tmp_path / "nope"
    load_user_guards(missing)  # should not raise
