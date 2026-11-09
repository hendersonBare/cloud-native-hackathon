"""GET /v1/talks: hybrid search on the conference agenda, boosted by the person's interests."""

from __future__ import annotations

import re

from rapport_common.models import MemoryRecord, TalkHit, TalkSearchResult

from .core import Briefer, fit, join_list, talk_hit, when

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _doc_words(r: MemoryRecord) -> set[str]:
    return _words(f"{r.title} {r.summary} {r.text} {' '.join(r.tags)}")


async def search_talks(b: Briefer, persona_id: str, q: str, *, limit: int = 10) -> TalkSearchResult:
    persona = b.own(persona_id)
    interests = set(persona.interests)
    query = q.strip()
    hits = await b.search(query or " ".join(persona.interests), indices=[b.conference], kinds=["talk"], size=30)
    qwords = _words(query)

    scored = []
    for rank, record in enumerate(hits):
        lexical = bool(qwords & _doc_words(record))
        overlap = len(interests & set(record.tags))
        # query match first, then the person's interests (the boost that breaks ties), then the store's own order
        scored.append(((1 if lexical else 0) if qwords else 0, overlap, -rank, record))
    scored.sort(key=lambda t: t[:3], reverse=True)

    talks: list[TalkHit] = []
    for _lex, overlap, _rank, record in scored[:limit]:
        talks.append(talk_hit(record, _reason(persona.language, query, sorted(interests & set(record.tags)), record)))
    return TalkSearchResult(query=q, talks=talks)


def _reason(lang: str, query: str, shared: list[str], record: MemoryRecord) -> str:
    where = when(record)
    if shared:
        topics = join_list(shared, lang)
        text = (
            f"Matches your interest in {topics} ({where})"
            if lang == "en"
            else f"Coincide con tu interés en {topics} ({where})"
        )
    elif query:
        text = f"Matches your search ({where})" if lang == "en" else f"Coincide con tu búsqueda ({where})"
    else:
        text = f"On the agenda ({where})" if lang == "en" else f"En la agenda ({where})"
    return fit(text, 160)
