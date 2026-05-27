from __future__ import annotations

from collections import OrderedDict

from fastapi import APIRouter, HTTPException, Query, Request

from pi_harness.api.models import (
    AgentTimelineRowDTO,
    BranchRequest,
    BranchResponse,
    RunDetailDTO,
    RunSummaryDTO,
    TimelineDTO,
    TrajectoryEventDTO,
)
from pi_harness.trajectory.runs import get_run, query_run_summaries
from pi_harness.trajectory.store import query_events

router = APIRouter(tags=["runs"])


def _db(request: Request):
    return request.app.state.config.trajectory_db_path


@router.get("/runs", response_model=list[RunSummaryDTO])
def list_runs(
    request: Request,
    status: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
) -> list[RunSummaryDTO]:
    summaries = query_run_summaries(status=status, limit=limit, db_path=_db(request))
    return [RunSummaryDTO(**vars(s)) for s in summaries]


@router.get("/runs/{run_id}", response_model=RunDetailDTO)
def get_run_detail(request: Request, run_id: str) -> RunDetailDTO:
    match = next(
        (s for s in query_run_summaries(db_path=_db(request)) if s.run_id == run_id),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="run not found")
    events = query_events(run_id=run_id, db_path=_db(request))
    return RunDetailDTO(
        summary=RunSummaryDTO(**vars(match)),
        events=[TrajectoryEventDTO(**vars(e)) for e in events],
    )


def _run_exists(request: Request, run_id: str) -> bool:
    return any(s.run_id == run_id for s in query_run_summaries(db_path=_db(request)))


@router.get("/runs/{run_id}/timeline", response_model=TimelineDTO)
def get_timeline(request: Request, run_id: str) -> TimelineDTO:
    if not _run_exists(request, run_id):
        raise HTTPException(status_code=404, detail="run not found")
    events = query_events(run_id=run_id, db_path=_db(request))
    grouped: "OrderedDict[str, list[TrajectoryEventDTO]]" = OrderedDict()
    for e in sorted(events, key=lambda ev: ev.ts):
        grouped.setdefault(e.agent_id, []).append(TrajectoryEventDTO(**vars(e)))
    return TimelineDTO(
        run_id=run_id,
        agents=[AgentTimelineRowDTO(agent_id=a, events=evs) for a, evs in grouped.items()],
    )


@router.post("/runs/{run_id}/branch", response_model=BranchResponse)
def branch_run(request: Request, run_id: str, body: BranchRequest) -> BranchResponse:
    if get_run(run_id, db_path=_db(request)) is None:
        raise HTTPException(status_code=404, detail="run not found")
    coord = request.app.state.coordinator_factory(request.app.state.config)
    try:
        handle = coord.branch(run_id, body.step_id, body.overrides)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return BranchResponse(
        run_id=handle.run_id, parent_run_id=run_id, branched_from_step=body.step_id
    )
