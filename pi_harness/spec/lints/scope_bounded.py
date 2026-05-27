"""Rule: every spec must declare at least one non-goal (explicit scope edge)."""
from __future__ import annotations

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import LintViolation

RULE_NAME = "scope_bounded"


def check(spec: Spec) -> list[LintViolation]:
    if not spec.non_goals:
        return [
            LintViolation(
                rule_name=RULE_NAME,
                severity="error",
                message="non_goals is empty; declare at least one out-of-scope item",
                location="non_goals",
            )
        ]
    return []
