"""Thin subprocess wrapper over the real ``clawteam`` 0.2.x CLI.

Each public method shells out to exactly one ``clawteam`` invocation (with the
exception of ``install_template``, which writes a TOML file under the data
dir, because ClawTeam has no template-registration verb).

The top-level ``--data-dir`` flag from ``Config.clawteam_state_dir`` is
injected on every call so multiple harness instances can sandbox state.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, List, Mapping, Optional, Sequence

from pi_harness.clawteam_profile import ProfileSpec
from pi_harness.config import Config

__all__ = [
    "ClawTeamClient",
    "ClawTeamCLIError",
    "ClawTeamTimeout",
    "ClawTeamRunFailure",
    "TERMINAL_STATUSES",
    "FAILURE_STATUSES",
]

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
FAILURE_STATUSES = frozenset({"failed", "cancelled"})


class ClawTeamCLIError(RuntimeError):
    """Raised when the ClawTeam CLI exits with a non-zero status."""

    def __init__(self, command: Sequence[str], returncode: int, stderr: str) -> None:
        self.command = list(command)
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"clawteam command {self.command!r} exited {returncode}: {stderr.strip()}"
        )


class ClawTeamTimeout(TimeoutError):
    """Raised when ``wait_for_completion`` exceeds the deadline."""


class ClawTeamRunFailure(RuntimeError):
    """Raised when ``wait_for_completion`` observes a failed task."""


@dataclass
class ClawTeamClient:
    """Wrapper around the ``clawteam`` 0.2.x CLI.

    Args:
        config: Project :class:`Config`. ``clawteam_state_dir`` is passed via
            ``--data-dir`` on every call; the OpenAI key is forwarded via the
            subprocess env.
        binary: Override the CLI binary name (handy for tests / pinned installs).
    """

    config: Config
    binary: str = "clawteam"

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["OPENAI_API_KEY"] = self.config.openai_api_key
        return env

    def _base_args(self, *, json_output: bool = False) -> List[str]:
        """Top-level clawteam args (binary + global flags) before any subcommand."""
        args: List[str] = [self.binary, "--data-dir", str(self.config.clawteam_state_dir)]
        if json_output:
            args.append("--json")
        return args

    def _run(
        self,
        subcommand: Sequence[str],
        *,
        json_output: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        cmd = [*self._base_args(json_output=json_output), *subcommand]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=self._env(),
            check=False,
        )
        if check and result.returncode != 0:
            raise ClawTeamCLIError(cmd, result.returncode, result.stderr or result.stdout)
        return result

    # ---- team lifecycle ------------------------------------------------- #

    def launch_team(
        self,
        template: str,
        team_name: str,
        goal: str,
        profile: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Spawn a new ClawTeam team from a template.

        Real invocation: ``clawteam --data-dir D launch TEMPLATE --team Y --goal Z [--profile P]``
        """
        sub: List[str] = [
            "launch", template,
            "--team", team_name,
            "--goal", goal,
        ]
        if profile is not None:
            sub.extend(["--profile", profile])
        return self._run(sub)

    def cleanup_team(self, team_name: str) -> subprocess.CompletedProcess:
        """Destroy ``team_name`` and free its worktrees.

        Real invocation: ``clawteam --data-dir D team cleanup TEAM --force``
        """
        return self._run(["team", "cleanup", team_name, "--force"])

    # ---- read state ----------------------------------------------------- #

    def list_tasks(self, team_name: str) -> List[Mapping[str, Any]]:
        """Return the task board for ``team_name`` as a list of dicts.

        Real invocation: ``clawteam --data-dir D --json task list TEAM``
        """
        result = self._run(["task", "list", team_name], json_output=True)
        payload = json.loads(result.stdout or "[]")
        if not isinstance(payload, list):
            raise ClawTeamCLIError(
                [*self._base_args(json_output=True), "task", "list", team_name],
                0,
                f"expected JSON list, got {type(payload).__name__}",
            )
        return payload

    def peek_inbox(
        self,
        team_name: str,
        agent: Optional[str] = None,
        limit: int = 10,
    ) -> List[Mapping[str, Any]]:
        """Peek at the inbox of ``agent`` inside ``team_name`` (non-destructive).

        Real invocation: ``clawteam --data-dir D --json inbox peek TEAM [--agent A] --limit N``
        """
        sub: List[str] = ["inbox", "peek", team_name, "--limit", str(limit)]
        if agent is not None:
            sub.extend(["--agent", agent])
        result = self._run(sub, json_output=True)
        payload = json.loads(result.stdout or "[]")
        if not isinstance(payload, list):
            raise ClawTeamCLIError(
                [*self._base_args(json_output=True), *sub],
                0,
                f"expected JSON list, got {type(payload).__name__}",
            )
        return payload

    # ---- profile + template setup -------------------------------------- #

    def register_profile(self, spec: ProfileSpec) -> subprocess.CompletedProcess:
        """Create or update a ClawTeam profile from a :class:`ProfileSpec`.

        Real invocation: ``clawteam --data-dir D profile set NAME --agent ... --model ... ...``
        """
        return self._run(["profile", "set", *spec.to_set_args()])

    USER_TEMPLATES_DIR: ClassVar[Path] = Path.home() / ".clawteam" / "templates"

    def install_template(self, name: str, toml_text: str) -> Path:
        """Drop a user-template TOML at ``~/.clawteam/templates/<name>.toml``.

        ClawTeam 0.2.x loads user templates ONLY from this fixed path —
        ``--data-dir`` does not influence template lookup. The harness writes
        to the global user-templates dir and callers are responsible for
        cleaning up if they want isolation.

        Returns the absolute target path.
        """
        templates_dir = self.USER_TEMPLATES_DIR
        templates_dir.mkdir(parents=True, exist_ok=True)
        target = templates_dir / f"{name}.toml"
        target.write_text(toml_text)
        return target

    # ---- completion polling -------------------------------------------- #

    def wait_for_completion(
        self,
        team_name: str,
        timeout: float,
        poll_interval: float = 5.0,
    ) -> bool:
        """Block until every task on the board reaches a terminal status.

        Returns:
            ``True`` if all tasks finished cleanly within ``timeout``.

        Raises:
            ClawTeamRunFailure: If any task reaches a failure status.
            ClawTeamTimeout: If ``timeout`` elapses before all tasks finish.
        """
        deadline = time.monotonic() + timeout
        while True:
            tasks = self.list_tasks(team_name)
            if tasks:
                failed = [t for t in tasks if t.get("status") in FAILURE_STATUSES]
                if failed:
                    failed_ids = ", ".join(
                        str(t.get("task_id", t.get("id", "?"))) for t in failed
                    )
                    raise ClawTeamRunFailure(
                        f"team={team_name!r} task(s) failed: {failed_ids}"
                    )
                if all(t.get("status") in TERMINAL_STATUSES for t in tasks):
                    return True
            if time.monotonic() >= deadline:
                raise ClawTeamTimeout(
                    f"team={team_name!r} did not finish within {timeout:.1f}s"
                )
            time.sleep(poll_interval)
