"""Memory access for a delegate: shareable memory of its own company plus the conference agenda. Nothing else.

The two indices are hard-wired here. No method takes an index (or anything that selects one) as input.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from rapport_common import names
from rapport_common.interfaces import InMemoryStore, MemoryStore
from rapport_common.models import TAG, MemoryRecord

log = logging.getLogger("rapport.delegate.memory")

_TAG = re.compile(TAG)
_OFFERABLE_KINDS = ["document", "note"]


def open_store(self_org: str) -> MemoryStore:
    """The delegate's store. rapport_memory lands in a separate PR, so import it here, not at module top."""
    indices = [names.shareable_index(self_org), names.CONFERENCE_INDEX]
    try:
        from rapport_memory import store_from_env  # type: ignore[import-not-found]

        return store_from_env(indices)
    except Exception as exc:  # ImportError until the memory PR merges; a misconfigured client must not kill the demo
        log.warning("rapport_memory unavailable (%s); using an empty in-memory store", type(exc).__name__)
        return InMemoryStore()


class SelfMemory:
    """What this delegate can see: `rapport-<org>-shareable` and `rapport-conference`."""

    def __init__(self, store: MemoryStore, self_org: str) -> None:
        self._store = store
        self._self_org = self_org
        self._shareable = [names.shareable_index(self_org)]
        self._all = [names.shareable_index(self_org), names.CONFERENCE_INDEX]

    async def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Stores are synchronous (elasticsearch-py); keep the event loop free."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _sendable(self, records: list[MemoryRecord]) -> list[MemoryRecord]:
        """Belt and braces: only this company's public/partner records can ever be offered or answered."""
        return [r for r in records if r.org_id == self._self_org and r.share_level in ("public", "partner")]

    async def profile_card(self, persona_id: str) -> MemoryRecord | None:
        """The shareable profile card `profile-<persona>-shareable`; None when the person has not uploaded one."""
        record = await self._call(self._store.get, f"profile-{persona_id}-shareable", indices=self._shareable)
        if record is None:
            hits = await self._call(
                self._store.search, "profile", indices=self._shareable, kinds=["profile"],
                owner_persona_id=persona_id, size=5,
            )
            record = next((h for h in hits if h.profile and h.profile.visibility == "shareable"), None)
        if record is None or record.profile is None or record.profile.visibility != "shareable":
            return None
        if record.share_level == "internal" or record.owner_persona_id != persona_id:
            return None
        return record

    async def vocabulary(self, query: str) -> list[str]:
        """Tags used by the records visible to this delegate and relevant to `query`, most relevant first."""
        hits = await self._call(self._store.search, query, indices=self._all, size=20)
        seen: dict[str, None] = {}
        for record in hits:
            for tag in record.tags:
                if _TAG.match(tag):
                    seen.setdefault(tag, None)
        return list(seen)

    async def search_offers(self, interests: list[str], query: str, size: int = 6) -> list[MemoryRecord]:
        """Own shareable records for the peer's interests: tag match first, then plain text relevance."""
        hits: list[MemoryRecord] = []
        if interests:
            hits = await self._call(
                self._store.search, query, indices=self._shareable, tags=interests, kinds=_OFFERABLE_KINDS, size=size
            )
        if not hits:
            hits = await self._call(
                self._store.search, query, indices=self._shareable, kinds=_OFFERABLE_KINDS, size=size
            )
        return self._sendable(hits)

    async def ask_candidates(self, topic: str, ask_text: str, size: int = 5) -> list[MemoryRecord]:
        """Candidates for an answer. Deterministic first: records tagged with the topic.

        Only if there are none, a search using the ask text. The text is a search string and nothing else.
        """
        hits = await self._call(
            self._store.search, topic, indices=self._shareable, tags=[topic], kinds=_OFFERABLE_KINDS, size=size
        )
        hits = self._sendable(hits)
        if hits:
            return hits
        by_text = await self._call(
            self._store.search, ask_text, indices=self._shareable, kinds=_OFFERABLE_KINDS, size=size
        )
        return self._sendable(by_text)

    async def find_talks(self, interests: list[str], size: int = 5) -> list[MemoryRecord]:
        """Agenda talks matching the mutual interests."""
        if not interests:
            return []
        query = " ".join(interests)
        hits = await self._call(
            self._store.search, query, indices=[names.CONFERENCE_INDEX], tags=interests, kinds=["talk"], size=size
        )
        return [h for h in hits if h.kind == "talk" and h.talk is not None]

    async def get_talk(self, talk_id: str) -> MemoryRecord | None:
        record = await self._call(self._store.get, talk_id, indices=[names.CONFERENCE_INDEX])
        return record if record is not None and record.kind == "talk" and record.talk is not None else None
