"""Built-in Sensors (feedback, fire after a tool result is observed).

Each sensor is a callable class with a ``kind`` class attribute satisfying
the :class:`pi_harness.guards.types.Sensor` protocol.

* :class:`RegexAssertionSensor` — computational; assert (or assert absence of)
  a regex in the stringified output.
* :class:`ExitCodeSensor` — computational; assert exit codes for bash-like
  tools.
* :class:`JudgeAgentSensor` — inferential; an LLM scores tool output against
  a natural-language criterion (OpenAI-backed in v1).
* :class:`TokenBudgetSensor` — computational; tracks cumulative tokens per
  agent and emits soft / hard warnings.
"""
from __future__ import annotations

import json
import re

from openai import OpenAI

from pi_harness.guards.types import ActionResult, GuardKind, GuardResult


# ---------------------------------------------------------------------------
# RegexAssertionSensor
# ---------------------------------------------------------------------------


class RegexAssertionSensor:
    """Assert that the stringified tool output matches (or doesn't match) a
    pattern.

    Computational. Concatenates all values in ``result["output"]`` with
    ``str()`` and runs ``re.search``. ``must_match=True`` means the pattern
    MUST be present; ``must_match=False`` means it MUST NOT be present.
    """

    kind = GuardKind.COMPUTATIONAL_SENSOR

    def __init__(self, pattern: str, must_match: bool) -> None:
        self.pattern = pattern
        self.regex = re.compile(pattern)
        self.must_match = must_match

    def __call__(self, result: ActionResult) -> GuardResult:
        text = str(result.get("output", ""))
        hit = self.regex.search(text) is not None

        if self.must_match and hit:
            return GuardResult(
                allow=True,
                reason=f"pattern {self.pattern!r} matched",
                metadata={"pattern": self.pattern, "must_match": True},
            )
        if self.must_match and not hit:
            return GuardResult(
                allow=False,
                reason=f"pattern {self.pattern!r} did not match",
                metadata={"pattern": self.pattern, "must_match": True},
            )
        if not self.must_match and hit:
            return GuardResult(
                allow=False,
                reason=f"pattern {self.pattern!r} should not match but did",
                metadata={"pattern": self.pattern, "must_match": False},
            )
        return GuardResult(
            allow=True,
            reason=f"pattern {self.pattern!r} absent (ok)",
            metadata={"pattern": self.pattern, "must_match": False},
        )


# ---------------------------------------------------------------------------
# ExitCodeSensor
# ---------------------------------------------------------------------------


class ExitCodeSensor:
    """Assert that the tool's ``exit_code`` is in ``expected_codes``.

    For bash-like tools that include ``exit_code`` in the result. Tools
    without an ``exit_code`` key pass through.
    """

    kind = GuardKind.COMPUTATIONAL_SENSOR

    def __init__(self, expected_codes: set[int]) -> None:
        self.expected: set[int] = set(expected_codes)

    def __call__(self, result: ActionResult) -> GuardResult:
        if "exit_code" not in result:
            return GuardResult(allow=True, reason="no exit_code in result, skipped")

        code = result["exit_code"]
        if code in self.expected:
            return GuardResult(
                allow=True,
                reason=f"exit code {code} ok",
                metadata={"exit_code": code},
            )
        return GuardResult(
            allow=False,
            reason=f"exit code {code} not in expected {sorted(self.expected)}",
            metadata={"exit_code": code, "expected": sorted(self.expected)},
        )


# ---------------------------------------------------------------------------
# JudgeAgentSensor (inferential, OpenAI-backed)
# ---------------------------------------------------------------------------


JUDGE_SYSTEM_PROMPT = (
    "You are a strict pass/fail judge. Given a criterion and an action result, "
    "decide whether the result satisfies the criterion.\n\n"
    "Respond with ONLY a JSON object of the form:\n"
    '{"verdict": "PASS" | "FAIL", "confidence": <float 0..1>, "reason": "<short>"}'
)


class JudgeAgentSensor:
    """Inferential sensor: an LLM scores tool output against a
    natural-language criterion.

    Uses the OpenAI client directly (no streaming, single completion). v1 is
    OpenAI-only; multi-provider arrives in v2. Returns ``confidence`` from
    the judge's structured JSON. If JSON parse fails, ``allow=False`` and
    ``confidence=None``.
    """

    kind = GuardKind.INFERENTIAL_SENSOR

    def __init__(self, criterion: str, judge_model: str, api_key: str) -> None:
        self.criterion = criterion
        self.judge_model = judge_model
        self._client = OpenAI(api_key=api_key)

    def __call__(self, result: ActionResult) -> GuardResult:
        user_prompt = (
            f"Criterion: {self.criterion}\n\n"
            f"Action tool: {result.get('tool')}\n"
            f"Action input: {json.dumps(result.get('input', {}))[:500]}\n"
            f"Action output: {json.dumps(result.get('output', {}))[:2000]}"
        )

        response = self._client.chat.completions.create(
            model=self.judge_model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return GuardResult(
                allow=False,
                reason=f"judge response parse error: {content[:120]}",
                confidence=None,
                metadata={"raw": content},
            )

        verdict = data.get("verdict", "FAIL")
        confidence = data.get("confidence")
        reason = data.get("reason", "")

        if isinstance(confidence, (int, float)):
            confidence = float(confidence)
        else:
            confidence = None

        return GuardResult(
            allow=(verdict == "PASS"),
            reason=f"{verdict}: {reason}",
            confidence=confidence,
            metadata={"criterion": self.criterion, "model": self.judge_model},
        )


# ---------------------------------------------------------------------------
# TokenBudgetSensor
# ---------------------------------------------------------------------------


class TokenBudgetSensor:
    """Track cumulative tokens per agent across a run; warn at soft, deny at
    hard.

    Reads ``tokens_in`` + ``tokens_out`` from the result (pi-agent records
    these). Soft breach -> ``allow=True`` with reason mentioning "soft"
    (advisory). Hard breach -> ``allow=False`` (the next step gets a deny
    signal).
    """

    kind = GuardKind.COMPUTATIONAL_SENSOR

    def __init__(self, soft_max: int, hard_max: int) -> None:
        if hard_max < soft_max:
            raise ValueError("hard_max must be >= soft_max")
        self.soft_max = soft_max
        self.hard_max = hard_max
        self._totals: dict[str, int] = {}

    def __call__(self, result: ActionResult) -> GuardResult:
        agent = result.get("agent_id", "")
        used = int(result.get("tokens_in", 0)) + int(result.get("tokens_out", 0))
        total = self._totals.get(agent, 0) + used
        self._totals[agent] = total

        if total > self.hard_max:
            return GuardResult(
                allow=False,
                reason=f"hard token budget exceeded: {total}/{self.hard_max}",
                metadata={"total": total, "hard_max": self.hard_max},
            )
        if total > self.soft_max:
            return GuardResult(
                allow=True,
                reason=f"soft budget exceeded: {total}/{self.soft_max}",
                metadata={"total": total, "soft_max": self.soft_max},
            )
        return GuardResult(
            allow=True,
            reason=f"under soft budget: {total}/{self.soft_max}",
            metadata={"total": total},
        )


__all__ = [
    "ExitCodeSensor",
    "JudgeAgentSensor",
    "RegexAssertionSensor",
    "TokenBudgetSensor",
]
