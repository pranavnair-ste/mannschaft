"""Rule: spec must have at least one acceptance criterion >= 3 words."""
from __future__ import annotations

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import LintViolation

RULE_NAME = "required_acceptance"
MIN_WORDS = 3


def check(spec: Spec) -> list[LintViolation]:
    if not spec.acceptance_criteria:
        return [
            LintViolation(
                rule_name=RULE_NAME,
                severity="error",
                message="acceptance_criteria is empty; at least one criterion required",
                location="acceptance_criteria",
            )
        ]
    has_long_enough = any(
        len(item.split()) >= MIN_WORDS for item in spec.acceptance_criteria
    )
    if not has_long_enough:
        return [
            LintViolation(
                rule_name=RULE_NAME,
                severity="error",
                message=f"every acceptance criterion is shorter than {MIN_WORDS} words",
                location="acceptance_criteria",
            )
        ]
    return []
