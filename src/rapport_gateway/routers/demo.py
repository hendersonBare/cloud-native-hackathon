"""POST /api/demo/reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from rapport_venue.api import get_service as venue_service

from ..schemas import ResetResult
from .guards import DepsDep, require_admin

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post(
    "/reset",
    response_model=ResetResult,
    dependencies=[Depends(require_admin)],
    summary="Clear in-memory state (requests, encounters, replay buffer, limits, calendar, venue)",
    responses={401: {"description": "admin token required"}, 403: {"description": "wrong admin token"}},
)
async def reset(deps: DepsDep) -> ResetResult:
    await deps.backend.reset()
    if deps.calendar is not None:
        deps.calendar.reset()
    venue_service().reset()  # venue sharing flags back to the seed, every stored GPS fix forgotten
    return ResetResult()
