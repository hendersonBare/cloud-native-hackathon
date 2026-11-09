"""Helpers shared by the venue tests (a plain module, imported by name like the other test folders' helpers)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from rapport_venue.geometry import M_PER_DEG

NOW = datetime(2026, 11, 9, 17, 0, tzinfo=timezone.utc)


class FakeClock:
    """A settable clock for the service's ``clock`` argument."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def geo_for(venue: dict, x: float, y: float) -> tuple[float, float]:
    """The (lat, lng) that ``geo_to_venue`` maps to venue metres (x, y): its inverse, for building GPS fixes."""
    lat0, lng0 = venue["geo"]["lat"], venue["geo"]["lng"]
    return lat0 + y / M_PER_DEG, lng0 + x / (M_PER_DEG * math.cos(lat0 * math.pi / 180))
