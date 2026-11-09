"""Every route in mock mode (RAPPORT_MOCK=1): no Kubernetes, no briefers, no keys."""

import pytest
from gateway_support import AVA, BO, KAI, collect, drain, eventually, make_stack, types

from rapport_common.models import (
    AskAnswer,
    GatewayEvent,
    PersonaProfile,
    ResearchResult,
    TalkSearchResult,
)
from rapport_gateway.timefmt import local_label


@pytest.fixture
async def stack():
    s = await make_stack(mock=True)
    yield s
    await s.close()


async def connect(stack, a=AVA, b=BO, **extra):
    r = await stack.client.post("/api/connect", json={"from_persona_id": a, "to_persona_id": b, **extra})
    assert r.status_code == 200, r.text
    return r.json()["request_id"]


async def test_health_and_personas(stack):
    assert (await stack.client.get("/healthz")).json() == {"ok": True, "version": "test"}
    body = (await stack.client.get("/api/personas")).json()
    assert len(body["personas"]) == 12 and len(body["orgs"]) == 6
    assert {o["org_id"] for o in body["orgs"] if o["agents_enabled"]} == {"acme", "bluefin"}


async def test_openapi_is_on_with_tags_and_response_models(stack):
    spec = (await stack.client.get("/openapi.json")).json()
    assert (await stack.client.get("/docs")).status_code == 200
    assert {t["name"] for t in spec["tags"]} >= {"personas", "stream", "connect", "discover", "demo", "calendar"}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if path == "/api/stream":
                continue
            # every operation documents its success: a JSON model, 204 No Content, or the calendar's .ics file
            code = next((c for c in ("200", "201", "202", "204") if c in op["responses"]), None)
            assert code, (method, path)
            if code == "204":
                continue
            content = op["responses"][code]["content"]
            assert content.get("application/json", {}).get("schema") or "text/calendar" in content, (method, path)


async def test_profile_defaults_to_the_fixture(stack):
    r = await stack.client.get("/api/profile", params={"persona_id": AVA})
    profile = PersonaProfile.model_validate(r.json())
    assert profile.persona_id == AVA and profile.shareable and profile.private
    assert (await stack.client.get("/api/profile", params={"persona_id": "nobody.x"})).status_code == 404
    assert (await stack.client.get("/api/profile", params={"persona_id": "kestrel.mia"})).status_code == 422


async def test_upload_plays_the_upload_phase(stack):
    phone = stack.watch(AVA)
    swarm = stack.watch(None)
    files = {"file": ("ava-cv.md", b"# Ava", "text/markdown")}
    r = await stack.client.post("/api/context", data={"persona_id": AVA, "visibility": "shareable"}, files=files)
    assert r.status_code == 200
    profile = PersonaProfile.model_validate(r.json())
    assert profile.source_files == ["ava-cv.md"]
    events = await collect(phone, "profile_updated")
    assert PersonaProfile.model_validate(events[-1].data).persona_id == AVA
    assert "profile_updated" not in types(drain(swarm))
    assert (await stack.client.get("/api/profile", params={"persona_id": AVA})).json()["source_files"] == ["ava-cv.md"]


async def test_upload_validation(stack):
    form = {"persona_id": AVA, "visibility": "shareable"}
    bad_type = await stack.client.post("/api/context", data=form, files={"file": ("cv.exe", b"x", "x/y")})
    assert bad_type.status_code == 415
    big = await stack.client.post(
        "/api/context", data=form, files={"file": ("cv.txt", b"x" * (2 * 1024 * 1024 + 1), "text/plain")}
    )
    assert big.status_code == 413
    assert (await stack.client.post("/api/context", data=form)).status_code == 422
    assert (
        await stack.client.post("/api/context", data={**form, "visibility": "secret", "text": "x"})
    ).status_code == 422
    assert (
        await stack.client.post("/api/context", data={**form, "persona_id": "no.body", "text": "x"})
    ).status_code == 404
    ok = await stack.client.post("/api/context", data={**form, "text": "I like eBPF"})
    assert ok.status_code == 200


async def test_connect_then_accept_replays_the_accept_phase_with_fresh_ids(stack):
    bo_phone, swarm = stack.watch(BO), stack.watch(None)
    request_id = await connect(stack, malicious=True)
    first = drain(bo_phone)
    assert types(first) == ["connect_request"] and first[0].data["request_id"] == request_id

    accepted = await stack.client.post(f"/api/connect/{request_id}/accept", json={"persona_id": BO})
    assert accepted.status_code == 200
    encounter_id = accepted.json()["encounter_id"]
    assert encounter_id.startswith("enc-") and encounter_id != "enc-1a2b3c4d"

    events = [e for e in await collect(swarm, "encounter_completed") if e.type != "connect_request"]
    assert {e.encounter_id for e in events if e.encounter_id} == {encounter_id}
    kinds = types(events)
    assert kinds[0] == "encounter_started" and kinds[-1] == "encounter_completed"
    assert {"pod_status", "exchange_message", "policy_decision", "shared_brief"} <= set(kinds)
    assert "private_brief" not in kinds
    denies = [e for e in events if e.type == "policy_decision" and e.data["decision"] == "deny"]
    assert denies and denies[0].data["rule_id"] == "pricing_needs_approval"
    # timestamps are re-stamped to now and unique per (type, ts, encounter)
    keys = [(e.type, e.ts, e.encounter_id) for e in events]
    assert len(set(keys)) == len(keys)
    assert all(abs((e.ts - GatewayEvent(type="error").ts).total_seconds()) < 30 for e in events)


async def test_accept_is_idempotent_and_checked(stack):
    request_id = await connect(stack)
    assert (await stack.client.post(f"/api/connect/{request_id}/accept", json={"persona_id": AVA})).status_code == 403
    assert (await stack.client.post("/api/connect/req-nope/accept", json={"persona_id": BO})).status_code == 404
    a = await stack.client.post(f"/api/connect/{request_id}/accept", json={"persona_id": BO})
    b = await stack.client.post(f"/api/connect/{request_id}/accept", json={"persona_id": BO})
    assert a.json() == b.json()


async def test_connect_validation(stack):
    bad = {"from_persona_id": AVA, "to_persona_id": "acme.sam"}
    assert (await stack.client.post("/api/connect", json=bad)).status_code == 422  # same company
    assert (await stack.client.post("/api/connect", json={**bad, "to_persona_id": "kestrel.mia"})).status_code == 422
    assert (await stack.client.post("/api/connect", json={**bad, "to_persona_id": "no.one"})).status_code == 404
    assert (await stack.client.post("/api/connect", json={"from_persona_id": AVA})).status_code == 422
    assert (await stack.client.post("/api/connect", json={**bad, "to_persona_id": BO, "extra": 1})).status_code == 422


async def test_right_swipe_on_bo_plays_the_swipe_phase_and_the_request_can_be_accepted(stack):
    ava, bo, swarm = stack.watch(AVA), stack.watch(BO), stack.watch(None)
    r = await stack.client.post(
        "/api/swipe", json={"persona_id": AVA, "target_persona_id": BO, "direction": "right", "malicious": True}
    )
    assert r.status_code == 202 and r.json() == {"accepted": True}
    ava_events = await collect(ava, "agent_decision")
    assert types(ava_events)[:3] == ["deep_dive_started", "deep_dive_ready", "agent_decision"]
    decision = next(e for e in ava_events if e.type == "agent_decision")
    request_id = decision.data["request_id"]
    assert request_id and request_id != "req-01" and decision.data["action"] == "agent_handshake"
    bo_events = await collect(bo, "connect_request")
    req = next(e for e in bo_events if e.type == "connect_request")
    assert (
        req.data["request_id"] == request_id and req.data["initiated_by"] == "agent" and req.data["malicious"] is True
    )
    swarm_types = types(drain(swarm))
    assert "agent_decision" in swarm_types and "deep_dive_ready" not in swarm_types
    # Bo accepts the agent's request
    ok = await stack.client.post(f"/api/connect/{request_id}/accept", json={"persona_id": BO})
    assert ok.status_code == 200


async def test_swipe_without_autonomy_and_on_people_without_agents(stack):
    ava = stack.watch(AVA)
    await stack.client.post(
        "/api/swipe", json={"persona_id": AVA, "target_persona_id": BO, "direction": "right", "autonomy": False}
    )
    events = await collect(ava, "agent_decision")
    decision = next(e for e in events if e.type == "agent_decision")
    assert decision.data["action"] == "human_intro" and decision.data["request_id"] is None
    assert next(e for e in events if e.type == "deep_dive_ready").data["decision"]["action"] == "human_intro"

    await stack.client.post(
        "/api/swipe", json={"persona_id": AVA, "target_persona_id": "lumenly.priya", "direction": "right"}
    )
    events = await collect(ava, "agent_decision")
    assert next(e for e in events if e.type == "agent_decision").data["action"] == "human_intro"


async def test_left_swipe_only_records(stack):
    ava = stack.watch(AVA)
    r = await stack.client.post(
        "/api/swipe", json={"persona_id": AVA, "target_persona_id": "kestrel.mia", "direction": "left"}
    )
    assert r.status_code == 202 and drain(ava) == []
    assert (
        await stack.client.post(
            "/api/swipe", json={"persona_id": AVA, "target_persona_id": "no.one", "direction": "left"}
        )
    ).status_code == 404
    assert (
        await stack.client.post("/api/swipe", json={"persona_id": AVA, "target_persona_id": AVA, "direction": "right"})
    ).status_code == 422
    assert (
        await stack.client.post("/api/swipe", json={"persona_id": AVA, "target_persona_id": BO, "direction": "up"})
    ).status_code == 422


async def test_ask_cites_the_bluefin_note(stack):
    r = await stack.client.post("/api/ask", json={"persona_id": AVA, "question": "What did we promise Bluefin?"})
    answer = AskAnswer.model_validate(r.json())
    assert answer.citations[0].memory_id == "acme-note-0007"
    other = AskAnswer.model_validate(
        (await stack.client.post("/api/ask", json={"persona_id": AVA, "question": "Weather?"})).json()
    )
    assert other.citations == []
    assert (await stack.client.post("/api/ask", json={"persona_id": "no.one", "question": "x"})).status_code == 404
    assert (await stack.client.post("/api/ask", json={"persona_id": AVA, "question": "x" * 501})).status_code == 422


async def test_talks_are_utc_and_the_zero_code_talk_is_330pm_mst(stack):
    result = TalkSearchResult.model_validate(
        (await stack.client.get("/api/talks", params={"persona_id": AVA, "q": "ebpf tracing"})).json()
    )
    zero = next(t for t in result.talks if t.talk_id == "talk-ebpf-zero-code")
    assert zero.starts_at.utcoffset().total_seconds() == 0 and zero.starts_at.hour == 22 and zero.starts_at.minute == 30
    assert local_label(zero.starts_at) == "3:30 PM MST"
    everything = TalkSearchResult.model_validate(
        (await stack.client.get("/api/talks", params={"persona_id": AVA})).json()
    )
    assert len(everything.talks) == 5
    nothing = TalkSearchResult.model_validate(
        (await stack.client.get("/api/talks", params={"persona_id": AVA, "q": "zzzz"})).json()
    )
    assert nothing.talks == []


async def test_research_honours_exclusions_limit_and_filters(stack):
    async def research(**body):
        r = await stack.client.post("/api/research", json={"persona_id": AVA, **body})
        assert r.status_code == 200
        return ResearchResult.model_validate(r.json())

    full = await research()
    assert [c.persona_id for c in full.cards][0] == BO and len(full.cards) == 4
    assert [c.persona_id for c in (await research(exclude_persona_ids=[BO])).cards][0] == "lumenly.priya"
    assert len((await research(limit=2)).cards) == 2
    only_agents = await research(filters={"has_agent": True})
    assert [c.persona_id for c in only_agents.cards] == [BO]
    assert (await research(filters={"interests": ["ebpf"]})).cards[0].persona_id == BO
    assert (await research(filters={"interests": ["nothing-like-this"]})).cards == []
    from_bluefin = await stack.client.post("/api/research", json={"persona_id": BO})
    assert BO not in [c["persona_id"] for c in from_bluefin.json()["cards"]]


async def test_reset_clears_state_and_requires_the_admin_token_when_set(stack):
    request_id = await connect(stack)
    assert (await stack.client.post("/api/demo/reset")).json() == {"ok": True}
    assert (await stack.client.post(f"/api/connect/{request_id}/accept", json={"persona_id": BO})).status_code == 404
    assert drain(stack.watch(AVA)) == []  # replay buffer cleared


async def test_admin_token(stack):
    locked = await make_stack(mock=True, admin_token="s3cret")
    try:
        assert (await locked.client.post("/api/demo/reset")).status_code == 401
        wrong = await locked.client.post("/api/demo/reset", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 403
        ok = await locked.client.post("/api/demo/reset", headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200
    finally:
        await locked.close()


async def test_internal_events_is_404_on_the_public_app(stack):
    for method in ("post", "get", "put"):
        r = await getattr(stack.client, method)("/internal/events")
        assert r.status_code == 404
    assert (await stack.client.post("/internal/anything/else", json={})).status_code == 404


async def test_internal_app_serves_only_internal_events(stack):
    assert (await stack.internal.get("/healthz")).status_code == 404
    assert (await stack.internal.get("/api/personas")).status_code == 404
    assert (await stack.internal.get("/docs")).status_code == 404
    assert (await stack.internal.post("/internal/events", json={})).status_code == 422


async def test_second_run_after_reset_uses_new_ids(stack):
    swarm = stack.watch(None)
    ids = []
    for _ in range(2):
        rid = await connect(stack)
        ids.append(
            (await stack.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})).json()["encounter_id"]
        )
        await eventually(lambda: "encounter_completed" in types(list(swarm.queue._queue)))  # noqa: SLF001
        drain(swarm)
        await stack.client.post("/api/demo/reset")
    assert ids[0] != ids[1]


async def test_mock_accept_works_for_other_pairs(stack):
    swarm = stack.watch(None)
    rid = await connect(stack, "acme.sam", KAI)
    r = await stack.client.post(f"/api/connect/{rid}/accept", json={"persona_id": KAI})
    assert r.status_code == 200
    events = await collect(swarm, "encounter_completed")
    started = next(e for e in events if e.type == "encounter_started")
    assert started.data == {"initiator_persona_id": "acme.sam", "responder_persona_id": KAI}
