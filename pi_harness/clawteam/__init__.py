"""Subprocess-based wrapper around the ``clawteam`` CLI.

Plans 2, 5, and 7 import ``ClawTeamClient`` (and the typed exceptions) from
this package.
"""

from pi_harness.clawteam.client import (
    ClawTeamCLIError,
    ClawTeamClient,
    ClawTeamRunFailure,
    ClawTeamTimeout,
    TERMINAL_STATUSES,
    FAILURE_STATUSES,
)

__all__ = [
    "ClawTeamClient",
    "ClawTeamCLIError",
    "ClawTeamRunFailure",
    "ClawTeamTimeout",
    "TERMINAL_STATUSES",
    "FAILURE_STATUSES",
]
