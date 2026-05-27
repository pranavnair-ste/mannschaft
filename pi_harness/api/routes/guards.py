from __future__ import annotations

from fastapi import APIRouter, Request

from pi_harness.api.models import PromotionCandidateDTO
from pi_harness.guards.promote import suggest_promotions
from pi_harness.trajectory.store import init_db

router = APIRouter(prefix="/guards", tags=["guards"])


@router.get("/promotion-candidates", response_model=list[PromotionCandidateDTO])
def promotion_candidates(request: Request) -> list[PromotionCandidateDTO]:
    db_path = request.app.state.config.trajectory_db_path
    init_db(db_path)  # tolerate a fresh system with no runs yet
    return [PromotionCandidateDTO(**vars(s)) for s in suggest_promotions(db_path=db_path)]
