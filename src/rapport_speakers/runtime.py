"""Wire a store, pipeline and search from the environment.

With `ES_URL` and a key set (or `SPEAKERS_STORE=es`), everything reads and writes Elasticsearch, which must be
seeded first with `python -m rapport_speakers.cli seed`. Otherwise an in-memory store is seeded from the
committed fixtures at startup, so the API and CLI work with no keys at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import STORE_ES, Settings
from .pipeline import Pipeline, SeedReport, seed
from .search import SpeakerSearch
from .store import InMemorySpeakerStore, SpeakerStore

log = logging.getLogger("rapport.speakers")


@dataclass
class Runtime:
    settings: Settings
    store: SpeakerStore
    pipeline: Pipeline
    search: SpeakerSearch
    seed_report: SeedReport | None = None


def build_runtime(settings: Settings | None = None, *, seed_memory: bool = True) -> Runtime:
    settings = settings or Settings.from_env()
    report = None
    if settings.store == STORE_ES:
        from .es_store import EsSpeakerStore

        store: SpeakerStore = EsSpeakerStore(settings)
    else:
        store = InMemorySpeakerStore()
        if seed_memory:
            report = seed(store, settings)
            log.info("in-memory speaker store seeded from fixtures: %s", report.counts)
    return Runtime(settings, store, Pipeline(store, settings), SpeakerSearch(store, settings), report)
