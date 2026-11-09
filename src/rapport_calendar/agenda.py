"""Where the conference agenda comes from.

``SeedTalkSource`` serves the seed agenda. ``BrieferTalkSource`` asks the persona's company briefer for talk
recommendations (``GET {briefer}/v1/talks``) and falls back to the seed on any failure, so the calendar never
breaks because an agent is down. Only IDs and error class names are logged.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timezone
from typing import Literal, Protocol

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from rapport_common.models import TalkHit, TalkSearchResult
from rapport_common.names import agents_enabled, briefer_url, org_of

log = logging.getLogger("rapport.calendar.agenda")

BRIEFER_TIMEOUT_SECONDS = 3.0
MAX_AGENDA_ITEMS = 20
_CACHE_LIMIT = 500
_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class AgendaResult:
    source: Literal["briefer", "seed"]
    talks: list[TalkHit]


class TalkSource(Protocol):
    async def search(self, persona_id: str, query: str) -> AgendaResult:
        """Talks for this person matching ``query`` (empty = all), sorted by start time, at most 20."""
        ...

    def lookup(self, talk_id: str) -> TalkHit | None:
        """A talk this source has served or holds, by id; ``None`` when unknown."""
        ...


def matches(talk: TalkHit, query: str) -> bool:
    """Case-insensitive word match: every query word must start a word of the title, track, room or speakers."""
    terms = _WORD.findall(query.lower())
    if not terms:
        return True
    words = _WORD.findall(" ".join([talk.title, talk.track, talk.room, *talk.speakers]).lower())
    return all(any(word.startswith(term) for word in words) for term in terms)


class SeedTalkSource:
    """The seed agenda, filtered locally."""

    def __init__(self, talks: Sequence[TalkHit]) -> None:
        self._talks = {t.talk_id: t for t in talks}

    async def search(self, persona_id: str, query: str) -> AgendaResult:
        hits = sorted((t for t in self._talks.values() if matches(t, query)), key=lambda t: (t.starts_at, t.title))
        return AgendaResult("seed", hits[:MAX_AGENDA_ITEMS])

    def lookup(self, talk_id: str) -> TalkHit | None:
        return self._talks.get(talk_id)


class BrieferTalkSource:
    """Briefer recommendations for companies that run agents; the seed for everyone else and on any error."""

    def __init__(self, fallback: SeedTalkSource, *, timeout: float = BRIEFER_TIMEOUT_SECONDS) -> None:
        self._fallback = fallback
        self._timeout = timeout
        self._cache: dict[str, TalkHit] = {}

    async def search(self, persona_id: str, query: str) -> AgendaResult:
        if os.environ.get("RAPPORT_CALENDAR_AGENDA") == "seed":
            return await self._fallback.search(persona_id, query)
        try:
            org_id = org_of(persona_id)
            if not agents_enabled(org_id):
                return await self._fallback.search(persona_id, query)
            talks = await self._ask_briefer(org_id, persona_id, query)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("briefer unavailable persona=%s error=%s", persona_id, type(exc).__name__)
            return await self._fallback.search(persona_id, query)
        for talk in talks:
            self._remember(talk)
        talks.sort(key=lambda t: (t.starts_at, t.title))
        return AgendaResult("briefer", talks[:MAX_AGENDA_ITEMS])

    def lookup(self, talk_id: str) -> TalkHit | None:
        return self._fallback.lookup(talk_id) or self._cache.get(talk_id)

    async def _ask_briefer(self, org_id: str, persona_id: str, query: str) -> list[TalkHit]:
        # The httpx client span would carry the full URL, query included; calendar.agenda already covers this call.
        with suppress_http_instrumentation():
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{briefer_url(org_id)}/v1/talks", params={"persona_id": persona_id, "q": query}
                )
        response.raise_for_status()
        result = TalkSearchResult.model_validate(response.json())  # untrusted: parse into the contract
        talks: list[TalkHit] = []
        for talk in result.talks:
            if talk.starts_at.tzinfo is None:
                raise ValueError("talk without a timezone")
            talks.append(talk.model_copy(update={"starts_at": talk.starts_at.astimezone(timezone.utc)}))
        return talks

    def _remember(self, talk: TalkHit) -> None:
        self._cache.pop(talk.talk_id, None)
        self._cache[talk.talk_id] = talk
        while len(self._cache) > _CACHE_LIMIT:
            del self._cache[next(iter(self._cache))]
