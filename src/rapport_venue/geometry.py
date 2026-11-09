"""Venue geometry: GPS to floor-plan metres, which room a point is in, and the walking route between two people.

An exact port of ``web/app/venue-model.js`` (the find screen and the JS mock use that file); the tests pin the same
numbers. Pure functions over the venue dict loaded from ``data/venue.json``.

Coordinates are metres on the floor plan: origin at the south-west corner, x east, y north. Points are ``[x, y]``
(any two-item sequence on input, lists on output). Routes leave a room by its door, walk along the corridor's centre
line and enter the other room by its door.

Rounding matches JavaScript's ``Math.round`` (ties go up, towards +infinity), not Python's ``round()`` (ties go to
even). Sums are plain left-to-right loops, because ``sum()`` of floats is compensated since Python 3.12 and would not
give the same last bits as the JS loop.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

M_PER_DEG = 111320
COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")

Venue = dict[str, Any]
Room = dict[str, Any]
Point = Sequence[float]


def _round(n: float) -> int:
    """JavaScript ``Math.round``: the nearest integer, ties towards +infinity.

    ``floor(n)`` plus one when the fractional part is at least a half. Unlike ``floor(n + 0.5)`` this never rounds
    0.49999999999999994 up (the addition would round to 1.0), so it agrees with ``Math.round`` for every double."""
    whole = math.floor(n)
    return whole + 1 if n - whole >= 0.5 else whole


def round1(n: float) -> float:
    """``Math.round(n * 10) / 10``: one decimal, ties up."""
    return _round(n * 10) / 10


def _clamp(n: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, n))


def _dist(p: Point, q: Point) -> float:
    return math.hypot(q[0] - p[0], q[1] - p[1])


def geo_to_venue(venue: Venue, lat: float, lng: float) -> tuple[float, float]:
    """GPS degrees to floor-plan metres (equirectangular; fine across a building). Not clamped or rounded."""
    lat0 = venue["geo"]["lat"]
    lng0 = venue["geo"]["lng"]
    return (lng - lng0) * M_PER_DEG * math.cos((lat0 * math.pi) / 180), (lat - lat0) * M_PER_DEG


def place_on_site(venue: Venue, x: float, y: float) -> tuple[float, float] | None:
    """Clamp a point into the venue (rounded to 0.1 m), or None when it is more than outside_margin_m outside it."""
    m = venue["outside_margin_m"]
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    if x < -m or y < -m or x > venue["width_m"] + m or y > venue["height_m"] + m:
        return None
    return round1(_clamp(x, 0, venue["width_m"])), round1(_clamp(y, 0, venue["height_m"]))


def corridor_of(venue: Venue) -> Room | None:
    """The first room flagged ``corridor``."""
    return next((r for r in venue["rooms"] if r.get("corridor")), None)


def room_at(venue: Venue, x: float, y: float) -> Room | None:
    """The room a point is in: the first non-corridor room (file order) containing it, edges included; else the
    corridor. Rooms win over the corridor on a shared edge."""

    def inside(r: Room) -> bool:
        return r["x"] <= x <= r["x"] + r["w"] and r["y"] <= y <= r["y"] + r["h"]

    return next((r for r in venue["rooms"] if not r.get("corridor") and inside(r)), None) or corridor_of(venue)


def bearing(p: Point, q: Point) -> int:
    """Degrees clockwise from north, 0..359."""
    deg = (math.atan2(q[0] - p[0], q[1] - p[1]) * 180) / math.pi
    return _round((deg + 360) % 360) % 360


def compass(deg: float) -> str:
    return COMPASS[_round(deg / 45) % 8]


def route(venue: Venue, a: Point, b: Point) -> list[list[float]]:
    """Waypoints ``[x, y]`` from a to b. A point within 0.01 m of the one before it (in the unfiltered list, as in
    the JS) is dropped."""
    ra = room_at(venue, a[0], a[1])
    rb = room_at(venue, b[0], b[1])
    pts: list[list[float]] = [[a[0], a[1]]]
    if ra["id"] != rb["id"]:
        cy = venue["corridor_y"]
        if ra.get("corridor"):
            pts.append([a[0], cy])
        else:
            pts.append([ra["door"][0], ra["door"][1]])
            pts.append([ra["door"][0], cy])
        if rb.get("corridor"):
            pts.append([b[0], cy])
        else:
            pts.append([rb["door"][0], cy])
            pts.append([rb["door"][0], rb["door"][1]])
    pts.append([b[0], b[1]])
    return [[p[0], p[1]] for i, p in enumerate(pts) if i == 0 or _dist(pts[i - 1], p) > 0.01]


def legs(venue: Venue, a: Point, b: Point, pts: list[list[float]] | None = None) -> list[dict[str, Any]]:
    """Turn-by-turn legs as data (the screen words them): ``same_room`` | ``leave`` -> ``walk`` (east/west, metres)
    -> ``enter``, then ``arrive`` (metres and compass for the last stretch)."""
    if pts is None:
        pts = route(venue, a, b)
    ra = room_at(venue, a[0], a[1])
    rb = room_at(venue, b[0], b[1])
    out: list[dict[str, Any]] = []
    if ra["id"] == rb["id"]:
        out.append({"kind": "same_room", "room_id": ra["id"]})
    else:
        if not ra.get("corridor"):
            out.append({"kind": "leave", "room_id": ra["id"]})
        start_x = a[0] if ra.get("corridor") else ra["door"][0]
        end_x = b[0] if rb.get("corridor") else rb["door"][0]
        dx = end_x - start_x
        if abs(dx) >= 1:
            out.append(
                {
                    "kind": "walk",
                    "room_id": corridor_of(venue)["id"],
                    "direction": "east" if dx > 0 else "west",
                    "meters": _round(abs(dx)),
                }
            )
        if not rb.get("corridor"):
            out.append({"kind": "enter", "room_id": rb["id"]})
    last = pts[-2] if len(pts) > 1 else pts[0]
    end = pts[-1]
    out.append({"kind": "arrive", "meters": _round(_dist(last, end)), "compass": compass(bearing(last, end))})
    return out


def directions(venue: Venue, a: Point, b: Point) -> dict[str, Any]:
    """Everything the map needs between two placed points: route, distance_m, bearing_deg, compass and legs."""
    pts = route(venue, a, b)
    length = 0.0
    for i in range(1, len(pts)):  # a plain loop, like the JS (sum() is compensated since Python 3.12)
        length += _dist(pts[i - 1], pts[i])
    deg = bearing(a, b)
    return {
        "route": pts,
        "distance_m": _round(length),
        "bearing_deg": deg,
        "compass": compass(deg),
        "legs": legs(venue, a, b, pts),
    }


def public_venue(venue: Venue) -> dict[str, Any]:
    """The venue fields a client may see: no check-in spots, no sharing flags, no GPS anchor."""
    return {
        "id": venue["id"],
        "name": venue["name"],
        "width_m": venue["width_m"],
        "height_m": venue["height_m"],
        "corridor_y": venue["corridor_y"],
        "rooms": [
            {
                "id": r["id"],
                "name": r["name"],
                "x": r["x"],
                "y": r["y"],
                "w": r["w"],
                "h": r["h"],
                "door": r.get("door"),
                "corridor": bool(r.get("corridor")),
            }
            for r in venue["rooms"]
        ],
    }
