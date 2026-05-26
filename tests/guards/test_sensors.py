"""Tests for the four built-in Sensors in pi_harness.guards.sensors."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pi_harness.guards.sensors import (
    ExitCodeSensor,
    JudgeAgentSensor,
    RegexAssertionSensor,
    TokenBudgetSensor,
)
from pi_harness.guards.types import GuardKind


def _result(output_text="hello world", **kw):
    base = {
        "run_id": "r", "agent_id": "a", "step_id": "s",
        "tool": "bash", "input": {}, "output": {"stdout": output_text},
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# RegexAssertionSensor
# ---------------------------------------------------------------------------


def test_regex_sensor_kind():
    s = RegexAssertionSensor(pattern=r"hello", must_match=True)
    assert s.kind == GuardKind.COMPUTATIONAL_SENSOR


def test_regex_sensor_must_match_passes():
    s = RegexAssertionSensor(pattern=r"hello", must_match=True)
    r = s(_result("hello world"))
    assert r.allow is True


def test_regex_sensor_must_match_fails():
    s = RegexAssertionSensor(pattern=r"goodbye", must_match=True)
    r = s(_result("hello world"))
    assert r.allow is False
    assert "did not match" in r.reason


def test_regex_sensor_must_not_match_passes():
    s = RegexAssertionSensor(pattern=r"error", must_match=False)
    r = s(_result("hello world"))
    assert r.allow is True


def test_regex_sensor_must_not_match_fails():
    s = RegexAssertionSensor(pattern=r"hello", must_match=False)
    r = s(_result("hello world"))
    assert r.allow is False
    assert "should not match" in r.reason


def test_regex_sensor_handles_non_string_output():
    s = RegexAssertionSensor(pattern=r"x", must_match=True)
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "t",
        "input": {}, "output": {"data": [1, 2]},
    })
    # Coerces output to str(...) for matching
    assert r.allow is False


# ---------------------------------------------------------------------------
# ExitCodeSensor
# ---------------------------------------------------------------------------


def test_exit_code_sensor_allows_expected():
    s = ExitCodeSensor(expected_codes={0})
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
        "input": {}, "output": {}, "exit_code": 0,
    })
    assert r.allow is True


def test_exit_code_sensor_denies_unexpected():
    s = ExitCodeSensor(expected_codes={0})
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
        "input": {}, "output": {}, "exit_code": 1,
    })
    assert r.allow is False
    assert "exit code 1" in r.reason


def test_exit_code_sensor_skips_when_no_exit_code():
    s = ExitCodeSensor(expected_codes={0})
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
        "input": {}, "output": {},
    })
    assert r.allow is True
    assert "no exit_code" in r.reason


# ---------------------------------------------------------------------------
# JudgeAgentSensor (OpenAI mocked)
# ---------------------------------------------------------------------------


def _mock_openai_response(verdict: str, confidence: float):
    """Build a mock OpenAI ChatCompletion response."""
    msg = MagicMock()
    msg.content = (
        f'{{"verdict": "{verdict}", "confidence": {confidence}, "reason": "stub"}}'
    )
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@patch("pi_harness.guards.sensors.OpenAI")
def test_judge_agent_sensor_passes(mock_openai_cls):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response("PASS", 0.95)
    mock_openai_cls.return_value = mock_client

    s = JudgeAgentSensor(
        criterion="Output must mention 'success'",
        judge_model="gpt-4o-mini",
        api_key="sk-test",
    )
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
        "input": {}, "output": {"stdout": "task success"},
    })
    assert r.allow is True
    assert r.confidence == 0.95


@patch("pi_harness.guards.sensors.OpenAI")
def test_judge_agent_sensor_fails(mock_openai_cls):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_openai_response("FAIL", 0.8)
    mock_openai_cls.return_value = mock_client

    s = JudgeAgentSensor(
        criterion="Output must mention 'success'",
        judge_model="gpt-4o-mini",
        api_key="sk-test",
    )
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
        "input": {}, "output": {"stdout": "fail"},
    })
    assert r.allow is False
    assert r.confidence == 0.8


@patch("pi_harness.guards.sensors.OpenAI")
def test_judge_agent_sensor_handles_invalid_json(mock_openai_cls):
    mock_client = MagicMock()
    bad = MagicMock()
    bad.choices = [MagicMock(message=MagicMock(content="not json at all"))]
    mock_client.chat.completions.create.return_value = bad
    mock_openai_cls.return_value = mock_client

    s = JudgeAgentSensor(
        criterion="x",
        judge_model="gpt-4o-mini",
        api_key="sk-test",
    )
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "t",
        "input": {}, "output": {},
    })
    assert r.allow is False
    assert r.confidence is None
    assert "parse" in r.reason.lower()


@patch("pi_harness.guards.sensors.OpenAI")
def test_judge_agent_sensor_kind_is_inferential(mock_openai_cls):
    s = JudgeAgentSensor(
        criterion="x", judge_model="gpt-4o-mini", api_key="sk-test",
    )
    assert s.kind == GuardKind.INFERENTIAL_SENSOR


# ---------------------------------------------------------------------------
# TokenBudgetSensor
# ---------------------------------------------------------------------------


def test_token_budget_sensor_allows_under_soft():
    s = TokenBudgetSensor(soft_max=1000, hard_max=2000)
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "t",
        "input": {}, "output": {}, "tokens_in": 100, "tokens_out": 200,
    })
    assert r.allow is True
    assert "under soft" in r.reason


def test_token_budget_sensor_warns_above_soft():
    s = TokenBudgetSensor(soft_max=1000, hard_max=2000)
    # Step 1 consumes 800
    s({
        "run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "t",
        "input": {}, "output": {}, "tokens_in": 400, "tokens_out": 400,
    })
    # Step 2 pushes over soft (now 1100 cumulative)
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s2", "tool": "t",
        "input": {}, "output": {}, "tokens_in": 150, "tokens_out": 150,
    })
    assert r.allow is True   # soft is a warning, not a block
    assert "soft" in r.reason.lower()


def test_token_budget_sensor_denies_above_hard():
    s = TokenBudgetSensor(soft_max=1000, hard_max=2000)
    r = s({
        "run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "t",
        "input": {}, "output": {}, "tokens_in": 1500, "tokens_out": 600,
    })
    assert r.allow is False
    assert "hard" in r.reason.lower()


def test_token_budget_sensor_per_agent():
    s = TokenBudgetSensor(soft_max=1000, hard_max=2000)
    r1 = s({
        "run_id": "r", "agent_id": "agent1", "step_id": "s", "tool": "t",
        "input": {}, "output": {}, "tokens_in": 1500, "tokens_out": 0,
    })
    r2 = s({
        "run_id": "r", "agent_id": "agent2", "step_id": "s", "tool": "t",
        "input": {}, "output": {}, "tokens_in": 100, "tokens_out": 100,
    })
    assert "soft" in r1.reason.lower() or r1.allow is True
    assert r2.allow is True


def test_token_budget_sensor_rejects_inverted_caps():
    import pytest
    with pytest.raises(ValueError, match="hard_max must be >= soft_max"):
        TokenBudgetSensor(soft_max=2000, hard_max=1000)
