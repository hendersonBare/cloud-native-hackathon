"""Venue payloads.

These shapes are venue-specific and live here because ``rapport_common`` is integrator-owned.
CONTRACT CHANGE REQUEST: promote them into ``rapport_common.models`` once the integrator agrees.

Positions are floor-plan metres (origin at the south-west corner, x east, y north), never GPS degrees. Raw latitude
and longitude only ever appear in ``LocationUpdate`` (the request body) and are never stored or returned.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    model_serializer,
)
from rapport_common.models import Contract


def _no_nan(value: Any) -> Any:
    """``json.loads`` accepts NaN and Infinity. Swap them for a string the float check rejects, so the 422 echoes a
    JSON-safe input: echoing a NaN makes FastAPI's validation error response itself fail with a 500."""
    if isinstance(value, float) and not math.isfinite(value):
        return "not a finite number"
    return value


PersonaId = Annotated[str, Field(min_length=1, max_length=64)]
FiniteFloat = Annotated[float, BeforeValidator(_no_nan)]
PositionSource = Literal["gps", "checkin"]
PeerStatus = Literal["sharing", "not_sharing"]
LegKind = Literal["same_room", "leave", "walk", "enter", "arrive"]


class Room(Contract):
    id: str
    name: str
    x: float
    y: float
    w: float
    h: float
    door: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None  # [x, y] on the room's edge
    corridor: bool = False


class PublicVenue(Contract):
    """The floor plan a client may see: no check-in spots, sharing flags or GPS anchor."""

    id: str
    name: str
    width_m: float
    height_m: float
    corridor_y: float  # the corridor's centre line, where routes walk
    rooms: list[Room]


class Position(Contract):
    persona_id: str
    x: float  # metres, 0.1 m resolution
    y: float
    room_id: str
    source: PositionSource  # "gps": a fresh shared fix; "checkin": the person's check-in spot
    accuracy_m: float | None = None  # GPS only
    updated_at: AwareDatetime | None = None  # GPS only; None for check-ins


class VenueView(Contract):
    persona_id: str
    venue: PublicVenue
    sharing: bool  # my consent flag: others may find me
    me: Position


class LocationUpdate(Contract):
    """A GPS fix from the phone. Converted to venue metres at once; the degrees are never stored or logged."""

    persona_id: PersonaId
    lat: FiniteFloat = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: FiniteFloat = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: FiniteFloat | None = Field(default=None, ge=0, le=5000, allow_inf_nan=False)


class SharingBody(Contract):
    persona_id: PersonaId
    enabled: StrictBool  # consent: only a JSON true turns sharing on


class SharingState(Contract):
    persona_id: str
    enabled: bool


class Leg(Contract):
    """One step of the directions. Only the fields that apply to ``kind`` are sent (no nulls), like the JS model."""

    kind: LegKind
    room_id: str | None = None  # same_room, leave, walk (the corridor), enter
    direction: Literal["east", "west"] | None = None  # walk
    meters: int | None = None  # walk, arrive
    compass: str | None = None  # arrive

    @model_serializer(mode="wrap")
    def _drop_nulls(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        return {k: v for k, v in data.items() if v is not None} if isinstance(data, dict) else data


class Directions(Contract):
    """From me to a peer. When the peer is not sharing, ``to`` is None and the route is empty: nothing about them is
    revealed. Serialised with the key ``from`` (``from_`` in Python)."""

    model_config = ConfigDict(extra="forbid", validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)

    persona_id: str
    to_persona_id: str
    peer_status: PeerStatus
    from_: Position = Field(alias="from")
    to: Position | None = None
    route: list[list[float]] = Field(default_factory=list)  # waypoints [x, y] in metres
    distance_m: int | None = None  # walking distance along the route
    bearing_deg: int | None = None  # straight-line bearing to the peer, clockwise from north
    compass: str | None = None
    legs: list[Leg] = Field(default_factory=list)
