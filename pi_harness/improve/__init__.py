"""Post-hoc improve-agent: analyzes completed runs, emits curator candidates.

Public API (called by Plan 5's topology coordinator at run completion):

- :func:`run_for_completed_run` — the single orchestration entry point.
- :class:`ImproveReport` — summary returned by ``run_for_completed_run``.
- :class:`ImproveError` — raised on agent failure; never swallowed.

LLM-emitted candidate types (subordinate API for Plan 5 + tests):

- :class:`ProposedUpdate`, :class:`ProposedPrune`, :class:`PruneTrigger`
- :func:`parse_agent_response` — pydantic validator for raw LLM output.
- :class:`ImproveAgent` — exposed for unit-level injection only.
"""

from pi_harness.improve.agent import ImproveAgent, ImproveError
from pi_harness.improve.candidates import (
    ProposedPrune,
    ProposedUpdate,
    PruneTrigger,
    parse_agent_response,
)
from pi_harness.improve.runner import ImproveReport, run_for_completed_run

__all__ = [
    "ProposedPrune",
    "ProposedUpdate",
    "ImproveAgent",
    "ImproveError",
    "ImproveReport",
    "PruneTrigger",
    "parse_agent_response",
    "run_for_completed_run",
]
