"""/internal/events: source and party checks, mapping, remember, completion, failure, timeout."""

import json

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
    drain,
    eventually,
    exchange_data,
    make_stack,
    policy_data,
    private_brief,
    shared_brief,
    status_data,
    types,
)

from rapport_common.models import MemoryRecord
from rapport_gateway.k8s import PodInfo, PodRegistry


@pytest.fixture
def briefers():
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{ACME_BRIEFER}/v1/brief").mock(
            side_effect=lambda r: httpx.Response(
                200, json=private_brief(AVA, BO, json.loads(r.content)["encounter_id"])
            )
        )
        router.post(f"{BLUEFIN_BRIEFER}/v1/brief").mock(
            side_effect=lambda r: httpx.Response(
                200, json=private_brief(BO, AVA, json.loads(r.content)["encounter_id"])
            )
        )
        router.remember_acme = router.post(f"{ACME_BRIEFER}/v1/remember").mock(
            return_value=httpx.Response(200, json={"written": 2})
        )
        router.remember_bluefin = router.post(f"{BLUEFIN_BRIEFER}/v1/remember").mock(
            return_value=httpx.Response(200, json={"written": 2})
        )
        yield router


async def start_encounter(stack, malicious=False):
    rid = (
        await stack.client.post(
            "/api/connect", json={"from_persona_id": AVA, "to_persona_id": BO, "malicious": malicious}
        )
    ).json()["request_id"]
    eid = (await stack.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})).json()["encounter_id"]
    # let both private briefs land first so later assertions only see what the delegates cause
    await eventually(lambda: sum(e.type == "private_brief" for e in stack.deps.bus._buffer) == 2)  # noqa: SLF001
    return eid


async def post(stack, body):
    return await stack.internal.post("/internal/events", json=body)


@pytest.fixture
async def stack(briefers):
    s = await make_stack()
    yield s
    await s.close()


async def test_rejects_unknown_encounters(stack):
    r = await post(stack, delegate_event("enc-nope", "acme", AVA, "delegate_status", status_data("initiator")))
    assert r.status_code == 403 and r.json() == {"detail": "event rejected"}


async def test_rejects_a_mismatched_org_persona_or_side(stack):
    eid = await start_encounter(stack)
    cases = [
        delegate_event(eid, "bluefin", AVA, "delegate_status", status_data("initiator")),  # org of the other party
        delegate_event(eid, "acme", BO, "delegate_status", status_data("initiator")),  # persona of the other party
        delegate_event(eid, "kestrel", "kestrel.mia", "delegate_status", status_data("initiator")),  # outsider
        delegate_event(eid, "acme", AVA, "delegate_status", status_data("responder")),  # wrong side
        delegate_event(eid, "acme", AVA, "exchange_message", exchange_data("bluefin", "acme")),  # forged sender
        delegate_event(eid, "acme", AVA, "policy_decision", policy_data("bluefin")),  # another org's decision
        delegate_event(eid, "acme", AVA, "shared_brief", shared_brief(eid, BO).model_dump(mode="json")),  # not hers
        delegate_event(eid, "acme", AVA, "shared_brief", shared_brief("enc-other", AVA).model_dump(mode="json")),
    ]
    for body in cases:
        assert (await post(stack, body)).status_code == 403, body["type"]


async def test_rejects_malformed_bodies(stack):
    assert (await post(stack, {"encounter_id": "x"})).status_code == 422
    bad = delegate_event("enc-1", "acme", AVA, "delegate_status", {"side": "nope"})
    assert (await post(stack, bad)).status_code == 422


async def test_maps_delegate_events_to_gateway_events(stack):
    eid = await start_encounter(stack)
    swarm, ava = stack.watch(None), stack.watch(AVA)
    drain(swarm), drain(ava)
    for body in (
        delegate_event(eid, "acme", AVA, "delegate_status", status_data("initiator")),
        delegate_event(eid, "acme", AVA, "exchange_message", exchange_data("acme", "bluefin")),
        delegate_event(eid, "bluefin", BO, "policy_decision", policy_data("bluefin")),
    ):
        assert (await post(stack, body)).status_code == 202
    events = drain(swarm)
    assert types(events) == ["exchange_message", "policy_decision"]  # delegate_status started has no gateway event
    assert all(e.encounter_id == eid and e.persona_id is None for e in events)
    assert drain(ava) == []  # swarm-only


async def test_shared_briefs_go_to_the_right_phone_are_remembered_and_complete_the_encounter(stack, briefers):
    eid = await start_encounter(stack)
    ava, bo, swarm = stack.watch(AVA), stack.watch(BO), stack.watch(None)
    drain(ava), drain(bo), drain(swarm)

    r = await post(
        stack, delegate_event(eid, "acme", AVA, "shared_brief", shared_brief(eid, AVA).model_dump(mode="json"))
    )
    assert r.status_code == 202
    assert types(drain(ava)) == ["shared_brief"] and drain(bo) == []
    assert "encounter_completed" not in types(drain(swarm))

    await post(
        stack,
        delegate_event(eid, "bluefin", BO, "shared_brief", shared_brief(eid, BO, followups=2).model_dump(mode="json")),
    )
    assert "encounter_completed" in types(await collect(bo, "encounter_completed"))
    done = [e for e in drain(swarm) if e.type == "encounter_completed"]
    assert done[0].data == {"status": "completed", "detail": None}

    await eventually(lambda: briefers.remember_acme.called and briefers.remember_bluefin.called)
    acme_records = [
        MemoryRecord.model_validate(r) for r in json.loads(briefers.remember_acme.calls.last.request.content)["records"]
    ]
    assert [r.kind for r in acme_records] == ["encounter_summary", "followup"]
    for record in acme_records:  # internal to Acme, about Bluefin, tied to the encounter
        assert record.org_id == "acme" and record.share_level == "internal"
        assert record.about_org_ids == ["bluefin"] and record.about_persona_ids == [BO]
        assert record.source.type == "encounter" and record.source.encounter_id == eid
        assert record.owner_persona_id == AVA
    assert acme_records[0].tags == ["encounter", "ebpf"]  # "Not A Tag" is not a valid slug and is dropped
    bluefin_records = [
        MemoryRecord.model_validate(r)
        for r in json.loads(briefers.remember_bluefin.calls.last.request.content)["records"]
    ]
    assert [r.kind for r in bluefin_records] == ["encounter_summary", "followup", "followup"]
    assert all(r.org_id == "bluefin" and r.about_org_ids == ["acme"] for r in bluefin_records)


async def test_a_repeated_shared_brief_is_delivered_once(stack):
    eid = await start_encounter(stack)
    ava = stack.watch(AVA)
    drain(ava)
    body = delegate_event(eid, "acme", AVA, "shared_brief", shared_brief(eid, AVA).model_dump(mode="json"))
    assert (await post(stack, body)).status_code == 202
    assert (await post(stack, body)).status_code == 202
    assert types(drain(ava)) == ["shared_brief"]


async def test_remember_failure_never_blocks_the_encounter(stack, briefers):
    briefers.remember_acme.mock(return_value=httpx.Response(500))
    briefers.remember_bluefin.mock(side_effect=httpx.ConnectError("down"))
    eid = await start_encounter(stack)
    swarm = stack.watch(None)
    await post(stack, delegate_event(eid, "acme", AVA, "shared_brief", shared_brief(eid, AVA).model_dump(mode="json")))
    await post(stack, delegate_event(eid, "bluefin", BO, "shared_brief", shared_brief(eid, BO).model_dump(mode="json")))
    assert "encounter_completed" in types(await collect(swarm, "encounter_completed"))


async def test_a_failed_delegate_fails_the_encounter_at_once(stack):
    eid = await start_encounter(stack)
    swarm, bo = stack.watch(None), stack.watch(BO)
    drain(swarm), drain(bo)
    r = await post(stack, delegate_event(eid, "bluefin", BO, "delegate_status", status_data("responder", "failed")))
    assert r.status_code == 202
    failed = next(e for e in drain(swarm) if e.type == "encounter_completed")
    assert failed.data["status"] == "failed" and "responder" in failed.data["detail"]
    assert "encounter_completed" in types(drain(bo))
    # nothing more is accepted for a failed encounter
    late = delegate_event(eid, "acme", AVA, "exchange_message", exchange_data("acme", "bluefin"))
    assert (await post(stack, late)).status_code == 403


async def test_closing_status_is_still_accepted_after_completion(stack):
    eid = await start_encounter(stack)
    for who, org in ((AVA, "acme"), (BO, "bluefin")):
        await post(stack, delegate_event(eid, org, who, "shared_brief", shared_brief(eid, who).model_dump(mode="json")))
    done = delegate_event(eid, "acme", AVA, "delegate_status", status_data("initiator", "done"))
    assert (await post(stack, done)).status_code == 202
    late = delegate_event(eid, "acme", AVA, "exchange_message", exchange_data("acme", "bluefin"))
    assert (await post(stack, late)).status_code == 403


async def test_timeout_fails_the_encounter(briefers):
    s = await make_stack(encounter_timeout_s=0.05)
    try:
        swarm = s.watch(None)
        await start_encounter(s)
        events = await collect(swarm, "encounter_completed")
        done = next(e for e in events if e.type == "encounter_completed")
        assert done.data == {"status": "failed", "detail": "timeout"}
    finally:
        await s.close()


async def test_kubernetes_mode_requires_the_callers_ip_to_be_a_pod_of_that_encounter(briefers):
    registry = PodRegistry()
    s = await make_stack(registry=registry, check_delegate_ip=True)
    s.deps.encounters._ip_grace_s = 0.05  # noqa: SLF001 - keep the test fast
    try:
        eid = await start_encounter(s)
        event = delegate_event(eid, "acme", AVA, "exchange_message", exchange_data("acme", "bluefin"))
        assert (await post(s, event)).status_code == 403  # the test client's IP is no pod
        peer = "127.0.0.1"  # what ASGITransport reports as the caller
        registry.update(PodInfo("d-acme", "org-acme", "enc-other", "acme", "initiator", "Running", peer))
        assert (await post(s, event)).status_code == 403  # a pod, but of another encounter
        registry.update(PodInfo("d-bluefin", "org-bluefin", eid, "bluefin", "responder", "Running", peer))
        assert (await post(s, event)).status_code == 403  # right encounter, wrong org
        registry.update(PodInfo("d-acme2", "org-acme", eid, "acme", "initiator", "Running", peer))
        assert (await post(s, event)).status_code == 202
    finally:
        await s.close()
