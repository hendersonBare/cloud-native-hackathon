"""HTTP routes. The gateway mounts ``router`` in-process; ``get_service`` is the dependency tests and the gateway
can override with ``app.dependency_overrides``."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Request, Depends, Query, Response
from opentelemetry import trace
from pydantic import AwareDatetime

from .models import (
    AddTalkBody,
    AgendaView,
    CalendarEvent,
    CalendarView,
    ConferenceModeBody,
    ConferenceModeState,
    CreateEventBody,
    CreateEventResult,
    FreeBusy,
    MeetingProposal,
    ProposeBody,
    RespondBody,
    UpdateEventBody,
)
from .service import MAX_QUERY_LENGTH, CalendarService

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

_service: CalendarService | None = None


def get_service() -> CalendarService:
    """The process-wide service (created on first use). Override it in tests with ``dependency_overrides``."""
    global _service
    if _service is None:
        _service = CalendarService()
    return _service


Service = Annotated[CalendarService, Depends(get_service)]
PersonaId = Annotated[str, Query(description="Whose calendar", min_length=1, max_length=64)]

def _scrub_query_from_server_span(request: Request) -> None:
    """The search text is private: the HTTP server span (set up by init_telemetry) records the full URL, so replace
    the URL attributes that carry the query string with the bare path."""
    span = trace.get_current_span()
    if not span.is_recording():
        return
    path = request.url.path
    for key, value in (
        ("http.url", f"{request.url.scheme}://{request.url.netloc}{path}"),
        ("url.full", f"{request.url.scheme}://{request.url.netloc}{path}"),
        ("http.target", path),
        ("url.query", ""),
    ):
        span.set_attribute(key, value)


_UNKNOWN_PERSONA = {404: {"description": "unknown_persona or event_not_found"}}
# 409 codes, so the OpenAPI page documents every refusal the phone handles.
_CONFLICTS = {
    409: {
        "description": "calendar_full, not_editable, not_deletable, not_a_meeting, meeting_closed, already_added "
        "or no_mutual_slot"
    }
}
_ERRORS = {**_UNKNOWN_PERSONA, **_CONFLICTS}


@router.get("", response_model=CalendarView, responses=_UNKNOWN_PERSONA)
async def get_calendar(
    service: Service,
    persona_id: PersonaId,
    start: Annotated[date | None, Query(description="First local day, YYYY-MM-DD (default: week start)")] = None,
    days: Annotated[int, Query(ge=1, le=14)] = 7,
) -> CalendarView:
    return await service.view(persona_id, start, days)


@router.post("/events", status_code=201, response_model=CreateEventResult, responses=_ERRORS)
async def create_event(body: CreateEventBody, service: Service) -> CreateEventResult:
    return await service.create_event(body)


@router.patch("/events/{event_id}", response_model=CalendarEvent, responses=_ERRORS)
async def update_event(event_id: str, body: UpdateEventBody, service: Service) -> CalendarEvent:
    return await service.update_event(event_id, body)


@router.delete("/events/{event_id}", status_code=204, response_class=Response, responses=_ERRORS)
async def delete_event(event_id: str, persona_id: PersonaId, service: Service) -> Response:
    await service.delete_event(event_id, persona_id)
    return Response(status_code=204)


@router.post("/events/{event_id}/respond", response_model=CalendarEvent, responses=_ERRORS)
async def respond(event_id: str, body: RespondBody, service: Service) -> CalendarEvent:
    return await service.respond(event_id, body)


@router.put("/conference-mode", response_model=ConferenceModeState, responses=_UNKNOWN_PERSONA)
async def set_conference_mode(body: ConferenceModeBody, service: Service) -> ConferenceModeState:
    return await service.set_conference_mode(body)


# The scrub is a route dependency, not a call in the handler: it must also run when validation fails (422).
@router.get(
    "/agenda",
    response_model=AgendaView,
    responses=_UNKNOWN_PERSONA,
    dependencies=[Depends(_scrub_query_from_server_span)],
)
async def get_agenda(
    service: Service,
    persona_id: PersonaId,
    q: Annotated[str, Query(max_length=MAX_QUERY_LENGTH)] = "",
) -> AgendaView:
    return await service.agenda(persona_id, q)


@router.post("/talks", status_code=201, response_model=CreateEventResult, responses=_ERRORS)
async def add_talk(body: AddTalkBody, service: Service) -> CreateEventResult:
    return await service.add_talk(body)


@router.post(
    "/propose",
    status_code=201,
    response_model=MeetingProposal,
    responses={
        200: {"description": "A meeting with this person already existed", "model": MeetingProposal},
        **_ERRORS,
    },
)
async def propose(body: ProposeBody, service: Service, response: Response) -> MeetingProposal:
    proposal = await service.propose(body)
    if not proposal.created:
        response.status_code = 200
    return proposal


@router.get("/freebusy", response_model=FreeBusy, responses=_UNKNOWN_PERSONA)
async def get_freebusy(
    service: Service, persona_id: PersonaId, start: AwareDatetime, end: AwareDatetime
) -> FreeBusy:
    return await service.freebusy(persona_id, start, end)


@router.get("/export.ics", response_class=Response, responses={200: {"content": {"text/calendar": {}}}})
async def export_ics(service: Service, persona_id: PersonaId) -> Response:
    body = await service.export_ics(persona_id)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="rapport-{persona_id}.ics"'},
    )
