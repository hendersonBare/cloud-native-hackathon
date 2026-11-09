"""GET /api/stream: Server-Sent Events for a phone or the swarm panel.

The platform's edge proxy cuts a stream after about 15 s, so the gateway ends each stream itself after
RAPPORT_SSE_MAX_SECONDS and relies on EventSource reconnecting: every event carries an `id:`, `retry: 1000`
makes clients reconnect within a second, and the reconnect's Last-Event-ID replays only what was missed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Query
from sse_starlette import EventSourceResponse, ServerSentEvent

from ..bus import EventBus
from ..errors import GatewayError, require_persona
from .guards import DepsDep

router = APIRouter(prefix="/api", tags=["stream"])

RETRY_MS = 1000
EDGE_KEEPALIVE_S = 15.0


def sse_frame(event_type: str, data: str, event_id: int | None = None) -> ServerSentEvent:
    """`id: <n>`, `event: <type>`, `data: <GatewayEvent JSON>`, blank line (LF separators, as in SPEC 7.1)."""
    return ServerSentEvent(data=data, event=event_type, id=None if event_id is None else str(event_id), sep="\n")


def retry_frame() -> ServerSentEvent:
    return ServerSentEvent(retry=RETRY_MS, sep="\n")


def keepalive() -> ServerSentEvent:
    return ServerSentEvent(comment="keepalive", sep="\n")


def parse_event_id(raw: str | None) -> int | None:
    try:
        return int(raw.strip()) if raw and raw.strip() else None
    except ValueError:
        return None


async def event_frames(
    bus: EventBus, persona_id: str | None, *, after_id: int | None = None, max_seconds: float = 0.0
) -> AsyncIterator[ServerSentEvent]:
    """Subscribe when the response starts (replaying recent matching events), unsubscribe when it ends.
    With max_seconds > 0 the generator returns after that long, which closes the stream cleanly."""
    sub = bus.subscribe(persona_id, after_id=after_id)
    deadline = time.monotonic() + max_seconds if max_seconds > 0 else None
    try:
        yield retry_frame()
        while True:
            if deadline is None:
                event = await sub.queue.get()
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    return
            yield sse_frame(event.type, event.model_dump_json(), getattr(event, "seq", None))
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
    last_event_id: Annotated[
        str | None, Query(description="Fallback for the Last-Event-ID header: replay only newer events")
    ] = None,
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID", include_in_schema=False)] = None,
) -> EventSourceResponse:
    if (persona_id is None) == (view is None):
        raise GatewayError(422, "pass exactly one of persona_id or view=swarm")
    if view is not None and view != "swarm":
        raise GatewayError(422, "view must be 'swarm'")
    if persona_id is not None:
        require_persona(persona_id)
    after_id = parse_event_id(last_event_id_header)
    if after_id is None:
        after_id = parse_event_id(last_event_id)
    max_seconds = deps.settings.sse_max_seconds
    ping = deps.settings.keepalive_s
    if max_seconds > 0:
        ping = min(ping, EDGE_KEEPALIVE_S, max_seconds / 2)
    return EventSourceResponse(
        event_frames(deps.bus, persona_id, after_id=after_id, max_seconds=max_seconds),
        sep="\n",
        ping=ping,
        ping_message_factory=keepalive,
        headers={"Cache-Control": "no-cache"},
    )
