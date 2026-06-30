"""Validate the Claude Code skill file shape."""
from __future__ import annotations

from pathlib import Path

import yaml

SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "pi-harness" / "SKILL.md"


def test_skill_file_exists():
    assert SKILL_PATH.exists(), f"missing {SKILL_PATH}"


def test_skill_has_frontmatter():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.find("\n---\n", 4)
    assert end > 0, "frontmatter not terminated"
    front = yaml.safe_load(text[4:end])
    assert front["name"] == "pi-harness"
    assert front.get("description"), "description required"


def test_skill_body_mentions_bash_invocation():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "Bash" in text or "bash" in text
    # The dispatch skill now routes through the mannschaft pipeline (`ms launch`),
    # not the retired legacy `pi-harness launch` slash command.
    assert "ms launch" in text
