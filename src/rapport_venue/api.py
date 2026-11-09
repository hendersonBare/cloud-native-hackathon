"""HTTP routes. The gateway mounts ``router`` in-process; ``get_service`` is the dependency tests and the gateway
can override with ``app.dependency_overrides``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from .models import Directions, LocationUpdate, Position, SharingBody, SharingState, VenueView
from .service import VenueService

router = APIRouter(prefix="/api/venue", tags=["venue"])

_service: VenueService | None = None


def get_service() -> VenueService:
    """The process-wide service (created on first use). Override it in tests with ``dependency_overrides``."""
    global _service
    if _service is None:
        _service = VenueService()
    return _service


Service = Annotated[VenueService, Depends(get_service)]
PersonaId = Annotated[str, Query(description="Who is asking", min_length=1, max_length=64)]

_UNKNOWN_PERSONA = {404: {"description": "unknown_persona"}}


@router.get("", response_model=VenueView, responses=_UNKNOWN_PERSONA)
async def get_venue(service: Service, persona_id: PersonaId) -> VenueView:
    """The floor plan, my sharing flag and where I am (fresh GPS, else my check-in spot)."""
    return service.view(persona_id)


@router.put(
    "/location",
    response_model=Position,
    responses={
        **_UNKNOWN_PERSONA,
        409: {"description": "sharing_off"},
        422: {"description": "too_inaccurate, outside_venue or a validation error"},
    },
)
async def put_location(body: LocationUpdate, service: Service) -> Position:
    """A GPS fix from the phone, placed on the floor plan. Only the placed point is kept."""
    return service.update_location(body)


@router.put("/sharing", response_model=SharingState, responses=_UNKNOWN_PERSONA)
async def put_sharing(body: SharingBody, service: Service) -> SharingState:
    """Consent to be found. Turning it off deletes my stored GPS fix at once."""
    return service.set_sharing(body)


@router.get(
    "/directions",
    response_model=Directions,
    response_model_by_alias=True,  # the JSON key is "from"
    responses={**_UNKNOWN_PERSONA, 422: {"description": "same_person or a validation error"}},
)
async def get_directions(
    service: Service,
    persona_id: PersonaId,
    to: Annotated[str, Query(description="Whom to find", min_length=1, max_length=64)],
) -> Directions:
    """The walking route from me to ``to``. A peer who is not sharing gets ``peer_status: not_sharing`` and nothing
    else."""
    return service.directions(persona_id, to)
