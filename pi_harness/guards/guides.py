"""Built-in computational Guides (feedforward, deterministic).

Each guide is a callable class with a ``kind`` class attribute satisfying the
:class:`pi_harness.guards.types.Guide` protocol. The four built-ins ship in
v1; inferential guides are user-provided.

* :class:`AllowlistGuide` — deny tool calls whose name is not in an allowlist.
* :class:`PathScopeGuide` — for file-like tools, deny if the ``path`` input
  resolves outside an allowed root (via ``os.path.realpath`` so symlink and
  ``..`` escapes are blocked).
* :class:`SchemaValidatorGuide` — JSON-Schema-validate a specific tool's input.
* :class:`RateLimitGuide` — per-(agent_id, tool) sliding-window limiter.
"""
from __future__ import annotations

import os
import time
from collections import deque
from pathlib import Path

import jsonschema

from pi_harness.guards.types import ActionIntent, GuardKind, GuardResult


class AllowlistGuide:
    """Deny tool calls whose ``tool`` name is not in ``allowed_tools``."""

    kind = GuardKind.COMPUTATIONAL_GUIDE

    def __init__(self, allowed_tools: list[str]) -> None:
        self.allowed: set[str] = set(allowed_tools)

    def __call__(self, intent: ActionIntent) -> GuardResult:
        tool = intent.get("tool", "")
        if tool in self.allowed:
            return GuardResult(
                allow=True,
                reason=f"tool {tool!r} on allowlist",
                metadata={"tool": tool},
            )
        return GuardResult(
            allow=False,
            reason=f"tool {tool!r} not in allowlist {sorted(self.allowed)}",
            metadata={"tool": tool, "allowed": sorted(self.allowed)},
        )


class PathScopeGuide:
    """For file-like tools, deny if the input ``path`` resolves outside
    ``allowed_paths``.

    Uses ``os.path.realpath`` (resolves symlinks AND ``..``) so dotdot escapes
    and symlink tricks cannot bypass the check. Tools with no ``path`` key
    (e.g. plain bash with ``cmd``) pass through.
    """

    kind = GuardKind.COMPUTATIONAL_GUIDE

    def __init__(self, allowed_paths: list[Path]) -> None:
        self.allowed: list[str] = [os.path.realpath(str(p)) for p in allowed_paths]

    def __call__(self, intent: ActionIntent) -> GuardResult:
        path_value = intent.get("input", {}).get("path")
        if path_value is None:
            return GuardResult(allow=True, reason="no path in input, skipped")

        real = os.path.realpath(str(path_value))
        for root in self.allowed:
            if real == root or real.startswith(root + os.sep):
                return GuardResult(
                    allow=True,
                    reason=f"path inside scope {root}",
                    metadata={"real": real, "scope": root},
                )

        return GuardResult(
            allow=False,
            reason=f"path {real!r} outside scope {self.allowed}",
            metadata={"real": real, "allowed": self.allowed},
        )


class SchemaValidatorGuide:
    """Validate the ``input`` of a specific tool against a JSON Schema.

    Only fires for ``intent["tool"] == tool_name``; other tools pass through.
    On schema failure, returns ``allow=False`` with the validator's error.
    """

    kind = GuardKind.COMPUTATIONAL_GUIDE

    def __init__(self, tool_name: str, schema: dict) -> None:
        self.tool_name = tool_name
        self.schema = schema
        self._validator = jsonschema.Draft202012Validator(schema)

    def __call__(self, intent: ActionIntent) -> GuardResult:
        if intent.get("tool") != self.tool_name:
            return GuardResult(
                allow=True,
                reason=f"different tool, skipped (want {self.tool_name!r})",
            )

        errors = list(self._validator.iter_errors(intent.get("input", {})))
        if not errors:
            return GuardResult(allow=True, reason="schema ok")

        msg = "; ".join(e.message for e in errors)
        return GuardResult(
            allow=False,
            reason=f"schema fail: {msg}",
            metadata={"errors": [e.message for e in errors]},
        )


class RateLimitGuide:
    """Per-(agent_id, tool) sliding-window limiter.

    Keeps a 60-second window of call timestamps per ``(agent_id, tool)`` key.
    Calls beyond ``max_per_minute`` in that window are denied. Other tools
    pass through.
    """

    kind = GuardKind.COMPUTATIONAL_GUIDE
    WINDOW_SECONDS = 60.0

    def __init__(self, tool_name: str, max_per_minute: int) -> None:
        self.tool_name = tool_name
        self.max = max_per_minute
        self._buckets: dict[tuple[str, str], deque[float]] = {}

    def __call__(self, intent: ActionIntent) -> GuardResult:
        if intent.get("tool") != self.tool_name:
            return GuardResult(allow=True, reason="different tool, skipped")

        key = (intent.get("agent_id", ""), self.tool_name)
        now = time.monotonic()
        bucket = self._buckets.setdefault(key, deque())

        # Evict timestamps outside the window
        while bucket and bucket[0] < now - self.WINDOW_SECONDS:
            bucket.popleft()

        if len(bucket) >= self.max:
            return GuardResult(
                allow=False,
                reason=(
                    f"rate limit exceeded: "
                    f"{len(bucket)}/{self.max} per {int(self.WINDOW_SECONDS)}s"
                ),
                metadata={"current": len(bucket), "max": self.max},
            )

        bucket.append(now)
        return GuardResult(
            allow=True,
            reason=f"rate ok: {len(bucket)}/{self.max}",
            metadata={"current": len(bucket), "max": self.max},
        )


__all__ = [
    "AllowlistGuide",
    "PathScopeGuide",
    "RateLimitGuide",
    "SchemaValidatorGuide",
]
