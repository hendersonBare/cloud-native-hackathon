"""POST /v1/brief: the private brief for one person about the person they are about to meet.

The structure is assembled deterministically from the counterparty's DIRECTORY entry, the viewer's own notes,
own shareable documents, the viewer's private goals and the conference agenda. The LLM only polishes wording and
translates; if it is missing, slow or wrong, the templates below are the answer. Nothing here reads another
company's indices.
"""

from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel

from rapport_common.models import BriefRequest, MemoryRecord, Persona, PrivateBrief, TalkHit
from rapport_common.telemetry import ATTR_ENCOUNTER, ATTR_ORG, ATTR_PERSONA, ATTR_RESULT_COUNT, tracer
from rapport_memory.profiles import card_id

from .core import Briefer, cite, fit, join_list, talk_hit, when
from .llm import data_block

log = logging.getLogger("rapport.briefer.brief")

SPAN_BRIEF = "brief.generate"
SLO_BUDGET_S = 4.5  # the SLO is 5 s from accept; the LLM may only use what is left of this
LLM_CAP_S = 3.5

# goal words that should match directory words even when the spelling differs
_SYNONYMS = {
    "healthcare": {"hospital", "health", "clinical", "medical", "hipaa"},
    "security": {"hipaa", "compliance", "zero-trust"},
    "cost": {"finops", "spend", "bill"},
}

SYSTEM = (
    "Polish a networking brief for one conference attendee. Rewrite each string in the language named in the "
    "data so it reads naturally, keeping every fact, name and number exactly. Do not add facts. Return the same "
    "number of items in each list, in the same order."
)


class _Polish(BaseModel):
    headline: str
    talking_points: list[str]
    watch_outs: list[str]
    goal_matches: list[str]
    conversation_starters: list[str]


async def make_brief(b: Briefer, req: BriefRequest) -> PrivateBrief:
    started = time.monotonic()
    persona = b.own(req.persona_id)
    cp = b.known(req.counterparty_persona_id)
    with tracer("rapport.briefer").start_as_current_span(SPAN_BRIEF) as span:
        span.set_attribute(ATTR_ENCOUNTER, req.encounter_id)
        span.set_attribute(ATTR_PERSONA, persona.persona_id)
        span.set_attribute(ATTR_ORG, b.org_id)
        brief = await _assemble(b, req, persona, cp, started)
        span.set_attribute(ATTR_RESULT_COUNT, len(brief.history) + len(brief.suggested_talks))
        return brief


async def _assemble(b: Briefer, req: BriefRequest, persona: Persona, cp: Persona, started: float) -> PrivateBrief:
    lang = persona.language
    shared = [i for i in persona.interests if i in cp.interests]
    notes, docs, talks, goals = await asyncio.gather(
        _notes_about(b, cp),
        b.search(" ".join(cp.interests), indices=[b.shareable], kinds=["document"], tags=cp.interests, size=3)
        if cp.interests
        else _none(),
        _suggested_talks(b, shared, persona.interests, lang),
        _private_goals(b, persona),
    )
    goal_matches = _goal_matches(goals, cp, b.org_name(cp.org_id), lang)

    draft = PrivateBrief(
        encounter_id=req.encounter_id,
        persona_id=persona.persona_id,
        counterparty_persona_id=cp.persona_id,
        language=lang,
        headline=_headline(cp, b.org_name(cp.org_id), shared, lang),
        talking_points=_talking_points(cp, docs, shared, lang),
        watch_outs=[fit(f"{n.title}: {n.summary or n.text}", 200) for n in notes[:2]],
        goal_matches=goal_matches,
        conversation_starters=_starters(cp, talks, lang, b),
        history=[cite(n) for n in notes[:3]],
        suggested_talks=talks,
    )
    return await _polish(b, draft, started)


async def _none() -> list[MemoryRecord]:
    return []


async def _notes_about(b: Briefer, cp: Persona) -> list[MemoryRecord]:
    """Own-company notes about the person (first) or their company: account notes and past encounter outcomes."""
    by_org, by_name = await asyncio.gather(
        b.search(f"{cp.name} {b.org_name(cp.org_id)}", indices=[b.internal], about_org_ids=[cp.org_id], size=6),
        b.search(f"{cp.name} {cp.title}", indices=[b.internal], size=10),
    )
    direct = [r for r in by_name if cp.persona_id in r.about_persona_ids]
    merged: list[MemoryRecord] = []
    for r in [*direct, *by_org]:
        if r.kind != "profile" and all(m.memory_id != r.memory_id for m in merged):
            merged.append(r)
    # the person first, then the account note over follow-ups
    order = {"account_note": 0, "note": 1, "encounter_summary": 2, "followup": 3}
    merged.sort(key=lambda r: (cp.persona_id not in r.about_persona_ids, order.get(r.kind, 4)))
    return merged


async def _private_goals(b: Briefer, persona: Persona) -> list[str]:
    card = await b.get(card_id(persona.persona_id, "private"), indices=[b.internal])
    if card is not None and card.profile is not None and card.profile.goals:
        return card.profile.goals
    return persona.goals


async def _suggested_talks(b: Briefer, shared: list[str], mine: list[str], lang: str) -> list[TalkHit]:
    if not shared:
        return []
    records = await b.search(" ".join(shared), indices=[b.conference], kinds=["talk"], tags=shared, size=8)
    records = [r for r in records if r.talk is not None]
    # shared topics first, then the rest of MY interests (it is my brief), then the earliest start
    records.sort(
        key=lambda r: (-len(set(shared) & set(r.tags)), -len(set(mine) & set(r.tags)), r.talk.starts_at)  # type: ignore[union-attr]
    )
    out = []
    for r in records[:2]:
        topics = join_list(sorted(set(shared) & set(r.tags)), lang)
        reason = (
            f"Both of you follow {topics} ({when(r)})" if lang == "en" else f"A ambos les interesa {topics} ({when(r)})"
        )
        out.append(talk_hit(r, reason))
    return out


def _expand(words: set[str]) -> set[str]:
    out = set(words)
    for w in words:
        out |= _SYNONYMS.get(w, set())
    return out


_STOPWORDS = {
    "find", "meet", "the", "and", "for", "with", "that", "this", "from", "into", "partner", "design", "team",
    "teams", "new", "get", "have", "need", "needs", "want", "wants", "make", "help", "cut", "lower", "close",
    "quarter", "this", "all", "are", "our", "your", "their", "who",
}  # fmt: skip


def _tokens(text: str) -> set[str]:
    words = "".join(c if c.isalnum() or c == "-" else " " for c in text.lower()).split()
    return {t for t in words if len(t) > 2 and t not in _STOPWORDS}


def _goal_matches(goals: list[str], cp: Persona, org_name: str, lang: str) -> list[str]:
    """Which of MY private goals this person could help with, judged against their directory entry."""
    theirs = _expand(_tokens(" ".join([*cp.interests, *cp.goals, cp.title, org_name])) | {i for i in cp.interests})
    out = []
    for goal in goals:
        overlap = _expand(_tokens(goal)) & theirs
        if overlap:
            why = join_list(sorted(overlap)[:2], lang)
            line = f"{goal}: {cp.name} fits ({why})" if lang == "en" else f"{goal}: {cp.name} encaja ({why})"
            out.append(fit(line, 200))
    return out[:2]


def _headline(cp: Persona, org_name: str, shared: list[str], lang: str) -> str:
    base = f"{cp.name}, {cp.title} at {org_name}" if lang == "en" else f"{cp.name}, {cp.title} en {org_name}"
    if shared:
        topics = join_list(shared[:3], lang)
        base += f". Shared interests: {topics}" if lang == "en" else f". Intereses en común: {topics}"
    return fit(base, 200)


def _talking_points(cp: Persona, docs: list[MemoryRecord], shared: list[str], lang: str) -> list[str]:
    en = lang == "en"
    points: list[str] = []
    if cp.goals:
        points.append(f"{cp.name} wants to: {cp.goals[0]}" if en else f"{cp.name} quiere: {cp.goals[0]}")
    if docs:
        d = docs[0]
        points.append(
            f'You can offer "{d.title}": {fit(d.summary, 120)}'
            if en
            else f'Puedes ofrecer "{d.title}": {fit(d.summary, 120)}'
        )
    if shared:
        topics = join_list(shared, lang)
        points.append(f"Common ground: {topics}" if en else f"Terreno común: {topics}")
    if len(docs) > 1:
        points.append(f'Also relevant: "{docs[1].title}"' if en else f'También relevante: "{docs[1].title}"')
    return [fit(p, 240) for p in points[:3]]


def _starters(cp: Persona, talks: list[TalkHit], lang: str, b: Briefer) -> list[str]:
    en = lang == "en"
    out = []
    if cp.goals:
        out.append(f"Ask how they are approaching: {cp.goals[0]}" if en else f"Pregunta cómo abordan: {cp.goals[0]}")
    if talks:
        t = talks[0]
        out.append(f'Suggest going to "{t.title}" together' if en else f'Propón asistir juntos a "{t.title}"')
    return [fit(s, 240) for s in out[:2]]


async def _polish(b: Briefer, draft: PrivateBrief, started: float) -> PrivateBrief:
    remaining = min(LLM_CAP_S, SLO_BUDGET_S - (time.monotonic() - started))
    if remaining < 1.0:
        return draft
    payload = {
        "language": draft.language,
        "headline": draft.headline,
        "talking_points": draft.talking_points,
        "watch_outs": draft.watch_outs,
        "goal_matches": draft.goal_matches,
        "conversation_starters": draft.conversation_starters,
    }
    out = await b.llm.parse(system=SYSTEM, user=data_block("brief-draft", payload), schema=_Polish, timeout=remaining)
    if out is None:
        return draft
    updates: dict = {}
    if out.headline.strip():
        updates["headline"] = fit(out.headline, 200)
    for name, limit in (
        ("talking_points", 240),
        ("watch_outs", 240),
        ("goal_matches", 200),
        ("conversation_starters", 240),
    ):
        new = getattr(out, name)
        old = getattr(draft, name)
        if len(new) == len(old) and all(s.strip() for s in new):  # same shape or keep the deterministic text
            updates[name] = [fit(s, limit) for s in new]
    return draft.model_copy(update=updates)
