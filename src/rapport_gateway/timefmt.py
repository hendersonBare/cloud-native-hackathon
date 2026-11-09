"""Times are stored in UTC; anything shown to a person uses America/Denver with its label (for example 3:30 PM MST)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    DENVER: timezone | ZoneInfo = ZoneInfo("America/Denver")
except ZoneInfoNotFoundError:  # a minimal image without tzdata: fall back to standard time
    DENVER = timezone(timedelta(hours=-7), "MST")


def utc_at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """A wall-clock time in Denver (e.g. the conference's 3:30 PM) as a timezone-aware UTC datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=DENVER).astimezone(timezone.utc)


def local_label(moment: datetime) -> str:
    """'3:30 PM MST' for an aware datetime."""
    local = moment.astimezone(DENVER)
    suffix = "AM" if local.hour < 12 else "PM"
    return f"{local.hour % 12 or 12}:{local.minute:02d} {suffix} {local.tzname()}"
