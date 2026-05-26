"""Types for the guides/sensors control surface.

Defines the public type vocabulary used by the rest of the package:

* :class:`GuardKind` — the Fowler 2x2 quadrant a guard occupies.
* :class:`GuardResult` — the allow/deny decision a Guide or Sensor returns.
* :class:`ActionIntent` / :class:`ActionResult` — typed dicts mirroring
  pi-coding-agent's tool-call / tool-result stdio events.
* :class:`Guide` / :class:`Sensor` — protocol types implementations satisfy.
* :func:`register_guide` / :func:`register_sensor` — decorators that wire
  user-defined classes into the module-level registries (``GUIDE_REGISTRY``
  and ``SENSOR_REGISTRY``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Final, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from pi_harness.trajectory.schema import TrajectoryEvent


# ---------------------------------------------------------------------------
# GuardKind + GuardResult
# ---------------------------------------------------------------------------


class GuardKind(str, Enum):
    """The Fowler 2x2 quadrant a guard occupies.

    Feedforward (before action) = Guide. Feedback (after action) = Sensor.
    Deterministic rule = Computational. LLM judgment = Inferential.
    """

    COMPUTATIONAL_GUIDE = "computational_guide"
    INFERENTIAL_GUIDE = "inferential_guide"
    COMPUTATIONAL_SENSOR = "computational_sensor"
    INFERENTIAL_SENSOR = "inferential_sensor"


@dataclass
class GuardResult:
    """The decision a Guide or Sensor returns.

    Attributes:
        allow: ``True`` to let the action proceed, ``False`` to deny it (for
            guides) or flag it (for sensors — the tool has already run).
        reason: Short human-readable explanation, recorded in the trajectory
            event's metadata.
        confidence: Optional float in [0, 1]. Computational guards leave this
            as ``None``; inferential guards populate it from the judge's score.
        metadata: Free-form structured detail (matched pattern, path that
            failed scope, etc.) — surfaced to the dashboard and to
            ``promote.suggest_promotions``.
    """

    allow: bool
    reason: str
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ActionIntent / ActionResult — typed dicts mirroring pi-coding-agent's stdio
# ---------------------------------------------------------------------------


class ActionIntent(TypedDict, total=False):
    """pi-coding-agent's pending tool call.

    Shape mirrors pi-coding-agent's stdout JSON line for
    ``{type: "tool_call"}``. ``total=False`` so callers can pass partial
    dicts in tests; production callers should populate all five required
    keys (``run_id``, ``agent_id``, ``step_id``, ``tool``, ``input``).
    """

    run_id: str
    agent_id: str
    step_id: str
    tool: str
    input: dict[str, Any]


class ActionResult(TypedDict, total=False):
    """pi-coding-agent's tool result.

    Shape mirrors pi-coding-agent's stdout JSON line for
    ``{type: "tool_result"}``, augmented with timing and token usage the
    GuardRunner / capture layer record. Required keys: ``run_id``,
    ``agent_id``, ``step_id``, ``tool``, ``input``, ``output``. Optional:
    ``exit_code`` (for bash-like tools), ``duration_ms``, ``tokens_in``,
    ``tokens_out``.
    """

    run_id: str
    agent_id: str
    step_id: str
    tool: str
    input: dict[str, Any]
    output: dict[str, Any]
    exit_code: int
    duration_ms: int
    tokens_in: int
    tokens_out: int


# ---------------------------------------------------------------------------
# Guide / Sensor protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class Guide(Protocol):
    """Pre-action callable. Inspects an ActionIntent, returns a GuardResult.

    Concrete implementations should expose a ``kind: GuardKind`` class
    attribute so the GuardRunner can route them and the dashboard can group
    them.
    """

    kind: GuardKind

    def __call__(self, intent: ActionIntent) -> GuardResult: ...


@runtime_checkable
class Sensor(Protocol):
    """Post-action callable. Inspects an ActionResult, returns a GuardResult.

    ``allow=False`` from a sensor does not cancel the action (the tool already
    ran) but does emit a ``sensor_fired`` event with ``outcome="error"``,
    which feeds ``promote.suggest_promotions`` and the dashboard's flag list.
    """

    kind: GuardKind

    def __call__(self, result: ActionResult) -> GuardResult: ...


# ---------------------------------------------------------------------------
# Registries — user guards opt-in via @register_guide / @register_sensor
# ---------------------------------------------------------------------------


GUIDE_REGISTRY: dict[str, type] = {}
SENSOR_REGISTRY: dict[str, type] = {}


def register_guide(name: str):
    """Decorator. Registers a Guide class under ``name`` in
    :data:`GUIDE_REGISTRY`.

    User-defined guides in ``~/.pi-harness/guards/*.py`` use this to make
    themselves visible to GuardRunner via name-based wiring in Topology
    configs.

    Raises:
        ValueError: if ``name`` is already in the registry.
    """

    def deco(cls):
        if name in GUIDE_REGISTRY:
            raise ValueError(f"Guide {name!r} already registered")
        GUIDE_REGISTRY[name] = cls
        return cls

    return deco


def register_sensor(name: str):
    """Decorator. Registers a Sensor class under ``name`` in
    :data:`SENSOR_REGISTRY`.

    Raises:
        ValueError: if ``name`` is already in the registry.
    """

    def deco(cls):
        if name in SENSOR_REGISTRY:
            raise ValueError(f"Sensor {name!r} already registered")
        SENSOR_REGISTRY[name] = cls
        return cls

    return deco


# ---------------------------------------------------------------------------
# TrajectoryEvent format — guard firings stash metadata under ``_guard_meta``
# ---------------------------------------------------------------------------


GUARD_META_KEY: Final[str] = "_guard_meta"
"""Key under which :class:`GuardRunner` stashes guard-specific metadata in a
``TrajectoryEvent.output`` mapping. Consumers (dashboards, ``promote``
analysis, downstream plans) should read via :func:`get_guard_meta` rather
than hard-coding the key string.
"""


def get_guard_meta(event: "TrajectoryEvent") -> dict[str, Any]:
    """Return the guard metadata sub-mapping for a guide/sensor event.

    Returns an empty dict if the event has no ``_guard_meta`` entry (e.g.
    the event was not emitted by a :class:`GuardRunner`, or ``output`` is
    ``None``). The returned dict typically carries ``guide`` / ``sensor``
    (class name), ``guide_kind`` / ``sensor_kind`` (a :class:`GuardKind`
    value), ``reason``, ``confidence``, ``guard_metadata``, and ``allow``.
    """
    output = event.output or {}
    meta = output.get(GUARD_META_KEY, {})
    if isinstance(meta, dict):
        return meta
    return {}


def get_guard_allow(event: "TrajectoryEvent") -> bool | None:
    """Return the ``allow`` boolean from a guide/sensor event, or ``None``.

    Convenience accessor — ``outcome`` on the event is the lossy mapping
    (allow→``success``, deny→``blocked``); this returns the original boolean
    stashed under :data:`GUARD_META_KEY`.
    """
    value = get_guard_meta(event).get("allow")
    return value if isinstance(value, bool) else None


__all__ = [
    "ActionIntent",
    "ActionResult",
    "GUARD_META_KEY",
    "GUIDE_REGISTRY",
    "GuardKind",
    "GuardResult",
    "Guide",
    "SENSOR_REGISTRY",
    "Sensor",
    "get_guard_allow",
    "get_guard_meta",
    "register_guide",
    "register_sensor",
]
