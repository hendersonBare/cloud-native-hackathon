"""POST /v1/deep-dive: one LLM call recommends a conversation plan and a decision; deterministic guardrails decide.

Guardrails run AFTER the LLM and every outcome is recorded in `decision.checks` (docs/FEATURE-DISCOVER.md):
the target's company runs agents (else human_intro), match_score >= 40 (else skip), no `do-not-contact` note
(else skip), confidence >= 0.5 (else human_intro). Severity only ever goes up: handshake < human_intro < skip.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel

from rapport_common import names
from rapport_memory.profiles import card_id
from rapport_common.models import (
    AgentDecision,
    Citation,
    ConversationPlan,
    DeepDive,
    DeepDiveRequest,
    MemoryRecord,
    Persona,
)

from .core import Briefer, cite, fit, join_list, when
from .llm import data_block
from .research import _talks_by_person, notes_about_org, score_for

MIN_MATCH_SCORE = 40
MIN_CONFIDENCE = 0.5
FALLBACK_CONFIDENCE = 0.7
_SEVERITY = {"agent_handshake": 0, "human_intro": 1, "skip": 2}

SYSTEM = (
    "Prepare a conversation between the viewer and the target person using only the data block. Return: a short "
    "summary (at most 350 characters), up to 3 goals for the viewer, up to 3 questions to ask, up to 2 watch-outs, "
    "a one-sentence opener, and a recommended action: agent_handshake (the viewer's agent starts a connection with "
    "the target's agent), human_intro (the people should meet in person) or skip, with a reason of at most 200 "
    "characters and a confidence between 0 and 1. In cited_ids list the ids of the sources you used. Reply in the "
    "language named in the data."
)


class _DiveOut(BaseModel):
    summary: str
    goals: list[str]
    questions: list[str]
    watch_outs: list[str]
    opener: str
    action: Literal["agent_handshake", "human_intro", "skip"]
    reason: str
    confidence: float
    cited_ids: list[str]


async def deep_dive(b: Briefer, req: DeepDiveRequest) -> DeepDive:
    viewer = b.own(req.persona_id)
    target = b.known(req.target_persona_id)
    if target.persona_id == viewer.persona_id:
        raise HTTPException(status_code=422, detail="cannot deep dive on yourself")
    lang = viewer.language

    card, notes, talks_map, offers, goals, past, score, blocked = await asyncio.gather(
        b.get(names.attendee_card_id(target.persona_id), indices=[b.conference]),
        notes_about_org(b, target),
        _talks_by_person(b, " ".join(target.interests)),
        _offers(b, target),
        _viewer_goals(b, viewer),
        _past_outcomes(b, target),
        score_for(b, viewer, target),
        _do_not_contact(b, target),  # its own tag-filtered query: never limited by the notes shown in the prompt
    )
    notes = notes[:5]
    talks = talks_map.get(target.persona_id, [])
    info = card.profile if card is not None else None
    t_interests = info.interests if info and info.interests else target.interests
    t_goals = info.goals if info and info.goals else target.goals
    t_headline = info.headline if info else f"{target.title} at {b.org_name(target.org_id)}"
    shared = [i for i in viewer.interests if i in t_interests]

    sources: dict[str, MemoryRecord] = {r.memory_id: r for r in [*notes, *offers, *past, *talks]}
    out = await b.llm.parse(
        system=SYSTEM,
        user=data_block(
            "deep-dive",
            {
                "language": lang,
                "viewer": {"name": viewer.name, "title": viewer.title, "interests": viewer.interests, "goals": goals},
                "target": {  # attendee-written text: untrusted data
                    "name": target.name,
                    "title": target.title,
                    "company": b.org_name(target.org_id),
                    "headline": t_headline,
                    "interests": t_interests,
                    "looking_for": t_goals,
                    "runs_agents": names.agents_enabled(target.org_id),
                },
                "match_score": score,
                "shared_interests": shared,
                "sources": [
                    {"id": r.memory_id, "kind": r.kind, "title": r.title, "text": fit(r.text or r.summary, 500)}
                    for r in sources.values()
                ],
            },
        ),
        schema=_DiveOut,
    )

    if out is not None and out.summary.strip() and out.opener.strip():
        summary = fit(out.summary, 400)
        plan = ConversationPlan(
            goals=[fit(g, 200) for g in out.goals if g.strip()][:3],
            offers=[fit(o.title, 200) for o in offers][:3],
            questions=[fit(q, 200) for q in out.questions if q.strip()][:3],
            watch_outs=[fit(w, 200) for w in out.watch_outs if w.strip()][:2],
            opener=fit(out.opener, 200),
        )
        cited = [sources[i] for i in dict.fromkeys(out.cited_ids) if i in sources]  # unknown ids dropped
        action, reason, confidence = out.action, fit(out.reason, 240), min(1.0, max(0.0, out.confidence))
    else:
        summary = _summary(lang, target, b.org_name(target.org_id), shared, t_goals)
        plan = _plan(lang, target, goals, offers, notes, t_goals, shared, talks)
        cited = []
        action, reason = _fallback_action(b, lang, target, score)
        confidence = FALLBACK_CONFIDENCE
    if not cited:
        cited = [*notes[:2], *offers[:2], *past[:1]]
    intro = _human_intro_reason(lang, target, talks, shared)

    action, reason, checks = _guardrails(lang, action, reason, confidence, score, target, blocked, intro)
    return DeepDive(
        persona_id=viewer.persona_id,
        target_persona_id=target.persona_id,
        language=lang,
        summary=summary,
        plan=plan,
        decision=AgentDecision(action=action, reason=fit(reason, 240), confidence=round(confidence, 2), checks=checks),
        citations=_dedupe([cite(r) for r in cited])[:5],
    )


# ----------------------------------------------------------------------------------------- gathering
async def _offers(b: Briefer, target: Persona) -> list[MemoryRecord]:
    """The viewer's own shareable items that match the target's interests (up to 5)."""
    if not target.interests:
        return []
    hits = await b.search(
        " ".join(target.interests), indices=[b.shareable], kinds=["document"], tags=target.interests, size=5
    )
    return hits[:5]


async def _viewer_goals(b: Briefer, viewer: Persona) -> list[str]:
    card = await b.get(card_id(viewer.persona_id, "private"), indices=[b.internal])
    return card.profile.goals if card and card.profile and card.profile.goals else viewer.goals


async def _past_outcomes(b: Briefer, target: Persona) -> list[MemoryRecord]:
    return await b.search(
        f"{target.name} {b.org_name(target.org_id)}",
        indices=[b.internal],
        kinds=["encounter_summary", "followup"],
        about_org_ids=[target.org_id],
        size=5,
    )


async def _do_not_contact(b: Briefer, target: Persona) -> bool:
    """True if the viewer's company has a `do-not-contact` note about this person, or about their whole company
    (a company-level note names no individuals)."""
    notes = await b.search(f"{target.name} do not contact", indices=[b.internal], tags=["do-not-contact"], size=50)
    return any(
        target.persona_id in n.about_persona_ids or (target.org_id in n.about_org_ids and not n.about_persona_ids)
        for n in notes
    )


def _dedupe(cites: list[Citation]) -> list[Citation]:
    seen: dict[str, Citation] = {}
    for c in cites:
        seen.setdefault(c.memory_id, c)
    return list(seen.values())


# ----------------------------------------------------------------------------------------- fallbacks
def _fallback_action(b: Briefer, lang: str, target: Persona, score: int) -> tuple[str, str]:
    """No LLM: handshake when the target's company runs agents and the match is good, else a human intro."""
    if names.agents_enabled(target.org_id) and score >= MIN_MATCH_SCORE:
        org = b.org_name(target.org_id)
        if lang == "es":
            return "agent_handshake", f"{org} usa agentes y la coincidencia es {score}/100."
        return "agent_handshake", f"{org} runs agents and the match is {score}/100."
    return "human_intro", ""


def _human_intro_reason(lang: str, target: Persona, talks: list[MemoryRecord], shared: list[str]) -> str:
    """A concrete suggestion: after their talk if they have one, else a topic to open with."""
    if talks:
        t = talks[0]
        assert t.talk is not None
        at = when(t)
        if lang == "es":
            return f"Habla con {target.name} después de su charla de las {at}."
        return f"Catch {target.name} after their {at.split(',')[0]} talk in {t.talk.room}."
    topic = shared[0] if shared else (target.interests[0] if target.interests else "the conference")
    if lang == "es":
        return f"Preséntate a {target.name} en una sesión sobre {topic}."
    return f"Introduce yourself to {target.name} at a session on {topic}; they have no agent to hand off to."


def _summary(lang: str, target: Persona, org: str, shared: list[str], goals: list[str]) -> str:
    if lang == "es":
        text = f"{target.name} ({target.title}, {org})"
        text += f" comparte tu interés en {join_list(shared, lang)}." if shared else "."
        if goals:
            text += f" Busca: {goals[0]}."
    else:
        text = f"{target.name} ({target.title}, {org})"
        text += f" shares your interest in {join_list(shared, lang)}." if shared else "."
        if goals:
            text += f" Looking for: {goals[0]}."
    return fit(text, 400)


def _plan(
    lang: str,
    target: Persona,
    goals: list[str],
    offers: list[MemoryRecord],
    notes: list[MemoryRecord],
    t_goals: list[str],
    shared: list[str],
    talks: list[MemoryRecord],
) -> ConversationPlan:
    es = lang == "es"
    questions = [(f"¿Cómo abordan: {g}?" if es else f"How are you approaching: {g}?") for g in t_goals[:2]]
    if shared:
        questions.append(
            f"¿Qué han probado con {shared[0]}?" if es else f"What have you tried with {shared[0]} so far?"
        )
    opener = (
        f"Hola {target.name}, vi que te interesa {shared[0]}."
        if es and shared
        else f"Hi {target.name}, I saw you care about {shared[0]}; what are you working on?"
        if shared
        else (f"Hola {target.name}, ¿en qué trabajas?" if es else f"Hi {target.name}, what are you working on?")
    )
    return ConversationPlan(
        goals=[fit(g, 200) for g in goals[:3]],
        offers=[fit(o.title, 200) for o in offers[:3]],
        questions=[fit(q, 200) for q in questions[:3]],
        watch_outs=[fit(f"{n.title}: {n.summary or n.text}", 200) for n in notes[:2]],
        opener=fit(opener, 200),
    )


# ----------------------------------------------------------------------------------------- guardrails
def _guardrails(
    lang: str,
    action: str,
    reason: str,
    confidence: float,
    score: int,
    target: Persona,
    blocked: bool,
    intro_reason: str,
) -> tuple[str, str, list[str]]:
    original = action
    checks: list[str] = []
    runs_agents = names.agents_enabled(target.org_id)
    checks.append(f"target_company_runs_agents: {'pass' if runs_agents else 'fail -> human_intro'}")
    if not runs_agents:
        action = _worse(action, "human_intro")
    checks.append(f"match_score>={MIN_MATCH_SCORE}: {'pass' if score >= MIN_MATCH_SCORE else 'fail -> skip'} ({score})")
    if score < MIN_MATCH_SCORE:
        action = _worse(action, "skip")
    checks.append(f"no_do_not_contact_note: {'fail -> skip' if blocked else 'pass'}")
    if blocked:
        action = _worse(action, "skip")
    checks.append(
        f"confidence>={MIN_CONFIDENCE}: {'pass' if confidence >= MIN_CONFIDENCE else 'fail -> human_intro'} "
        f"({confidence:.2f})"
    )
    if confidence < MIN_CONFIDENCE:
        action = _worse(action, "human_intro")

    if action != original:  # the model's reason no longer matches the decision
        if action == "human_intro":
            reason = intro_reason
        else:
            why = "do-not-contact note" if blocked else f"low match score ({score})"
            reason = f"Skipping: {why}." if lang == "en" else f"Se omite: {why}."
    elif action == "human_intro" and not reason.strip():
        reason = intro_reason
    return action, reason or intro_reason, checks


def _worse(current: str, required: str) -> str:
    return required if _SEVERITY[required] > _SEVERITY[current] else current
