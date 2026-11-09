"""Shared state and helpers for one briefer: the company it serves, its store, its LLM and persona checks.

The briefer reads only its own company's two indices plus the conference index. `Briefer.search` refuses any
other index, so a bug elsewhere cannot read another company's memory.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException

from rapport_common import names
from rapport_common.interfaces import MemoryStore
from rapport_common.models import Citation, MemoryRecord, Persona, TalkHit

from .llm import LLM
from .timefmt import as_utc, denver_label

log = logging.getLogger("rapport.briefer")


@dataclass
class CardMemo:
    """What research remembers per (viewer, target): the written reason and the score the viewer saw."""

    why_meet: str
    match_score: int


@dataclass
class Briefer:
    org_id: str
    store: MemoryStore
    llm: LLM
    directory: dict[str, Persona] = field(default_factory=names.personas)
    orgs: dict = field(default_factory=names.orgs)
    memo: dict[tuple[str, str], CardMemo] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.shareable = names.shareable_index(self.org_id)
        self.internal = names.internal_index(self.org_id)
        self.conference = names.CONFERENCE_INDEX
        self.allowed = {self.shareable, self.internal, self.conference}

    # ------------------------------------------------------------------ personas
    def known(self, persona_id: str) -> Persona:
        persona = self.directory.get(persona_id)
        if persona is None:
            raise HTTPException(status_code=404, detail="unknown persona")
        return persona

    def own(self, persona_id: str) -> Persona:
        """404 for an unknown persona, 403 for a persona of another company."""
        persona = self.known(persona_id)
        if persona.org_id != self.org_id:
            raise HTTPException(status_code=403, detail="persona belongs to another company")
        return persona

    def org_name(self, org_id: str) -> str:
        org = self.orgs.get(org_id)
        return org.name if org else org_id

    # ------------------------------------------------------------------ store (sync interface -> threads)
    async def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("memory store call failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=503, detail="memory store unavailable") from exc

    async def search(self, query: str, *, indices: list[str], **kwargs: Any) -> list[MemoryRecord]:
        if not set(indices) <= self.allowed:
            raise RuntimeError("briefer may only read its own indices and the conference index")
        return await self._call(self.store.search, query, indices=indices, **kwargs)

    async def get(self, memory_id: str, *, indices: list[str]) -> MemoryRecord | None:
        if not set(indices) <= self.allowed:
            raise RuntimeError("briefer may only read its own indices and the conference index")
        return await self._call(self.store.get, memory_id, indices=indices)

    async def write(self, records: list[MemoryRecord]) -> int:
        return await self._call(self.store.write, records)


# ---------------------------------------------------------------------- small shared helpers
def snippet(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def cite(record: MemoryRecord) -> Citation:
    return Citation(
        memory_id=record.memory_id,
        title=record.title[:200],
        kind=record.kind,
        snippet=snippet(record.summary or record.text),
    )


def talk_hit(record: MemoryRecord, reason: str | None = None) -> TalkHit:
    talk = record.talk
    assert talk is not None
    return TalkHit(
        talk_id=record.memory_id,
        title=record.title[:200],
        starts_at=as_utc(talk.starts_at),
        room=talk.room,
        track=talk.track,
        speakers=talk.speakers,
        reason=reason[:160] if reason else None,
    )


def when(record: MemoryRecord) -> str:
    """ "3:30 PM MST, Room B" for a talk record."""
    assert record.talk is not None
    return f"{denver_label(record.talk.starts_at)}, {record.talk.room}"


def join_list(items: list[str], lang: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    word = "y" if lang == "es" else "and"
    return f"{', '.join(items[:-1])} {word} {items[-1]}"


def fit(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
