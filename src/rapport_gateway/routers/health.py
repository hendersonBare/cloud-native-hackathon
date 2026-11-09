"""GET /healthz."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import Health
from .guards import DepsDep

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=Health, summary="Liveness and the deployed version")
async def healthz(deps: DepsDep) -> Health:
    return Health(ok=True, version=deps.settings.version)
