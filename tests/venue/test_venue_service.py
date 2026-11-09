"""The venue rules: consent, freshness, placing GPS fixes, directions and what is never revealed."""

from __future__ import annotations

import dataclasses
import logging

import pytest
from fastapi import HTTPException
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from rapport_common.telemetry import ATTR_PERSONA
from rapport_venue import service as service_module
from rapport_venue.models import LocationUpdate, SharingBody
from rapport_venue.service import VenueService
from venue_support import NOW, geo_for

AVA, SAM, BO, MIA, LENA, RAJ, PRIYA = (
    "acme.ava", "acme.sam", "bluefin.bo", "kestrel.mia", "harborline.lena", "kestrel.raj", "lumenly.priya"
)


def fix(venue: dict, persona_id: str, x: float, y: float, accuracy_m: float | None = 8.0) -> LocationUpdate:
    lat, lng = geo_for(venue, x, y)
    return LocationUpdate(persona_id=persona_id, lat=lat, lng=lng, accuracy_m=accuracy_m)


def error_of(call) -> tuple[int, str]:
    with pytest.raises(HTTPException) as caught:
        call()
    return caught.value.status_code, caught.value.detail


# ----------------------------------------------------------------------------- consent
def test_sharing_comes_from_the_seed_and_defaults_to_off(service):
    assert service.view(AVA).sharing is True
    assert service.view(LENA).sharing is False  # "false" in the seed
    assert service.view(RAJ).sharing is False  # not in the seed at all


def test_sharing_toggles(service):
    assert service.set_sharing(SharingBody(persona_id=LENA, enabled=True)).enabled is True
    assert service.view(LENA).sharing is True
    assert service.set_sharing(SharingBody(persona_id=LENA, enabled=False)).model_dump() == {
        "persona_id": LENA,
        "enabled": False,
    }
    assert service.view(LENA).sharing is False


def test_turning_sharing_off_deletes_the_gps_fix_at_once(service, venue):
    assert service.update_location(fix(venue, AVA, 30, 55)).source == "gps"
    service.set_sharing(SharingBody(persona_id=AVA, enabled=False))
    assert AVA not in service._fixes
    assert service.view(AVA).me.source == "checkin"
    service.set_sharing(SharingBody(persona_id=AVA, enabled=True))
    me = service.view(AVA).me  # sharing again does not bring the old fix back
    assert (me.source, me.x, me.y) == ("checkin", 70, 18)


def test_location_needs_sharing(service, venue):
    assert error_of(lambda: service.update_location(fix(venue, LENA, 30, 55))) == (409, "sharing_off")
    assert LENA not in service._fixes


# ----------------------------------------------------------------------------- placing a fix
def test_update_location_places_the_fix(service, venue):
    lat, lng = geo_for(venue, 42.79, 22.26)
    pos = service.update_location(LocationUpdate(persona_id=AVA, lat=lat, lng=lng, accuracy_m=12.5))
    assert pos.model_dump() == {
        "persona_id": AVA,
        "x": 42.8,
        "y": 22.3,
        "room_id": "expo-hall",
        "source": "gps",
        "accuracy_m": 12.5,
        "updated_at": NOW,
    }
    assert service.view(AVA).me == pos


def test_only_the_placed_point_is_stored(service, venue):
    lat, lng = geo_for(venue, 42.79, 22.26)
    service.update_location(LocationUpdate(persona_id=AVA, lat=lat, lng=lng, accuracy_m=5))
    stored = dataclasses.asdict(service._fixes[AVA])
    assert stored == {"x": 42.8, "y": 22.3, "accuracy_m": 5, "at": NOW}
    assert lat not in stored.values() and lng not in stored.values()


def test_a_fix_just_outside_is_clamped_and_far_outside_is_rejected(service, venue):
    pos = service.update_location(fix(venue, AVA, -10, 80))
    assert (pos.x, pos.y, pos.room_id) == (0, 70, "main-hall")
    assert error_of(lambda: service.update_location(fix(venue, AVA, -16, 10))) == (422, "outside_venue")
    far = LocationUpdate(persona_id=AVA, lat=40.0, lng=-105.5)
    assert error_of(lambda: service.update_location(far)) == (422, "outside_venue")
    assert service.view(AVA).me.x == 0  # the rejected fixes left the last good one alone


def test_too_inaccurate(service, venue):
    assert error_of(lambda: service.update_location(fix(venue, AVA, 30, 55, accuracy_m=100.5))) == (
        422,
        "too_inaccurate",
    )
    assert service.update_location(fix(venue, AVA, 30, 55, accuracy_m=100)).source == "gps"  # the limit is inclusive
    assert service.update_location(fix(venue, AVA, 30, 55, accuracy_m=None)).accuracy_m is None


def test_unknown_persona(service, venue):
    nobody = "nobody.here"
    assert error_of(lambda: service.view(nobody)) == (404, "unknown_persona")
    assert error_of(lambda: service.set_sharing(SharingBody(persona_id=nobody, enabled=True))) == (
        404,
        "unknown_persona",
    )
    assert error_of(lambda: service.update_location(fix(venue, nobody, 30, 55))) == (404, "unknown_persona")
    assert error_of(lambda: service.directions(nobody, AVA)) == (404, "unknown_persona")
    assert error_of(lambda: service.directions(AVA, nobody)) == (404, "unknown_persona")


# ----------------------------------------------------------------------------- freshness
def test_gps_is_used_while_fresh_then_falls_back_to_the_check_in(service, venue, clock):
    service.update_location(fix(venue, AVA, 30, 55))
    clock.advance(600)  # gps_ttl_s: still fresh
    assert service.view(AVA).me.source == "gps"
    clock.advance(1)
    me = service.view(AVA).me
    assert (me.source, me.x, me.y, me.room_id, me.accuracy_m, me.updated_at) == (
        "checkin", 70, 18, "lobby-cafe", None, None
    )
    assert AVA not in service._fixes  # a stale fix is forgotten, not just hidden


def test_a_person_without_a_check_in_is_at_the_corridor_centre(service):
    me = service.view(RAJ).me
    assert (me.x, me.y, me.room_id, me.source) == (60, 35, "concourse", "checkin")


# ----------------------------------------------------------------------------- view
def test_view_shows_only_the_public_venue_and_my_own_position(service):
    view = service.view(AVA)
    dumped = view.model_dump()
    assert set(dumped) == {"persona_id", "venue", "sharing", "me"}
    assert set(dumped["venue"]) == {"id", "name", "width_m", "height_m", "corridor_y", "rooms"}
    assert dumped["me"]["persona_id"] == AVA
    text = view.model_dump_json()
    for other in (SAM, BO, MIA, LENA, PRIYA):
        assert other not in text
    assert "104.999" not in text and "39.742" not in text  # no GPS anchor


# ----------------------------------------------------------------------------- directions
def test_directions_between_check_ins_match_the_reference(service):
    found = service.directions(AVA, MIA)
    assert found.peer_status == "sharing" and found.from_.persona_id == AVA and found.to.persona_id == MIA
    assert found.route == [[70, 18], [75, 30], [75, 35], [86, 35], [86, 40], [88, 58]]
    assert (found.distance_m, found.bearing_deg, found.compass) == (52, 24, "north-east")
    assert [leg.kind for leg in found.legs] == ["leave", "walk", "enter", "arrive"]
    assert found.legs[1].meters == 11 and found.legs[1].direction == "east"

    same_room = service.directions(AVA, BO)
    assert (same_room.distance_m, same_room.bearing_deg, same_room.compass) == (11, 75, "east")
    far = service.directions(SAM, PRIYA)
    assert (far.distance_m, far.bearing_deg) == (130, 62)


def test_directions_use_fresh_gps_on_both_ends(service, venue, clock):
    service.update_location(fix(venue, AVA, 25, 55))  # main hall
    service.update_location(fix(venue, MIA, 62, 60))  # room A
    found = service.directions(AVA, MIA)
    assert (found.from_.source, found.to.source) == ("gps", "gps")
    assert found.route == [[25, 55], [25, 40], [25, 35], [62, 35], [62, 40], [62, 60]]
    assert found.distance_m == 82
    clock.advance(601)
    stale = service.directions(AVA, MIA)
    assert (stale.from_.source, stale.to.source) == ("checkin", "checkin")


def test_a_peer_who_is_not_sharing_reveals_nothing(service, venue):
    service.update_location(fix(venue, MIA, 62, 60))
    service.set_sharing(SharingBody(persona_id=MIA, enabled=False))
    for peer in (MIA, LENA, RAJ):
        found = service.directions(AVA, peer)
        assert found.model_dump(by_alias=True, exclude={"from_"}) == {
            "persona_id": AVA,
            "to_persona_id": peer,
            "peer_status": "not_sharing",
            "to": None,
            "route": [],
            "distance_m": None,
            "bearing_deg": None,
            "compass": None,
            "legs": [],
        }
        assert found.from_.persona_id == AVA


def test_i_can_find_a_sharing_peer_while_not_sharing_myself(service):
    found = service.directions(LENA, AVA)
    assert found.peer_status == "sharing" and found.from_.source == "checkin" and found.to.room_id == "lobby-cafe"


def test_same_person(service):
    assert error_of(lambda: service.directions(AVA, AVA)) == (422, "same_person")


# ----------------------------------------------------------------------------- configuration and reset
def test_origin_from_the_environment(monkeypatch, venue, clock):
    monkeypatch.setenv("RAPPORT_VENUE_ORIGIN", "40.0, -105.25")
    moved = VenueService(clock=clock)
    anchored = {**venue, "geo": {"lat": 40.0, "lng": -105.25}}
    pos = moved.update_location(fix(anchored, AVA, 30, 55))
    assert (pos.x, pos.y, pos.room_id) == (30, 55, "main-hall")
    assert error_of(lambda: moved.update_location(fix(venue, AVA, 30, 55))) == (422, "outside_venue")
    assert "geo" not in moved.view(AVA).model_dump()["venue"]  # the anchor is never public


@pytest.mark.parametrize("raw", ["40.0", "north,east", "40,-105,3", "91,-105", "40,-181", "nan,-105", "inf,0"])
def test_a_malformed_origin_is_ignored_with_a_warning(monkeypatch, caplog, venue, clock, raw):
    monkeypatch.setenv("RAPPORT_VENUE_ORIGIN", raw)
    with caplog.at_level(logging.WARNING, logger="rapport.venue"):
        svc = VenueService(clock=clock)
    assert svc.update_location(fix(venue, AVA, 30, 55)).x == 30  # still the file's anchor
    assert "RAPPORT_VENUE_ORIGIN" in caplog.text and raw not in caplog.text


def test_reset_restores_the_seed(service, venue):
    service.update_location(fix(venue, AVA, 30, 55))
    service.set_sharing(SharingBody(persona_id=LENA, enabled=True))
    service.set_sharing(SharingBody(persona_id=BO, enabled=False))
    service.reset()
    assert service._fixes == {}
    assert (service.view(AVA).me.source, service.view(LENA).sharing, service.view(BO).sharing) == (
        "checkin", False, True
    )


def test_the_seed_venue_is_not_mutated(venue, clock):
    VenueService(venue=venue, clock=clock).set_sharing(SharingBody(persona_id=AVA, enabled=False))
    assert venue["sharing"][AVA] is True


@pytest.mark.parametrize(
    "broken",
    [
        lambda v: v["rooms"].pop(),  # no corridor
        lambda v: v["rooms"][0].update(door=None),  # a room without a door
        lambda v: v.pop("gps_ttl_s"),
    ],
)
def test_a_venue_the_geometry_cannot_route_fails_at_start_up(venue, broken):
    broken(venue)
    with pytest.raises(ValueError):
        VenueService(venue=venue)


# ----------------------------------------------------------------------------- privacy of logs and spans
@pytest.fixture
def spans(monkeypatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(service_module, "tracer", lambda name="rapport": provider.get_tracer(name))
    return exporter


def test_spans_carry_ids_only(service, venue, spans):
    service.view(AVA)
    service.update_location(fix(venue, AVA, 30, 55))
    service.set_sharing(SharingBody(persona_id=MIA, enabled=False))
    service.directions(AVA, BO)
    service.directions(AVA, MIA)
    finished = spans.get_finished_spans()
    assert [s.name for s in finished] == [
        "venue.view", "venue.location", "venue.sharing", "venue.directions", "venue.directions"
    ]
    for span in finished:
        assert set(span.attributes) <= {ATTR_PERSONA, service_module.ATTR_PEER_STATUS}
        assert span.attributes[ATTR_PERSONA] == AVA or span.name == "venue.sharing"
    assert [s.attributes[service_module.ATTR_PEER_STATUS] for s in finished[-2:]] == ["sharing", "not_sharing"]


def test_gps_degrees_never_reach_logs_or_spans(service, venue, spans, caplog):
    update = fix(venue, AVA, 42.79, 22.26)
    with caplog.at_level(logging.DEBUG):
        service.update_location(update)
        service.directions(BO, AVA)
        error_of(lambda: service.update_location(LocationUpdate(persona_id=AVA, lat=40.0, lng=-105.5)))
    exported = " ".join(
        str(dict(s.attributes)) + str([dict(e.attributes) for e in s.events]) for s in spans.get_finished_spans()
    )
    for degrees in (update.lat, update.lng, 40.0, -105.5):
        for text in (str(degrees), f"{degrees:.4f}"):
            assert text not in caplog.text and text not in exported
