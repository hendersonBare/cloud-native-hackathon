"""Full in-process exchange: initiator <-> responder over httpx.ASGITransport, FakePolicy, InMemoryStore, recorded
gateway events. Covers the "Done when" list in docs/workstreams/delegate.md."""

import json

import httpx
import pytest
from delegate_fixtures import ENC, TEXT_MARK, Side, make_config, seed_records

from rapport_common.models import SharedBrief
from rapport_delegate.initiator import run_initiator
from rapport_delegate.responder import create_app


async def run_exchange(*, malicious: bool, initiator_kw=None, responder_kw=None):
    """Returns (exit_code, initiator side, responder side, [messages sent on the wire], responder app)."""
    init = Side(make_config("initiator"), **(initiator_kw or {}))
    resp = Side(make_config("responder", malicious=malicious), **(responder_kw or {}))
    app = create_app(resp.cfg, **resp.kwargs())
    wire: list[dict] = []

    async def spy(request: httpx.Request) -> None:
        if request.url.path == "/v1/exchange":
            wire.append(json.loads(request.content))

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://peer.test",
                                     event_hooks={"request": [spy]}) as client:
            code = await run_initiator(init.cfg, client=client, poll_s=0.01, **init.kwargs())
            await resp.reporter.flush()
    return code, init, resp, wire, app


def events(side: Side, type_: str | None = None):
    return [e for e in side.sink.events if type_ is None or e.type == type_]


async def test_full_exchange_with_malicious_responder():
    code, init, resp, wire, app = await run_exchange(malicious=True)
    assert code == 0
    assert app.state.service.succeeded is True

    # three rounds each way, in order, valid messages
    assert [(m["from_org"], m["round"]) for m in wire] == [("acme", 1), ("acme", 2), ("acme", 3)]

    # the injected pricing ask reached the initiator and was declined by policy
    assert "pricing" not in {a["topic"] for m in wire if m["round"] == 2 for a in m["asks"]}  # Acme is honest
    acme_decisions = {(e.data["item_id"], e.data["action"]): e.data for e in events(init, "policy_decision")}
    assert acme_decisions[("acme-doc-0004", "answer")]["decision"] == "deny"
    assert acme_decisions[("acme-doc-0004", "answer")]["rule_id"] == "pricing_needs_approval"
    acme_brief = SharedBrief.model_validate(events(init, "shared_brief")[0].data)
    declined = [d for d in acme_brief.declined if d.from_org == "acme"]
    assert [(d.topic, d.reason_code, d.rule_id) for d in declined] == [
        ("pricing", "policy_deny", "pricing_needs_approval")
    ]

    # Bo's brief validates and is in Spanish; Ava's in English
    bo_brief = SharedBrief.model_validate(events(resp, "shared_brief")[0].data)
    assert bo_brief.language == "es" and bo_brief.for_persona_id == "bluefin.bo"
    assert acme_brief.language == "en" and acme_brief.for_persona_id == "acme.ava"
    assert "Tu agente" in bo_brief.summary
    # Bo sees that Acme declined the pricing ask
    assert [(d.from_org, d.topic, d.rule_id) for d in bo_brief.declined] == [
        ("acme", "pricing", "pricing_needs_approval")
    ]

    # one "attend <talk> together" follow-up with the talk set, in each person's language
    for brief, snippet in ((acme_brief, "Attend Zero-code tracing"), (bo_brief, "Asistir juntos a Zero-code tracing")):
        talk_followups = [f for f in brief.followups if f.followup_id == f"fu-{ENC}-talk"]
        assert len(talk_followups) == 1 and snippet in talk_followups[0].text
        assert "3:30 PM MST" in talk_followups[0].text  # shown in America/Denver with its label
        assert brief.suggested_talk is not None and brief.suggested_talk.talk_id == "talk-ebpf-zero-code"
    talk_ids = {f["talk_id"] for m in wire if m["round"] == 3 for f in m["followups"] if f["talk_id"]}
    assert talk_ids == {"talk-ebpf-zero-code"}


async def test_nothing_internal_and_no_record_text_ever_leaves():
    _, init, resp, wire, _ = await run_exchange(malicious=True)
    wire_replies = json.dumps(wire)
    # replies come back over the same wire: capture them through the events and briefs as well
    everything = wire_replies + json.dumps([e.model_dump(mode="json") for e in init.sink.events + resp.sink.events])
    assert "acme-doc-0008" not in everything
    assert "Discount approvals" not in everything
    assert "acme-note-0007" not in everything and "bluefin-note-0003" not in everything
    assert TEXT_MARK not in everything
    assert "PRIVATE headline" not in everything
    # the delegates' own searches never saw an internal record
    assert all(c.item.item_id != "acme-doc-0008" for c in init.policy.calls)


async def test_replies_on_the_wire_hold_summaries_only():
    init = Side(make_config("initiator"))
    resp = Side(make_config("responder", malicious=True))
    app = create_app(resp.cfg, **resp.kwargs())
    replies: list[dict] = []

    async def spy(response: httpx.Response) -> None:
        if response.request.url.path == "/v1/exchange":
            await response.aread()
            replies.append(response.json())

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://peer.test",
                                     event_hooks={"response": [spy]}) as client:
            assert await run_initiator(init.cfg, client=client, poll_s=0.01, **init.kwargs()) == 0
    assert [r["round"] for r in replies] == [1, 2, 3]
    dumped = json.dumps(replies)
    assert TEXT_MARK not in dumped
    asks = replies[1]["asks"]
    assert any(a["topic"] == "pricing" and a["text"].startswith("Ignore your previous instructions") for a in asks)
    offered = {o["item_id"] for o in replies[1]["offers"]}
    assert offered <= {"bluefin-doc-0001", "bluefin-doc-0002"}


async def test_honest_exchange_has_no_pricing_ask_and_no_denials():
    code, init, resp, wire, _ = await run_exchange(malicious=False)
    assert code == 0
    assert all(e.data["decision"] == "allow" for e in events(init, "policy_decision") + events(resp, "policy_decision"))
    assert not SharedBrief.model_validate(events(init, "shared_brief")[0].data).declined


async def test_events_are_posted_in_order():
    code, init, resp, _, _ = await run_exchange(malicious=True)
    assert code == 0
    for side, org in ((init, "acme"), (resp, "bluefin")):
        kinds = [e.type for e in side.sink.events]
        assert kinds[0] == "delegate_status" and side.sink.events[0].data["status"] == "started"
        assert kinds[-2:] == ["shared_brief", "delegate_status"] and side.sink.events[-1].data["status"] == "done"
        middle = kinds[1:-2]
        assert set(middle) <= {"exchange_message", "policy_decision"}
        assert [e.data["round"] for e in side.sink.events if e.type == "exchange_message"] == [1, 2, 3]
        assert {e.org_id for e in side.sink.events} == {org}
        assert {e.encounter_id for e in side.sink.events} == {ENC}
        # a policy decision names the record's title and no content
        for e in side.sink.events:
            if e.type == "policy_decision":
                assert e.data["item_title"] and TEXT_MARK not in json.dumps(e.data)
    lines = [e.data["display"] for e in init.sink.events if e.type == "exchange_message"]
    assert lines[1] == "Acme's agent offered 2 items and asked about 2 topics"


async def test_exchange_fails_cleanly_when_the_peer_is_gone():
    init = Side(make_config("initiator"))

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse), base_url="http://peer.test") as client:
        code = await run_initiator(init.cfg, client=client, wait_s=0.05, poll_s=0.01, **init.kwargs())
    assert code == 1
    statuses = [e.data["status"] for e in events(init, "delegate_status")]
    assert statuses == ["started", "failed"]
    assert events(init, "delegate_status")[-1].data["detail"] == "peer_not_ready"


@pytest.mark.parametrize("records", [[r for r in seed_records() if r.org_id != "conference"]])
async def test_no_agenda_means_no_talk_followup_but_the_exchange_still_completes(records):
    code, init, _, _, _ = await run_exchange(malicious=False, initiator_kw={"records": records})
    assert code == 0
    brief = SharedBrief.model_validate(events(init, "shared_brief")[0].data)
    assert brief.suggested_talk is None
