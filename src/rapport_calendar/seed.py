"""Load and validate ``data/seed.json``.

The seed gives wall-clock times as ``day`` (0 = ``week_start``) plus ``"HH:MM"``. They are converted to aware UTC
with the seed's fixed ``utc_offset`` (the conference week is all MST), so Python and the JS mock agree to the second.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Annotated

from pydantic import StringConstraints
from rapport_common.models import Contract, TalkHit
from rapport_common.names import personas

from .models import CalendarEvent, EventKind, EventSource, EventStatus, Response

SEED_PATH = Path(__file__).parent / "data" / "seed.json"

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
ClockTime = Annotated[str, StringConstraints(pattern=_HHMM)]
UtcOffset = Annotated[str, StringConstraints(pattern=r"^[+-]\d{2}:\d{2}$")]


class _WorkingHours(Contract):
    start: ClockTime
    end: ClockTime


class _SeedAgendaItem(Contract):
    talk_id: str
    title: str
    day: int
    start: ClockTime
    room: str
    track: str
    speakers: list[str] = []


class _SeedEvent(Contract):
    event_id: str
    persona_id: str
    kind: EventKind
    source: EventSource
    title: str
    day: int
    start: ClockTime
    end: ClockTime
    location: str = ""
    capture: bool = False
    status: EventStatus = "confirmed"
    talk_id: str | None = None
    meeting_id: str | None = None
    with_persona_ids: list[str] = []
    responses: dict[str, Response] = {}
    note: str | None = None


class _SeedFile(Contract):
    version: int
    note: str = ""
    timezone: str
    utc_offset: UtcOffset
    week_start: date
    working_hours: _WorkingHours
    slot_minutes: int
    talk_minutes: int
    conference_mode: dict[str, bool]
    agenda: list[_SeedAgendaItem]
    events: list[_SeedEvent]


def parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def parse_offset(value: str) -> tzinfo:
    sign = -1 if value.startswith("-") else 1
    hours, minutes = value[1:].split(":")
    return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))


def local_to_utc(week_start: date, day: int, hhmm: str, tz: tzinfo) -> datetime:
    """``day`` days after ``week_start`` at wall-clock ``HH:MM`` in ``tz``, as aware UTC."""
    moment = datetime.combine(week_start + timedelta(days=day), parse_hhmm(hhmm), tzinfo=tz)
    return moment.astimezone(timezone.utc)


@dataclass(frozen=True)
class CalendarSeed:
    """The validated seed: conference settings, the talk agenda and every persona's starting events."""

    timezone_name: str
    tz: tzinfo
    week_start: date
    work_start: time
    work_end: time
    slot_minutes: int
    talk_minutes: int
    conference_mode: dict[str, bool]
    agenda: list[TalkHit]
    events: list[CalendarEvent]

    def local_midnight(self, day: date) -> datetime:
        """Start of the local day ``day`` as aware UTC."""
        return datetime.combine(day, time(0, 0), tzinfo=self.tz).astimezone(timezone.utc)

    @property
    def week_start_utc(self) -> datetime:
        return self.local_midnight(self.week_start)

    @property
    def week_end_utc(self) -> datetime:
        return self.local_midnight(self.week_start + timedelta(days=7))

    def week_days(self) -> list[date]:
        return [self.week_start + timedelta(days=offset) for offset in range(7)]


def _check_events(events: list[CalendarEvent]) -> None:
    known = set(personas())
    seen: set[str] = set()
    meetings: dict[str, list[CalendarEvent]] = {}
    for ev in events:
        if ev.event_id in seen:
            raise ValueError(f"duplicate seed event id {ev.event_id}")
        seen.add(ev.event_id)
        if ev.persona_id not in known or not set(ev.with_persona_ids) <= known:
            raise ValueError(f"seed event {ev.event_id} names an unknown persona")
        if ev.kind == "meeting":
            if not ev.meeting_id or set(ev.responses) != {ev.persona_id, *ev.with_persona_ids}:
                raise ValueError(f"seed meeting {ev.event_id} needs a meeting_id and one response per participant")
            meetings.setdefault(ev.meeting_id, []).append(ev)
    for meeting_id, copies in meetings.items():
        first = copies[0]
        owners = {c.persona_id for c in copies}
        if len(copies) != len(owners) or owners != set(first.responses):
            raise ValueError(f"seed meeting {meeting_id} needs exactly one copy per participant")
        for other in copies[1:]:
            if (other.starts_at, other.ends_at, other.status, other.responses) != (
                first.starts_at, first.ends_at, first.status, first.responses
            ):
                raise ValueError(f"seed meeting {meeting_id} copies disagree")


def load_seed(path: Path = SEED_PATH) -> CalendarSeed:
    """Read, validate and convert the seed file. Raises ``ValueError`` when it is inconsistent."""
    raw = _SeedFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    tz = parse_offset(raw.utc_offset)
    week = raw.week_start

    agenda = [
        TalkHit(
            talk_id=item.talk_id,
            title=item.title,
            starts_at=local_to_utc(week, item.day, item.start, tz),
            room=item.room,
            track=item.track,
            speakers=item.speakers,
        )
        for item in raw.agenda
    ]
    if len({t.talk_id for t in agenda}) != len(agenda):
        raise ValueError("duplicate talk_id in the seed agenda")

    events = [
        CalendarEvent(
            event_id=e.event_id,
            persona_id=e.persona_id,
            kind=e.kind,
            title=e.title,
            starts_at=local_to_utc(week, e.day, e.start, tz),
            ends_at=local_to_utc(week, e.day, e.end, tz),
            location=e.location,
            status=e.status,
            capture=e.capture,
            source=e.source,
            talk_id=e.talk_id,
            meeting_id=e.meeting_id,
            with_persona_ids=list(e.with_persona_ids),
            responses=dict(e.responses),
            note=e.note,
        )
        for e in raw.events
    ]
    _check_events(events)
    if not set(raw.conference_mode) <= set(personas()):
        raise ValueError("conference_mode names an unknown persona")

    return CalendarSeed(
        timezone_name=raw.timezone,
        tz=tz,
        week_start=week,
        work_start=parse_hhmm(raw.working_hours.start),
        work_end=parse_hhmm(raw.working_hours.end),
        slot_minutes=raw.slot_minutes,
        talk_minutes=raw.talk_minutes,
        conference_mode=dict(raw.conference_mode),
        agenda=agenda,
        events=events,
    )
