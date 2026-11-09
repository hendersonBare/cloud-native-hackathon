"""POST /api/connect and POST /api/connect/{request_id}/accept."""

from __future__ import annotations

from fastapi import APIRouter

from rapport_common.models import AcceptBody, ConnectBody

from ..schemas import EncounterCreated, RequestCreated
from .guards import DepsDep

router = APIRouter(prefix="/api", tags=["connect"])


@router.post(
    "/connect",
    response_model=RequestCreated,
    summary="Ask another person's agent to meet; their phone gets a connect_request event",
    responses={404: {"description": "unknown persona"}, 422: {"description": "no agent, or same company"}},
)
async def create_connect_request(body: ConnectBody, deps: DepsDep) -> RequestCreated:
    return RequestCreated(request_id=await deps.backend.connect(body))


@router.post(
    "/connect/{request_id}/accept",
    response_model=EncounterCreated,
    summary="The asked person accepts: creates the Encounter and starts both delegates",
    responses={
        403: {"description": "only the person who was asked can accept"},
        404: {"description": "unknown request"},
        502: {"description": "the cluster refused the Encounter"},
        503: {"description": "Kubernetes is not available"},
    },
)
async def accept_connect_request(request_id: str, body: AcceptBody, deps: DepsDep) -> EncounterCreated:
    return EncounterCreated(encounter_id=await deps.backend.accept(request_id, body))
