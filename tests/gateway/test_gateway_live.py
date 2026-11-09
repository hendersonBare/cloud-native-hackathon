"""Live mode: briefers mocked with respx, Kubernetes faked. Proxies, connect/accept, errors, rate limits."""

import json

import httpx
import pytest
import respx
from gateway_support import (
    ACME_BRIEFER,
    AVA,
    BLUEFIN_BRIEFER,
    BO,
    FakeLauncher,
    collect,
    drain,
    make_stack,
    private_brief,
    types,
)

from rapport_common.models import AskAnswer, PersonaProfile, ResearchResult, TalkSearchResult
from rapport_gateway.k8s import encounter_manifest

PROFILE = PersonaProfile(persona_id=AVA).model_dump(mode="json")


@pytest.fixture
async def stack():
    s = await make_stack()
    yield s
    await s.close()


@pytest.fixture
def briefers():
    with respx.mock(assert_all_called=False) as router:
        yield router


def brief_route(router, base, persona, other):
    return router.post(f"{base}/v1/brief").mock(
        side_effect=lambda request: httpx.Response(
            200, json=private_brief(persona, other, json.loads(request.content)["encounter_id"])
        )
    )


async def test_connect_accept_creates_the_encounter_and_pushes_each_brief_to_its_own_phone(stack, briefers):
    acme_brief = brief_route(briefers, ACME_BRIEFER, AVA, BO)
    bluefin_brief = brief_route(briefers, BLUEFIN_BRIEFER, BO, AVA)
    ava, bo, swarm = stack.watch(AVA), stack.watch(BO), stack.watch(None)

    r = await stack.client.post("/api/connect", json={"from_persona_id": AVA, "to_persona_id": BO, "malicious": True})
    request_id = r.json()["request_id"]
    assert types(drain(bo)) == ["connect_request"]
    done = await stack.client.post(f"/api/connect/{request_id}/accept", json={"persona_id": BO})
    encounter_id = done.json()["encounter_id"]

    # the Encounter was created with both parties; only the responder is malicious
    [(created_id, spec, traceparent)] = stack.launcher.launched
    assert created_id == encounter_id
    assert spec.initiator.model_dump() == {"orgId": "acme", "personaId": AVA, "malicious": False}
    assert spec.responder.model_dump() == {"orgId": "bluefin", "personaId": BO, "malicious": True}
    assert traceparent is None or traceparent.startswith("00-")

    ava_events = await collect(ava, "private_brief")
    bo_events = await collect(bo, "private_brief")
    assert "encounter_started" in types(ava_events) and "encounter_started" in types(bo_events)
    assert next(e for e in ava_events if e.type == "private_brief").data["persona_id"] == AVA
    assert next(e for e in bo_events if e.type == "private_brief").data["persona_id"] == BO
    assert json.loads(acme_brief.calls.last.request.content) == {
        "encounter_id": encounter_id,
        "persona_id": AVA,
        "counterparty_persona_id": BO,
    }
    assert json.loads(bluefin_brief.calls.last.request.content)["persona_id"] == BO
    swarm_types = types(drain(swarm))
    assert "encounter_started" in swarm_types and "private_brief" not in swarm_types


async def test_accept_twice_creates_one_encounter(stack, briefers):
    brief_route(briefers, ACME_BRIEFER, AVA, BO)
    brief_route(briefers, BLUEFIN_BRIEFER, BO, AVA)
    rid = (await stack.client.post("/api/connect", json={"from_persona_id": AVA, "to_persona_id": BO})).json()[
        "request_id"
    ]
    a = await stack.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})
    b = await stack.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})
    assert a.json() == b.json() and len(stack.launcher.launched) == 1


async def test_brief_failure_sends_an_error_to_that_phone_only(stack, briefers):
    briefers.post(f"{ACME_BRIEFER}/v1/brief").mock(return_value=httpx.Response(500))
    brief_route(briefers, BLUEFIN_BRIEFER, BO, AVA)
    ava, bo = stack.watch(AVA), stack.watch(BO)
    rid = (await stack.client.post("/api/connect", json={"from_persona_id": AVA, "to_persona_id": BO})).json()[
        "request_id"
    ]
    assert (await stack.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})).status_code == 200
    assert "error" in types(await collect(ava, "error"))
    assert "private_brief" in types(await collect(bo, "private_brief"))


async def test_accept_returns_503_when_kubernetes_is_unavailable(briefers):
    s = await make_stack(launcher=FakeLauncher(unavailable=True))
    try:
        rid = (await s.client.post("/api/connect", json={"from_persona_id": AVA, "to_persona_id": BO})).json()[
            "request_id"
        ]
        r = await s.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})
        assert r.status_code == 503 and "Kubernetes" in r.json()["detail"]
        # the request is still pending, so a retry after the cluster recovers works
        s.launcher.unavailable = False
        brief_route(briefers, ACME_BRIEFER, AVA, BO)
        brief_route(briefers, BLUEFIN_BRIEFER, BO, AVA)
        assert (await s.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})).status_code == 200
    finally:
        await s.close()


async def test_context_upload_is_forwarded_unchanged_and_emits_profile_updated(stack, briefers):
    route = briefers.post(f"{ACME_BRIEFER}/v1/context").mock(return_value=httpx.Response(200, json=PROFILE))
    phone = stack.watch(AVA)
    r = await stack.client.post(
        "/api/context",
        data={"persona_id": AVA, "visibility": "private"},
        files={"file": ("cv.md", b"# Ava\nLikes eBPF", "text/markdown")},
    )
    assert r.status_code == 200 and r.json()["persona_id"] == AVA
    sent = route.calls.last.request
    assert sent.headers["content-type"].startswith("multipart/form-data")
    assert b'name="persona_id"' in sent.content and b'name="visibility"' in sent.content
    assert b"# Ava\nLikes eBPF" in sent.content and b'filename="cv.md"' in sent.content
    assert "profile_updated" in types(drain(phone))


async def test_text_only_upload_and_upstream_errors(stack, briefers):
    briefers.post(f"{ACME_BRIEFER}/v1/context").mock(return_value=httpx.Response(200, json=PROFILE))
    assert (
        await stack.client.post("/api/context", data={"persona_id": AVA, "visibility": "shareable", "text": "notes"})
    ).status_code == 200
    briefers.post(f"{BLUEFIN_BRIEFER}/v1/context").mock(return_value=httpx.Response(413))
    r = await stack.client.post("/api/context", data={"persona_id": BO, "visibility": "shareable", "text": "x"})
    assert r.status_code == 413


async def test_profile_ask_talks_research_are_proxied_to_the_persons_own_briefer(stack, briefers):
    briefers.get(f"{BLUEFIN_BRIEFER}/v1/profile", params={"persona_id": BO}).mock(
        return_value=httpx.Response(200, json=PersonaProfile(persona_id=BO).model_dump(mode="json"))
    )
    ask = briefers.post(f"{ACME_BRIEFER}/v1/ask").mock(
        return_value=httpx.Response(200, json=AskAnswer(answer="Sam promised Kai the questionnaire.").model_dump())
    )
    talks = briefers.get(f"{ACME_BRIEFER}/v1/talks", params={"persona_id": AVA, "q": "ebpf"}).mock(
        return_value=httpx.Response(200, json=TalkSearchResult(query="ebpf").model_dump(mode="json"))
    )
    research = briefers.post(f"{ACME_BRIEFER}/v1/research").mock(
        return_value=httpx.Response(200, json=ResearchResult(persona_id=AVA).model_dump(mode="json"))
    )
    assert (await stack.client.get("/api/profile", params={"persona_id": BO})).json()["persona_id"] == BO
    got = await stack.client.post("/api/ask", json={"persona_id": AVA, "question": "What did we promise Bluefin?"})
    assert got.json()["answer"].startswith("Sam promised")
    assert json.loads(ask.calls.last.request.content)["question"] == "What did we promise Bluefin?"
    assert (await stack.client.get("/api/talks", params={"persona_id": AVA, "q": "ebpf"})).json()["query"] == "ebpf"
    assert talks.called
    assert (await stack.client.post("/api/research", json={"persona_id": AVA})).json()["persona_id"] == AVA
    assert research.called


@pytest.mark.parametrize(
    "upstream,expected",
    [(403, 403), (404, 404), (422, 422), (500, 502), (503, 502)],
)
async def test_upstream_status_mapping(stack, briefers, upstream, expected):
    briefers.post(f"{ACME_BRIEFER}/v1/ask").mock(
        return_value=httpx.Response(upstream, json={"detail": "internal secret"})
    )
    r = await stack.client.post("/api/ask", json={"persona_id": AVA, "question": "q"})
    assert r.status_code == expected
    assert "secret" not in r.text  # upstream bodies are never echoed


async def test_briefer_unreachable_is_503_timeout_is_504_and_garbage_is_502(stack, briefers):
    ask = briefers.post(f"{ACME_BRIEFER}/v1/ask")
    ask.mock(side_effect=httpx.ConnectError("down"))
    assert (await stack.client.post("/api/ask", json={"persona_id": AVA, "question": "q"})).status_code == 503
    ask.mock(side_effect=httpx.ReadTimeout("slow"))
    assert (await stack.client.post("/api/ask", json={"persona_id": AVA, "question": "q"})).status_code == 504
    ask.mock(return_value=httpx.Response(200, json={"nonsense": True}))
    assert (await stack.client.post("/api/ask", json={"persona_id": AVA, "question": "q"})).status_code == 502


async def test_people_without_an_agent_have_no_briefer(stack):
    assert (await stack.client.post("/api/ask", json={"persona_id": "kestrel.mia", "question": "q"})).status_code == 422
    assert (await stack.client.get("/api/talks", params={"persona_id": "no.one"})).status_code == 404


async def test_llm_backed_calls_are_limited_per_client_ip(briefers):
    s = await make_stack(llm_calls_per_minute=3)
    try:
        briefers.post(f"{ACME_BRIEFER}/v1/ask").mock(
            return_value=httpx.Response(200, json=AskAnswer(answer="a").model_dump())
        )
        body = {"persona_id": AVA, "question": "q"}
        codes = [(await s.client.post("/api/ask", json=body)).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        blocked = await s.client.post("/api/ask", json=body)
        assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) >= 1
        # another client (the address the proxy saw last) has its own budget
        for i in range(3):
            xff = {"X-Forwarded-For": f"10.1.1.{i}, 203.0.113.9"}  # the first entry is forgeable and ignored
            assert (await s.client.post("/api/ask", json=body, headers=xff)).status_code == 200
        forged = await s.client.post("/api/ask", json=body, headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.9"})
        assert forged.status_code == 429
        # health is never limited
        assert (await s.client.get("/healthz")).status_code == 200
    finally:
        await s.close()


async def test_rate_limit_covers_research_context_and_right_swipes(briefers):
    s = await make_stack(llm_calls_per_minute=1)
    try:
        briefers.post(f"{ACME_BRIEFER}/v1/research").mock(
            return_value=httpx.Response(200, json=ResearchResult(persona_id=AVA).model_dump(mode="json"))
        )
        assert (await s.client.post("/api/research", json={"persona_id": AVA})).status_code == 200
        assert (await s.client.post("/api/research", json={"persona_id": AVA})).status_code == 429
        form = {"persona_id": AVA, "visibility": "shareable", "text": "x"}
        assert (await s.client.post("/api/context", data=form)).status_code == 429
        right = {"persona_id": AVA, "target_persona_id": BO, "direction": "right"}
        assert (await s.client.post("/api/swipe", json=right)).status_code == 429
        left = {**right, "direction": "left"}
        briefers.post(f"{ACME_BRIEFER}/v1/remember").mock(return_value=httpx.Response(200, json={"written": 1}))
        assert (await s.client.post("/api/swipe", json=left)).status_code == 202  # skips cost nothing
    finally:
        await s.close()


async def test_reset_clears_live_state(stack, briefers):
    rid = (await stack.client.post("/api/connect", json={"from_persona_id": AVA, "to_persona_id": BO})).json()[
        "request_id"
    ]
    assert (await stack.client.post("/api/demo/reset")).status_code == 200
    assert (await stack.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})).status_code == 404


def test_encounter_manifest_matches_the_crd_contract():
    from rapport_common.models import EncounterParty, EncounterSpec

    spec = EncounterSpec(
        initiator=EncounterParty(orgId="acme", personaId=AVA),
        responder=EncounterParty(orgId="bluefin", personaId=BO, malicious=True),
    )
    body = encounter_manifest("enc-1a2b3c4d", spec, "00-abc-def-01")
    assert body["apiVersion"] == "rapport.dev/v1alpha1" and body["kind"] == "Encounter"
    assert body["metadata"]["annotations"] == {"rapport.dev/traceparent": "00-abc-def-01"}
    assert body["metadata"]["labels"] == {"app.kubernetes.io/part-of": "rapport"}
    assert body["spec"]["responder"] == {"orgId": "bluefin", "personaId": BO, "malicious": True}
    assert body["spec"]["ttlSeconds"] == 600
    assert "annotations" in encounter_manifest("enc-x", spec, None)["metadata"]
