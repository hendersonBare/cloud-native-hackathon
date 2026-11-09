"""POST /v1/research: the Discover deck for one viewer (docs/FEATURE-DISCOVER.md, "Research").

Reads only the opt-in attendee directory (`kind=attendee` cards in the conference index), the public agenda and
the viewer's OWN internal notes. Ranking, scores, talks and history are deterministic; ONE batched LLM call
writes `why_meet` for the cards that are not cached yet, with a template as the fallback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import BaseModel

from rapport_common import names
from rapport_common.models import (
    DiscoverFilters,
    MemoryRecord,
    Persona,
    PersonCard,
    ResearchRequest,
    ResearchResult,
    TalkHit,
)

from .core import Briefer, CardMemo, cite, fit, join_list, talk_hit, when
from .llm import data_block
from .timefmt import as_utc

_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)
_NOTE_KINDS = ("account_note", "note")
DEFAULT_RELEVANCE = 0.3

SYSTEM = (
    "For each person in the data, write one friendly sentence (at most 220 characters) saying why the viewer "
    "should meet them, in the language named in the data. Use only the facts given for that person. "
    "Return one item per person, using the persona_id exactly as given."
)


class _WhyItem(BaseModel):
    persona_id: str
    why_meet: str


class _WhyBatch(BaseModel):
    items: list[_WhyItem]


@dataclass
class Entry:
    target: Persona
    card: MemoryRecord | None
    interests: list[str]
    looking_for: list[str]
    headline: str
    shared: list[str]
    history: list[MemoryRecord]
    talks: list[MemoryRecord]
    relevance: float
    score: int
    why: str = ""
    sort_key: tuple = field(default=(), repr=False)


def match_score(overlap: float, relevance: float, has_history: bool) -> int:
    return round(100 * (0.5 * overlap + 0.3 * relevance + 0.2 * (1 if has_history else 0)))


def _relevance(position: int, total: int) -> float:
    """1.0 for the top hybrid hit, falling linearly to 0.3 for the last."""
    return 1.0 if total <= 1 else 1.0 - (1.0 - DEFAULT_RELEVANCE) * position / (total - 1)


# ---------------------------------------------------------------------------------------- gathering
async def _cards(b: Briefer, query: str, eligible: dict[str, Persona]) -> tuple[dict[str, MemoryRecord], list[str]]:
    """Attendee cards of the eligible people (opt-in only) and the order the hybrid search ranked them in."""
    hits = await b.search(query, indices=[b.conference], kinds=["attendee"], size=50)
    cards: dict[str, MemoryRecord] = {}
    order: list[str] = []
    for r in hits:
        pid = r.owner_persona_id
        if pid in eligible and pid not in cards:
            cards[pid] = r
            order.append(pid)
    missing = [pid for pid in eligible if pid not in cards]  # a ranked search may skip non-matching cards
    fetched = await asyncio.gather(*(b.get(names.attendee_card_id(pid), indices=[b.conference]) for pid in missing))
    for pid, r in zip(missing, fetched, strict=True):
        if r is not None and r.kind == "attendee":
            cards[pid] = r
    return cards, order


async def _talks_by_person(b: Briefer, query: str) -> dict[str, list[MemoryRecord]]:
    talks = await b.search(query, indices=[b.conference], kinds=["talk"], size=50)
    out: dict[str, list[MemoryRecord]] = {}
    for t in talks:
        if t.talk is None:
            continue
        for pid in t.about_persona_ids:
            out.setdefault(pid, []).append(t)
    for lst in out.values():
        lst.sort(key=lambda t: as_utc(t.talk.starts_at))  # type: ignore[union-attr]
    return out


async def notes_about_org(b: Briefer, target: Persona) -> list[MemoryRecord]:
    """The viewer's OWN notes about this person or their company, the person's own notes first."""
    by_org, by_name = await asyncio.gather(
        b.search(
            f"{target.name} {b.org_name(target.org_id)}", indices=[b.internal], about_org_ids=[target.org_id], size=8
        ),
        b.search(f"{target.name} {target.title}", indices=[b.internal], kinds=list(_NOTE_KINDS), size=10),
    )
    merged: list[MemoryRecord] = []
    for r in [*by_org, *by_name]:
        about = target.persona_id in r.about_persona_ids or target.org_id in r.about_org_ids
        if about and r.kind in _NOTE_KINDS and all(m.memory_id != r.memory_id for m in merged):
            merged.append(r)
    merged.sort(key=lambda r: target.persona_id not in r.about_persona_ids)
    return merged


# ---------------------------------------------------------------------------------------- ranking
def _passes(f: DiscoverFilters, p: Persona, interests: list[str], card: MemoryRecord) -> bool:
    if f.interests:
        have = {i.lower() for i in [*interests, *card.tags]}
        if not have & {i.lower() for i in f.interests}:
            return False
    if f.roles and not any(role.lower() in p.title.lower() for role in f.roles):
        return False
    if f.org_ids and p.org_id not in f.org_ids:
        return False
    if f.has_agent is not None and names.agents_enabled(p.org_id) != f.has_agent:
        return False
    return not (f.language is not None and p.language != f.language)


def _entry(
    viewer: Persona,
    p: Persona,
    card: MemoryRecord | None,
    relevance: float,
    history: list[MemoryRecord],
    talks: list[MemoryRecord],
) -> Entry:
    info = card.profile if card is not None else None
    interests = (info.interests if info and info.interests else p.interests)[:8]
    shared = [i for i in viewer.interests if i in interests]
    overlap = min(1.0, len(shared) / max(1, len(viewer.interests)))
    score = match_score(overlap, relevance, bool(history))
    first_talk = min((as_utc(t.talk.starts_at) for t in talks if t.talk), default=_FAR_FUTURE)
    return Entry(
        target=p,
        card=card,
        interests=interests,
        looking_for=(info.goals if info and info.goals else p.goals)[:3],
        headline=(info.headline if info and info.headline else f"{p.title} at {p.org_id}")[:160],
        shared=shared,
        history=history,
        talks=talks,
        relevance=relevance,
        score=score,
        # score, then shared interests, then whose talk is soonest (most actionable), then relevance, then id
        sort_key=(-score, -len(shared), first_talk, -relevance, p.persona_id),
    )


async def rank(b: Briefer, viewer: Persona, filters: DiscoverFilters, exclude: list[str]) -> list[Entry]:
    eligible = {
        pid: p
        for pid, p in b.directory.items()
        if pid != viewer.persona_id and p.org_id != viewer.org_id and pid not in exclude
    }
    query = filters.looking_for or " ".join([*viewer.goals, *viewer.interests])
    (cards, order), talks = await asyncio.gather(_cards(b, query, eligible), _talks_by_person(b, query))

    kept = [
        pid
        for pid, card in cards.items()
        if _passes(filters, eligible[pid], _card_interests(card, eligible[pid]), card)
    ]
    ranked = [pid for pid in order if pid in kept] + [pid for pid in kept if pid not in order]

    rep = {eligible[pid].org_id: eligible[pid] for pid in ranked}  # one representative per company
    org_notes = dict(zip(rep, await asyncio.gather(*(notes_about_org(b, p) for p in rep.values())), strict=True))
    entries = []
    for i, pid in enumerate(ranked):
        p = eligible[pid]
        notes = [n for n in org_notes[p.org_id] if pid in n.about_persona_ids or p.org_id in n.about_org_ids]
        notes.sort(key=lambda n: pid not in n.about_persona_ids)
        entries.append(_entry(viewer, p, cards[pid], _relevance(i, len(ranked)), notes, talks.get(pid, [])))
    entries.sort(key=lambda e: e.sort_key)
    return entries


def _card_interests(card: MemoryRecord, p: Persona) -> list[str]:
    return (card.profile.interests if card.profile and card.profile.interests else p.interests)[:8]


# ---------------------------------------------------------------------------------------- why_meet
def template_why(lang: str, e: Entry) -> str:
    """ "You both care about X and Y; they're looking for Z." (and the Spanish equivalent)."""
    looking = e.looking_for[0] if e.looking_for else ""
    if lang == "es":
        parts = []
        if e.shared:
            parts.append(f"A ambos les interesan {join_list(e.shared[:3], lang)}")
        if looking:
            parts.append(f"{e.target.name} busca: {looking}")
        text = "; ".join(parts) + "." if parts else f"{e.target.name} podría ser un buen contacto."
    else:
        parts = []
        if e.shared:
            parts.append(f"You both care about {join_list(e.shared[:3], lang)}")
        if looking:
            parts.append(f"they're looking for {looking}" if parts else f"{e.target.name} is looking for {looking}")
        text = "; ".join(parts) + "." if parts else f"{e.target.name} could be a good contact."
    return fit(text, 240)


async def _write_why(b: Briefer, viewer: Persona, entries: list[Entry]) -> None:
    lang = viewer.language
    todo = []
    for e in entries:
        memo = b.memo.get((viewer.persona_id, e.target.persona_id))
        if memo is not None:
            e.why = memo.why_meet
        else:
            todo.append(e)
    if not todo:
        return
    out = await b.llm.parse(
        system=SYSTEM,
        user=data_block(
            "attendees",
            {
                "language": lang,
                "viewer": {"interests": viewer.interests, "goals": viewer.goals},
                "people": [
                    {
                        "persona_id": e.target.persona_id,
                        "name": e.target.name,
                        "title": e.target.title,
                        "company": b.org_name(e.target.org_id),
                        "headline": e.headline,
                        "looking_for": e.looking_for,
                        "shared_interests": e.shared,
                        "talks": [f"{t.title} ({when(t)})" for t in e.talks[:2]],
                        "viewer_company_history": [h.title for h in e.history[:2]],
                    }
                    for e in todo
                ],
            },
        ),
        schema=_WhyBatch,
    )
    written = {i.persona_id: i.why_meet.strip() for i in out.items} if out is not None else {}
    for e in todo:  # unknown persona_ids in the output are simply never looked up
        e.why = fit(written[e.target.persona_id], 240) if written.get(e.target.persona_id) else template_why(lang, e)
        b.memo[(viewer.persona_id, e.target.persona_id)] = CardMemo(why_meet=e.why, match_score=e.score)


def _talk_hits(e: Entry) -> list[TalkHit]:
    return [talk_hit(t, f"Speaking at {when(t)}") for t in e.talks[:2]]


def _card(b: Briefer, e: Entry) -> PersonCard:
    p = e.target
    return PersonCard(
        persona_id=p.persona_id,
        name=p.name,
        title=p.title,
        org_id=p.org_id,
        org_name=b.org_name(p.org_id),
        language=p.language,
        headline=e.headline,
        interests=e.interests,
        looking_for=e.looking_for,
        agent_available=names.agents_enabled(p.org_id),
        match_score=e.score,
        shared_interests=e.shared,
        why_meet=e.why,
        their_talks=_talk_hits(e),
        company_history=[cite(h) for h in e.history[:2]],
    )


async def research(b: Briefer, req: ResearchRequest) -> ResearchResult:
    viewer = b.own(req.persona_id)
    entries = (await rank(b, viewer, req.filters, req.exclude_persona_ids))[: req.limit]
    await _write_why(b, viewer, entries)
    for e in entries:  # remember the score the viewer saw; the deep dive's guardrail uses the same number
        memo = b.memo.get((viewer.persona_id, e.target.persona_id))
        if memo is not None:
            memo.match_score = e.score
    return ResearchResult(persona_id=viewer.persona_id, cards=[_card(b, e) for e in entries])


async def score_for(b: Briefer, viewer: Persona, target: Persona) -> int:
    """The match score the viewer saw for this person (cached), else the score from a default deck."""
    memo = b.memo.get((viewer.persona_id, target.persona_id))
    if memo is not None:
        return memo.match_score
    entries = await rank(b, viewer, DiscoverFilters(), [])
    entry = next((e for e in entries if e.target.persona_id == target.persona_id), None)
    if entry is not None:
        return entry.score
    history = await notes_about_org(b, target)  # not in the directory deck (own company, or no card)
    card = await b.get(names.attendee_card_id(target.persona_id), indices=[b.conference])
    talks = (await _talks_by_person(b, " ".join(target.interests))).get(target.persona_id, [])
    return _entry(viewer, target, card, DEFAULT_RELEVANCE, history, talks).score
