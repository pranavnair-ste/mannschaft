"""FastAPI HTTP surface for the spec layer.

Default port: 8800 (ClawTeam's `board serve --port 8080` uses 8080 — do NOT
collide). Run directly: `uv run python -m pi_harness.spec.editor` or
`uv run pi-harness serve`.

The /launch route bridges to Plan 5's Coordinator through the shared
spec_to_runspec helper so the dashboard and the CLI emit identical runs.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from pi_harness.spec.decomposer import DecomposedTask
from pi_harness.spec.format import (
    Spec,
    parse_spec,
    serialize_spec,
    spec_path,
    spec_storage_dir,
)
from pi_harness.spec.linter import Linter, LintResult
from pi_harness.spec.runspec import build_coordinator, spec_to_runspec

# Routes live on a router so both this module's standalone ``app`` and the
# Symphony dashboard app (pi_harness.api.server) can mount the same /specs
# surface without duplicating handlers.
router = APIRouter()


# ---------- request / response models ----------


class CreateSpecBody(BaseModel):
    title: str
    goal: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)


class UpdateSpecBody(BaseModel):
    title: str | None = None
    goal: str | None = None
    acceptance_criteria: list[str] | None = None
    constraints: list[str] | None = None
    non_goals: list[str] | None = None
    topology: str | None = None
    sync_mode: str | None = None
    executor: str | None = None
    sync_profile: str | None = None
    session_id: str | None = None
    corpus_classifications: list[str] | None = None


class SpecList(BaseModel):
    specs: list[Spec]


class DecomposeResponse(BaseModel):
    tasks: list[DecomposedTask]


class LaunchResponse(BaseModel):
    run_id: str


# ---------- helpers ----------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "untitled"


def _new_spec_id(title: str) -> str:
    return f"spec-{_slugify(title)[:32]}-{uuid.uuid4().hex[:6]}"


def _load(spec_id: str) -> Spec:
    path = spec_path(spec_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")
    return parse_spec(path)


# ---------- dependencies (override-able in tests) ----------


def get_config():
    from pi_harness.config import load_config

    return load_config()


def get_decomposer():
    from pi_harness.spec.decomposer import Decomposer

    return Decomposer(get_config())


def get_coordinator():
    return build_coordinator(get_config())


# ---------- CRUD routes ----------


@router.get("/specs", response_model=SpecList)
def list_specs() -> SpecList:
    storage = spec_storage_dir()
    if not storage.exists():
        return SpecList(specs=[])
    specs: list[Spec] = []
    for path in sorted(storage.glob("*.md")):
        try:
            specs.append(parse_spec(path))
        except ValueError:
            continue  # skip malformed files; don't take the whole list down
    return SpecList(specs=specs)


@router.get("/specs/{spec_id}", response_model=Spec)
def get_spec(spec_id: str) -> Spec:
    return _load(spec_id)


@router.post("/specs", response_model=Spec, status_code=status.HTTP_201_CREATED)
def create_spec(body: CreateSpecBody) -> Spec:
    now = _now()
    spec = Spec(
        id=_new_spec_id(body.title),
        title=body.title,
        goal=body.goal,
        acceptance_criteria=list(body.acceptance_criteria),
        constraints=list(body.constraints),
        non_goals=list(body.non_goals),
        created_at=now,
        updated_at=now,
        linter_score=None,
        status="draft",
    )
    serialize_spec(spec, spec_path(spec.id))
    return spec


@router.put("/specs/{spec_id}", response_model=Spec)
def update_spec(spec_id: str, body: UpdateSpecBody) -> Spec:
    spec = _load(spec_id)
    data = spec.__dict__.copy()
    data.update(body.model_dump(exclude_unset=True))
    data["updated_at"] = _now()
    updated = Spec(**data)
    serialize_spec(updated, spec_path(spec_id))
    return updated


# ---------- linter + decomposer routes ----------


@router.post("/specs/{spec_id}/lint", response_model=LintResult)
def lint_spec(spec_id: str) -> LintResult:
    spec = _load(spec_id)
    result = Linter().lint(spec)
    data = spec.__dict__.copy()
    data["linter_score"] = result.score
    data["updated_at"] = _now()
    if not result.errors:
        data["status"] = "linted"
    serialize_spec(Spec(**data), spec_path(spec_id))
    return result


@router.post("/specs/{spec_id}/decompose", response_model=DecomposeResponse)
def decompose_spec(spec_id: str, decomposer=Depends(get_decomposer)) -> DecomposeResponse:
    spec = _load(spec_id)
    if spec.linter_score is None or spec.linter_score < 1.0:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "spec must lint to score 1.0 before decomposition",
                "current_score": spec.linter_score,
                "remediation": [
                    "POST /specs/{id}/lint to re-run the linter after edits",
                    "fix every error and warning until score == 1.0",
                ],
            },
        )
    tasks = decomposer.decompose(spec)
    data = spec.__dict__.copy()
    data["status"] = "decomposed"
    data["updated_at"] = _now()
    serialize_spec(Spec(**data), spec_path(spec_id))
    return DecomposeResponse(tasks=tasks)


@router.post("/specs/{spec_id}/launch", response_model=LaunchResponse)
def launch_spec(
    spec_id: str,
    decomposer=Depends(get_decomposer),
    coordinator=Depends(get_coordinator),
) -> LaunchResponse:
    spec = _load(spec_id)
    if spec.status != "decomposed":
        raise HTTPException(
            status_code=409,
            detail=(
                f"spec status is {spec.status!r}; expected 'decomposed'. "
                "POST /specs/{id}/decompose first."
            ),
        )
    # Tasks aren't persisted on the spec, so re-derive them for the launch.
    tasks = decomposer.decompose(spec)
    run_spec = spec_to_runspec(spec, tasks)
    handle = coordinator.launch(run_spec)

    data = spec.__dict__.copy()
    data["status"] = "running"
    data["updated_at"] = _now()
    serialize_spec(Spec(**data), spec_path(spec_id))
    return LaunchResponse(run_id=handle.run_id)


app = FastAPI(title="Pi-Harness Spec Editor", version="0.1.0")
app.include_router(router)


def main() -> None:  # pragma: no cover
    import uvicorn

    port = int(os.environ.get("PI_HARNESS_SPEC_PORT", "8800"))
    uvicorn.run("pi_harness.spec.editor:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
