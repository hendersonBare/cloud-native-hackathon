"""The venue rules: who shares their location, where everyone is and how to walk to them.

In-memory state seeded from ``data/venue.json``; ``reset()`` restores it. The clock is injectable for tests.

Privacy: a GPS fix is converted to floor-plan metres at once and only the placed point (0.1 m), its accuracy and
its time are kept; the latitude and longitude are never stored, logged or put on a span. A fix is kept only while
its owner shares and for at most ``gps_ttl_s``. Sharing is a per-person consent flag: turning it off deletes the
stored fix at once, and directions to someone who is not sharing reveal nothing about them.

Per-device consent: turning sharing on returns a random ``sharing_token`` to that device only (the service keeps its
SHA-256). GPS fixes, and turning sharing on again while a device holds it, need that token, so nobody else can feed or
take over someone's location. Turning sharing off never needs it: that only reduces exposure, and it lets a person
switch off sharing that someone else switched on. The gateway has no logins, so this is not identity: anyone can still
switch sharing on for a person who isn't sharing, which reveals only that person's check-in spot. The public venue never
includes other people's check-in spots, sharing flags or the GPS anchor. Spans and logs carry persona IDs only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from opentelemetry.trace import Span
from rapport_common.names import personas
from rapport_common.telemetry import ATTR_PERSONA, tracer

from . import geometry
from .models import (
    Directions,
    Leg,
    LocationUpdate,
    Position,
    PublicVenue,
    SharingBody,
    SharingState,
    VenueView,
)

log = logging.getLogger("rapport.venue")

VENUE_FILE = Path(__file__).parent / "data" / "venue.json"
ORIGIN_ENV = "RAPPORT_VENUE_ORIGIN"
ATTR_PEER_STATUS = "rapport.venue.peer_status"


class VenueError(HTTPException):
    """An API error with a machine-readable code as its ``detail`` (e.g. ``sharing_off``)."""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(status_code=status_code, detail=code)


@dataclass(frozen=True)
class _Fix:
    """A placed GPS fix: venue metres only, never degrees."""

    x: float
    y: float
    accuracy_m: float | None
    at: datetime


@contextmanager
def _span(name: str, persona_id: str) -> Iterator[Span]:
    with tracer("rapport.venue").start_as_current_span(name) as span:
        span.set_attribute(ATTR_PERSONA, persona_id)
        yield span


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def load_venue(path: Path = VENUE_FILE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _origin_from_env() -> dict[str, float] | None:
    """``RAPPORT_VENUE_ORIGIN="lat,lng"`` anchors the floor plan's south-west corner on demo day. A malformed value is
    ignored with a warning that does not repeat it."""
    raw = os.environ.get(ORIGIN_ENV)
    if not raw:
        return None
    try:
        lat_s, lng_s = raw.split(",")
        lat, lng = float(lat_s), float(lng_s)
        if math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180:
            return {"lat": lat, "lng": lng}
    except ValueError:
        pass
    log.warning("%s is not 'lat,lng' in degrees; using the venue file's anchor", ORIGIN_ENV)
    return None


def _check_venue(venue: dict[str, Any]) -> None:
    """Fail at start-up, not mid-request, on a venue the geometry cannot route."""
    PublicVenue.model_validate(geometry.public_venue(venue))
    if geometry.corridor_of(venue) is None:
        raise ValueError("the venue needs a room with corridor: true")
    if any(r.get("door") is None for r in venue["rooms"] if not r.get("corridor")):
        raise ValueError("every room except the corridor needs a door")
    for key in ("geo", "gps_ttl_s", "outside_margin_m", "max_accuracy_m"):
        if key not in venue:
            raise ValueError(f"the venue needs {key}")


class VenueService:
    def __init__(
        self,
        *,
        venue: dict[str, Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._venue = copy.deepcopy(venue) if venue is not None else load_venue()
        origin = _origin_from_env()
        if origin is not None:
            self._venue["geo"] = origin
        _check_venue(self._venue)
        self._public = PublicVenue.model_validate(geometry.public_venue(self._venue))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._persona_ids = frozenset(personas())
        self._lock = threading.Lock()
        self._sharing: dict[str, bool] = {}
        self._fixes: dict[str, _Fix] = {}
        self._tokens: dict[str, bytes] = {}  # persona_id -> SHA-256 of the sharing token its device holds
        self.reset()

    # ------------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        """Restore the seed: sharing flags from the venue file (missing = off) and no GPS fixes."""
        seeded = self._venue.get("sharing", {})
        with self._lock:
            self._sharing = {pid: seeded.get(pid) is True for pid in self._persona_ids}
            self._fixes = {}
            self._tokens = {}

    def now(self) -> datetime:
        return self._clock().astimezone(timezone.utc)

    # ------------------------------------------------------------------ endpoints
    def view(self, persona_id: str) -> VenueView:
        self._require(persona_id)
        with _span("venue.view", persona_id):
            with self._lock:
                self._prune()
                return VenueView(
                    persona_id=persona_id,
                    venue=self._public.model_copy(deep=True),
                    sharing=self._sharing[persona_id],
                    me=self._position(persona_id),
                )

    def set_sharing(self, body: SharingBody) -> SharingState:
        pid = body.persona_id
        self._require(pid)
        with _span("venue.sharing", pid):
            token: str | None = None
            with self._lock:
                if not body.enabled:
                    # Anyone may withdraw: it only reduces exposure. Forget the fix and the device at once.
                    self._sharing[pid] = False
                    self._fixes.pop(pid, None)
                    self._tokens.pop(pid, None)
                elif pid in self._tokens:
                    if not self._holds(pid, body.sharing_token):
                        raise VenueError(403, "shared_from_another_device")
                    self._sharing[pid] = True
                    token = body.sharing_token
                else:
                    token = secrets.token_urlsafe(32)
                    self._tokens[pid] = _digest(token)
                    self._sharing[pid] = True
            log.info("venue sharing set persona=%s enabled=%s", pid, body.enabled)
            return SharingState(persona_id=pid, enabled=body.enabled, sharing_token=token)

    def update_location(self, body: LocationUpdate) -> Position:
        """Place a GPS fix on the floor plan and keep only the placed point. The degrees are never kept or logged."""
        pid = body.persona_id
        self._require(pid)
        with _span("venue.location", pid):
            with self._lock:
                if not self._sharing[pid]:
                    raise VenueError(409, "sharing_off")
                if not self._holds(pid, body.sharing_token):
                    raise VenueError(403, "not_this_device")
                if body.accuracy_m is not None and body.accuracy_m > self._venue["max_accuracy_m"]:
                    raise VenueError(422, "too_inaccurate")
                placed = geometry.place_on_site(self._venue, *geometry.geo_to_venue(self._venue, body.lat, body.lng))
                if placed is None:
                    raise VenueError(422, "outside_venue")
                self._fixes[pid] = _Fix(x=placed[0], y=placed[1], accuracy_m=body.accuracy_m, at=self.now())
                return self._position(pid)

    def directions(self, persona_id: str, to: str) -> Directions:
        self._require(persona_id)
        self._require(to)
        if to == persona_id:
            raise VenueError(422, "same_person")
        with _span("venue.directions", persona_id) as span:
            with self._lock:
                self._prune()
                me = self._position(persona_id)
                if not self._sharing[to]:
                    span.set_attribute(ATTR_PEER_STATUS, "not_sharing")
                    # Nothing about the peer: no position, no route, no distance, no bearing.
                    return Directions(persona_id=persona_id, to_persona_id=to, peer_status="not_sharing", from_=me)
                peer = self._position(to)
            span.set_attribute(ATTR_PEER_STATUS, "sharing")
            found = geometry.directions(self._venue, (me.x, me.y), (peer.x, peer.y))
            return Directions(
                persona_id=persona_id,
                to_persona_id=to,
                peer_status="sharing",
                from_=me,
                to=peer,
                route=found["route"],
                distance_m=found["distance_m"],
                bearing_deg=found["bearing_deg"],
                compass=found["compass"],
                legs=[Leg.model_validate(leg) for leg in found["legs"]],
            )

    # ------------------------------------------------------------------ helpers (call with the lock held)
    def _holds(self, persona_id: str, token: str | None) -> bool:
        """Whether ``token`` is the one this persona's sharing device holds (constant-time compare)."""
        stored = self._tokens.get(persona_id)
        return stored is not None and token is not None and secrets.compare_digest(stored, _digest(token))

    def _require(self, persona_id: str) -> None:
        if persona_id not in self._persona_ids:
            raise VenueError(404, "unknown_persona")

    def _prune(self) -> None:
        """Forget fixes older than gps_ttl_s, so a stale position is never kept, let alone shown."""
        now = self.now()
        ttl = self._venue["gps_ttl_s"]
        for pid in [p for p, fix in self._fixes.items() if (now - fix.at).total_seconds() > ttl]:
            del self._fixes[pid]

    def _position(self, persona_id: str) -> Position:
        """My stored GPS fix when I share and it is at most gps_ttl_s old, else my check-in spot (the corridor's
        centre for someone without one)."""
        fix = self._fixes.get(persona_id)
        if (
            fix is not None
            and self._sharing[persona_id]
            and (self.now() - fix.at).total_seconds() <= self._venue["gps_ttl_s"]
        ):
            return self._placed(persona_id, fix.x, fix.y, "gps", fix.accuracy_m, fix.at)
        spot = self._venue.get("checkins", {}).get(persona_id)
        if spot is None:
            corridor = geometry.corridor_of(self._venue)
            spot = (corridor["x"] + corridor["w"] / 2, corridor["y"] + corridor["h"] / 2)
        return self._placed(persona_id, float(spot[0]), float(spot[1]), "checkin", None, None)

    def _placed(
        self,
        persona_id: str,
        x: float,
        y: float,
        source: str,
        accuracy_m: float | None,
        at: datetime | None,
    ) -> Position:
        room = geometry.room_at(self._venue, x, y)
        return Position(
            persona_id=persona_id,
            x=x,
            y=y,
            room_id=room["id"],
            source=source,
            accuracy_m=accuracy_m,
            updated_at=at,
        )
