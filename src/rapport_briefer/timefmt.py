"""Times are stored in UTC. Anything shown to a person uses America/Denver with its label ("3:30 PM MST")."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    DENVER = ZoneInfo("America/Denver")
except ZoneInfoNotFoundError:  # no tzdata on the box: the conference is in MST
    DENVER = timezone(timedelta(hours=-7), "MST")  # type: ignore[assignment]


def as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def denver_label(dt: datetime) -> str:
    """ "3:30 PM MST" for a stored UTC time."""
    local = as_utc(dt).astimezone(DENVER)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} {local.tzname()}"
