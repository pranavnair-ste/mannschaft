"""On-disk spec format: YAML frontmatter + markdown body.

Storage layout:
    <PI_HARNESS_HOME or ~/.pi-harness>/specs/<spec_id>.md

The frontmatter holds the typed metadata the linter, decomposer, and launch
bridge read. The body is a regenerated human-readable rendering of the same
fields. One ``Spec`` shape serves both the FastAPI editor and the CLI; the
``parse_spec_file`` alias exists for CLI call sites that read an arbitrary path.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import yaml

SpecStatus = Literal["draft", "linted", "decomposed", "running", "complete"]

FRONTMATTER_DELIM = "---"

# Run-shape fields carry launch metadata consumed by the spec_to_runspec bridge.
# They default so the editor's CRUD bodies (which only set the core fields) and
# hand-edited files stay valid.
_RUN_SHAPE_DEFAULTS = {
    "topology": "sequential",
    "sync_mode": "per_agent",
    "executor": "pi",
    "sync_profile": None,
    "session_id": None,
}


@dataclass
class Spec:
    id: str
    title: str
    goal: str
    acceptance_criteria: list[str]
    constraints: list[str]
    non_goals: list[str]
    created_at: str
    updated_at: str
    linter_score: float | None
    status: SpecStatus
    # ---- run-shape (Plan 7 launch metadata) ----
    topology: str = "sequential"
    sync_mode: str = "per_agent"
    executor: str = "pi"
    sync_profile: str | None = None
    session_id: str | None = None
    corpus_classifications: list[str] = field(default_factory=list)


def _home_dir() -> Path:
    raw = os.environ.get("PI_HARNESS_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".pi-harness"


def spec_storage_dir() -> Path:
    return _home_dir() / "specs"


def spec_path(spec_id: str) -> Path:
    return spec_storage_dir() / f"{spec_id}.md"


def _build_body(spec: Spec) -> str:
    lines: list[str] = [f"# {spec.title}", "", "## Goal", "", spec.goal, ""]
    if spec.acceptance_criteria:
        lines += ["## Acceptance Criteria", ""]
        lines += [f"- {item}" for item in spec.acceptance_criteria]
        lines.append("")
    if spec.constraints:
        lines += ["## Constraints", ""]
        lines += [f"- {item}" for item in spec.constraints]
        lines.append("")
    if spec.non_goals:
        lines += ["## Non-Goals", ""]
        lines += [f"- {item}" for item in spec.non_goals]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def serialize_spec(spec: Spec, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = asdict(spec)
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=True, default_flow_style=False)
    body = _build_body(spec)
    contents = f"{FRONTMATTER_DELIM}\n{yaml_block}{FRONTMATTER_DELIM}\n\n{body}"
    path.write_text(contents, encoding="utf-8")


def parse_spec(path: Path) -> Spec:
    text = path.read_text(encoding="utf-8")
    if not text.startswith(FRONTMATTER_DELIM):
        raise ValueError(f"Spec file {path} is missing YAML frontmatter")
    parts = text.split(f"\n{FRONTMATTER_DELIM}\n", 2)
    if len(parts) < 2:
        raise ValueError(f"Spec file {path} has malformed frontmatter")
    yaml_block = parts[0][len(FRONTMATTER_DELIM) :].lstrip("\n")
    data = yaml.safe_load(yaml_block) or {}
    # Accept `spec_id` as an alias for `id` from older / hand-authored files.
    if "id" not in data and "spec_id" in data:
        data["id"] = data.pop("spec_id")
    # Defaults for back-compat with hand-edited files.
    data.setdefault("constraints", [])
    data.setdefault("non_goals", [])
    data.setdefault("linter_score", None)
    data.setdefault("status", "draft")
    for key, default in _RUN_SHAPE_DEFAULTS.items():
        data.setdefault(key, default)
    data.setdefault("corpus_classifications", [])
    # Drop any unknown keys (e.g. a stray `agents:` block from an older scaffold)
    # so the dataclass constructor doesn't choke.
    allowed = set(Spec.__dataclass_fields__)
    data = {k: v for k, v in data.items() if k in allowed}
    return Spec(**data)


# CLI call sites read an arbitrary path; same parser.
parse_spec_file = parse_spec
