"""Rule: each acceptance criterion should be measurable (digit, unit, or verb)."""
from __future__ import annotations

import re

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import LintViolation

RULE_NAME = "measurable_criteria"

_DIGIT_RE = re.compile(r"\d")
_UNIT_RE = re.compile(
    r"\b(ms|s|sec|seconds|minutes|hours|kb|mb|gb|%|px|req/s)\b", re.IGNORECASE
)
_TEST_HINT_RE = re.compile(r"`[^`]+`|\bpytest\b|\bnpm test\b|\buv run\b|\bbash \$|\bcurl\b")
_OBSERVABLE_RE = re.compile(
    r"\b(returns?|exits?|responds?|writes?|creates?|deletes?|produces?)\b", re.IGNORECASE
)


def _is_measurable(line: str) -> bool:
    return bool(
        _DIGIT_RE.search(line)
        or _UNIT_RE.search(line)
        or _TEST_HINT_RE.search(line)
        or _OBSERVABLE_RE.search(line)
    )


def check(spec: Spec) -> list[LintViolation]:
    out: list[LintViolation] = []
    for idx, item in enumerate(spec.acceptance_criteria):
        if not _is_measurable(item):
            out.append(
                LintViolation(
                    rule_name=RULE_NAME,
                    severity="warning",
                    message=(
                        "criterion has no measurable signal "
                        "(no number, unit, test command, or observable verb)"
                    ),
                    location=f"acceptance_criteria[{idx}]",
                )
            )
    return out
