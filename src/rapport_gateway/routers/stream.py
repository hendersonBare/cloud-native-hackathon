"""GET /api/stream: Server-Sent Events for a phone or the swarm panel."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query
from sse_starlette import EventSourceResponse, ServerSentEvent

from ..bus import EventBus
from ..errors import GatewayError, require_persona
from .guards import DepsDep

router = APIRouter(prefix="/api", tags=["stream"])


def sse_frame(event_type: str, data: str) -> ServerSentEvent:
    """`event: <type>`, `data: <GatewayEvent JSON>`, blank line (LF separators, as in SPEC 7.1)."""
    return ServerSentEvent(data=data, event=event_type, sep="\n")


def keepalive() -> ServerSentEvent:
    return ServerSentEvent(comment="keepalive", sep="\n")


async def event_frames(bus: EventBus, persona_id: str | None) -> AsyncIterator[ServerSentEvent]:
    """Subscribe when the response starts (replaying recent matching events), unsubscribe when it ends."""
    sub = bus.subscribe(persona_id)
    try:
        while True:
            event = await sub.queue.get()
            yield sse_frame(event.type, event.model_dump_json())
    finally:
        bus.unsubscribe(sub)


@router.get(
    "/stream",
    response_model=None,
    response_class=EventSourceResponse,
    summary="Server-Sent Events: a phone (?persona_id=) or the swarm panel (?view=swarm)",
    responses={200: {"content": {"text/event-stream": {}}, "description": "GatewayEvent frames"}},
)
async def stream(
    deps: DepsDep,
    persona_id: Annotated[str | None, Query(description="e.g. acme.ava: that person's phone")] = None,
    view: Annotated[str | None, Query(description="'swarm': the swarm panel")] = None,
) -> EventSourceResponse:
    if (persona_id is None) == (view is None):
        raise GatewayError(422, "pass exactly one of persona_id or view=swarm")
    if view is not None and view != "swarm":
        raise GatewayError(422, "view must be 'swarm'")
    if persona_id is not None:
        require_persona(persona_id)
    return EventSourceResponse(
        event_frames(deps.bus, persona_id),
        sep="\n",
        ping=deps.settings.keepalive_s,
        ping_message_factory=keepalive,
        headers={"Cache-Control": "no-cache"},
    )
