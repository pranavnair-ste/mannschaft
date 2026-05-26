"""Guides + Sensors — control-system surface for pi-coding-agent tool stream.

This package wraps pi-coding-agent's tool stream with an ordered chain of
``Guide`` callables (before each tool call) and ``Sensor`` callables (after
each tool result). Each firing emits a ``TrajectoryEvent`` via Plan 2's
trajectory store, classified as ``"guide_fired"`` or ``"sensor_fired"``.

The :mod:`promote` submodule performs offline statistical analysis on stored
sensor firings to suggest stub Guides users can install at
``~/.pi-harness/guards/<name>.py``.

Public re-exports below are the API Plan 5 (Topology) and Plan 8 (Dashboard)
import from.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from pi_harness.guards.types import (
    ActionIntent,
    ActionResult,
    GUIDE_REGISTRY,
    GuardKind,
    GuardResult,
    Guide,
    SENSOR_REGISTRY,
    Sensor,
    register_guide,
    register_sensor,
)


def load_user_guards(directory: Path) -> None:
    """Import every ``*.py`` file in ``directory`` so its ``@register_guide``
    and ``@register_sensor`` side effects populate :data:`GUIDE_REGISTRY` and
    :data:`SENSOR_REGISTRY`.

    Silently no-ops if ``directory`` does not exist. The convention is
    ``~/.pi-harness/guards/`` but callers may pass any path (tests do).
    """
    directory = Path(directory)
    if not directory.exists():
        return

    for py in sorted(directory.glob("*.py")):
        module_name = f"pi_harness_user_guards.{py.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)


__all__ = [
    "ActionIntent",
    "ActionResult",
    "GUIDE_REGISTRY",
    "GuardKind",
    "GuardResult",
    "Guide",
    "SENSOR_REGISTRY",
    "Sensor",
    "load_user_guards",
    "register_guide",
    "register_sensor",
]
