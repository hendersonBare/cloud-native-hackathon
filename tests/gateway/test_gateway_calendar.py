"""The calendar API (src/rapport_calendar) mounted in the gateway: routes, reset, isolation, the shared_brief hook."""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx
import pytest
import respx
from gateway_support import (
    ACME_BRIEFER,
    AVA,
    BLUEFIN_BRIEFER,
    BO,
    collect,
    delegate_event,
    eventually,
    make_stack,
    private_brief,
    shared_brief,
    types,
)

from rapport_common.models import TalkHit
from rapport_gateway.logfilters import PathOnlyAccessLog, QueryFreeHttpxLog, install_log_filters

EDGE_TALK = "talk-ebpf-edge"  # on the seed agenda, Monday 4:00 PM MST; Bo's seed calendar does not have it


def _suggested(talk_id: str, title: str = "Anything the delegate wrote") -> TalkHit:
    return TalkHit(
        talk_id=talk_id, title=title, starts_at=datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc), room="?", track="?"
    )


@pytest.fixture
async def mock_stack():
    s = await make_stack(mock=True)
    yield s
    await s.close()


# ----------------------------------------------------------------------------- routes through the gateway app
async def test_calendar_routes_are_served_by_the_gateway(mock_stack):
    r = await mock_stack.client.get("/api/calendar", params={"persona_id": AVA})
    assert r.status_code == 200
    view = r.json()
    assert view["timezone"] == "America/Denver"
    assert "evt-ava-ebpf" in {e["event_id"] for e in view["events"]}
    assert (await mock_stack.client.get("/api/calendar", params={"persona_id": "nobody.x"})).status_code == 404


async def test_mock_mode_agenda_comes_from_the_seed_without_calling_a_briefer(mock_stack):
    with respx.mock(assert_all_called=False) as router:
        briefer = router.get(f"{ACME_BRIEFER}/v1/talks")
        r = await mock_stack.client.get("/api/calendar/agenda", params={"persona_id": AVA, "q": "ebpf"})
    assert r.status_code == 200
    assert r.json()["source"] == "seed" and r.json()["items"]
    assert not briefer.called


async def test_patch_put_and_delete_reach_the_calendar(mock_stack):
    c = mock_stack.client
    patched = await c.patch("/api/calendar/events/evt-ava-ebpf", json={"persona_id": AVA, "capture": False})
    assert patched.status_code == 200 and patched.json()["capture"] is False
    mode = await c.put("/api/calendar/conference-mode", json={"persona_id": AVA, "enabled": False})
    assert mode.status_code == 200 and mode.json() == {"persona_id": AVA, "enabled": False}
    assert (await c.delete("/api/calendar/events/evt-ava-edge", params={"persona_id": AVA})).status_code == 204


async def test_demo_reset_restores_the_seeded_calendar(mock_stack):
    c = mock_stack.client
    created = await c.post(
        "/api/calendar/events",
        json={
            "persona_id": AVA,
            "title": "Synthetic event",
            "starts_at": "2026-11-12T17:00:00Z",
            "ends_at": "2026-11-12T17:30:00Z",
        },
    )
    assert created.status_code == 201
    event_id = created.json()["event"]["event_id"]
    assert (await c.post("/api/demo/reset")).status_code == 200
    view = (await c.get("/api/calendar", params={"persona_id": AVA})).json()
    assert event_id not in {e["event_id"] for e in view["events"]}
    assert "evt-ava-ebpf" in {e["event_id"] for e in view["events"]}


async def test_each_gateway_app_has_its_own_calendar():
    a, b = await make_stack(mock=True), await make_stack(mock=True)
    try:
        assert a.deps.calendar is not b.deps.calendar
        await a.client.patch("/api/calendar/events/evt-ava-ebpf", json={"persona_id": AVA, "capture": False})
        b_view = (await b.client.get("/api/calendar", params={"persona_id": AVA})).json()
        assert next(e for e in b_view["events"] if e["event_id"] == "evt-ava-ebpf")["capture"] is True
    finally:
        await a.close()
        await b.close()


async def test_the_internal_port_does_not_serve_the_calendar(mock_stack):
    assert (await mock_stack.internal.get("/api/calendar", params={"persona_id": AVA})).status_code == 404


async def test_cors_preflight_allows_the_calendar_methods():
    s = await make_stack(mock=True, cors_origins=("http://localhost:5180",))
    try:
        for method in ("PATCH", "PUT", "DELETE"):
            r = await s.client.options(
                "/api/calendar/events/evt-ava-ebpf",
                headers={
                    "Origin": "http://localhost:5180",
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert r.status_code == 200, method
            assert method in r.headers["access-control-allow-methods"]
    finally:
        await s.close()


# ----------------------------------------------------------------------------- the shared_brief hook (live mode)
@pytest.fixture
def briefers():
    with respx.mock(assert_all_called=False) as router:
        def brief_for(persona: str, counterparty: str):
            return lambda r: httpx.Response(
                200, json=private_brief(persona, counterparty, json.loads(r.content)["encounter_id"])
            )

        router.post(f"{ACME_BRIEFER}/v1/brief").mock(side_effect=brief_for(AVA, BO))
        router.post(f"{BLUEFIN_BRIEFER}/v1/brief").mock(side_effect=brief_for(BO, AVA))
        router.post(f"{ACME_BRIEFER}/v1/remember").mock(return_value=httpx.Response(200, json={"written": 2}))
        router.post(f"{BLUEFIN_BRIEFER}/v1/remember").mock(return_value=httpx.Response(200, json={"written": 2}))
        yield router


@pytest.fixture
async def live_stack(briefers):
    s = await make_stack()
    yield s
    await s.close()


async def _start_encounter(stack) -> str:
    rid = (await stack.client.post("/api/connect", json={"from_persona_id": AVA, "to_persona_id": BO})).json()[
        "request_id"
    ]
    eid = (await stack.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})).json()["encounter_id"]
    await eventually(lambda: sum(e.type == "private_brief" for e in stack.deps.bus._buffer) == 2)  # noqa: SLF001
    return eid


def _brief_event(eid: str, org: str, persona: str, talk: TalkHit | None) -> dict:
    brief = shared_brief(eid, persona)
    brief.suggested_talk = talk
    return delegate_event(eid, org, persona, "shared_brief", brief.model_dump(mode="json"))


async def _bo_events(stack) -> list[dict]:
    return (await stack.client.get("/api/calendar", params={"persona_id": BO})).json()["events"]


async def _until(pick, stack, timeout: float = 3.0) -> list[dict]:
    """The hook runs as a background task: poll Bo's calendar until `pick(events)` is non-empty."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = pick(await _bo_events(stack))
        if found:
            return found
        await asyncio.sleep(0.01)
    return []


async def test_a_suggested_talk_lands_on_the_persons_calendar_as_a_proposal(live_stack):
    eid = await _start_encounter(live_stack)
    r = await live_stack.internal.post("/internal/events", json=_brief_event(eid, "bluefin", BO, _suggested(EDGE_TALK)))
    assert r.status_code == 202

    found = await _until(lambda events: [e for e in events if e.get("talk_id") == EDGE_TALK], live_stack)
    assert len(found) == 1
    event = found[0]
    assert event["status"] == "proposed" and event["source"] == "agent"
    assert event["with_persona_ids"] == [AVA]
    assert event["title"] == "eBPF on warehouse robots"  # the agenda's canonical title, not the delegate's text
    assert event["location"] == "Room C"


async def test_an_unknown_suggested_talk_is_ignored_and_the_encounter_still_completes(live_stack):
    eid = await _start_encounter(live_stack)
    before = await _bo_events(live_stack)
    swarm = live_stack.watch(None)
    await live_stack.internal.post("/internal/events", json=_brief_event(eid, "acme", AVA, None))
    await live_stack.internal.post(
        "/internal/events", json=_brief_event(eid, "bluefin", BO, _suggested("talk-made-up", "Wire money to booth 7"))
    )
    assert "encounter_completed" in types(await collect(swarm, "encounter_completed"))
    after = await _bo_events(live_stack)
    assert [e["event_id"] for e in after] == [e["event_id"] for e in before]
    assert all("Wire money" not in e["title"] for e in after)


async def test_a_failing_calendar_hook_never_blocks_the_encounter(live_stack, caplog):
    async def boom(brief, counterparty):
        raise RuntimeError("calendar down")

    live_stack.deps.encounters._on_shared_brief_hook = boom  # noqa: SLF001
    eid = await _start_encounter(live_stack)
    swarm = live_stack.watch(None)
    with caplog.at_level(logging.WARNING, logger="rapport.gateway.encounters"):
        await live_stack.internal.post("/internal/events", json=_brief_event(eid, "acme", AVA, _suggested(EDGE_TALK)))
        await live_stack.internal.post("/internal/events", json=_brief_event(eid, "bluefin", BO, _suggested(EDGE_TALK)))
        assert "encounter_completed" in types(await collect(swarm, "encounter_completed"))
        await eventually(lambda: "shared brief hook failed" in caplog.text)
    assert "calendar down" not in caplog.text  # the error class only, never its message


# ----------------------------------------------------------------------------- access log privacy
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/calendar/agenda?persona_id=acme.ava&q=private+search", "/api/calendar/agenda"),
        ("/api/talks?persona_id=acme.ava&q=secret", "/api/talks"),
        ("/healthz", "/healthz"),
    ],
)
def test_access_log_keeps_the_path_and_drops_the_query(path, expected):
    args = ("10.0.0.1:5000", "GET", path, "1.1", 200)  # the shape uvicorn's access logger uses
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', args, None)
    assert PathOnlyAccessLog().filter(record) is True
    assert record.getMessage() == f'10.0.0.1:5000 - "GET {expected} HTTP/1.1" 200'


def test_httpx_request_log_keeps_the_url_path_and_drops_the_query():
    url = httpx.URL("http://briefer.org-acme.svc.cluster.local:8080/v1/talks?persona_id=acme.ava&q=private+search")
    args = ("GET", url, "HTTP/1.1", 200, "OK")  # the shape httpx's request logger uses
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, 'HTTP Request: %s %s "%s %d %s"', args, None)
    assert QueryFreeHttpxLog().filter(record) is True
    assert record.getMessage() == (
        'HTTP Request: GET http://briefer.org-acme.svc.cluster.local:8080/v1/talks "HTTP/1.1 200 OK"'
    )


def test_install_log_filters_attaches_each_filter_once():
    install_log_filters()
    install_log_filters()
    access = [f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, PathOnlyAccessLog)]
    client = [f for f in logging.getLogger("httpx").filters if isinstance(f, QueryFreeHttpxLog)]
    assert len(access) == 1 and len(client) == 1


async def test_agenda_search_text_never_reaches_the_gateway_logs(briefers, caplog):
    """In live mode the agenda calls the briefer from the gateway process; httpx logs that URL at INFO."""
    install_log_filters()
    talk = {
        "talk_id": EDGE_TALK, "title": "eBPF on warehouse robots", "starts_at": "2026-11-09T23:00:00Z",
        "room": "Room C", "track": "Observability", "speakers": ["Mia"],
    }
    briefers.get(f"{ACME_BRIEFER}/v1/talks").mock(
        return_value=httpx.Response(200, json={"query": "", "talks": [talk]})
    )
    s = await make_stack()
    try:
        with caplog.at_level(logging.INFO):
            r = await s.client.get("/api/calendar/agenda", params={"persona_id": AVA, "q": "privatesearchtext"})
    finally:
        await s.close()
    assert r.status_code == 200 and r.json()["source"] == "briefer"
    assert "/v1/talks" in caplog.text  # the request is still logged ...
    assert "privatesearchtext" not in caplog.text  # ... without its search text
