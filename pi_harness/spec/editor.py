"""FastAPI HTTP surface for the spec layer.

This module exposes a `router` (mounted by `pi_harness.api.server`) and a
standalone `app` (for tests + isolated debugging via
`uv run python -m pi_harness.spec.editor`). The canonical user-facing
entry point is `pi-harness serve`, which boots the unified dashboard app
(`pi_harness.api.server`) — that mounts this router alongside the runs /
corpus / guards / ws routes on a single port (default 8800).

The /launch route bridges to Plan 5's Coordinator through the shared
spec_to_runspec helper so the dashboard and the CLI emit identical runs.
"""
from __future__ import annotations

import os
import re
import threading
import uuid
from datetime import datetime, timezone

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, status
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

logger = logging.getLogger(__name__)

# Routes live on a router so both this module's standalone ``app`` and the
# Symphony dashboard app (pi_harness.api.server) can mount the same /specs
# surface without duplicating handlers.
router = APIRouter()

# Serializes spec-file read-modify-write across ALL in-process spec mutators
# (every CRUD/lint/decompose/launch handler + the background launch finalizer),
# so no writer's read-then-write can interleave with — and clobber — another's
# (audit #33). Paired with the atomic write in serialize_spec. Every mutation
# MUST go through _patch_spec; do slow work (LLM decompose, coordinator.launch)
# BEFORE calling it so the lock is held only for the file read-modify-write.
_SPEC_LOCK = threading.Lock()


def _patch_spec(spec_id: str, mutate) -> Spec:
    """Atomic, lock-guarded read-modify-write of a spec file.

    Under ``_SPEC_LOCK``: re-read the spec FRESH from disk, apply
    ``mutate(data: dict) -> dict``, and serialize. Re-reading inside the lock is
    what makes concurrent field edits survive: a mutator only overwrites the
    fields it changes, on top of whatever the latest writer (e.g. the finalizer's
    status flip) committed."""
    with _SPEC_LOCK:
        data = parse_spec(spec_path(spec_id)).__dict__.copy()
        updated = Spec(**mutate(data))
        serialize_spec(updated, spec_path(spec_id))
        return updated


def _set_spec_status(spec_id: str, new_status: str) -> None:
    """Flip a spec's status (launch finalizer). Tolerant of a missing/changed
    spec file; updates only status/updated_at so concurrent field edits survive."""
    def _mutate(data: dict) -> dict:
        data["status"] = new_status
        data["updated_at"] = _now()
        return data

    try:
        _patch_spec(spec_id, _mutate)
    except Exception:
        logger.exception("finalizer: failed to update status for spec %s", spec_id)


def _finalize_run(coordinator, handle, spec_id: str, timeout: float = 1800.0) -> None:
    """Background-task body: wait for the team to terminate, run the improve
    loop + teardown via on_completion, and flip the spec to its post-run
    status. Errors are logged; they must not crash the FastAPI worker."""
    success = False
    try:
        result = coordinator.wait_for_completion(handle, timeout=timeout)
        success = bool(getattr(result, "success", False))
        coordinator.on_completion(handle)
    except Exception:
        logger.exception("finalizer: background completion failed for run %s", handle.run_id)
    _set_spec_status(spec_id, "complete" if success else "decomposed")


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
    try:
        path = spec_path(spec_id)
    except ValueError as exc:
        # Reject a malformed/traversing spec_id with 400, not a 500 (audit #30).
        raise HTTPException(status_code=400, detail=str(exc))
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
        except Exception:
            # Skip ANY unreadable/corrupt spec (bad YAML, missing field, etc.)
            # rather than 500-ing the whole listing on one bad file (audit #31).
            logger.warning("list_specs: skipping unreadable spec %s", path, exc_info=True)
            continue
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


# Fields the decomposer reads when generating tasks; changing any of these
# invalidates the persisted decomposition and the linter score.
_DECOMPOSER_INPUT_FIELDS = frozenset(
    {"title", "goal", "acceptance_criteria", "constraints", "non_goals"}
)


@router.put("/specs/{spec_id}", response_model=Spec)
def update_spec(spec_id: str, body: UpdateSpecBody) -> Spec:
    _load(spec_id)  # 400/404 before taking the lock
    patch = body.model_dump(exclude_unset=True)

    def _mutate(data: dict) -> dict:
        data.update(patch)
        data["updated_at"] = _now()
        if _DECOMPOSER_INPUT_FIELDS & patch.keys():
            data["status"] = "draft"
            data["linter_score"] = None
            data["decomposed_tasks"] = None
        return data

    return _patch_spec(spec_id, _mutate)


# ---------- linter + decomposer routes ----------


@router.post("/specs/{spec_id}/lint", response_model=LintResult)
def lint_spec(spec_id: str) -> LintResult:
    result = Linter().lint(_load(spec_id))  # read + lint outside the lock

    def _mutate(data: dict) -> dict:
        data["linter_score"] = result.score
        data["updated_at"] = _now()
        # Lint promotes draft → linted, but never demotes a decomposed/running
        # spec — only an edit (PUT) invalidates the decomposition.
        if not result.errors and data["status"] == "draft":
            data["status"] = "linted"
        return data

    _patch_spec(spec_id, _mutate)
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
    tasks = decomposer.decompose(spec)  # LLM call — OUTSIDE the lock

    def _mutate(data: dict) -> dict:
        data["status"] = "decomposed"
        data["updated_at"] = _now()
        data["decomposed_tasks"] = [t.model_dump() for t in tasks]
        return data

    _patch_spec(spec_id, _mutate)
    return DecomposeResponse(tasks=tasks)


@router.post("/specs/{spec_id}/launch", response_model=LaunchResponse)
def launch_spec(
    spec_id: str,
    background_tasks: BackgroundTasks,
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
    if spec.decomposed_tasks is not None:
        tasks = [DecomposedTask(**t) for t in spec.decomposed_tasks]
    else:
        # Legacy specs decomposed before the persistence change have status
        # "decomposed" but no stored tasks; fall back to a live decomposer call.
        tasks = decomposer.decompose(spec)
    run_spec = spec_to_runspec(spec, tasks)
    handle = coordinator.launch(run_spec)  # launches the team — OUTSIDE the lock

    def _mutate(data: dict) -> dict:
        data["status"] = "running"
        data["updated_at"] = _now()
        return data

    _patch_spec(spec_id, _mutate)

    # Reconcile the run after the HTTP response is sent: poll ClawTeam to
    # completion, run improve + teardown, flip spec status. Without this the
    # registry stays stuck on 'running' forever (the /launch endpoint is
    # otherwise fire-and-forget; the CLI path is what currently drives
    # wait_for_completion).
    background_tasks.add_task(_finalize_run, coordinator, handle, spec_id)

    return LaunchResponse(run_id=handle.run_id)


app = FastAPI(title="Pi-Harness Spec Editor", version="0.1.0")
app.include_router(router)


def main() -> None:  # pragma: no cover
    import uvicorn

    port = int(os.environ.get("PI_HARNESS_SPEC_PORT", "8800"))
    uvicorn.run("pi_harness.spec.editor:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
