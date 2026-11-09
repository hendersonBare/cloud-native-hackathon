"""The geometry port pins the numbers of the JS reference (web/app/venue-model.js), including its half-up rounding."""

from __future__ import annotations

import math

import pytest
from rapport_venue import geometry as g


def spot(venue: dict, persona_id: str) -> list[float]:
    return venue["checkins"][persona_id]


# ----------------------------------------------------------------------------- reference numbers (from the JS)
def test_directions_lobby_to_room_b(venue):
    got = g.directions(venue, spot(venue, "acme.ava"), spot(venue, "kestrel.mia"))
    assert got == {
        "route": [[70, 18], [75, 30], [75, 35], [86, 35], [86, 40], [88, 58]],
        "distance_m": 52,
        "bearing_deg": 24,
        "compass": "north-east",
        "legs": [
            {"kind": "leave", "room_id": "lobby-cafe"},
            {"kind": "walk", "room_id": "concourse", "direction": "east", "meters": 11},
            {"kind": "enter", "room_id": "room-b"},
            {"kind": "arrive", "meters": 18, "compass": "north"},
        ],
    }


def test_directions_same_room(venue):
    got = g.directions(venue, spot(venue, "acme.ava"), spot(venue, "bluefin.bo"))
    assert got == {
        "route": [[70, 18], [81, 21]],
        "distance_m": 11,
        "bearing_deg": 75,
        "compass": "east",
        "legs": [{"kind": "same_room", "room_id": "lobby-cafe"}, {"kind": "arrive", "meters": 11, "compass": "east"}],
    }


def test_directions_expo_to_room_c(venue):
    got = g.directions(venue, spot(venue, "acme.sam"), spot(venue, "lumenly.priya"))
    assert (got["distance_m"], got["bearing_deg"], got["compass"]) == (130, 62, "north-east")
    assert got["route"] == [[20, 12], [30, 30], [30, 35], [109, 35], [109, 40], [110, 60]]
    assert got["legs"] == [
        {"kind": "leave", "room_id": "expo-hall"},
        {"kind": "walk", "room_id": "concourse", "direction": "east", "meters": 79},
        {"kind": "enter", "room_id": "room-c"},
        {"kind": "arrive", "meters": 20, "compass": "north"},
    ]


def test_geo_to_venue_and_place_on_site(venue):
    x, y = g.geo_to_venue(venue, 39.7422, -104.9985)
    assert x == pytest.approx(42.7987, abs=1e-4) and y == pytest.approx(22.264, abs=1e-6)
    assert g.place_on_site(venue, x, y) == (42.8, 22.3)


def test_room_at(venue):
    assert g.room_at(venue, 50, 40)["id"] == "main-hall"  # shared corner: first room in file order
    assert g.room_at(venue, 60, 35)["id"] == "concourse"
    assert g.room_at(venue, 60, 15)["id"] == "expo-hall"  # shared wall with the café: file order wins
    assert g.room_at(venue, 75, 30)["id"] == "lobby-cafe"  # a door on the edge belongs to the room
    assert g.room_at(venue, 120, 70)["id"] == "room-c"
    assert g.corridor_of(venue)["id"] == "concourse"


# ----------------------------------------------------------------------------- rounding is JS Math.round
def test_round_is_half_up_like_math_round():
    assert [g._round(n) for n in (0.5, 1.5, 2.5, -2.5, -0.5)] == [1, 2, 3, -2, 0]
    assert g._round(0.49999999999999994) == 0  # floor(n + 0.5) would say 1; Math.round says 0
    assert g.round1(0.25) == 0.3 and g.round1(2.45) == 2.5  # Python's round() would give 0.2
    assert g.round1(42.798705) == 42.8


def test_compass_ties_round_up():
    assert [g.compass(d) for d in (0, 22.4, 22.5, 67.5, 180, 337.4, 337.5, 359)] == [
        "north", "north", "north-east", "east", "south", "north-west", "north", "north"
    ]


def test_walk_meters_round_half_up(venue):
    # From the corridor at x = 21.5 to Room A's door at x = 62: 40.5 m, which Math.round makes 41 (round() says 40).
    walk = next(leg for leg in g.legs(venue, (21.5, 35), (62, 55)) if leg["kind"] == "walk")
    assert walk == {"kind": "walk", "room_id": "concourse", "direction": "east", "meters": 41}


def test_bearing():
    assert g.bearing((0, 0), (0, 10)) == 0
    assert g.bearing((0, 0), (10, 0)) == 90
    assert g.bearing((0, 0), (0, -10)) == 180
    assert g.bearing((0, 0), (-10, 0)) == 270
    assert g.bearing((0, 0), (-1, 1000)) == 0  # 359.94 rounds to 360, which wraps to 0
    assert g.bearing((5, 5), (5, 5)) == 0


# ----------------------------------------------------------------------------- routes
def test_route_drops_repeated_points(venue):
    # Starting on the café's door: the door waypoint is the start point and is dropped.
    assert g.route(venue, (75, 30), (86, 58)) == [[75, 30], [75, 35], [86, 35], [86, 40], [86, 58]]
    # Starting on the corridor's centre line: the "step onto the corridor" point is the start point.
    assert g.route(venue, (10, 35), (88, 58)) == [[10, 35], [86, 35], [86, 40], [88, 58]]
    assert g.route(venue, (10, 35), (10.005, 35)) == [[10, 35]]  # closer than 0.01 m


def test_corridor_to_room_and_room_to_corridor(venue):
    into = g.directions(venue, (10, 32), (88, 58))
    assert into["route"] == [[10, 32], [10, 35], [86, 35], [86, 40], [88, 58]]
    assert [leg["kind"] for leg in into["legs"]] == ["walk", "enter", "arrive"]
    out = g.directions(venue, (88, 58), (100, 36))
    assert out["route"] == [[88, 58], [86, 40], [86, 35], [100, 35], [100, 36]]
    assert out["legs"][:2] == [
        {"kind": "leave", "room_id": "room-b"},
        {"kind": "walk", "room_id": "concourse", "direction": "east", "meters": 14},
    ]
    assert out["legs"][-1]["kind"] == "arrive" and len(out["legs"]) == 3  # no "enter" for the corridor


def test_short_walk_is_skipped(venue):
    # Room A's door (x 62) and a corridor point at x 62.4: under a metre, so no walk leg.
    assert [leg["kind"] for leg in g.legs(venue, (62, 55), (62.4, 37))] == ["leave", "arrive"]


def test_same_point(venue):
    got = g.directions(venue, (70, 18), (70, 18))
    assert got["route"] == [[70, 18]] and got["distance_m"] == 0 and got["bearing_deg"] == 0
    assert got["legs"] == [{"kind": "same_room", "room_id": "lobby-cafe"}, {"kind": "arrive", "meters": 0,
                                                                            "compass": "north"}]


def test_distance_is_the_route_length(venue):
    got = g.directions(venue, spot(venue, "acme.ava"), spot(venue, "kestrel.mia"))
    pts = got["route"]
    total = sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))
    assert abs(got["distance_m"] - total) <= 0.5


# ----------------------------------------------------------------------------- placing and the public venue
def test_place_on_site_clamps_within_the_margin_and_rejects_beyond_it(venue):
    assert g.place_on_site(venue, -15, -15) == (0, 0)
    assert g.place_on_site(venue, 135, 85) == (120, 70)
    assert g.place_on_site(venue, 60.04, 10.06) == (60.0, 10.1)
    for x, y in ((-15.1, 10), (10, -15.1), (135.1, 10), (10, 85.1)):
        assert g.place_on_site(venue, x, y) is None
    for x, y in ((math.nan, 10), (10, math.inf), (-math.inf, 0)):
        assert g.place_on_site(venue, x, y) is None


def test_public_venue_leaves_out_private_fields(venue):
    public = g.public_venue(venue)
    assert set(public) == {"id", "name", "width_m", "height_m", "corridor_y", "rooms"}
    assert len(public["rooms"]) == 8
    concourse = next(r for r in public["rooms"] if r["id"] == "concourse")
    assert concourse["corridor"] is True and concourse["door"] is None
    assert all(r["corridor"] is False for r in public["rooms"] if r["id"] != "concourse")
    assert "checkins" not in str(public) and "sharing" not in str(public) and "geo" not in public
