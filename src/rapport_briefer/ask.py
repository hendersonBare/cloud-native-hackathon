"""POST /v1/ask: RAG over the company's internal + shareable memory and the conference agenda, with citations."""

from __future__ import annotations

import re

from pydantic import BaseModel

from rapport_common.models import AskAnswer, AskRequest, Citation, MemoryKind, MemoryRecord

from .core import Briefer, cite, fit
from .llm import data_block

MAX_CITATIONS = 5
# attendee cards are the public directory and profile records are per-person: neither answers a memory question
ASK_KINDS: list[MemoryKind] = ["talk", "note", "document", "account_note", "encounter_summary", "followup"]
_KIND_PRIORITY = {"account_note": 0, "encounter_summary": 1, "followup": 2}

SYSTEM = (
    "You are a private assistant for one conference attendee. Answer the question using only the numbered "
    "sources in the data block. Be brief (at most 4 sentences) and reply in the language named in the data. "
    "List in cited_ids the ids of the sources you used; use only ids that appear in the data."
)


class _AskOut(BaseModel):
    answer: str
    cited_ids: list[str]


def mentioned(b: Briefer, question: str) -> tuple[list[str], list[str]]:
    """Org ids and persona ids of OTHER companies named in the question (matched against the directory)."""
    q = question.lower()
    orgs: list[str] = []
    people: list[str] = []
    for org_id, org in b.orgs.items():
        if org_id == b.org_id:
            continue
        if re.search(rf"\b{re.escape(org_id)}\b", q) or org.name.lower() in q:
            orgs.append(org_id)
    for pid, person in b.directory.items():
        if person.org_id == b.org_id:
            continue
        if re.search(rf"\b{re.escape(person.name.lower())}\b", q):
            people.append(pid)
            if person.org_id not in orgs:
                orgs.append(person.org_id)
    return orgs, people


async def answer(b: Briefer, req: AskRequest) -> AskAnswer:
    persona = b.own(req.persona_id)
    orgs, _people = mentioned(b, req.question)

    general = await b.search(
        req.question, indices=[b.internal, b.shareable, b.conference], kinds=ASK_KINDS, size=MAX_CITATIONS
    )
    about: list[MemoryRecord] = []
    if orgs:
        about = await b.search(
            req.question, indices=[b.internal, b.shareable], kinds=ASK_KINDS, about_org_ids=orgs, size=8
        )
        about.sort(key=lambda r: _KIND_PRIORITY.get(r.kind, 3))  # stable: notes, then encounter outcomes

    hits: list[MemoryRecord] = []
    for record in [*about, *general]:
        if all(h.memory_id != record.memory_id for h in hits):
            hits.append(record)
    hits = hits[:MAX_CITATIONS]
    if not hits:
        return AskAnswer(answer=_nothing(persona.language), citations=[])

    by_id = {r.memory_id: r for r in hits}
    out = await b.llm.parse(
        system=SYSTEM,
        user=data_block(
            "ask",
            {
                "language": persona.language,
                "question": req.question,
                "sources": [
                    {"id": r.memory_id, "title": r.title, "kind": r.kind, "text": fit(r.text or r.summary, 700)}
                    for r in hits
                ],
            },
        ),
        schema=_AskOut,
    )
    if out is not None and out.answer.strip():
        cited = [by_id[i] for i in dict.fromkeys(out.cited_ids) if i in by_id]  # unknown ids are dropped
        return AskAnswer(answer=out.answer.strip(), citations=[cite(r) for r in (cited or hits)])
    return AskAnswer(answer=_template(persona.language, hits), citations=[cite(r) for r in hits])


def _nothing(lang: str) -> str:
    if lang == "es":
        return "No encontré nada sobre eso en tu memoria."
    return "I couldn't find anything about that in your memory."


def _template(lang: str, hits: list[MemoryRecord]) -> str:
    """The no-LLM answer: the top hits, in order, each as 'title: summary'."""
    lead = "Esto es lo que encontré en tu memoria:" if lang == "es" else "Here is what I found in your memory:"
    lines = [f"{i}. {r.title}: {fit(r.summary or r.text, 200)}" for i, r in enumerate(hits[:3], 1)]
    return "\n".join([lead, *lines])


def citations_of(records: list[MemoryRecord]) -> list[Citation]:
    return [cite(r) for r in records]
