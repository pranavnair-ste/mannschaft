"""Rule: warn on vague language. Wordlist configurable via env var."""
from __future__ import annotations

import os
import re

from pi_harness.spec.format import Spec
from pi_harness.spec.linter import LintViolation

RULE_NAME = "vague_terms"

_DEFAULT_WORDS = (
    "simple",
    "easy",
    "fast",
    "should",
    "robust",
    "scalable",
    "smooth",
    "intuitive",
)


def _active_wordlist() -> tuple[str, ...]:
    raw = os.environ.get("PI_HARNESS_VAGUE_WORDS")
    if raw is None:
        return _DEFAULT_WORDS
    return tuple(w.strip().lower() for w in raw.split(",") if w.strip())


def _scan(field_name: str, lines: list[str], words: tuple[str, ...]) -> list[LintViolation]:
    if not words:
        return []
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE
    )
    out: list[LintViolation] = []
    for idx, line in enumerate(lines, start=1):
        for m in pattern.finditer(line):
            term = m.group(1).lower()
            out.append(
                LintViolation(
                    rule_name=RULE_NAME,
                    severity="warning",
                    message=f"vague term '{term}' — replace with a measurable phrase",
                    location=f"{field_name}:line={idx}",
                )
            )
    return out


def check(spec: Spec) -> list[LintViolation]:
    words = _active_wordlist()
    violations: list[LintViolation] = []
    violations += _scan("goal", [spec.goal], words)
    violations += _scan("acceptance_criteria", list(spec.acceptance_criteria), words)
    violations += _scan("constraints", list(spec.constraints), words)
    violations += _scan("non_goals", list(spec.non_goals), words)
    return violations
