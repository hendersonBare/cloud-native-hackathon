"""Every HTTP route through the ASGI app, including the error codes, plus the app and gateway wiring."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from rapport_venue import api as api_module
from rapport_venue.api import get_service, router
from rapport_venue.app import create_app
from rapport_venue.service import VenueService
from venue_support import geo_for

VENUE = "/api/venue"
AVA, BO, MIA, LENA = "acme.ava", "bluefin.bo", "kestrel.mia", "harborline.lena"


def gps(venue: dict, persona_id: str, x: float, y: float, **extra) -> dict:
    lat, lng = geo_for(venue, x, y)
    return {"persona_id": persona_id, "lat": lat, "lng": lng, **extra}


# ----------------------------------------------------------------------------- GET /api/venue
async def test_get_venue(client):
    res = await client.get(VENUE, params={"persona_id": AVA})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"persona_id", "venue", "sharing", "me"} and body["sharing"] is True
    assert set(body["venue"]) == {"id", "name", "width_m", "height_m", "corridor_y", "rooms"}
    assert body["venue"]["id"] == "conference-level-1" and len(body["venue"]["rooms"]) == 8
    assert body["me"] == {
        "persona_id": AVA,
        "x": 70.0,
        "y": 18.0,
        "room_id": "lobby-cafe",
        "source": "checkin",
        "accuracy_m": None,
        "updated_at": None,
    }


async def test_get_venue_errors(client):
    unknown = await client.get(VENUE, params={"persona_id": "nobody.here"})
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "unknown_persona"})
    assert (await client.get(VENUE)).status_code == 422
    assert (await client.get(VENUE, params={"persona_id": "x" * 65})).status_code == 422


# ----------------------------------------------------------------------------- PUT /api/venue/location
async def test_put_location(client, venue):
    res = await client.put(f"{VENUE}/location", json=gps(venue, AVA, 42.79, 22.26, accuracy_m=9))
    assert res.status_code == 200
    assert res.json() == {
        "persona_id": AVA,
        "x": 42.8,
        "y": 22.3,
        "room_id": "expo-hall",
        "source": "gps",
        "accuracy_m": 9.0,
        "updated_at": "2026-11-09T17:00:00Z",
    }
    me = (await client.get(VENUE, params={"persona_id": AVA})).json()["me"]
    assert me["source"] == "gps" and "lat" not in me and "lng" not in me


async def test_put_location_rule_errors(client, venue):
    off = await client.put(f"{VENUE}/location", json=gps(venue, LENA, 30, 55))
    assert (off.status_code, off.json()) == (409, {"detail": "sharing_off"})
    blurry = await client.put(f"{VENUE}/location", json=gps(venue, AVA, 30, 55, accuracy_m=250))
    assert (blurry.status_code, blurry.json()) == (422, {"detail": "too_inaccurate"})
    away = await client.put(f"{VENUE}/location", json={"persona_id": AVA, "lat": 40.0, "lng": -105.5})
    assert (away.status_code, away.json()) == (422, {"detail": "outside_venue"})
    unknown = await client.put(f"{VENUE}/location", json=gps(venue, "nobody.here", 30, 55))
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "unknown_persona"})


async def test_put_location_validation(client, venue):
    good = gps(venue, AVA, 30, 55)
    cases = {
        "lat above 90": {**good, "lat": 91},
        "lat below -90": {**good, "lat": -90.5},
        "lng above 180": {**good, "lng": 180.5},
        "lat as text": {**good, "lat": "north"},
        "missing lng": {k: v for k, v in good.items() if k != "lng"},
        "negative accuracy": {**good, "accuracy_m": -1},
        "accuracy over 5000": {**good, "accuracy_m": 5001},
        "empty persona": {**good, "persona_id": ""},
        "unknown field": {**good, "altitude": 1600},
    }
    for name, body in cases.items():
        assert (await client.put(f"{VENUE}/location", json=body)).status_code == 422, name
    # json.loads accepts NaN and Infinity; they must be a clean 422, not a 500 from echoing them back.
    for field in (b"lat", b"lng", b"accuracy_m"):
        for raw in (b"NaN", b"Infinity", b"-Infinity"):
            body = b'{"persona_id": "acme.ava", "lat": 39.7421, "lng": -104.9989, "%s": %s}' % (field, raw)
            res = await client.put(f"{VENUE}/location", content=body, headers={"content-type": "application/json"})
            assert res.status_code == 422, (field, raw)
            assert res.json()["detail"][0]["loc"] == ["body", field.decode()]


# ----------------------------------------------------------------------------- PUT /api/venue/sharing
async def test_put_sharing(client, venue):
    await client.put(f"{VENUE}/location", json=gps(venue, AVA, 30, 55))
    res = await client.put(f"{VENUE}/sharing", json={"persona_id": AVA, "enabled": False})
    assert (res.status_code, res.json()) == (200, {"persona_id": AVA, "enabled": False})
    view = (await client.get(VENUE, params={"persona_id": AVA})).json()
    assert view["sharing"] is False and view["me"]["source"] == "checkin"
    blocked = await client.put(f"{VENUE}/location", json=gps(venue, AVA, 30, 55))
    assert (blocked.status_code, blocked.json()) == (409, {"detail": "sharing_off"})
    on = await client.put(f"{VENUE}/sharing", json={"persona_id": LENA, "enabled": True})
    assert on.json() == {"persona_id": LENA, "enabled": True}


async def test_put_sharing_needs_a_real_boolean(client):
    for enabled in ("yes", "true", 1, None):
        res = await client.put(f"{VENUE}/sharing", json={"persona_id": LENA, "enabled": enabled})
        assert res.status_code == 422, enabled
    assert (await client.put(f"{VENUE}/sharing", json={"persona_id": LENA})).status_code == 422
    unknown = await client.put(f"{VENUE}/sharing", json={"persona_id": "nobody.here", "enabled": True})
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "unknown_persona"})


# ----------------------------------------------------------------------------- GET /api/venue/directions
async def test_get_directions(client):
    res = await client.get(f"{VENUE}/directions", params={"persona_id": AVA, "to": MIA})
    assert res.status_code == 200
    body = res.json()
    assert "from" in body and "from_" not in body
    assert body["from"]["persona_id"] == AVA and body["to"]["persona_id"] == MIA
    assert body["peer_status"] == "sharing"
    assert body["route"] == [[70, 18], [75, 30], [75, 35], [86, 35], [86, 40], [88, 58]]
    assert (body["distance_m"], body["bearing_deg"], body["compass"]) == (52, 24, "north-east")
    assert body["legs"] == [  # only the fields that apply to each kind, like the JS model
        {"kind": "leave", "room_id": "lobby-cafe"},
        {"kind": "walk", "room_id": "concourse", "direction": "east", "meters": 11},
        {"kind": "enter", "room_id": "room-b"},
        {"kind": "arrive", "meters": 18, "compass": "north"},
    ]


async def test_get_directions_to_someone_not_sharing(client):
    res = await client.get(f"{VENUE}/directions", params={"persona_id": AVA, "to": LENA})
    assert res.status_code == 200
    body = res.json()
    assert body["peer_status"] == "not_sharing" and body["from"]["persona_id"] == AVA
    assert {k: body[k] for k in ("to", "route", "distance_m", "bearing_deg", "compass", "legs")} == {
        "to": None,
        "route": [],
        "distance_m": None,
        "bearing_deg": None,
        "compass": None,
        "legs": [],
    }
    assert "22.0" not in res.text and "58.0" not in res.text  # Lena's check-in spot (22, 58) is not in the answer


async def test_get_directions_errors(client):
    same = await client.get(f"{VENUE}/directions", params={"persona_id": AVA, "to": AVA})
    assert (same.status_code, same.json()) == (422, {"detail": "same_person"})
    for params in ({"persona_id": AVA, "to": "nobody.here"}, {"persona_id": "nobody.here", "to": AVA}):
        res = await client.get(f"{VENUE}/directions", params=params)
        assert (res.status_code, res.json()) == (404, {"detail": "unknown_persona"})
    assert (await client.get(f"{VENUE}/directions", params={"persona_id": AVA})).status_code == 422


async def test_openapi_documents_the_from_key(client):
    spec = (await client.get("/openapi.json")).json()
    assert "from" in spec["components"]["schemas"]["Directions"]["properties"]
    assert {f"{VENUE}", f"{VENUE}/location", f"{VENUE}/sharing", f"{VENUE}/directions"} <= set(spec["paths"])


# ----------------------------------------------------------------------------- app wiring
async def test_healthz(client, monkeypatch):
    assert (await client.get("/healthz")).json() == {"ok": True, "version": "dev"}
    monkeypatch.setenv("RAPPORT_VERSION", "1.2.3")
    assert (await client.get("/healthz")).json() == {"ok": True, "version": "1.2.3"}


async def test_static_files_are_mounted_only_when_web_dir_exists(service, tmp_path):
    (tmp_path / "index.html").write_text("<h1>Rapport</h1>", encoding="utf-8")

    async def fetch(app: FastAPI, path: str) -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            return await http.get(path)

    served = create_app(service, web_dir=tmp_path)
    assert (await fetch(served, "/")).text == "<h1>Rapport</h1>"
    assert (await fetch(served, f"{VENUE}?persona_id={AVA}")).headers["content-type"] == "application/json"
    for app in (create_app(service), create_app(service, web_dir=tmp_path / "missing")):
        assert (await fetch(app, "/")).status_code == 404
        assert (await fetch(app, "/healthz")).status_code == 200


async def test_router_can_be_mounted_by_another_app(service):
    host = FastAPI()
    host.include_router(router)
    host.dependency_overrides[get_service] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host), base_url="http://test") as http:
        assert (await http.get(VENUE, params={"persona_id": BO})).json()["me"]["room_id"] == "lobby-cafe"


def test_get_service_is_a_lazy_singleton(monkeypatch):
    monkeypatch.setattr(api_module, "_service", None)
    first = get_service()
    assert isinstance(first, VenueService) and get_service() is first


async def test_the_gateway_serves_the_venue_and_its_demo_reset_resets_it(monkeypatch, service, venue):
    from rapport_gateway.app import create_app as create_gateway
    from rapport_gateway.settings import Settings

    monkeypatch.setattr(api_module, "_service", service)  # the singleton both the route and the reset use
    gateway = create_gateway(Settings(mock=True, version="test", web_dir=None, mock_speed=1000.0))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://gw") as http:
            moved = await http.put(f"{VENUE}/location", json=gps(venue, AVA, 30, 55))
            assert moved.status_code == 200 and moved.json()["source"] == "gps"
            off = await http.put(f"{VENUE}/sharing", json={"persona_id": BO, "enabled": False})
            assert off.status_code == 200
            assert (await http.post("/api/demo/reset")).json() == {"ok": True}
            view = (await http.get(VENUE, params={"persona_id": AVA})).json()
            assert view["me"]["source"] == "checkin"
            assert (await http.get(VENUE, params={"persona_id": BO})).json()["sharing"] is True
    finally:
        await gateway.state.deps.stop()
