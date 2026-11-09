from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rapport_speakers.config import Settings
from rapport_speakers.pipeline import Pipeline, seed
from rapport_speakers.search import SpeakerSearch
from rapport_speakers.store import InMemorySpeakerStore

# A fixed conference day (MST) so times and labels are stable whatever day the tests run.
CONF_DAY = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def conf_day() -> datetime:
    return CONF_DAY


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def seeded(settings):
    store = InMemorySpeakerStore()
    report = seed(store, settings, now=CONF_DAY)
    return store, report


@pytest.fixture
def pipeline(seeded, settings) -> Pipeline:
    return Pipeline(seeded[0], settings)


@pytest.fixture
def search(seeded, settings) -> SpeakerSearch:
    return SpeakerSearch(seeded[0], settings)
