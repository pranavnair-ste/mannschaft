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
import re
import tempfile
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
    # Persisted output of POST /specs/{id}/decompose. None means "not
    # decomposed yet (or content changed since)" — /launch falls back to a
    # live decomposer call. Stored as plain dicts so YAML round-trips cleanly
    # and DecomposedTask stays owned by pi_harness.spec.decomposer.
    decomposed_tasks: list[dict] | None = None


def _home_dir() -> Path:
    raw = os.environ.get("PI_HARNESS_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".pi-harness"


def spec_storage_dir() -> Path:
    return _home_dir() / "specs"


# A spec_id becomes a filename, so it must be a single safe slug — no path
# separators, no '.'/'..'. Without this, an attacker-supplied spec_id (CLI arg
# or HTTP path param) could read/write/delete files outside the specs dir
# (audit #12/#17/#30).
_SPEC_ID_RE = re.compile(r"[A-Za-z0-9._-]+")


def validate_spec_id(spec_id: str) -> str:
    """Return ``spec_id`` unchanged if it is a safe slug; else raise ValueError."""
    if (
        not isinstance(spec_id, str)
        or spec_id in {".", ".."}
        or _SPEC_ID_RE.fullmatch(spec_id) is None
    ):
        raise ValueError(
            f"invalid spec_id {spec_id!r}: must match [A-Za-z0-9._-]+ "
            "(no path separators, not '.'/'..')"
        )
    return spec_id


def spec_path(spec_id: str) -> Path:
    """Resolve the on-disk path for ``spec_id``, validating it cannot escape the
    specs directory (path traversal)."""
    validate_spec_id(spec_id)
    storage = spec_storage_dir()
    path = storage / f"{spec_id}.md"
    # Belt-and-suspenders: the resolved file must sit directly in the specs dir.
    if path.resolve().parent != storage.resolve():
        raise ValueError(f"spec_id {spec_id!r} escapes the specs directory")
    return path


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
    # Atomic write: a concurrent reader (dashboard/finalizer) never sees a torn
    # file, and a crash mid-write can't corrupt an existing spec (audit #33).
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contents)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
    data.setdefault("decomposed_tasks", None)
    # Drop any unknown keys (e.g. a stray `agents:` block from an older scaffold)
    # so the dataclass constructor doesn't choke.
    allowed = set(Spec.__dataclass_fields__)
    data = {k: v for k, v in data.items() if k in allowed}
    return Spec(**data)


# CLI call sites read an arbitrary path; same parser.
parse_spec_file = parse_spec
