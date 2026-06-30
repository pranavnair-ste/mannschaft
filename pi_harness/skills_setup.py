# pi_harness/skills_setup.py
"""Skill provisioning for the sovereign session.

The session must route teams through the mannschaft pipeline, not the raw
`clawteam` CLI. A stale pi skill at ~/.pi/agent/skills/clawteam teaches the
value-stripped shortcut, so we reversibly move it aside on `ms chat` first-run.
"""
from __future__ import annotations

from pathlib import Path


def repo_skills_dir() -> Path:
    """The repo's skills/ directory (sibling of the pi_harness package)."""
    return Path(__file__).resolve().parents[1] / "skills"


def raw_clawteam_skill_dir() -> Path:
    return Path.home() / ".pi" / "agent" / "skills" / "clawteam"


def retire_raw_clawteam_skill(*, skills_root: Path | None = None) -> Path | None:
    """Move the stale raw-clawteam pi skill aside. Idempotent, non-destructive.

    Returns the backup path if something was moved, else None.
    """
    root = skills_root if skills_root is not None else raw_clawteam_skill_dir().parent
    target = root / "clawteam"
    if not target.exists():
        return None

    backup = root / "clawteam.disabled"
    if backup.exists():
        n = 1
        while (root / f"clawteam.disabled.{n}").exists():
            n += 1
        backup = root / f"clawteam.disabled.{n}"

    target.rename(backup)
    print(
        f"note: disabled the raw-clawteam pi skill (moved {target} -> {backup}); "
        f"restore with `mv {backup} {target}` if you want it back."
    )
    return backup
