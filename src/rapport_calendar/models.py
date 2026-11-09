"""Calendar payloads.

These shapes are calendar-specific and live here because ``rapport_common`` is integrator-owned.
CONTRACT CHANGE REQUEST: promote them into ``rapport_common.models`` once the integrator agrees.
They reuse the contract models ``TalkHit`` and ``SharedBrief``; never redefine those here.

Every datetime on the wire is ISO 8601 with an explicit offset and is normalised to aware UTC.
Naive datetimes are rejected (FastAPI answers 422).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, Field, StringConstraints, model_validator
from rapport_common.models import Contract, TalkHit

TIMEZONE = "America/Denver"
MAX_EVENTS_PER_PERSONA = 200

EventKind = Literal["talk", "meeting", "personal"]
EventStatus = Literal["confirmed", "proposed", "declined"]
EventSource = Literal["seed", "conference", "agent", "user"]
Response = Literal["pending", "accepted", "declined"]
MeetingPurpose = Literal["coffee", "meeting"]


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


# An aware datetime, converted to UTC. A naive input fails validation.
UTCDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class CalendarEvent(Contract):
    event_id: str  # "evt-<12 hex>"; seed ids are readable, e.g. "evt-ava-ebpf"
    persona_id: str  # owner of this copy
    kind: EventKind
    title: str = Field(min_length=1, max_length=120)
    starts_at: UTCDatetime
    ends_at: UTCDatetime
    location: str = Field(default="", max_length=80)
    status: EventStatus = "confirmed"
    capture: bool = False  # auto-transcribe this session
    source: EventSource
    talk_id: str | None = None  # kind == "talk" and from the agenda
    meeting_id: str | None = None  # kind == "meeting"; shared by every participant's copy
    with_persona_ids: list[str] = Field(default_factory=list)  # other participants
    responses: dict[str, Response] = Field(default_factory=dict)  # meetings only: persona_id -> response
    note: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _check_range(self) -> CalendarEvent:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class CalendarView(Contract):
    persona_id: str
    timezone: str = TIMEZONE
    week_start: date  # Monday of the conference week (local date)
    start: date  # first local day in this view
    days: int = Field(ge=1, le=14)
    now: UTCDatetime  # server clock
    conference_mode: bool
    events: list[CalendarEvent]  # in the window, status != "declined", sorted by (starts_at, title)


class CreateEventBody(Contract):
    """A personal event."""

    persona_id: str
    title: Title
    starts_at: UTCDatetime
    ends_at: UTCDatetime
    location: str = Field(default="", max_length=80)
    capture: bool = False


class CreateEventResult(Contract):
    timezone: str = TIMEZONE
    event: CalendarEvent
    conflicts: list[str] = Field(default_factory=list)  # ids of the owner's overlapping non-declined events


class UpdateEventBody(Contract):
    """All fields optional except persona_id; at least one must be set."""

    persona_id: str
    capture: bool | None = None  # any of my events
    title: Title | None = None  # source == "user" only
    starts_at: UTCDatetime | None = None  # source == "user" only
    ends_at: UTCDatetime | None = None  # source == "user" only
    location: str | None = Field(default=None, max_length=80)  # source == "user" only

    @model_validator(mode="after")
    def _need_a_field(self) -> UpdateEventBody:
        if all(getattr(self, name) is None for name in ("capture", "title", "starts_at", "ends_at", "location")):
            raise ValueError("at least one field to update is required")
        return self


class RespondBody(Contract):
    persona_id: str
    response: Literal["accept", "decline"]


class ConferenceModeBody(Contract):
    persona_id: str
    enabled: bool


class ConferenceModeState(Contract):
    persona_id: str
    enabled: bool


class AgendaItem(Contract):
    talk: TalkHit
    ends_at: UTCDatetime  # talk.starts_at + 30 min (TalkHit has no end)
    in_calendar: bool  # the viewer already has an event with this talk_id


class AgendaView(Contract):
    persona_id: str
    timezone: str = TIMEZONE
    source: Literal["briefer", "seed"]  # "seed" = the briefer was unavailable or disabled
    query: str
    items: list[AgendaItem] = Field(max_length=20)  # sorted by starts_at


class AddTalkBody(Contract):
    persona_id: str
    talk_id: str


class ProposeBody(Contract):
    persona_id: str  # proposer
    with_persona_id: str  # invitee; != persona_id
    purpose: MeetingPurpose = "coffee"  # no free text crosses companies: titles and locations are templated
    duration_minutes: int = Field(default=30, ge=15, le=120)  # a multiple of 15, checked by the service
    not_before: UTCDatetime | None = None  # default: now


class MeetingProposal(Contract):
    timezone: str = TIMEZONE
    meeting_id: str
    created: bool  # False: an active meeting with this person already existed
    starts_at: UTCDatetime
    ends_at: UTCDatetime
    status: EventStatus  # "proposed" or "confirmed"
    event: CalendarEvent  # the PROPOSER's copy


class BusyBlock(Contract):
    starts_at: UTCDatetime
    ends_at: UTCDatetime


class FreeBusy(Contract):
    """The only cross-person view: no titles, no ids, no locations."""

    persona_id: str
    timezone: str = TIMEZONE
    start: UTCDatetime
    end: UTCDatetime
    busy: list[BusyBlock]  # merged, sorted, non-declined events only
