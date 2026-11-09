"""Pure scheduling helpers: overlap, merged busy time and the first mutual free slot. No I/O."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, time, timedelta, timezone, tzinfo

Interval = tuple[datetime, datetime]
_FIRST_WEEKDAYS = 5  # Monday to Friday are 0..4


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """True when the half-open intervals share time. Back-to-back intervals do not overlap."""
    return a_start < b_end and a_end > b_start


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """Sort and merge overlapping or touching intervals."""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def clip_intervals(intervals: Iterable[Interval], start: datetime, end: datetime) -> list[Interval]:
    """Keep the part of each interval inside ``[start, end)``; drop the ones that fall outside."""
    clipped = [(max(s, start), min(e, end)) for s, e in intervals if overlaps(s, e, start, end)]
    return merge_intervals(clipped)


def ceil_to_grid(moment: datetime, tz: tzinfo, step_minutes: int = 15) -> datetime:
    """Round ``moment`` up to the next ``step_minutes`` boundary of the local wall clock; returned as UTC."""
    local = moment.astimezone(tz)
    floored = local.replace(second=0, microsecond=0)
    if floored < local:
        floored += timedelta(minutes=1)
    remainder = (floored.hour * 60 + floored.minute) % step_minutes
    if remainder:
        floored += timedelta(minutes=step_minutes - remainder)
    return floored.astimezone(timezone.utc)


def first_mutual_slot(
    busy_a: Iterable[Interval],
    busy_b: Iterable[Interval],
    *,
    earliest: datetime,
    duration: timedelta,
    days: Sequence[date],
    tz: tzinfo,
    work_start: time,
    work_end: time,
    step_minutes: int = 15,
) -> Interval | None:
    """The first slot of ``duration`` that is free for both people.

    Candidates start on a ``step_minutes`` grid of the local clock, on weekdays among ``days``, no earlier than
    ``earliest``, and must end by ``work_end``. Returns ``(start, end)`` in UTC, or ``None``.
    """
    busy = merge_intervals([*busy_a, *busy_b])
    floor = ceil_to_grid(earliest, tz, step_minutes)
    for day in days:
        if day.weekday() >= _FIRST_WEEKDAYS:
            continue
        opens = ceil_to_grid(datetime.combine(day, work_start, tzinfo=tz), tz, step_minutes)
        closes = datetime.combine(day, work_end, tzinfo=tz).astimezone(timezone.utc)
        cursor = max(opens, floor)
        while cursor + duration <= closes:
            blocker = next((b for b in busy if overlaps(cursor, cursor + duration, b[0], b[1])), None)
            if blocker is None:
                return cursor, cursor + duration
            cursor = ceil_to_grid(blocker[1], tz, step_minutes)
    return None
