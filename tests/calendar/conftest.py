"""Shared fixtures (tests/calendar has no __init__.py: a package named "calendar" would shadow the stdlib).

A fixed clock, a seed-only talk source (no network) and an in-process HTTP client."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from calendar_support import NOW
from rapport_calendar.agenda import SeedTalkSource
from rapport_calendar.app import create_app
from rapport_calendar.seed import load_seed
from rapport_calendar.service import CalendarService


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test independent of the developer's environment."""
    for var in ("RAPPORT_CALENDAR_AGENDA", "RAPPORT_CALENDAR_NOW", "RAPPORT_VERSION"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def seed():
    return load_seed()


@pytest.fixture
def service(seed) -> CalendarService:
    return CalendarService(seed=seed, talk_source=SeedTalkSource(seed.agenda), now=lambda: NOW)


@pytest_asyncio.fixture
async def client(service: CalendarService) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http
