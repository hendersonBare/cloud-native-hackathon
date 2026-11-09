"""POST /api/demo/reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..schemas import ResetResult
from .guards import DepsDep, require_admin

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post(
    "/reset",
    response_model=ResetResult,
    dependencies=[Depends(require_admin)],
    summary="Clear in-memory state (requests, encounters, replay buffer, limits)",
    responses={401: {"description": "admin token required"}, 403: {"description": "wrong admin token"}},
)
async def reset(deps: DepsDep) -> ResetResult:
    await deps.backend.reset()
    return ResetResult()
