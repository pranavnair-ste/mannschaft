"""Linter: runs every discovered rule, aggregates violations, computes score."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pi_harness.spec.format import Spec
from pi_harness.spec.lints import all_rules

Severity = Literal["error", "warning"]


@dataclass
class LintViolation:
    rule_name: str
    severity: Severity
    message: str
    location: str  # e.g. "acceptance_criteria[0]" or "goal:line=3"


@dataclass
class LintResult:
    errors: list[LintViolation] = field(default_factory=list)
    warnings: list[LintViolation] = field(default_factory=list)
    score: float = 1.0

    @property
    def violations(self) -> list[LintViolation]:
        """All violations, errors first. Convenience for callers (CLI display)
        that don't care about the error/warning split."""
        return [*self.errors, *self.warnings]


class Linter:
    """Aggregates discovered lint rules into a LintResult."""

    def __init__(self) -> None:
        self._rules = all_rules()

    def rule_names(self) -> list[str]:
        return sorted(self._rules)

    def lint(self, spec: Spec) -> LintResult:
        errors: list[LintViolation] = []
        warnings: list[LintViolation] = []
        for _, mod in self._rules.items():
            for v in mod.check(spec):
                if v.severity == "error":
                    errors.append(v)
                else:
                    warnings.append(v)
        score = self._score(errors, warnings)
        return LintResult(errors=errors, warnings=warnings, score=score)

    @staticmethod
    def _score(errors: list[LintViolation], warnings: list[LintViolation]) -> float:
        score = 1.0
        if errors:
            score -= 0.5
        score -= 0.1 * (min(len(warnings), 5) / 5.0)
        return max(0.0, round(score, 4))
