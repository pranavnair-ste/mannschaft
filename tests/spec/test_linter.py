"""Tests for the linter aggregation, scoring, and per-rule behavior."""
from __future__ import annotations

import pytest

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import Linter, LintResult, LintViolation


def _spec(**overrides) -> Spec:
    defaults = dict(
        id="spec-x",
        title="t",
        goal="Let users cancel an in-flight upload",
        acceptance_criteria=[
            "The endpoint returns 200 within 200ms",
            "The worker writes a marker file to disk",
        ],
        constraints=[],
        non_goals=["Pagination is out of scope"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=None,
        status="draft",
    )
    defaults.update(overrides)
    return Spec(**defaults)


# ---------- aggregation + scoring ----------


def test_clean_spec_scores_one() -> None:
    result = Linter().lint(_spec())
    assert result.errors == []
    assert result.warnings == []
    assert result.score == 1.0


def test_lint_result_shape() -> None:
    result = Linter().lint(_spec())
    assert isinstance(result, LintResult)
    assert isinstance(result.errors, list)
    assert isinstance(result.warnings, list)
    assert 0.0 <= result.score <= 1.0


def test_violations_property_combines_errors_and_warnings() -> None:
    result = Linter().lint(_spec(acceptance_criteria=[], goal="make it simple"))
    # at least one error (empty AC) + at least one warning (vague 'simple')
    assert result.errors and result.warnings
    assert result.violations == [*result.errors, *result.warnings]


def test_violation_carries_rule_name_and_location() -> None:
    bad = _spec(acceptance_criteria=[])
    result = Linter().lint(bad)
    assert any(v.rule_name == "required_acceptance" for v in result.errors)
    v = next(v for v in result.errors if v.rule_name == "required_acceptance")
    assert isinstance(v, LintViolation)
    assert v.severity == "error"
    assert v.message
    assert v.location


def test_error_drops_score_below_one() -> None:
    result = Linter().lint(_spec(acceptance_criteria=[]))
    assert result.score < 1.0


def test_warnings_only_keeps_score_above_threshold() -> None:
    result = Linter().lint(_spec(goal="a simple and easy thing"))
    assert result.errors == []
    assert any(v.severity == "warning" for v in result.warnings)
    assert result.score < 1.0
    assert result.score >= 0.9


def test_linter_discovers_all_four_rules() -> None:
    rules = set(Linter().rule_names())
    assert {
        "required_acceptance",
        "vague_terms",
        "scope_bounded",
        "measurable_criteria",
    } <= rules


# ---------- required_acceptance ----------


def test_required_acceptance_fails_on_empty() -> None:
    result = Linter().lint(_spec(acceptance_criteria=[]))
    rule_errors = [v for v in result.errors if v.rule_name == "required_acceptance"]
    assert len(rule_errors) == 1
    assert "empty" in rule_errors[0].message.lower()


def test_required_acceptance_fails_when_all_too_short() -> None:
    result = Linter().lint(_spec(acceptance_criteria=["one two", "ok"]))
    rule_errors = [v for v in result.errors if v.rule_name == "required_acceptance"]
    assert len(rule_errors) == 1
    assert "3" in rule_errors[0].message or "three" in rule_errors[0].message.lower()


def test_required_acceptance_passes_with_one_long_enough() -> None:
    result = Linter().lint(_spec(acceptance_criteria=["the worker writes a file", "ok"]))
    rule_errors = [v for v in result.errors if v.rule_name == "required_acceptance"]
    assert rule_errors == []


# ---------- vague_terms ----------


def test_vague_terms_flags_each_occurrence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PI_HARNESS_VAGUE_WORDS", raising=False)
    s = _spec(
        goal="It should be simple and fast",
        acceptance_criteria=["The UI feels intuitive when scrolling smoothly enough"],
    )
    result = Linter().lint(s)
    vague = [v for v in result.warnings if v.rule_name == "vague_terms"]
    # goal: should, simple, fast -> 3; ac[0]: intuitive -> 1 (smoothly != smooth)
    assert len(vague) == 4


def test_vague_terms_is_case_insensitive() -> None:
    result = Linter().lint(_spec(goal="Make it ROBUST"))
    vague = [v for v in result.warnings if v.rule_name == "vague_terms"]
    assert len(vague) == 1
    assert vague[0].severity == "warning"


def test_vague_terms_configurable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_HARNESS_VAGUE_WORDS", "fluffy,kinda")
    s = _spec(goal="A fluffy and robust system")
    result = Linter().lint(s)
    vague = [v for v in result.warnings if v.rule_name == "vague_terms"]
    assert len(vague) == 1
    assert "fluffy" in vague[0].message.lower()


def test_vague_terms_location_carries_field_and_line() -> None:
    result = Linter().lint(
        _spec(acceptance_criteria=["the worker writes a file", "this should be measurable in 5s"])
    )
    vague = [v for v in result.warnings if v.rule_name == "vague_terms"]
    assert len(vague) == 1
    assert "acceptance_criteria" in vague[0].location
    assert "line=2" in vague[0].location


# ---------- scope_bounded ----------


def test_scope_bounded_fails_on_empty_non_goals() -> None:
    result = Linter().lint(_spec(non_goals=[]))
    rule_errors = [v for v in result.errors if v.rule_name == "scope_bounded"]
    assert len(rule_errors) == 1
    assert rule_errors[0].location == "non_goals"


def test_scope_bounded_passes_with_non_goal() -> None:
    result = Linter().lint(_spec(non_goals=["resuming after cancel"]))
    rule_errors = [v for v in result.errors if v.rule_name == "scope_bounded"]
    assert rule_errors == []


# ---------- measurable_criteria ----------


def test_measurable_criteria_warns_on_unmeasurable() -> None:
    result = Linter().lint(
        _spec(acceptance_criteria=["the experience is delightful and polished"])
    )
    warn = [v for v in result.warnings if v.rule_name == "measurable_criteria"]
    assert len(warn) == 1
    assert "measurable" in warn[0].message.lower()


def test_measurable_criteria_accepts_digit() -> None:
    result = Linter().lint(_spec(acceptance_criteria=["cancellation aborts within 200ms"]))
    warn = [v for v in result.warnings if v.rule_name == "measurable_criteria"]
    assert warn == []


def test_measurable_criteria_accepts_observable_verb() -> None:
    result = Linter().lint(
        _spec(acceptance_criteria=["pressing cancel returns the user to the upload screen"])
    )
    warn = [v for v in result.warnings if v.rule_name == "measurable_criteria"]
    assert warn == []


def test_measurable_criteria_accepts_test_command() -> None:
    result = Linter().lint(
        _spec(acceptance_criteria=["`pytest tests/upload/test_cancel.py` passes"])
    )
    warn = [v for v in result.warnings if v.rule_name == "measurable_criteria"]
    assert warn == []
