"""Briefer HTTP API: health, personas (403/404), talks, ask, brief, remember. In-process, fake LLM, InMemoryStore."""

from __future__ import annotations

import json

import pytest
from briefer_support import FakeLLM, client, fresh_store

from rapport_briefer.ask import _AskOut
from rapport_briefer.brief import _Polish
from rapport_common.interfaces import InMemoryStore
from rapport_common.models import AskAnswer, PrivateBrief, TalkSearchResult


async def test_healthz():
    async with client() as c:
        r = await c.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


# ----------------------------------------------------------------------------------------- 403 / 404
FOREIGN, UNKNOWN = "bluefin.bo", "nobody.here"


def _calls(persona: str):
    return [
        ("GET", "/v1/talks", {"params": {"persona_id": persona, "q": "ebpf"}}),
        ("GET", "/v1/profile", {"params": {"persona_id": persona}}),
        ("POST", "/v1/ask", {"json": {"persona_id": persona, "question": "hi"}}),
        (
            "POST",
            "/v1/brief",
            {"json": {"encounter_id": "enc-1", "persona_id": persona, "counterparty_persona_id": "bluefin.kai"}},
        ),
        ("POST", "/v1/research", {"json": {"persona_id": persona}}),
        ("POST", "/v1/deep-dive", {"json": {"persona_id": persona, "target_persona_id": "bluefin.kai"}}),
        ("POST", "/v1/context", {"data": {"persona_id": persona, "visibility": "shareable", "text": "hello"}}),
    ]


@pytest.mark.parametrize("idx", range(7))
async def test_other_companys_persona_is_403_and_unknown_is_404(idx):
    async with client("acme") as c:
        for persona, status in ((FOREIGN, 403), (UNKNOWN, 404)):
            method, path, kw = _calls(persona)[idx]
            r = await c.request(method, path, **kw)
            assert r.status_code == status, (path, persona, r.text)
            assert "detail" in r.json()


async def test_unknown_counterparty_is_404():
    async with client() as c:
        r = await c.post(
            "/v1/brief", json={"encounter_id": "e", "persona_id": "acme.ava", "counterparty_persona_id": "x.y"}
        )
    assert r.status_code == 404


async def test_bad_body_is_422():
    async with client() as c:
        r = await c.post("/v1/ask", json={"persona_id": "acme.ava"})
    assert r.status_code == 422


# ----------------------------------------------------------------------------------------- talks
async def test_talks_ebpf_puts_zero_code_first_with_utc_times_and_a_reason():
    async with client("acme") as c:
        r = await c.get("/v1/talks", params={"persona_id": "acme.ava", "q": "ebpf"})
    result = TalkSearchResult.model_validate(r.json())
    ids = [t.talk_id for t in result.talks]
    assert ids[0] == "talk-ebpf-zero-code"
    assert set(ids[:3]) == {"talk-ebpf-zero-code", "talk-ebpf-cost", "talk-ebpf-edge"}
    first = result.talks[0]
    assert first.starts_at.utcoffset().total_seconds() == 0 and first.starts_at.hour == 22  # 3:30 PM MST
    assert "3:30 PM MST" in first.reason and "Room B" in first.reason
    assert len(result.talks) <= 10


async def test_talks_without_query_uses_interests_and_spanish_reason_for_bo():
    async with client("bluefin") as c:
        r = await c.get("/v1/talks", params={"persona_id": "bluefin.bo"})
    talks = TalkSearchResult.model_validate(r.json()).talks
    assert talks and talks[0].reason.startswith("Coincide con tu interés")


# ----------------------------------------------------------------------------------------- remember
def _followup(mid: str, org: str, about: str):
    return {
        "memory_id": mid,
        "org_id": org,
        "share_level": "internal",
        "kind": "followup",
        "title": "Send the security questionnaire",
        "text": "Send Kai the security questionnaire this week.",
        "summary": "Send Kai the security questionnaire",
        "tags": ["bluefin"],
        "about_org_ids": [about],
        "source": {"type": "encounter", "encounter_id": "enc-1"},
        "followup": {"status": "proposed", "owner_org_id": org, "counterparty_org_id": about},
    }


async def test_remember_writes_own_records_and_skips_other_orgs():
    store = fresh_store()
    async with client("acme", store) as c:
        r = await c.post(
            "/v1/remember",
            json={"records": [_followup("fu-1", "acme", "bluefin"), _followup("fu-2", "bluefin", "acme")]},
        )
    assert r.status_code == 200 and r.json() == {"written": 1}
    internal = ["rapport-acme-internal", "rapport-bluefin-internal"]
    assert store.get("fu-1", indices=internal) is not None
    assert store.get("fu-2", indices=internal) is None


async def test_remember_rejects_invalid_records_and_writes_nothing():
    store = InMemoryStore()
    bad = _followup("fu-3", "acme", "bluefin")
    del bad["followup"]  # a followup record needs followup info
    async with client("acme", store) as c:
        r = await c.post("/v1/remember", json={"records": [bad]})
    assert r.status_code == 422
    assert store.get("fu-3", indices=["rapport-acme-internal"]) is None


# ----------------------------------------------------------------------------------------- ask
QUESTION = "What did we promise Bluefin?"


async def test_ask_cites_the_bluefin_note_without_an_llm():
    async with client("acme", llm=FakeLLM()) as c:
        r = await c.post("/v1/ask", json={"persona_id": "acme.ava", "question": QUESTION})
    ans = AskAnswer.model_validate(r.json())
    ids = [c_.memory_id for c_ in ans.citations]
    assert "acme-note-0007" in ids
    assert all(len(c_.snippet) <= 240 for c_ in ans.citations) and len(ids) <= 5
    assert "security questionnaire" in ans.answer  # templated from the top hits
    assert not any(i.startswith("bluefin-") for i in ids)  # never another company's records
    assert not any(i.startswith(("attendee-", "profile-")) for i in ids)  # directory cards are not memory


async def test_ask_after_an_encounter_also_cites_followup_and_summary():
    store = fresh_store()
    summary = _followup("sum-1", "acme", "bluefin") | {
        "kind": "encounter_summary",
        "title": "Encounter with Bluefin",
        "followup": None,
    }
    summary.pop("followup")
    async with client("acme", store) as c:
        await c.post("/v1/remember", json={"records": [_followup("fu-1", "acme", "bluefin"), summary]})
        r = await c.post("/v1/ask", json={"persona_id": "acme.ava", "question": QUESTION})
    ids = [c_.memory_id for c_ in AskAnswer.model_validate(r.json()).citations]
    assert {"acme-note-0007", "fu-1", "sum-1"} <= set(ids)


async def test_ask_with_llm_keeps_known_ids_and_drops_unknown_ones():
    llm = FakeLLM(
        {
            "_AskOut": _AskOut(
                answer="You promised Kai the security questionnaire.", cited_ids=["acme-note-0007", "made-up-id"]
            )
        }
    )
    async with client("acme", llm=llm) as c:
        r = await c.post("/v1/ask", json={"persona_id": "acme.ava", "question": QUESTION})
    ans = AskAnswer.model_validate(r.json())
    assert ans.answer == "You promised Kai the security questionnaire."
    assert [c_.memory_id for c_ in ans.citations] == ["acme-note-0007"]
    # the question travels only inside the delimited data block of the user message
    call = llm.calls[0]
    assert QUESTION not in call.system and QUESTION in call.user and call.user.startswith("<data")


async def test_ask_with_nothing_found_says_so_in_the_persons_language():
    async with client("bluefin", store=InMemoryStore(), llm=FakeLLM()) as c:
        r = await c.post("/v1/ask", json={"persona_id": "bluefin.bo", "question": "zzz"})
    assert r.json()["citations"] == [] and r.json()["answer"].startswith("No encontré")


# ----------------------------------------------------------------------------------------- brief
BRIEF = {"encounter_id": "enc-1", "persona_id": "acme.ava", "counterparty_persona_id": "bluefin.bo"}


async def test_brief_without_llm_is_deterministic_and_complete():
    async with client("acme", llm=FakeLLM()) as c:
        r = await c.post("/v1/brief", json=BRIEF)
    assert r.status_code == 200
    b = PrivateBrief.model_validate(r.json())
    assert b.language == "en" and "Bo" in b.headline and "Bluefin Health" in b.headline
    assert [h.memory_id for h in b.history] == ["acme-note-0007"]
    assert b.watch_outs and "competitor" in b.watch_outs[0].lower()
    assert any(
        g.lower().startswith("find a design partner in healthcare") for g in b.goal_matches
    )  # Ava's private goal fits a hospital network
    assert 1 <= len(b.suggested_talks) <= 2 and b.suggested_talks[0].talk_id == "talk-ebpf-zero-code"
    assert any("Acme" in p or "case study" in p.lower() or "wants" in p for p in b.talking_points)
    assert len(b.talking_points) <= 3 and len(b.conversation_starters) <= 2


async def test_brief_for_bo_is_spanish_without_an_llm():
    async with client("bluefin", llm=FakeLLM()) as c:
        r = await c.post(
            "/v1/brief", json={"encounter_id": "e", "persona_id": "bluefin.bo", "counterparty_persona_id": "acme.ava"}
        )
    b = PrivateBrief.model_validate(r.json())
    assert b.language == "es"
    assert "Intereses en común" in b.headline and "en Acme Observability" in b.headline
    assert b.talking_points[0].startswith("Ava quiere:")
    assert [h.memory_id for h in b.history] == ["bluefin-note-0003"]  # Bluefin's own note about Acme
    assert not any(t.talk_id.startswith("acme-") for t in b.suggested_talks)


async def test_brief_uses_llm_polish_only_when_the_shape_matches():
    plain = await _brief_with(FakeLLM())
    polished = _Polish(
        headline="Meet Bo from Bluefin",
        talking_points=[f"P{i}" for i in range(len(plain.talking_points))],
        watch_outs=[f"W{i}" for i in range(len(plain.watch_outs))],
        goal_matches=[f"G{i}" for i in range(len(plain.goal_matches))],
        conversation_starters=["only one"] * (len(plain.conversation_starters) + 1),  # wrong length: rejected
    )
    llm = FakeLLM({"_Polish": polished})
    b = await _brief_with(llm)
    assert b.headline == "Meet Bo from Bluefin" and b.talking_points[0] == "P0"
    assert b.conversation_starters == plain.conversation_starters  # kept the deterministic text
    assert b.history == plain.history and b.suggested_talks == plain.suggested_talks  # IDs are never LLM-written
    assert 1.0 <= llm.calls[0].timeout <= 3.5  # capped to fit the 5 s SLO


async def _brief_with(llm) -> PrivateBrief:
    async with client("acme", llm=llm) as c:
        return PrivateBrief.model_validate((await c.post("/v1/brief", json=BRIEF)).json())


async def test_brief_never_reads_another_companys_indices():
    store = fresh_store()
    async with client("acme", store, FakeLLM()) as c:
        b = PrivateBrief.model_validate((await c.post("/v1/brief", json=BRIEF)).json())
    blob = json.dumps(b.model_dump(mode="json"))
    assert "bluefin-note-0003" not in blob and "bluefin-doc" not in blob


async def test_store_failure_is_a_503_not_a_500():
    class Broken(InMemoryStore):
        def search(self, *a, **k):
            raise ConnectionError("es down")

    async with client("acme", Broken(), FakeLLM()) as c:
        r = await c.get("/v1/talks", params={"persona_id": "acme.ava", "q": "ebpf"})
    assert r.status_code == 503 and r.json() == {"detail": "memory store unavailable"}


async def test_openai_wrapper_returns_none_without_a_key(monkeypatch):
    from pydantic import BaseModel

    from rapport_briefer.llm import OpenAILLM

    class S(BaseModel):
        x: str

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert await OpenAILLM().parse(system="s", user="u", schema=S) is None
