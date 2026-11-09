"""Discover: /v1/research (deck order, history, cache, one LLM call) and /v1/deep-dive (decision and checks)."""

from __future__ import annotations

from briefer_support import FakeLLM, client, doc, fresh_store

from rapport_briefer.deep_dive import _DiveOut
from rapport_briefer.research import _WhyBatch, _WhyItem
from rapport_common.models import DeepDive, MemoryRecord, ResearchResult

EBPF = {"persona_id": "acme.ava", "filters": {"interests": ["ebpf"]}}


async def _research(c, body=EBPF):
    r = await c.post("/v1/research", json=body)
    assert r.status_code == 200, r.text
    return ResearchResult.model_validate(r.json())


async def test_research_ebpf_returns_bo_then_priya_then_mia():
    async with client("acme", llm=FakeLLM()) as c:
        res = await _research(c)
    assert [card.persona_id for card in res.cards] == ["bluefin.bo", "lumenly.priya", "kestrel.mia"]
    bo, priya, mia = res.cards
    assert [h.memory_id for h in bo.company_history] == ["acme-note-0007"]
    assert bo.agent_available and not priya.agent_available and not mia.agent_available
    assert bo.match_score > priya.match_score >= mia.match_score
    assert bo.shared_interests == ["ebpf", "kubernetes"] and bo.org_name == "Bluefin Health" and bo.language == "es"
    assert [t.talk_id for t in priya.their_talks] == ["talk-ebpf-cost"]
    assert priya.their_talks[0].starts_at.hour == 21 and "2:30 PM MST" in priya.their_talks[0].reason
    assert [t.talk_id for t in mia.their_talks] == ["talk-ebpf-edge"]
    assert all(c_.company_history == [] for c_ in (priya, mia))
    assert bo.headline == "Platform lead moving 300 hospital services to Kubernetes"
    assert bo.looking_for == ["Cut observability costs", "Find tracing that needs no code changes"]


async def test_research_without_llm_uses_the_template_in_the_viewers_language():
    async with client("acme", llm=FakeLLM()) as c:
        res = await _research(c)
    assert res.cards[0].why_meet.startswith("You both care about ebpf and kubernetes; they're looking for")
    async with client("bluefin", llm=FakeLLM()) as c:
        res = await _research(c, {"persona_id": "bluefin.bo", "filters": {"interests": ["ebpf"]}})
    assert "bluefin.bo" == res.persona_id
    assert all(card.org_id != "bluefin" for card in res.cards)  # never the viewer's own company
    assert res.cards[0].why_meet.startswith("A ambos les interesan")


async def test_research_makes_one_batched_llm_call_and_caches_per_viewer_target():
    batch = _WhyBatch(
        items=[
            _WhyItem(persona_id="bluefin.bo", why_meet="Bo wants zero-code tracing."),
            _WhyItem(persona_id="not.real", why_meet="ignored"),
            _WhyItem(persona_id="lumenly.priya", why_meet="x" * 500),
        ]
    )
    llm = FakeLLM({"_WhyBatch": batch})
    async with client("acme", llm=llm) as c:
        first = await _research(c)
        again = await _research(c)
    assert len(llm.calls) == 1  # one call for the whole deck, none for the repeat
    assert first.cards[0].why_meet == "Bo wants zero-code tracing." == again.cards[0].why_meet
    assert len(first.cards[1].why_meet) <= 240  # truncated
    assert first.cards[2].why_meet.startswith("You both care about")  # not in the LLM output: template
    assert "Bo wants" not in llm.calls[0].system and llm.calls[0].user.startswith("<data")


async def test_research_filters_exclusions_and_limit():
    async with client("acme", llm=FakeLLM()) as c:
        agents = await _research(c, {"persona_id": "acme.ava", "filters": {"has_agent": True}})
        assert [x.persona_id for x in agents.cards] == ["bluefin.bo", "bluefin.kai"]
        roles = await _research(c, {"persona_id": "acme.ava", "filters": {"roles": ["sre"]}})
        assert [x.persona_id for x in roles.cards] == ["harborline.lena"]
        comp = await _research(c, {"persona_id": "acme.ava", "filters": {"org_ids": ["kestrel"], "language": "en"}})
        assert {x.persona_id for x in comp.cards} == {"kestrel.mia", "kestrel.raj"}
        excl = await _research(c, {**EBPF, "exclude_persona_ids": ["bluefin.bo"], "limit": 1})
        assert [x.persona_id for x in excl.cards] == ["lumenly.priya"]
        everyone = await _research(c, {"persona_id": "acme.ava"})
        assert {x.persona_id for x in everyone.cards}.isdisjoint({"acme.ava", "acme.sam"})
        assert len(everyone.cards) == 10


async def test_research_reads_only_opted_in_attendees():
    store = fresh_store()
    store._docs.pop("attendee-lumenly.priya")  # Priya never opted in
    async with client("acme", store, FakeLLM()) as c:
        res = await _research(c)
    assert [x.persona_id for x in res.cards] == ["bluefin.bo", "kestrel.mia"]


# ----------------------------------------------------------------------------------------- deep dive
def _dive(**kw) -> _DiveOut:
    base = dict(
        summary="Bo is a platform lead.",
        goals=["g1"],
        questions=["q1"],
        watch_outs=["w1"],
        opener="Hola Bo",
        action="agent_handshake",
        reason="Strong match.",
        confidence=0.9,
        cited_ids=["acme-note-0007", "made-up"],
    )
    return _DiveOut(**{**base, **kw})


async def _deep(c, target="bluefin.bo", viewer="acme.ava") -> DeepDive:
    r = await c.post("/v1/deep-dive", json={"persona_id": viewer, "target_persona_id": target})
    assert r.status_code == 200, r.text
    return DeepDive.model_validate(r.json())


async def test_deep_dive_fallback_bo_is_agent_handshake_and_priya_is_human_intro():
    async with client("acme", llm=FakeLLM()) as c:
        bo = await _deep(c)
        priya = await _deep(c, "lumenly.priya")
    assert bo.decision.action == "agent_handshake" and bo.decision.confidence == 0.7
    assert len(bo.decision.checks) == 4 and all("pass" in x for x in bo.decision.checks)
    assert "acme-note-0007" in [x.memory_id for x in bo.citations]
    assert bo.plan.offers and bo.plan.opener and bo.language == "en"
    assert "Case study" in " ".join(bo.plan.offers) or "one-pager" in " ".join(bo.plan.offers)
    assert priya.decision.action == "human_intro"
    assert priya.decision.reason == "Catch Priya after their 2:30 PM MST talk in Room A."
    assert any(x.startswith("target_company_runs_agents: fail") for x in priya.decision.checks)


async def test_deep_dive_llm_path_applies_ids_allow_list_and_one_call():
    llm = FakeLLM({"_DiveOut": _dive()})
    async with client("acme", llm=llm) as c:
        d = await _deep(c)
    assert len(llm.calls) == 1
    assert d.summary == "Bo is a platform lead." and d.plan.opener == "Hola Bo"
    assert d.decision.action == "agent_handshake" and d.decision.reason == "Strong match."
    assert [x.memory_id for x in d.citations] == ["acme-note-0007"]  # the unknown id was dropped
    assert "Bo is a platform lead" not in llm.calls[0].system


async def test_guardrail_downgrades_a_handshake_to_a_target_without_an_agent():
    async with client("acme", llm=FakeLLM({"_DiveOut": _dive()})) as c:
        d = await _deep(c, "lumenly.priya")
    assert d.decision.action == "human_intro"
    assert d.decision.reason.startswith("Catch Priya after")
    assert "target_company_runs_agents: fail -> human_intro" in d.decision.checks


async def test_guardrail_low_confidence_becomes_human_intro():
    async with client("acme", llm=FakeLLM({"_DiveOut": _dive(confidence=0.3)})) as c:
        d = await _deep(c)
    assert d.decision.action == "human_intro" and d.decision.confidence == 0.3
    assert any(x.startswith("confidence>=0.5: fail") for x in d.decision.checks)


async def test_guardrail_do_not_contact_note_skips():
    block = MemoryRecord(
        memory_id="acme-note-0099",
        org_id="acme",
        share_level="internal",
        kind="account_note",
        title="Do not contact Bo",
        text="Legal asked us to stop contacting Bo.",
        summary="Do not contact Bo.",
        tags=["do-not-contact"],
        about_org_ids=["bluefin"],
        about_persona_ids=["bluefin.bo"],
        source={"type": "seed"},
    )
    async with client("acme", fresh_store([block]), FakeLLM({"_DiveOut": _dive()})) as c:
        d = await _deep(c)
    assert d.decision.action == "skip" and "do-not-contact" in d.decision.reason
    assert "no_do_not_contact_note: fail -> skip" in d.decision.checks


async def test_guardrail_low_match_score_skips():
    # a target who shares nothing with Ava, has no history and no talks scores below 40
    async with client("acme", llm=FakeLLM({"_DiveOut": _dive(action="human_intro")})) as c:
        d = await _deep(c, "tidewater.ken")
    assert d.decision.action == "skip"
    assert any(x.startswith("match_score>=40: fail -> skip") for x in d.decision.checks)
    assert d.decision.reason.startswith("Skipping: low match score")


async def test_deep_dive_uses_the_score_the_viewer_saw_and_past_outcomes():
    follow = doc("acme-doc-x", "acme", "unused", "public", ["ebpf"])  # an extra shareable item is harmless
    summary = MemoryRecord(
        memory_id="sum-1",
        org_id="acme",
        share_level="internal",
        kind="encounter_summary",
        title="Encounter with Bluefin",
        text="Met Bo; agreed to follow up.",
        summary="Met Bo; follow up.",
        about_org_ids=["bluefin"],
        source={"type": "encounter"},
    )
    llm = FakeLLM({"_DiveOut": _dive(cited_ids=["sum-1"])})
    async with client("acme", fresh_store([follow, summary]), llm) as c:
        deck = await _research(c)
        d = await _deep(c)
    assert any(f"({deck.cards[0].match_score})" in x for x in d.decision.checks)
    assert [x.memory_id for x in d.citations] == ["sum-1"]
    assert "sum-1" in llm.calls[-1].user  # past outcomes about the target's company are gathered


async def test_deep_dive_rejects_self_and_foreign_viewers():
    async with client("acme", llm=FakeLLM()) as c:
        assert (
            await c.post("/v1/deep-dive", json={"persona_id": "acme.ava", "target_persona_id": "acme.ava"})
        ).status_code == 422
        assert (
            await c.post("/v1/deep-dive", json={"persona_id": "acme.ava", "target_persona_id": "nope.nope"})
        ).status_code == 404


async def test_deep_dive_spanish_viewer_gets_spanish_fallbacks():
    async with client("bluefin", llm=FakeLLM()) as c:
        d = await _deep(c, "lumenly.priya", "bluefin.bo")
    assert d.language == "es" and d.decision.action == "human_intro"
    assert d.decision.reason.startswith("Habla con Priya después de su charla de las 2:30 PM MST")
