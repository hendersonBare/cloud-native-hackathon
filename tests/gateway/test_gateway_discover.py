"""Discover decision branches (docs/FEATURE-DISCOVER.md): handshake, human intro, skip, rate-limited, autonomy off."""

import json

import httpx
import pytest
import respx
from gateway_support import ACME_BRIEFER, AVA, BO, collect, drain, eventually, make_stack, types

from rapport_common import names
from rapport_common.models import DeepDive, MemoryRecord

SWIPE = {"persona_id": AVA, "target_persona_id": BO, "direction": "right"}


def dive(action="agent_handshake", checks=None, target=BO) -> dict:
    return DeepDive.model_validate(
        {
            "persona_id": AVA,
            "target_persona_id": target,
            "language": "en",
            "summary": "Private summary.",
            "plan": {"opener": "Hi Bo"},
            "decision": {
                "action": action,
                "reason": "private reason",
                "confidence": 0.9,
                "checks": checks if checks is not None else ["target has an agent: yes"],
            },
            "citations": [],
        }
    ).model_dump(mode="json")


@pytest.fixture
def briefers():
    with respx.mock(assert_all_called=False) as router:
        router.deep = router.post(f"{ACME_BRIEFER}/v1/deep-dive")
        router.remember = router.post(f"{ACME_BRIEFER}/v1/remember").mock(
            return_value=httpx.Response(200, json={"written": 1})
        )
        yield router


@pytest.fixture
async def stack(briefers):
    s = await make_stack()
    yield s
    await s.close()


async def swipe_and_wait(stack, body=None, until="agent_decision"):
    ava, bo, swarm = stack.watch(AVA), stack.watch(BO), stack.watch(None)
    r = await stack.client.post("/api/swipe", json=body or SWIPE)
    assert r.status_code == 202 and r.json() == {"accepted": True}
    ava_events = await collect(ava, until)
    return ava_events, drain(bo), drain(swarm)


def decision_of(events):
    return next(e for e in events if e.type == "agent_decision")


async def test_handshake_creates_an_agent_connect_request_after_the_decision(stack, briefers):
    briefers.deep.mock(return_value=httpx.Response(200, json=dive()))
    ava, bo, swarm = await swipe_and_wait(stack, until="agent_decision")
    assert types(ava)[:3] == ["deep_dive_started", "deep_dive_ready", "agent_decision"]
    decision = decision_of(ava)
    assert decision.data["action"] == "agent_handshake" and decision.data["request_id"].startswith("req-")
    assert types(bo) == ["connect_request"]  # sent right after the decision, to the target's phone
    ready = next(e for e in ava if e.type == "deep_dive_ready")
    assert "handshakes this hour 1/5: yes" in ready.data["decision"]["checks"]
    # the swarm learns who and what, never why
    swarm_events = [e for e in swarm if e.type == "agent_decision"]
    assert swarm_events and "reason" not in swarm_events[0].data and "deep_dive_ready" not in types(swarm)


async def test_bo_gets_the_agent_connect_request_and_can_accept_it(stack, briefers):
    briefers.deep.mock(return_value=httpx.Response(200, json=dive()))
    bo = stack.watch(BO)
    ava = stack.watch(AVA)
    await stack.client.post("/api/swipe", json={**SWIPE, "malicious": True})
    await collect(ava, "agent_decision")
    events = await collect(bo, "connect_request")
    req = next(e for e in events if e.type == "connect_request")
    assert req.data["initiated_by"] == "agent" and req.data["malicious"] is True
    assert req.data["from_persona_id"] == AVA and req.data["to_persona_id"] == BO
    # the request is pending and accept-able by Bo only
    assert (
        await stack.client.post(f"/api/connect/{req.data['request_id']}/accept", json={"persona_id": AVA})
    ).status_code == 403


async def test_autonomy_off_downgrades_to_human_intro_and_sends_nothing(stack, briefers):
    briefers.deep.mock(return_value=httpx.Response(200, json=dive()))
    ava, bo, _ = await swipe_and_wait(stack, {**SWIPE, "autonomy": False})
    decision = decision_of(ava)
    assert decision.data["action"] == "human_intro" and decision.data["request_id"] is None
    ready = next(e for e in ava if e.type == "deep_dive_ready")
    assert ready.data["decision"]["action"] == "human_intro"
    assert "agent may act on its own: no" in ready.data["decision"]["checks"]
    assert "connect_request" not in types(bo)


async def test_hourly_limit_downgrades_the_sixth_handshake(stack, briefers):
    briefers.deep.mock(return_value=httpx.Response(200, json=dive()))
    ava = stack.watch(AVA)
    actions = []
    for _ in range(names.MAX_AGENT_HANDSHAKES_PER_HOUR + 1):
        drain(ava)
        await stack.client.post("/api/swipe", json=SWIPE)
        actions.append(decision_of(await collect(ava, "agent_decision")))
    assert [d.data["action"] for d in actions] == ["agent_handshake"] * 5 + ["human_intro"]
    assert actions[-1].data["request_id"] is None


@pytest.mark.parametrize("recommended", ["human_intro", "skip"])
async def test_the_briefers_other_decisions_pass_through(stack, briefers, recommended):
    briefers.deep.mock(return_value=httpx.Response(200, json=dive(recommended, ["match score 20 >= 40: no"])))
    ava, bo, _ = await swipe_and_wait(stack)
    assert decision_of(ava).data == {"target_persona_id": BO, "action": recommended, "request_id": None}
    ready = next(e for e in ava if e.type == "deep_dive_ready")
    assert ready.data["decision"]["checks"] == ["match score 20 >= 40: no"]
    assert "connect_request" not in types(bo)


async def test_agent_handshake_to_a_person_without_an_agent_becomes_human_intro(stack, briefers):
    briefers.deep.mock(return_value=httpx.Response(200, json=dive(target="lumenly.priya")))
    ava, _, _ = await swipe_and_wait(stack, {**SWIPE, "target_persona_id": "lumenly.priya"})
    assert decision_of(ava).data["action"] == "human_intro"


async def test_deep_dive_failure_still_emits_a_decision(stack, briefers):
    briefers.deep.mock(return_value=httpx.Response(500))
    ava, _, swarm = await swipe_and_wait(stack)
    kinds = types(ava)
    assert kinds[0] == "deep_dive_started" and "error" in kinds and "deep_dive_ready" not in kinds
    assert decision_of(ava).data["action"] == "human_intro"
    assert "error" not in types(swarm)


async def test_deep_dive_timeout_is_handled(briefers):
    s = await make_stack()
    try:
        briefers.deep.mock(side_effect=httpx.ReadTimeout("slow"))
        ava = s.watch(AVA)
        await s.client.post("/api/swipe", json=SWIPE)
        assert decision_of(await collect(ava, "agent_decision")).data["action"] == "human_intro"
    finally:
        await s.close()


async def test_deep_dive_ready_never_reaches_the_swarm_stream(stack, briefers):
    briefers.deep.mock(return_value=httpx.Response(200, json=dive()))
    _, _, swarm = await swipe_and_wait(stack)
    assert not {"deep_dive_started", "deep_dive_ready", "private_brief", "profile_updated"} & set(types(swarm))


async def test_left_swipe_remembers_the_skip_and_emits_nothing(stack, briefers):
    ava = stack.watch(AVA)
    r = await stack.client.post("/api/swipe", json={**SWIPE, "direction": "left", "target_persona_id": "kestrel.mia"})
    assert r.status_code == 202
    await eventually(lambda: briefers.remember.called)
    record = MemoryRecord.model_validate(json.loads(briefers.remember.calls.last.request.content)["records"][0])
    assert record.org_id == "acme" and record.share_level == "internal" and record.kind == "note"
    assert record.about_persona_ids == ["kestrel.mia"] and record.owner_persona_id == AVA
    assert not briefers.deep.called and drain(ava) == []


async def test_swipe_validation(stack):
    assert (await stack.client.post("/api/swipe", json={**SWIPE, "persona_id": "kestrel.mia"})).status_code == 422
    assert (await stack.client.post("/api/swipe", json={**SWIPE, "persona_id": "no.one"})).status_code == 404
    assert (await stack.client.post("/api/swipe", json={**SWIPE, "target_persona_id": "no.one"})).status_code == 404
