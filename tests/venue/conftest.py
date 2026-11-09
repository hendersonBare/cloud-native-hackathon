"""Shared fixtures: the seed venue, a settable clock, a fresh service and an in-process HTTP client."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from rapport_venue.app import create_app
from rapport_venue.service import VenueService, load_venue
from venue_support import FakeClock


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test independent of the developer's environment."""
    for var in ("RAPPORT_VENUE_ORIGIN", "RAPPORT_VERSION"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def venue() -> dict:
    return load_venue()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(clock: FakeClock) -> VenueService:
    return VenueService(clock=clock)


@pytest_asyncio.fixture
async def client(service: VenueService) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http
