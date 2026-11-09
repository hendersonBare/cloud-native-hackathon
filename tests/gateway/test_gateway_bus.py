"""Event bus routing (SPEC 7.1), replay, overflow, and the SSE wire format."""

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
    body = await read_sse(stack.app, f"persona_id={AVA}")
    text = body.decode()
    assert text.startswith("event: error\ndata: {")
    assert text.endswith("\n\n") and "\r" not in text
    import json

    data = json.loads(text.split("data: ", 1)[1].split("\n", 1)[0])
    assert data["type"] == "error" and data["persona_id"] == AVA and data["data"] == {"message": "hello"}
    assert read_sse.last_headers["content-type"].startswith("text/event-stream")


async def test_sse_keepalive_comment(stack):
    body = await read_sse(stack.app, "view=swarm", min_chunks=1)
    assert body.startswith(b": keepalive\n\n")


async def test_sse_swarm_stream_hides_private_events(stack):
    stack.deps.bus.emit("private_brief", BRIEF, persona_id=AVA, encounter_id="enc-1")
    stack.deps.bus.emit("error", {"message": "public"})
    body = (await read_sse(stack.app, "view=swarm", min_chunks=2)).decode()
    assert "event: error" in body and "private_brief" not in body


async def test_stream_query_validation(stack):
    assert (await stack.client.get("/api/stream")).status_code == 422
    assert (await stack.client.get("/api/stream?persona_id=acme.ava&view=swarm")).status_code == 422
    assert (await stack.client.get("/api/stream?view=nope")).status_code == 422
    assert (await stack.client.get("/api/stream?persona_id=nobody.x")).status_code == 404
