from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from pi_harness.api.models import RunDetailDTO, RunSummaryDTO, TrajectoryEventDTO
from pi_harness.trajectory.runs import query_run_summaries
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
