"""Time helpers shared by the calendar tests (a plain module: tests/calendar has no package, see conftest)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
MST = timezone(timedelta(hours=-7))
# Monday 2026-11-09 08:00 local, the first morning of the conference week.
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def local(day: int, hour: int, minute: int = 0) -> datetime:
    """Wall-clock time ``day`` days after Monday 2026-11-09, in the conference zone (aware)."""
    return datetime(2026, 11, 9, hour, minute, tzinfo=MST) + timedelta(days=day)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
