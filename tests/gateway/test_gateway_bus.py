"""Event bus routing (SPEC 7.1), replay, overflow, and the SSE wire format."""

import json
import re
import time
from datetime import datetime, timezone

import pytest
from gateway_support import AVA, BO, drain, make_stack, read_sse, types

from rapport_common.models import (
    AgentDecisionData,
    DeepDiveStartedData,
    EncounterCompletedData,
    EncounterStartedData,
    GatewayEvent,
    PersonaProfile,
)
from rapport_gateway.bus import EventBus
from rapport_gateway.settings import Settings

BRIEF = {
    "encounter_id": "enc-1",
    "persona_id": AVA,
    "counterparty_persona_id": BO,
    "language": "en",
    "headline": "h",
}
DEEP_DIVE = {
    "persona_id": AVA,
    "target_persona_id": BO,
    "language": "en",
    "summary": "s",
    "plan": {"opener": "hi"},
    "decision": {"action": "human_intro", "reason": "r", "confidence": 0.9},
}


def emit_all(bus: EventBus) -> None:
    bus.emit(
        "encounter_started",
        EncounterStartedData(initiator_persona_id=AVA, responder_persona_id=BO),
        encounter_id="enc-1",
    )
    bus.emit("private_brief", BRIEF, persona_id=AVA, encounter_id="enc-1")
    bus.emit("profile_updated", PersonaProfile(persona_id=AVA), persona_id=AVA)
    bus.emit("deep_dive_started", DeepDiveStartedData(target_persona_id=BO), persona_id=AVA)
    bus.emit("deep_dive_ready", DEEP_DIVE, persona_id=AVA)
    bus.emit("agent_decision", AgentDecisionData(target_persona_id=BO, action="human_intro"), persona_id=AVA)
    bus.emit("encounter_completed", EncounterCompletedData(status="completed"), encounter_id="enc-1")
    bus.emit("error", {"message": "x"}, persona_id=BO)


async def test_private_events_never_reach_the_swarm_but_agent_decision_reaches_both():
    bus = EventBus()
    swarm, ava, bo = bus.subscribe(None), bus.subscribe(AVA), bus.subscribe(BO)
    emit_all(bus)
    swarm_types = types(drain(swarm))
    for private in ("private_brief", "profile_updated", "deep_dive_started", "deep_dive_ready"):
        assert private not in swarm_types
    assert "agent_decision" in swarm_types
    assert "agent_decision" in types(drain(ava))
    assert "agent_decision" not in types(drain(bo))  # not Bo's event
    assert swarm_types == ["encounter_started", "agent_decision", "encounter_completed"]  # Bo's error is his alone


async def test_phone_gets_own_events_and_encounter_level_events_of_its_encounters():
    bus = EventBus()
    ava, bo, sam = bus.subscribe(AVA), bus.subscribe(BO), bus.subscribe("acme.sam")
    emit_all(bus)
    assert types(drain(ava)) == [
        "encounter_started",
        "private_brief",
        "profile_updated",
        "deep_dive_started",
        "deep_dive_ready",
        "agent_decision",
        "encounter_completed",
    ]
    assert types(drain(bo)) == ["encounter_started", "encounter_completed", "error"]
    assert types(drain(sam)) == []  # not part of enc-1


async def test_events_without_a_persona_are_not_sent_to_phones():
    bus = EventBus()
    ava = bus.subscribe(AVA)
    bus.emit(
        "pod_status", {"org_id": "acme", "side": "initiator", "pod": "p", "phase": "Running"}, encounter_id="enc-1"
    )
    assert drain(ava) == []


async def test_replay_buffer_catches_up_a_late_subscriber_with_only_matching_events():
    bus = EventBus()
    emit_all(bus)
    late_swarm, late_ava = bus.subscribe(None), bus.subscribe(AVA)
    assert "private_brief" not in types(drain(late_swarm))
    assert "private_brief" in types(drain(late_ava))
    assert drain(bus.subscribe(AVA, replay=False)) == []


async def test_bounded_queue_drops_the_oldest():
    bus = EventBus(queue_size=3)
    sub = bus.subscribe(None)
    for i in range(5):
        bus.emit("error", {"message": str(i)})
    got = [e.data["message"] for e in drain(sub)]
    assert got == ["2", "3", "4"] and sub.dropped == 2


async def test_replay_buffer_is_bounded():
    bus = EventBus(buffer_size=2)
    for i in range(5):
        bus.emit("error", {"message": str(i)})
    assert [e.data["message"] for e in drain(bus.subscribe(None))] == ["3", "4"]


async def test_dedupe_key_stays_unique_even_for_identical_timestamps():
    bus = EventBus()
    ts = datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)
    sent = [bus.publish(GatewayEvent(type="error", ts=ts, data={"message": "m"})) for _ in range(3)]
    keys = {(e.type, e.ts, e.encounter_id) for e in sent}
    assert len(keys) == 3


async def test_clear_forgets_buffer_and_membership():
    bus = EventBus()
    emit_all(bus)
    bus.clear()
    assert drain(bus.subscribe(AVA)) == []
    bus.emit("encounter_completed", EncounterCompletedData(status="completed"), encounter_id="enc-1")
    assert drain(bus.subscribe(AVA, replay=False)) == []


@pytest.fixture
async def stack():
    s = await make_stack(mock=False)
    yield s
    await s.close()


async def test_sse_wire_format_and_replay(stack):
    stack.deps.bus.emit("error", {"message": "hello"}, persona_id=AVA)
    body = await read_sse(stack.app, f"persona_id={AVA}", min_chunks=2)
    text = body.decode()
    assert text.startswith("retry: 1000\n\n")
    text = text.removeprefix("retry: 1000\n\n")
    assert re.match(r"id: \d+\nevent: error\ndata: \{", text)
    assert text.endswith("\n\n") and "\r" not in text
    data = json.loads(text.split("data: ", 1)[1].split("\n", 1)[0])
    assert data["type"] == "error" and data["persona_id"] == AVA and data["data"] == {"message": "hello"}
    assert read_sse.last_headers["content-type"].startswith("text/event-stream")


async def test_sse_keepalive_comment(stack):
    body = await read_sse(stack.app, "view=swarm", min_chunks=2)
    assert body.startswith(b"retry: 1000\n\n") and b": keepalive\n\n" in body


async def test_sse_swarm_stream_hides_private_events(stack):
    stack.deps.bus.emit("private_brief", BRIEF, persona_id=AVA, encounter_id="enc-1")
    stack.deps.bus.emit("error", {"message": "public"})
    body = (await read_sse(stack.app, "view=swarm", min_chunks=3)).decode()
    assert "event: error" in body and "private_brief" not in body


async def test_stream_query_validation(stack):
    assert (await stack.client.get("/api/stream")).status_code == 422
    assert (await stack.client.get("/api/stream?persona_id=acme.ava&view=swarm")).status_code == 422
    assert (await stack.client.get("/api/stream?view=nope")).status_code == 422
    assert (await stack.client.get("/api/stream?persona_id=nobody.x")).status_code == 404


# ----------------------------------------------------------------------------- ids, Last-Event-ID, rotation
def sse_ids(body: bytes) -> list[int]:
    return [int(m) for m in re.findall(r"^id: (\d+)$", body.decode(), flags=re.M)]


def sse_event_types(body: bytes) -> list[str]:
    return re.findall(r"^event: (\w+)$", body.decode(), flags=re.M)


async def test_event_ids_increase_and_replay_keeps_them(stack):
    bus = stack.deps.bus
    for n in range(3):
        bus.emit("error", {"message": str(n)})
    first = sse_ids(await read_sse(stack.app, "view=swarm", min_chunks=4))
    assert len(first) == 3 and first == sorted(set(first))
    bus.emit("error", {"message": "3"})
    again = sse_ids(await read_sse(stack.app, "view=swarm", min_chunks=5))
    assert again[:3] == first and again[3] > first[-1]  # replayed events keep their id
    bus.clear()
    bus.emit("error", {"message": "after clear"})
    assert sse_ids(await read_sse(stack.app, "view=swarm", min_chunks=2))[0] > again[-1]  # clear() keeps counting


async def test_reconnect_with_last_event_id_replays_only_newer_matching_events(stack):
    bus = stack.deps.bus
    bus.emit("agent_decision", AgentDecisionData(target_persona_id=BO, action="human_intro"), persona_id=AVA)
    bus.emit("error", {"message": "bo only"}, persona_id=BO)
    bus.emit("error", {"message": "mid"}, persona_id=AVA)
    seen = sse_ids(await read_sse(stack.app, f"persona_id={AVA}", min_chunks=3))
    assert len(seen) == 2
    bus.emit("error", {"message": "bo again"}, persona_id=BO)  # not Ava's
    bus.emit("error", {"message": "new"}, persona_id=AVA)
    body = await read_sse(
        stack.app, f"persona_id={AVA}", min_chunks=3, request_headers={"Last-Event-ID": str(seen[0])}
    )
    assert sse_event_types(body) == ["error", "error"] and b'"message":"mid"' in body and b'"message":"new"' in body
    assert b"bo again" not in body and b"bo only" not in body and b"agent_decision" not in body
    last = str(sse_ids(body)[-1])
    caught_up = await read_sse(stack.app, f"persona_id={AVA}", min_chunks=2, request_headers={"Last-Event-ID": last})
    assert sse_ids(caught_up) == [] and caught_up.startswith(b"retry: 1000")


async def test_last_event_id_query_fallback_and_header_precedence(stack):
    bus = stack.deps.bus
    bus.emit("error", {"message": "one"})
    bus.emit("error", {"message": "two"})
    first, second = sse_ids(await read_sse(stack.app, "view=swarm", min_chunks=3))
    via_query = await read_sse(stack.app, f"view=swarm&last_event_id={first}", min_chunks=2)
    assert sse_ids(via_query) == [second]
    both = await read_sse(
        stack.app, f"view=swarm&last_event_id={second}", min_chunks=3, request_headers={"Last-Event-ID": "0"}
    )
    assert sse_ids(both) == [first, second]  # the header wins
    junk = await read_sse(stack.app, "view=swarm", min_chunks=3, request_headers={"Last-Event-ID": "not-a-number"})
    assert sse_ids(junk) == [first, second]  # unparseable: today's full replay


async def test_private_events_never_reach_the_swarm_on_replay_after_reconnect(stack):
    bus = stack.deps.bus
    bus.emit("error", {"message": "marker"})
    marker = sse_ids(await read_sse(stack.app, "view=swarm", min_chunks=2))[0]
    bus.emit("private_brief", BRIEF, persona_id=AVA, encounter_id="enc-1")
    bus.emit("profile_updated", PersonaProfile(persona_id=AVA), persona_id=AVA)
    bus.emit("deep_dive_started", DeepDiveStartedData(target_persona_id=BO), persona_id=AVA)
    bus.emit("deep_dive_ready", DEEP_DIVE, persona_id=AVA)
    bus.emit("error", {"message": "public"})
    marker_header = {"Last-Event-ID": str(marker)}
    body = await read_sse(stack.app, "view=swarm", min_chunks=2, request_headers=marker_header)
    assert sse_event_types(body) == ["error"] and b"public" in body
    for private in ("private_brief", "profile_updated", "deep_dive_started", "deep_dive_ready"):
        assert private not in body.decode()
    phone = await read_sse(stack.app, f"persona_id={AVA}", min_chunks=5, request_headers=marker_header)
    assert "private_brief" in phone.decode() and "deep_dive_ready" in phone.decode()  # the owner still gets them


async def test_stream_is_closed_by_the_server_after_the_configured_maximum():
    s = await make_stack(mock=False, sse_max_seconds=0.4)
    try:
        started = time.monotonic()
        body = await read_sse(s.app, "view=swarm", until_closed=True, wait=5)
        assert read_sse.last_closed is True
        assert 0.3 <= time.monotonic() - started < 3
        assert body.startswith(b"retry: 1000\n\n") and b": keepalive" in body  # pings every max/2 or sooner
    finally:
        await s.close()


async def test_rotation_disabled_with_zero_keeps_the_stream_open():
    s = await make_stack(mock=False, sse_max_seconds=0)
    try:
        await read_sse(s.app, "view=swarm", until_closed=True, wait=0.6)
        assert read_sse.last_closed is False
    finally:
        await s.close()


def test_sse_max_seconds_from_env(monkeypatch):
    monkeypatch.delenv("RAPPORT_SSE_MAX_SECONDS", raising=False)
    assert Settings.from_env().sse_max_seconds == 12.0
    monkeypatch.setenv("RAPPORT_SSE_MAX_SECONDS", "0")
    assert Settings.from_env().sse_max_seconds == 0.0
    monkeypatch.setenv("RAPPORT_SSE_MAX_SECONDS", "5")
    assert Settings.from_env().sse_max_seconds == 5.0
