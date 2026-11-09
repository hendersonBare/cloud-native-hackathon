"""POST /internal/events: what delegates report. Mounted only on the cluster-only internal app."""

from __future__ import annotations

from fastapi import APIRouter, Request

from rapport_common.models import DelegateEvent

from .errors import EventRejected, GatewayError
from .routers.guards import DepsDep
from .schemas import Accepted

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post(
    "/events",
    status_code=202,
    response_model=Accepted,
    summary="A delegate reports a status, exchange message, policy decision or shared brief",
    responses={403: {"description": "unknown encounter, mismatched org/persona, or caller is not its pod"}},
)
async def delegate_event(event: DelegateEvent, request: Request, deps: DepsDep) -> Accepted:
    # the TCP peer, never X-Forwarded-For: this port has no proxy in front and the header could be forged
    ip = request.client.host if request.client else None
    try:
        await deps.encounters.handle_delegate_event(event, ip)
    except EventRejected as exc:
        raise GatewayError(403, "event rejected") from exc
    return Accepted()
