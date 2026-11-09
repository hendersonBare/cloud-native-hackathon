"""Interfaces between workstreams, plus an in-memory fake so nobody waits on Elasticsearch.

`rapport_memory.client.MemoryClient` (memory workstream) implements MemoryStore against
Elasticsearch. Until it lands, delegate/briefer code and tests use InMemoryStore.
"""

from __future__ import annotations

import re
from typing import Protocol

from .models import MemoryKind, MemoryRecord
from .names import index_for


class MemoryStore(Protocol):
    def search(
        self,
        query: str,
        *,
        indices: list[str],
        tags: list[str] | None = None,
        kinds: list[MemoryKind] | None = None,
        about_org_ids: list[str] | None = None,
        owner_persona_id: str | None = None,
        size: int = 5,
    ) -> list[MemoryRecord]:
        """Hybrid (keyword + semantic) search restricted to `indices`, with exact-match filters."""
        ...

    def get(self, memory_id: str, *, indices: list[str]) -> MemoryRecord | None: ...

    def write(self, records: list[MemoryRecord]) -> int:
        """Upsert by memory_id into names.index_for(record). Returns count written."""
        ...


_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


class InMemoryStore:
    """Keyword-overlap fake with the same filtering semantics as the real store."""

    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._docs: dict[str, tuple[str, MemoryRecord]] = {}
        if records:
            self.write(records)

    def write(self, records: list[MemoryRecord]) -> int:
        for r in records:
            self._docs[r.memory_id] = (index_for(r), r)
        return len(records)

    def get(self, memory_id: str, *, indices: list[str]) -> MemoryRecord | None:
        hit = self._docs.get(memory_id)
        return hit[1] if hit and hit[0] in indices else None

    def search(
        self,
        query: str,
        *,
        indices: list[str],
        tags: list[str] | None = None,
        kinds: list[MemoryKind] | None = None,
        about_org_ids: list[str] | None = None,
        owner_persona_id: str | None = None,
        size: int = 5,
    ) -> list[MemoryRecord]:
        q = _words(query)
        scored = []
        for index, r in self._docs.values():
            if index not in indices:
                continue
            if tags and not set(tags) & set(r.tags):
                continue
            if kinds and r.kind not in kinds:
                continue
            if about_org_ids and not set(about_org_ids) & set(r.about_org_ids):
                continue
            if owner_persona_id and r.owner_persona_id != owner_persona_id:
                continue
            score = len(q & _words(f"{r.title} {r.summary} {r.text} {' '.join(r.tags)}"))
            scored.append((score, r.created_at, r))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [r for _, _, r in scored[:size]]
