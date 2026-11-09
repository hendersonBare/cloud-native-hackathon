"""Rapport memory: the Elasticsearch client, the demo seed data and the store factory.

Consumers import `store_from_env` inside main()/startup, not at module top level.
"""

from __future__ import annotations

import logging
import os

from rapport_common.interfaces import InMemoryStore, MemoryStore
from rapport_common.names import index_for

log = logging.getLogger("rapport.memory")


def store_from_env(indices: list[str]) -> MemoryStore:
    """The memory store a service should use.

    With ES_URL and ES_API_KEY set: a MemoryClient that can touch only `indices`. Otherwise an InMemoryStore
    holding the seed records that live in `indices` (local runs, tests, and the demo fallback).
    """
    es_url = os.environ.get("ES_URL")
    api_key = os.environ.get("ES_API_KEY")
    if es_url and api_key:
        from .client import MemoryClient

        return MemoryClient(es_url, api_key, allowed_indices=list(indices))

    from .seed import seed_records

    allowed = set(indices)
    records = [r for r in seed_records() if index_for(r) in allowed]
    log.warning(
        "ES_URL/ES_API_KEY not set: using the in-memory store with %d seed records for %d indices",
        len(records), len(allowed),
    )
    return InMemoryStore(records)


__all__ = ["store_from_env"]
