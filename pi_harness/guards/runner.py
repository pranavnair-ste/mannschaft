"""GuardRunner — orchestrates guides + sensors around pi-coding-agent tool
calls.

Integration assumption (verify against pi-coding-agent docs):

    pi-coding-agent emits newline-delimited JSON to stdout. Each tool call is
    ``{"type": "tool_call", "id": str, "name": str, "input": dict}``. Each
    tool result is ``{"type": "tool_result", "id": str, "output": dict,
    "exit_code"?: int}``.

    A Python wrapper subprocess reads these lines, converts them to
    :class:`ActionIntent` / :class:`ActionResult` dicts, and calls
    :meth:`intercept_tool_call` / :meth:`intercept_tool_result`. On a denied
    intercept_tool_call the wrapper writes a synthetic
    ``{"type": "tool_result", "id": <same>, "output": {"error": <reason>},
    "exit_code": 1}`` to the agent's stdin, so the agent perceives a tool
    error and can recover.

    THIS WRAPPER IS NOT IMPLEMENTED IN THIS PLAN. Only the Python-side
    surface (this class) is. Wiring is a future integration plan.

Outcome and metadata mapping into Plan 2's :class:`TrajectoryEvent`:

    Plan 2 restricts ``outcome`` to ``{"success", "error", "blocked",
    "timeout"}``. We map a guide/sensor allow to ``"success"`` and a deny to
    ``"blocked"``.

    Plan 2's TrajectoryEvent has no free-form ``metadata`` field — it has
    typed ``input`` and ``output`` Mappings. We stash guard-specific
    metadata under a ``"_guard_meta"`` key inside ``output``:

        {
            "_guard_meta": {
                "guide" | "sensor": "<class name>",
                "guide_kind" | "sensor_kind": "<GuardKind.value>",
                "reason": "<short>",
                "confidence": <float | None>,
                "guard_metadata": {<GuardResult.metadata>},
                "allow": <bool>,
            },
            ...rest of real tool output passes through (sensors only)...
        }

    For ``classification="guide_fired"`` events the real tool hasn't run yet,
    so ``output`` only carries the ``"_guard_meta"`` key. For
    ``classification="sensor_fired"`` we preserve the underlying tool output
    alongside the guard metadata.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from pi_harness.guards.types import (
    GUARD_META_KEY,
    ActionIntent,
    ActionResult,
    GuardResult,
    Guide,
    Sensor,
)
from pi_harness.trajectory.schema import TrajectoryEvent
from pi_harness.trajectory.store import write_event


def _outcome(allow: bool) -> str:
    """Map a guide/sensor allow boolean to a TrajectoryEvent.outcome value.

    Plan 2's schema constrains outcome to ``{"success", "error", "blocked",
    "timeout"}`` — we use ``"success"`` for allow and ``"blocked"`` for deny.
    """
    return "success" if allow else "blocked"


def _guide_meta(guide: Guide, result: GuardResult) -> dict[str, Any]:
    """Build the ``_guard_meta`` payload for a guide firing."""
    kind_value = getattr(getattr(guide, "kind", None), "value", "unknown")
    return {
        "guide": type(guide).__name__,
        "guide_kind": kind_value,
        "reason": result.reason,
        "confidence": result.confidence,
        "guard_metadata": dict(result.metadata),
        "allow": result.allow,
    }


def _sensor_meta(sensor: Sensor, result: GuardResult) -> dict[str, Any]:
    """Build the ``_guard_meta`` payload for a sensor firing."""
    kind_value = getattr(getattr(sensor, "kind", None), "value", "unknown")
    return {
        "sensor": type(sensor).__name__,
        "sensor_kind": kind_value,
        "reason": result.reason,
        "confidence": result.confidence,
        "guard_metadata": dict(result.metadata),
        "allow": result.allow,
    }


class GuardRunner:
    """Per-(run, agent) container for guides + sensors. Wraps the tool stream.

    Construct one per agent in a run. Attach guides (run pre-action,
    short-circuit on first deny) and sensors (run post-action, all fire, no
    short-circuit). Each firing emits a :class:`TrajectoryEvent` via
    :func:`pi_harness.trajectory.store.write_event`.
    """

    def __init__(self, run_id: str, agent_id: str) -> None:
        self.run_id = run_id
        self.agent_id = agent_id
        self.guides: list[Guide] = []
        self.sensors: list[Sensor] = []

    def attach_guides(self, guides: Iterable[Guide]) -> None:
        """Append guides; existing guides are preserved (order-stable)."""
        self.guides.extend(list(guides))

    def attach_sensors(self, sensors: Iterable[Sensor]) -> None:
        """Append sensors; existing sensors are preserved (order-stable)."""
        self.sensors.extend(list(sensors))

    # ---------------------------------------------------------------- guides

    def intercept_tool_call(self, intent: ActionIntent) -> GuardResult:
        """Run all attached guides on ``intent``; first deny short-circuits.

        Every fire (allow or deny) emits a TrajectoryEvent with
        ``classification="guide_fired"``. Returns the first deny GuardResult,
        or the last allow GuardResult if all guides allow. Returns a default
        allow if no guides are attached.
        """
        last_allow: GuardResult = GuardResult(allow=True, reason="no guides attached")

        for guide in self.guides:
            result = guide(intent)
            self._emit_guide_event(intent, guide, result)

            if not result.allow:
                return result
            last_allow = result

        return last_allow

    def _emit_guide_event(
        self,
        intent: ActionIntent,
        guide: Guide,
        result: GuardResult,
    ) -> None:
        event = TrajectoryEvent(
            run_id=self.run_id,
            agent_id=self.agent_id,
            step_id=intent.get("step_id", ""),
            ts=datetime.now(timezone.utc),
            model="",
            tool=intent.get("tool", "") or "",
            input=dict(intent.get("input", {})),
            output={GUARD_META_KEY: _guide_meta(guide, result)},
            duration_ms=0,
            tokens_in=0,
            tokens_out=0,
            outcome=_outcome(result.allow),
            classification="guide_fired",
        )
        write_event(event)

    # --------------------------------------------------------------- sensors

    def intercept_tool_result(
        self,
        action_result: ActionResult,
    ) -> list[GuardResult]:
        """Run every attached sensor on ``action_result``. No short-circuit.

        Returns the list of GuardResults in attach order. Each fire emits a
        TrajectoryEvent with ``classification="sensor_fired"``.
        """
        out: list[GuardResult] = []
        for sensor in self.sensors:
            result = sensor(action_result)
            self._emit_sensor_event(action_result, sensor, result)
            out.append(result)
        return out

    def _emit_sensor_event(
        self,
        action_result: ActionResult,
        sensor: Sensor,
        result: GuardResult,
    ) -> None:
        merged_output: dict[str, Any] = dict(action_result.get("output", {}))
        merged_output[GUARD_META_KEY] = _sensor_meta(sensor, result)

        event = TrajectoryEvent(
            run_id=self.run_id,
            agent_id=self.agent_id,
            step_id=action_result.get("step_id", ""),
            ts=datetime.now(timezone.utc),
            model="",
            tool=action_result.get("tool", "") or "",
            input=dict(action_result.get("input", {})),
            output=merged_output,
            duration_ms=int(action_result.get("duration_ms", 0)),
            tokens_in=int(action_result.get("tokens_in", 0)),
            tokens_out=int(action_result.get("tokens_out", 0)),
            outcome=_outcome(result.allow),
            classification="sensor_fired",
        )
        write_event(event)


__all__ = ["GuardRunner"]
