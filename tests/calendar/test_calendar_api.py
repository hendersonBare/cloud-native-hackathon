"""Every HTTP route through the ASGI app, including the error codes, plus the app wiring."""

from __future__ import annotations

import httpx
from calendar_support import NOW, iso, local
from fastapi import FastAPI
from rapport_calendar import api as api_module
from rapport_calendar.api import get_service, router
from rapport_calendar.app import create_app
from rapport_calendar.service import CalendarService

CAL = "/api/calendar"


def new_event(**over) -> dict:
    body = {"persona_id": "acme.sam", "title": "Focus", "starts_at": iso(local(0, 11)), "ends_at": iso(local(0, 12))}
    return {**body, **over}


# ----------------------------------------------------------------------------- GET /api/calendar
async def test_get_calendar(client):
    res = await client.get(CAL, params={"persona_id": "acme.ava"})
    assert res.status_code == 200
    body = res.json()
    assert body["timezone"] == "America/Denver" and body["week_start"] == "2026-11-09" and body["days"] == 7
    assert body["now"] == iso(NOW) and body["conference_mode"] is True
    ebpf = next(e for e in body["events"] if e["event_id"] == "evt-ava-ebpf")
    assert ebpf["starts_at"] == "2026-11-09T22:30:00Z"
    starts = [e["starts_at"] for e in body["events"]]
    assert starts == sorted(starts)


async def test_get_calendar_window_and_validation(client):
    one_day = await client.get(CAL, params={"persona_id": "acme.ava", "start": "2026-11-10", "days": 1})
    assert [e["event_id"] for e in one_day.json()["events"]] == ["evt-ava-priya"]
    for params in ({"persona_id": "acme.ava", "days": 0}, {"persona_id": "acme.ava", "days": 15},
                   {"persona_id": "acme.ava", "start": "tomorrow"}, {}):
        assert (await client.get(CAL, params=params)).status_code == 422
    unknown = await client.get(CAL, params={"persona_id": "nobody.here"})
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "unknown_persona"})


# ----------------------------------------------------------------------------- events
async def test_create_update_delete_roundtrip(client):
    created = await client.post(f"{CAL}/events", json=new_event(location="Desk"))
    assert created.status_code == 201
    event = created.json()["event"]
    assert created.json()["conflicts"] == [] and event["source"] == "user" and event["kind"] == "personal"
    assert created.json()["timezone"] == "America/Denver"

    edit = {"persona_id": "acme.sam", "title": "Deep work"}
    patched = await client.patch(f"{CAL}/events/{event['event_id']}", json=edit)
    assert patched.status_code == 200 and patched.json()["title"] == "Deep work"

    deleted = await client.delete(f"{CAL}/events/{event['event_id']}", params={"persona_id": "acme.sam"})
    assert deleted.status_code == 204 and deleted.content == b""
    gone = await client.delete(f"{CAL}/events/{event['event_id']}", params={"persona_id": "acme.sam"})
    assert (gone.status_code, gone.json()) == (404, {"detail": "event_not_found"})


async def test_create_validation_errors_are_422(client):
    cases = {
        "naive start": new_event(starts_at="2026-11-09T11:00:00"),
        "blank title": new_event(title="   "),
        "missing title": {k: v for k, v in new_event().items() if k != "title"},
        "ends before starts": new_event(ends_at=iso(local(0, 10))),
        "over 12 hours": new_event(starts_at=iso(local(0, 7)), ends_at=iso(local(0, 20))),
        "outside the week": new_event(starts_at=iso(local(8, 9)), ends_at=iso(local(8, 10))),
        "unknown field": new_event(color="red"),
        "title too long": new_event(title="x" * 121),
    }
    for name, body in cases.items():
        assert (await client.post(f"{CAL}/events", json=body)).status_code == 422, name
    assert (await client.post(f"{CAL}/events", json=new_event(persona_id="nobody.here"))).status_code == 404


async def test_create_reports_conflicts(client):
    overlapping = new_event(persona_id="acme.ava", starts_at=iso(local(0, 9, 30)), ends_at=iso(local(0, 10, 30)))
    res = await client.post(f"{CAL}/events", json=overlapping)
    assert res.status_code == 201 and res.json()["conflicts"] == ["evt-ava-keynote"]


async def test_update_and_delete_rules(client):
    ava = {"persona_id": "acme.ava"}
    capture = await client.patch(f"{CAL}/events/evt-ava-dinner", json={**ava, "capture": True})
    assert capture.status_code == 200 and capture.json()["capture"] is True
    locked = await client.patch(f"{CAL}/events/evt-ava-keynote", json={**ava, "title": "Hacked"})
    assert (locked.status_code, locked.json()) == (409, {"detail": "not_editable"})
    assert (await client.patch(f"{CAL}/events/evt-ava-keynote", json=ava)).status_code == 422  # empty update
    foreign = await client.patch(f"{CAL}/events/evt-ava-keynote", json={"persona_id": "acme.sam", "capture": True})
    assert (foreign.status_code, foreign.json()) == (404, {"detail": "event_not_found"})

    protected = await client.delete(f"{CAL}/events/evt-ava-keynote", params=ava)
    assert (protected.status_code, protected.json()) == (409, {"detail": "not_deletable"})
    assert (await client.delete(f"{CAL}/events/evt-ava-otel", params=ava)).status_code == 204
    assert (await client.delete(f"{CAL}/events/evt-ava-otel")).status_code == 422  # persona_id is required


async def test_calendar_full_is_409(client, service):
    for _ in range(200 - 7):
        await client.post(f"{CAL}/events", json=new_event(persona_id="acme.ava"))
    res = await client.post(f"{CAL}/events", json=new_event(persona_id="acme.ava"))
    assert (res.status_code, res.json()) == (409, {"detail": "calendar_full"})


# ----------------------------------------------------------------------------- respond
async def test_respond_flow(client):
    first = await client.post(f"{CAL}/events/evt-ava-bo/respond", json={"persona_id": "acme.ava", "response": "accept"})
    assert first.status_code == 200 and first.json()["status"] == "proposed"
    bo_accepts = {"persona_id": "bluefin.bo", "response": "accept"}
    second = await client.post(f"{CAL}/events/evt-bo-ava/respond", json=bo_accepts)
    assert second.json()["status"] == "confirmed"
    ava = (await client.get(CAL, params={"persona_id": "acme.ava"})).json()["events"]
    assert next(e for e in ava if e["event_id"] == "evt-ava-bo")["status"] == "confirmed"

    ava_declines = {"persona_id": "acme.ava", "response": "decline"}
    declined = await client.post(f"{CAL}/events/evt-ava-bo/respond", json=ava_declines)
    assert declined.json()["status"] == "declined"
    closed = await client.post(f"{CAL}/events/evt-ava-bo/respond", json={**ava_declines, "response": "accept"})
    assert (closed.status_code, closed.json()) == (409, {"detail": "meeting_closed"})


async def test_respond_errors(client):
    ok = {"persona_id": "acme.ava", "response": "accept"}
    assert (await client.post(f"{CAL}/events/evt-ava-keynote/respond", json=ok)).json() == {"detail": "not_a_meeting"}
    assert (await client.post(f"{CAL}/events/evt-nope/respond", json=ok)).status_code == 404
    assert (await client.post(f"{CAL}/events/evt-ava-bo/respond", json={**ok, "response": "maybe"})).status_code == 422


# ----------------------------------------------------------------------------- conference mode, agenda, talks
async def test_conference_mode_and_talks(client):
    mode = await client.put(f"{CAL}/conference-mode", json={"persona_id": "acme.sam", "enabled": True})
    assert (mode.status_code, mode.json()) == (200, {"persona_id": "acme.sam", "enabled": True})
    assert (await client.get(CAL, params={"persona_id": "acme.sam"})).json()["conference_mode"] is True
    added = await client.post(f"{CAL}/talks", json={"persona_id": "acme.sam", "talk_id": "talk-hipaa-k8s"})
    assert added.status_code == 201 and added.json()["event"]["capture"] is True
    assert added.json()["timezone"] == "America/Denver"
    dup = await client.post(f"{CAL}/talks", json={"persona_id": "acme.sam", "talk_id": "talk-hipaa-k8s"})
    assert (dup.status_code, dup.json()) == (409, {"detail": "already_added"})
    nope = await client.post(f"{CAL}/talks", json={"persona_id": "acme.sam", "talk_id": "talk-nope"})
    assert (nope.status_code, nope.json()) == (404, {"detail": "unknown_talk"})


async def test_agenda(client):
    res = await client.get(f"{CAL}/agenda", params={"persona_id": "acme.ava", "q": "ebpf"})
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "seed" and body["query"] == "ebpf"
    assert [i["talk"]["talk_id"] for i in body["items"]] == ["talk-ebpf-cost", "talk-ebpf-zero-code", "talk-ebpf-edge"]
    assert {i["talk"]["talk_id"]: i["in_calendar"] for i in body["items"]}["talk-ebpf-edge"] is True
    assert body["items"][0]["ends_at"] == "2026-11-09T22:00:00Z"  # 14:30 MST + 30 minutes
    assert (await client.get(f"{CAL}/agenda", params={"persona_id": "acme.ava", "q": "x" * 101})).status_code == 422
    assert (await client.get(f"{CAL}/agenda", params={"persona_id": "nobody.here"})).status_code == 404


# ----------------------------------------------------------------------------- propose, free/busy, ics
async def test_propose_returns_201_then_200(client):
    body = {"persona_id": "acme.sam", "with_persona_id": "kestrel.raj"}
    first = await client.post(f"{CAL}/propose", json=body)
    assert first.status_code == 201
    assert first.json()["created"] is True and first.json()["starts_at"] == iso(local(0, 9))
    assert first.json()["timezone"] == "America/Denver"
    again = await client.post(f"{CAL}/propose", json=body)
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["meeting_id"] == first.json()["meeting_id"]


async def test_propose_errors(client):
    self_meeting = await client.post(f"{CAL}/propose", json={"persona_id": "acme.sam", "with_persona_id": "acme.sam"})
    assert (self_meeting.status_code, self_meeting.json()) == (422, {"detail": "same_person"})
    bad = {"persona_id": "acme.sam", "with_persona_id": "kestrel.raj"}
    odd = await client.post(f"{CAL}/propose", json={**bad, "duration_minutes": 20})
    assert (odd.status_code, odd.json()) == (422, {"detail": "invalid_duration"})
    assert (await client.post(f"{CAL}/propose", json={**bad, "duration_minutes": 5})).status_code == 422
    assert (await client.post(f"{CAL}/propose", json={**bad, "not_before": "2026-11-09T10:00:00"})).status_code == 422
    assert (await client.post(f"{CAL}/propose", json={**bad, "purpose": "gossip"})).status_code == 422
    assert (await client.post(f"{CAL}/propose", json={**bad, "with_persona_id": "nobody.here"})).status_code == 404
    for day in range(5):
        await client.post(f"{CAL}/events", json=new_event(
            persona_id="kestrel.raj", starts_at=iso(local(day, 9)), ends_at=iso(local(day, 18))))
    full = await client.post(f"{CAL}/propose", json=bad)
    assert (full.status_code, full.json()) == (409, {"detail": "no_mutual_slot"})


async def test_freebusy(client):
    res = await client.get(
        f"{CAL}/freebusy",
        params={"persona_id": "acme.ava", "start": iso(local(0, 0)), "end": iso(local(1, 0))},
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"persona_id", "timezone", "start", "end", "busy"} and body["timezone"] == "America/Denver"
    assert body["busy"][0] == {"starts_at": iso(local(0, 9)), "ends_at": iso(local(0, 10))}
    assert all(set(b) == {"starts_at", "ends_at"} for b in body["busy"])
    offset_form = await client.get(
        f"{CAL}/freebusy",
        params={"persona_id": "acme.ava", "start": "2026-11-09T00:00:00-07:00", "end": "2026-11-10T00:00:00-07:00"},
    )
    assert offset_form.json() == body
    for params in (
        {"persona_id": "acme.ava", "start": "2026-11-09T00:00:00", "end": "2026-11-10T00:00:00"},  # naive
        {"persona_id": "acme.ava", "start": iso(local(1, 0)), "end": iso(local(0, 0))},
        {"persona_id": "acme.ava", "start": iso(local(0, 0)), "end": iso(local(15, 0))},
        {"persona_id": "acme.ava"},
    ):
        assert (await client.get(f"{CAL}/freebusy", params=params)).status_code == 422


async def test_export_ics(client):
    res = await client.get(f"{CAL}/export.ics", params={"persona_id": "acme.ava"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/calendar; charset=utf-8"
    assert res.headers["content-disposition"] == 'attachment; filename="rapport-acme.ava.ics"'
    text = res.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == 7 and "STATUS:TENTATIVE" in text  # the proposed Bo coffee
    assert "UID:evt-ava-ebpf@rapport.dev" in text and "DTSTART:20261109T223000Z" in text
    assert "DTSTAMP:20261109T150000Z" in text
    await client.post(f"{CAL}/events/evt-ava-bo/respond", json={"persona_id": "acme.ava", "response": "decline"})
    after = await client.get(f"{CAL}/export.ics", params={"persona_id": "acme.ava"})
    assert after.text.count("BEGIN:VEVENT") == 6 and "evt-ava-bo@" not in after.text
    assert (await client.get(f"{CAL}/export.ics", params={"persona_id": "nobody.here"})).status_code == 404
    assert (await client.get(f"{CAL}/export.ics")).status_code == 422


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
    assert (await fetch(served, f"{CAL}?persona_id=acme.ava")).headers["content-type"] == "application/json"  # API wins
    assert (await fetch(served, "/healthz")).json()["ok"] is True
    for app in (create_app(service), create_app(service, web_dir=tmp_path / "missing")):
        assert (await fetch(app, "/")).status_code == 404
        assert (await fetch(app, "/healthz")).status_code == 200


async def test_router_can_be_mounted_by_the_gateway(service):
    gateway = FastAPI()
    gateway.include_router(router)
    gateway.dependency_overrides[get_service] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://test") as http:
        assert (await http.get(CAL, params={"persona_id": "acme.sam"})).json()["events"] == []


def test_get_service_is_a_lazy_singleton(monkeypatch):
    monkeypatch.setattr(api_module, "_service", None)
    first = get_service()
    assert isinstance(first, CalendarService) and get_service() is first
