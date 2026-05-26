"""Promote-to-Guide — offline analysis of sensor history.

When an inferential sensor (typically :class:`JudgeAgentSensor`) fires many
times with low-variance outcomes, the same decision can be cheaply
hard-coded. This module scans the trajectory store for such sensors and
produces stub Guide code the user can review and install at
``~/.pi-harness/guards/<name>.py``.

No LLM is involved here. The user's "promote" decision is still manual:
they read the stub, accept it, drop it in the guards directory, and on next
run :func:`pi_harness.guards.load_user_guards` picks it up.

Reading sensor metadata
-----------------------

:class:`pi_harness.guards.runner.GuardRunner` writes sensor firings as
:class:`TrajectoryEvent` rows with ``classification="sensor_fired"`` and
stashes the guard-specific metadata under ``event.output["_guard_meta"]``.
This module pulls the sensor name, kind, criterion, and allow flag from
that mapping.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pi_harness.guards.types import GUARD_META_KEY, get_guard_meta
from pi_harness.trajectory.schema import TrajectoryEvent
from pi_harness.trajectory.store import query_events


@dataclass
class PromotionSuggestion:
    """A candidate Guide derived from an oft-firing sensor's history.

    Attributes:
        sensor_name: Class name of the originating sensor (e.g.
            ``"JudgeAgentSensor"``).
        sensor_criterion: The natural-language criterion the sensor was
            constructed with.
        fires: Total observations included in the suggestion.
        allow_fraction: Fraction of fires that returned ``allow=True``.
        suggested_stub_code: Python source code for a candidate Guide /
            Sensor. The user reviews this and drops it into
            ``~/.pi-harness/guards/``.
        suggested_kind: The :class:`GuardKind`.value the stub belongs to
            (``"computational_guide"`` or ``"computational_sensor"``).
        evidence: Free-form record (allow_count, deny_count, sample reasons)
            used by the dashboard to explain the suggestion.
    """

    sensor_name: str
    sensor_criterion: str
    fires: int
    allow_fraction: float
    suggested_stub_code: str
    suggested_kind: str
    evidence: dict[str, Any] = field(default_factory=dict)


def suggest_promotions(
    min_fires: int = 20,
    low_variance_threshold: float = 0.1,
    *,
    db_path: Any = None,
) -> list[PromotionSuggestion]:
    """Scan sensor history and emit promotion candidates.

    A candidate is produced for each ``(sensor_name, criterion)`` group that:

      - has at least ``min_fires`` events, AND
      - has ``min(allow_fraction, 1-allow_fraction) <= low_variance_threshold``
        (i.e. outcomes are lopsided enough to hard-code).

    Only inferential sensors are considered — computational sensors are
    already deterministic and need no promotion.

    Args:
        min_fires: Minimum number of fires in a group before it's considered.
        low_variance_threshold: Maximum tolerated minority-fraction (e.g.
            ``0.1`` means at most 10% of fires can disagree with the
            majority).
        db_path: Optional override for the trajectory db path; forwarded to
            :func:`query_events`.
    """
    # Plan 2's query_events takes keyword args, not a dict filter. Pull all
    # events and filter by classification in Python — keeps the API call
    # simple and avoids dependency on a feature query_events may not expose.
    events = query_events(db_path=db_path)

    groups: dict[tuple[str, str], list[TrajectoryEvent]] = defaultdict(list)
    for ev in events:
        if ev.classification != "sensor_fired":
            continue
        meta = get_guard_meta(ev)
        if meta.get("sensor_kind") != "inferential_sensor":
            continue
        sensor = meta.get("sensor", "")
        criterion = meta.get("guard_metadata", {}).get("criterion", "")
        groups[(sensor, criterion)].append(ev)

    out: list[PromotionSuggestion] = []
    for (sensor_name, criterion), bucket in groups.items():
        n = len(bucket)
        if n < min_fires:
            continue

        allow_n = sum(1 for ev in bucket if get_guard_meta(ev).get("allow") is True)
        allow_frac = allow_n / n
        variance = min(allow_frac, 1.0 - allow_frac)
        if variance > low_variance_threshold:
            continue

        stub_code, stub_kind = _render_stub(
            sensor_name, criterion, bucket, allow_frac
        )
        out.append(
            PromotionSuggestion(
                sensor_name=sensor_name,
                sensor_criterion=criterion,
                fires=n,
                allow_fraction=allow_frac,
                suggested_stub_code=stub_code,
                suggested_kind=stub_kind,
                evidence={
                    "allow_count": allow_n,
                    "deny_count": n - allow_n,
                    "sample_reasons": [
                        get_guard_meta(ev).get("reason", "") for ev in bucket[:5]
                    ],
                },
            )
        )

    return out


# ---------------------------------------------------------------------------
# Stub generation
# ---------------------------------------------------------------------------


def _render_stub(
    sensor_name: str,
    criterion: str,
    events: list[TrajectoryEvent],
    allow_frac: float,
) -> tuple[str, str]:
    """Render a Python source stub for a candidate Guide or Sensor.

    Strategy:
      1. If a common substring is present in every allow-outcome event's
         output, emit a :class:`RegexAssertionSensor` stub asserting that
         substring.
      2. Otherwise, if every allow-outcome event's input shares the same set
         of top-level keys, emit a :class:`SchemaValidatorGuide` stub.
      3. Otherwise, emit a commented-out RegexAssertionSensor scaffold.

    Returns ``(source_code, suggested_kind)``.
    """
    safe_name = _slugify(criterion)
    allow_count = sum(
        1 for ev in events if get_guard_meta(ev).get("allow") is True
    )
    total = len(events)
    header = (
        f"# Auto-generated by pi_harness.guards.promote\n"
        f"# Promoted from {sensor_name}({criterion!r})\n"
        f"# Evidence: {allow_count}/{total} allow ({allow_frac:.2f}), low variance\n"
    )

    # Strategy 1: common substring across allow-outcome string output values.
    # We look only at string leaves of the output dict (e.g. stdout, stderr)
    # so the regex isn't anchored on dict-serialization noise like ``{'stdout':``.
    allow_outputs: list[str] = []
    for ev in events:
        if get_guard_meta(ev).get("allow") is not True:
            continue
        if not ev.output:
            continue
        # Concat string-typed leaves only, skipping _guard_meta.
        leaves: list[str] = []
        for key, value in ev.output.items():
            if key == GUARD_META_KEY:
                continue
            if isinstance(value, str):
                leaves.append(value)
        if leaves:
            allow_outputs.append("\n".join(leaves))

    substring = _longest_common_substring(allow_outputs)
    if substring and len(substring) >= 4 and not _is_trivial(substring):
        # repr() gives us a python string literal with all escapes handled,
        # which we then strip the surrounding quotes off so it slots into our
        # ``r'<pattern>'`` raw-string template safely. We also forbid
        # backslash-injection bugs by rejecting patterns that contain a
        # single quote (we'd need to switch quoting style — easier to
        # fall through to strategy 2/3).
        escaped = re.escape(substring)
        if "'" not in escaped and "\\" not in escaped:
            code = header + (
                f"from pi_harness.guards.sensors import RegexAssertionSensor\n"
                f"from pi_harness.guards.types import register_sensor\n\n"
                f"@register_sensor(name='{safe_name}')\n"
                f"class {_pascal(safe_name)}Sensor(RegexAssertionSensor):\n"
                f"    def __init__(self):\n"
                f"        super().__init__(pattern=r'{escaped}', must_match=True)\n"
            )
            return code, "computational_sensor"
        # When the substring contains regex metacharacters that re.escape
        # would backslash-escape, the safest emission is via repr() so the
        # literal compiles cleanly.
        code = header + (
            f"from pi_harness.guards.sensors import RegexAssertionSensor\n"
            f"from pi_harness.guards.types import register_sensor\n\n"
            f"@register_sensor(name='{safe_name}')\n"
            f"class {_pascal(safe_name)}Sensor(RegexAssertionSensor):\n"
            f"    def __init__(self):\n"
            f"        super().__init__(pattern={escaped!r}, must_match=True)\n"
        )
        return code, "computational_sensor"

    # Strategy 2: shared input key shape?
    allow_inputs = [
        dict(ev.input or {}) for ev in events if get_guard_meta(ev).get("allow") is True
    ]
    shared_keys = _shared_top_level_keys(allow_inputs)
    if shared_keys:
        tool_name = events[0].tool or "unknown"
        schema_props = {k: {"type": "string"} for k in sorted(shared_keys)}
        code = header + (
            f"from pi_harness.guards.guides import SchemaValidatorGuide\n"
            f"from pi_harness.guards.types import register_guide\n\n"
            f"@register_guide(name='{safe_name}')\n"
            f"class {_pascal(safe_name)}Guide(SchemaValidatorGuide):\n"
            f"    def __init__(self):\n"
            f"        super().__init__(\n"
            f"            tool_name={tool_name!r},\n"
            f"            schema={{\n"
            f"                'type': 'object',\n"
            f"                'properties': {schema_props!r},\n"
            f"                'required': {sorted(shared_keys)!r},\n"
            f"            }},\n"
            f"        )\n"
        )
        return code, "computational_guide"

    # Strategy 3: scaffold (always compiles)
    code = header + (
        f"from pi_harness.guards.sensors import RegexAssertionSensor\n"
        f"from pi_harness.guards.types import register_sensor\n\n"
        f"# TODO: replace 'PATTERN' below with a regex extracted from your outputs\n"
        f"@register_sensor(name='{safe_name}')\n"
        f"class {_pascal(safe_name)}Sensor(RegexAssertionSensor):\n"
        f"    def __init__(self):\n"
        f"        super().__init__(pattern=r'PATTERN', must_match=True)\n"
    )
    return code, "computational_sensor"


def _slugify(text: str) -> str:
    """Lowercase alphanumeric + underscores, falls back to 'promoted'."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return cleaned or "promoted"


def _pascal(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_") if part)


_TRIVIAL_SUBSTRINGS = {
    "stdout", "stderr", "output", "input", "true", "false", "none",
    "null", "data", " " * 4,
}


def _is_trivial(substring: str) -> bool:
    """Detect substrings that are common Python-dict noise rather than
    signal — e.g. ``{'stdout': '`` from the serialized output dict.

    We strip surrounding punctuation/spaces and reject if the result is in
    a small denylist or is purely punctuation.
    """
    stripped = substring.strip(" '\":{},[]")
    if not stripped:
        return True
    if stripped.lower() in _TRIVIAL_SUBSTRINGS:
        return True
    return False


def _longest_common_substring(strings: list[str]) -> str:
    """Return the longest substring that appears in every input string.

    Naive O(n*m^2) but sufficient: we cap inputs at the first 25 events and
    snippets at the first 500 chars.
    """
    if not strings:
        return ""
    strings = [s[:500] for s in strings[:25]]
    shortest = min(strings, key=len)
    best = ""
    for i in range(len(shortest)):
        # Skip windows that start with whitespace; they almost never indicate
        # a meaningful semantic anchor (e.g. they overlap dict separators).
        if shortest[i].isspace():
            continue
        for j in range(i + len(best) + 1, len(shortest) + 1):
            candidate = shortest[i:j]
            if all(candidate in s for s in strings):
                if len(candidate) > len(best):
                    best = candidate
            else:
                break
    return best


def _shared_top_level_keys(dicts: list[dict]) -> set[str]:
    """Intersection of top-level keys across all dicts (empty if the list is
    empty).
    """
    if not dicts:
        return set()
    keys = set(dicts[0].keys())
    for d in dicts[1:]:
        keys &= set(d.keys())
    return keys


__all__ = ["PromotionSuggestion", "suggest_promotions"]
