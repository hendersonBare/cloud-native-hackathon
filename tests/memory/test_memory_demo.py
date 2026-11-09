"""The demo behaviours the seed must support, checked on an InMemoryStore built from seed_records()."""

from __future__ import annotations

import re

import pytest

from rapport_common import names
from rapport_common.interfaces import InMemoryStore
from rapport_memory import store_from_env
from rapport_memory.seed import seed_records

CONF = names.CONFERENCE_INDEX
ACME_SHARE, ACME_INT = names.shareable_index("acme"), names.internal_index("acme")
BLUE_SHARE, BLUE_INT = names.shareable_index("bluefin"), names.internal_index("bluefin")


@pytest.fixture(scope="module")
def store() -> InMemoryStore:
    return InMemoryStore(seed_records())


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower()))


def topics_in(goals: list[str], indices: list[str], store: InMemoryStore) -> set[str]:
    """Goal words that are tags somewhere in the given shareable corpus (how a delegate picks an ask topic)."""
    vocabulary = {t for r in store.search("", indices=indices, size=1000) for t in r.tags}
    return {w for goal in goals for w in tokens(goal)} & vocabulary


def test_talk_search_ranks_the_headline_talk_first(store):
    ava = names.persona("acme.ava")
    boosted = "ebpf " + " ".join(ava.interests)
    for query in ("ebpf", boosted):
        hits = store.search(query, indices=[CONF], kinds=["talk"], size=5)
        assert hits[0].memory_id == "talk-ebpf-zero-code", query
    top3 = {r.memory_id for r in store.search("ebpf", indices=[CONF], kinds=["talk"], tags=["ebpf"], size=5)}
    assert top3 == {"talk-ebpf-zero-code", "talk-ebpf-cost", "talk-ebpf-edge"}


def test_what_did_we_promise_bluefin_finds_the_call_notes(store):
    acme_view = [ACME_INT, ACME_SHARE, CONF]
    assert store.search("What did we promise Bluefin?", indices=acme_view, size=3)[0].memory_id == "acme-note-0007"
    scoped = store.search("promise", indices=acme_view, about_org_ids=["bluefin"])
    assert [r.memory_id for r in scoped] == ["acme-note-0007"]
    # and the other company cannot see it
    assert store.get("acme-note-0007", indices=[BLUE_INT, BLUE_SHARE, CONF]) is None


def research_order(store: InMemoryStore, viewer_id: str, interests: list[str]) -> list[str]:
    """SPEC (FEATURE-DISCOVER) research scoring, with the seed as the only input."""
    viewer = names.persona(viewer_id)
    query = " ".join(interests + viewer.interests)
    cards = store.search(query, indices=[CONF], kinds=["attendee"], tags=interests, size=20)
    cards = [c for c in cards if c.org_id != viewer.org_id]
    notes = store.search("", indices=[names.internal_index(viewer.org_id)], size=100)
    scored = []
    for rank, card in enumerate(cards):
        relevance = 1.0 if len(cards) == 1 else 1.0 - 0.7 * rank / (len(cards) - 1)
        overlap = min(1.0, len(set(card.profile.interests) & set(viewer.interests)) / len(viewer.interests))
        history = any(card.owner_persona_id in n.about_persona_ids or card.org_id in n.about_org_ids for n in notes)
        scored.append((round(100 * (0.5 * overlap + 0.3 * relevance + 0.2 * history)), card.owner_persona_id))
    return [p for _, p in sorted(scored, reverse=True)]


def test_ava_research_for_ebpf_returns_bo_then_priya_then_mia(store):
    assert research_order(store, "acme.ava", ["ebpf"]) == ["bluefin.bo", "lumenly.priya", "kestrel.mia"]


def test_bo_company_history_cites_the_acme_note(store):
    notes = store.search("", indices=[ACME_INT], about_org_ids=["bluefin"])
    assert "acme-note-0007" in {n.memory_id for n in notes}
    assert "bluefin.bo" in next(n for n in notes if n.memory_id == "acme-note-0007").about_persona_ids


def shareable_goals(persona_id: str) -> list[str]:
    return next(r for r in seed_records() if r.memory_id == f"profile-{persona_id}-shareable").profile.goals[:3]


def test_bos_goals_lead_to_asks_acme_can_answer(store):
    topics = topics_in(shareable_goals("bluefin.bo"), [ACME_SHARE], store)
    assert {"security", "hipaa", "observability"} <= topics
    answer = store.search("", indices=[ACME_SHARE, CONF], tags=["security"], kinds=["document"])
    assert [r.memory_id for r in answer] == ["acme-doc-0003"]
    assert next(r for r in answer).share_level == "partner"


def test_malicious_pricing_ask_hits_the_denied_document_and_the_internal_one_stays_hidden(store):
    delegate_view = [ACME_SHARE, CONF]
    pricing = store.search("pricing", indices=delegate_view, tags=["pricing"])
    assert [r.memory_id for r in pricing] == ["acme-doc-0004"]  # policy denies this one (pricing_needs_approval)
    assert pricing[0].share_level == "partner"
    assert store.get("acme-doc-0008", indices=delegate_view) is None
    assert store.get("acme-doc-0008", indices=[ACME_INT]).share_level == "internal"


def test_avas_goals_lead_to_asks_bluefin_can_answer(store):
    topics = topics_in(shareable_goals("acme.ava"), [BLUE_SHARE], store)
    assert {"kubernetes", "platform-engineering"} <= topics
    answers = store.search("", indices=[BLUE_SHARE], tags=["kubernetes"])
    assert {r.memory_id for r in answers} == {"bluefin-doc-0001", "bluefin-doc-0002"}


@pytest.mark.parametrize("org", ["acme", "bluefin"])
def test_a_delegate_view_never_contains_internal_records(store, org):
    view = [names.shareable_index(org), CONF]
    everything = store.search("", indices=view, size=1000)
    assert everything and all(r.share_level != "internal" for r in everything)
    assert all(not r.memory_id.endswith("-private") for r in everything)
    for q in ("pricing discount", "Bluefin promise", "Healthcare design partner this quarter"):
        assert all(r.share_level != "internal" for r in store.search(q, indices=view, size=50))


def test_store_from_env_without_credentials_is_a_filtered_in_memory_store(monkeypatch, caplog):
    monkeypatch.delenv("ES_URL", raising=False)
    monkeypatch.delenv("ES_API_KEY", raising=False)
    with caplog.at_level("WARNING", logger="rapport.memory"):
        delegate = store_from_env([ACME_SHARE, CONF])
    assert isinstance(delegate, InMemoryStore)
    assert any(rec.levelname == "WARNING" for rec in caplog.records)
    records = delegate.search("", indices=[ACME_SHARE, CONF, ACME_INT, BLUE_SHARE], size=1000)
    ids = {r.memory_id for r in records}
    assert "acme-doc-0001" in ids and "talk-ebpf-zero-code" in ids
    assert not ids & {"acme-doc-0008", "acme-note-0007", "bluefin-doc-0001", "profile-acme.ava-private"}
    assert delegate.get("acme-doc-0008", indices=[ACME_INT]) is None  # not even when asked for explicitly


def test_store_from_env_briefer_gets_internal_and_shareable(monkeypatch):
    monkeypatch.delenv("ES_URL", raising=False)
    monkeypatch.delenv("ES_API_KEY", raising=False)
    briefer = store_from_env([ACME_INT, ACME_SHARE, CONF])
    assert briefer.get("acme-note-0007", indices=[ACME_INT]) is not None
    assert briefer.get("bluefin-note-0003", indices=[BLUE_INT]) is None


def test_store_from_env_with_credentials_builds_a_restricted_client(monkeypatch):
    from rapport_memory.client import MemoryClient

    monkeypatch.setenv("ES_URL", "https://es.invalid:443")
    monkeypatch.setenv("ES_API_KEY", "not-a-real-key")
    client = store_from_env([ACME_SHARE, CONF])
    assert isinstance(client, MemoryClient)
    with pytest.raises(ValueError):
        client.search("x", indices=[ACME_INT])  # refused locally, before any network call
    with pytest.raises(ValueError):
        client.write([r for r in seed_records() if r.memory_id == "acme-doc-0008"])


def test_only_one_url_var_means_in_memory(monkeypatch):
    monkeypatch.setenv("ES_URL", "https://es.invalid:443")
    monkeypatch.delenv("ES_API_KEY", raising=False)
    assert isinstance(store_from_env([CONF]), InMemoryStore)
