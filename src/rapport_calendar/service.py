"""The calendar rules. In-memory state guarded by an asyncio lock; clock and talk source are injectable.

Privacy: another person's events are never returned. The only cross-person read is free/busy time when proposing a
meeting, and meeting titles and locations are templated so no free text crosses companies. Spans and logs carry
IDs and counts only, never titles, notes, queries or locations.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from opentelemetry.trace import Span
from rapport_common.models import SharedBrief, TalkHit
from rapport_common.names import personas
from rapport_common.telemetry import ATTR_PERSONA, ATTR_RESULT_COUNT, tracer

from . import ics
from .agenda import BrieferTalkSource, SeedTalkSource, TalkSource
from .models import (
    MAX_EVENTS_PER_PERSONA,
    TIMEZONE,
    AddTalkBody,
    AgendaItem,
    AgendaView,
    BusyBlock,
    CalendarEvent,
    CalendarView,
    ConferenceModeBody,
    ConferenceModeState,
    CreateEventBody,
    CreateEventResult,
    FreeBusy,
    MeetingProposal,
    ProposeBody,
    RespondBody,
    UpdateEventBody,
)
from .seed import CalendarSeed, load_seed
from .slots import clip_intervals, first_mutual_slot, merge_intervals, overlaps

log = logging.getLogger("rapport.calendar")

MAX_EVENT_DURATION = timedelta(hours=12)
MAX_FREEBUSY_WINDOW = timedelta(days=14)
MAX_QUERY_LENGTH = 100
MAX_DECLINED_KEPT = 20  # declined meeting copies are kept so a late response gets "meeting_closed", but only a few
_MEETING_PLACES = {"coffee": ("Coffee", "Lobby café"), "meeting": ("Meeting", "Meeting room 2")}
_FALLBACK_TALK_TITLE = "Conference talk"


class CalendarError(HTTPException):
    """An API error with a machine-readable code as its ``detail`` (e.g. ``event_not_found``)."""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(status_code=status_code, detail=code)


@contextmanager
def _span(name: str, persona_id: str) -> Iterator[Span]:
    with tracer("rapport.calendar").start_as_current_span(name) as span:
        span.set_attribute(ATTR_PERSONA, persona_id)
        yield span


def _new_event_id() -> str:
    return f"evt-{secrets.token_hex(6)}"


def _new_meeting_id() -> str:
    return f"mtg-{secrets.token_hex(6)}"


def _out(event: CalendarEvent) -> CalendarEvent:
    """A copy, so callers can never mutate the service's state."""
    return event.model_copy(deep=True)


def _sort_key(event: CalendarEvent) -> tuple[datetime, str]:
    return event.starts_at, event.title


def _default_clock() -> Callable[[], datetime]:
    pinned = os.environ.get("RAPPORT_CALENDAR_NOW")
    if pinned:
        try:
            fixed = datetime.fromisoformat(pinned)
            if fixed.tzinfo is not None:
                fixed = fixed.astimezone(timezone.utc)
                return lambda: fixed
        except ValueError:
            pass
        log.warning("RAPPORT_CALENDAR_NOW is not an ISO 8601 time with an offset; using the real clock")
    return lambda: datetime.now(timezone.utc)


class CalendarService:
    def __init__(
        self,
        *,
        seed: CalendarSeed | None = None,
        talk_source: TalkSource | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._injected_seed = seed
        self._seed = seed or load_seed()
        self._talks: TalkSource = talk_source or BrieferTalkSource(SeedTalkSource(self._seed.agenda))
        self._clock = now or _default_clock()
        self._lock = asyncio.Lock()
        self._names = {pid: person.name for pid, person in personas().items()}
        self._events: dict[str, dict[str, CalendarEvent]] = {}
        self._conference_mode: dict[str, bool] = {}
        self.reset()

    # ------------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        """Restore the seed state. Synchronous and free of awaits, so it is atomic on the event loop."""
        self._seed = self._injected_seed or load_seed()
        self._events = {pid: {} for pid in self._names}
        for event in self._seed.events:
            self._events[event.persona_id][event.event_id] = _out(event)
        self._conference_mode = {pid: self._seed.conference_mode.get(pid, False) for pid in self._names}

    def now(self) -> datetime:
        return self._clock().astimezone(timezone.utc)

    # ------------------------------------------------------------------ view
    async def view(self, persona_id: str, start: date | None = None, days: int = 7) -> CalendarView:
        self._require(persona_id)
        if not 1 <= days <= 14:
            raise CalendarError(422, "invalid_days")
        first = start or self._seed.week_start
        try:
            window_start = self._seed.local_midnight(first)
            window_end = self._seed.local_midnight(first + timedelta(days=days))
        except OverflowError:
            raise CalendarError(422, "invalid_start") from None
        with _span("calendar.view", persona_id) as span:
            async with self._lock:
                events = sorted(
                    (
                        _out(e)
                        for e in self._events[persona_id].values()
                        if e.status != "declined" and overlaps(e.starts_at, e.ends_at, window_start, window_end)
                    ),
                    key=_sort_key,
                )
                mode = self._conference_mode[persona_id]
            span.set_attribute(ATTR_RESULT_COUNT, len(events))
        return CalendarView(
            persona_id=persona_id,
            timezone=TIMEZONE,
            week_start=self._seed.week_start,
            start=first,
            days=days,
            now=self.now(),
            conference_mode=mode,
            events=events,
        )

    # ------------------------------------------------------------------ create / update / delete
    async def create_event(self, body: CreateEventBody) -> CreateEventResult:
        self._require(body.persona_id)
        self._check_times(body.starts_at, body.ends_at)
        async with self._lock:
            self._check_capacity(body.persona_id)
            event = CalendarEvent(
                event_id=_new_event_id(),
                persona_id=body.persona_id,
                kind="personal",
                title=body.title,
                starts_at=body.starts_at,
                ends_at=body.ends_at,
                location=body.location,
                capture=body.capture,
                source="user",
            )
            conflicts = self._conflicts(event)
            self._events[body.persona_id][event.event_id] = event
            return CreateEventResult(event=_out(event), conflicts=conflicts)

    async def update_event(self, event_id: str, body: UpdateEventBody) -> CalendarEvent:
        self._require(body.persona_id)
        async with self._lock:
            event = self._find(body.persona_id, event_id)
            edits_details = any(v is not None for v in (body.title, body.starts_at, body.ends_at, body.location))
            if edits_details and event.source != "user":
                raise CalendarError(409, "not_editable")
            changes: dict[str, Any] = {}
            if body.capture is not None:
                changes["capture"] = body.capture
            if body.title is not None:
                changes["title"] = body.title
            if body.location is not None:
                changes["location"] = body.location
            if body.starts_at is not None or body.ends_at is not None:
                starts = body.starts_at or event.starts_at
                ends = body.ends_at or event.ends_at
                self._check_times(starts, ends)
                changes.update(starts_at=starts, ends_at=ends)
            updated = event.model_copy(update=changes)
            self._events[body.persona_id][event_id] = updated
            return _out(updated)

    async def delete_event(self, event_id: str, persona_id: str) -> None:
        self._require(persona_id)
        async with self._lock:
            event = self._find(persona_id, event_id)
            dismissable_suggestion = event.source == "agent" and event.kind == "talk"
            if event.source not in ("user", "conference") and not dismissable_suggestion:
                raise CalendarError(409, "not_deletable")
            del self._events[persona_id][event_id]

    # ------------------------------------------------------------------ meeting responses
    async def respond(self, event_id: str, body: RespondBody) -> CalendarEvent:
        self._require(body.persona_id)
        with _span("calendar.respond", body.persona_id) as span:
            async with self._lock:
                mine = self._find(body.persona_id, event_id)
                if mine.kind != "meeting" or not mine.meeting_id:
                    raise CalendarError(409, "not_a_meeting")
                if mine.status == "declined":
                    raise CalendarError(409, "meeting_closed")
                accepted = body.response == "accept"
                responses = {**mine.responses, body.persona_id: "accepted" if accepted else "declined"}
                if not accepted:
                    status = "declined"
                elif all(r == "accepted" for r in responses.values()):
                    status = "confirmed"
                else:
                    status = mine.status
                copies = 0
                owners: list[str] = []
                for owner, events in self._events.items():
                    for key, copy in list(events.items()):
                        if copy.meeting_id == mine.meeting_id:
                            changes: dict[str, Any] = {"responses": dict(responses), "status": status}
                            note = self._status_note(status, body.persona_id)
                            if note is not None:
                                changes["note"] = note
                            events[key] = copy.model_copy(update=changes)
                            owners.append(owner)
                            copies += 1
                span.set_attribute(ATTR_RESULT_COUNT, copies)
                result = _out(self._events[body.persona_id][event_id])
                for owner in owners:
                    self._prune_declined(owner)
                return result

    # ------------------------------------------------------------------ conference mode, agenda, talks
    async def set_conference_mode(self, body: ConferenceModeBody) -> ConferenceModeState:
        self._require(body.persona_id)
        async with self._lock:
            self._conference_mode[body.persona_id] = body.enabled
        return ConferenceModeState(persona_id=body.persona_id, enabled=body.enabled)

    async def agenda(self, persona_id: str, query: str = "") -> AgendaView:
        self._require(persona_id)
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise CalendarError(422, "query_too_long")
        with _span("calendar.agenda", persona_id) as span:
            result = await self._talks.search(persona_id, query)  # network call: outside the lock
            async with self._lock:
                have = {e.talk_id for e in self._events[persona_id].values() if e.talk_id}
            length = timedelta(minutes=self._seed.talk_minutes)
            items = [
                AgendaItem(talk=t, ends_at=t.starts_at + length, in_calendar=t.talk_id in have)
                for t in sorted(result.talks, key=lambda t: (t.starts_at, t.title))[:20]
            ]
            span.set_attribute(ATTR_RESULT_COUNT, len(items))
        return AgendaView(persona_id=persona_id, source=result.source, query=query, items=items)

    async def add_talk(self, body: AddTalkBody) -> CreateEventResult:
        """Add an agenda talk. Adding a talk the agents suggested accepts that suggestion."""
        self._require(body.persona_id)
        talk = self._talks.lookup(body.talk_id)
        if talk is None:
            raise CalendarError(404, "unknown_talk")
        if not self._talk_in_week(talk):
            raise CalendarError(422, "outside_conference_week")
        async with self._lock:
            capture = self._conference_mode[body.persona_id]
            existing = next((e for e in self._events[body.persona_id].values() if e.talk_id == talk.talk_id), None)
            if existing is not None:
                if existing.source != "agent" or existing.status != "proposed":
                    raise CalendarError(409, "already_added")
                accepted = existing.model_copy(
                    update={"source": "conference", "status": "confirmed", "capture": capture, "note": None}
                )
                self._events[body.persona_id][accepted.event_id] = accepted
                return CreateEventResult(event=_out(accepted), conflicts=self._conflicts(accepted))
            self._check_capacity(body.persona_id)
            event = self._talk_event(body.persona_id, talk, source="conference", status="confirmed", capture=capture)
            conflicts = self._conflicts(event)
            self._events[body.persona_id][event.event_id] = event
            return CreateEventResult(event=_out(event), conflicts=conflicts)

    def _mark_going_together(self, event: CalendarEvent, counterparty_persona_id: str) -> CalendarEvent | None:
        """Both people's agents agreed on a talk this person already has: say who they are going with."""
        if event.status == "declined" or counterparty_persona_id in event.with_persona_ids:
            return None
        with_ids = [*event.with_persona_ids, counterparty_persona_id]
        names = [self._names[pid] for pid in with_ids if pid in self._names]
        who = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
        if len(names) > 2:
            who = f"{names[0]} and {len(names) - 1} others"
        updated = event.model_copy(
            update={"with_persona_ids": with_ids, "note": f"Going with {who} · suggested by your agents"}
        )
        self._events[event.persona_id][event.event_id] = updated
        return _out(updated)

    async def record_shared_brief(self, brief: SharedBrief, counterparty_persona_id: str) -> CalendarEvent | None:
        """Encounter hook: add the talk the agents suggested as a proposed event.

        The suggestion comes from a delegate whose input includes counterparty text, so it is only an id: the event is
        built from this service's own copy of that talk (never the brief's title, room or time), and only for a talk
        inside the conference week. When the person already has that talk, the event is marked instead: the counterparty
        joins ``with_persona_ids`` and the note says "Going with <name> · suggested by your agents" (templated; only
        directory names). Returns the new or marked event, or ``None`` when nothing changed (no suggestion, an unknown
        person or talk, a full calendar, a declined event, or a repeat call for the same counterparty).
        """
        suggestion = brief.suggested_talk
        persona_id = brief.for_persona_id
        if suggestion is None:
            return None
        if (
            persona_id not in self._names
            or counterparty_persona_id not in self._names
            or counterparty_persona_id == persona_id
        ):
            log.warning("shared brief ignored by calendar encounter=%s", brief.encounter_id)
            return None
        talk = self._talks.lookup(suggestion.talk_id)
        if talk is None or not self._talk_in_week(talk):
            log.warning("shared brief suggested an unknown talk encounter=%s", brief.encounter_id)
            return None
        async with self._lock:
            existing = next((e for e in self._events[persona_id].values() if e.talk_id == talk.talk_id), None)
            if existing is not None:
                return self._mark_going_together(existing, counterparty_persona_id)
            if self._active_count(persona_id) >= MAX_EVENTS_PER_PERSONA:
                return None
            event = self._talk_event(
                persona_id, talk, source="agent", status="proposed", capture=False,
                with_persona_ids=[counterparty_persona_id], note="Suggested by your agents",
            )
            self._events[persona_id][event.event_id] = event
            return _out(event)

    # ------------------------------------------------------------------ scheduling
    async def propose(self, body: ProposeBody) -> MeetingProposal:
        self._require(body.persona_id)
        self._require(body.with_persona_id)
        if body.with_persona_id == body.persona_id:
            raise CalendarError(422, "same_person")
        if body.duration_minutes % self._seed.slot_minutes:
            raise CalendarError(422, "invalid_duration")
        with _span("calendar.propose", body.persona_id) as span:
            async with self._lock:
                now = self.now()
                existing = self._existing_meeting(body.persona_id, body.with_persona_id, now)
                if existing is not None:
                    span.set_attribute(ATTR_RESULT_COUNT, 0)
                    return self._proposal(existing, created=False)
                self._check_capacity(body.persona_id)
                self._check_capacity(body.with_persona_id)
                slot = first_mutual_slot(
                    self._busy(body.persona_id),
                    self._busy(body.with_persona_id),  # free/busy only: the invitee's titles are never read
                    earliest=max(body.not_before or now, now, self._seed.week_start_utc),  # never in the past
                    duration=timedelta(minutes=body.duration_minutes),
                    days=self._seed.week_days(),
                    tz=self._seed.tz,
                    work_start=self._seed.work_start,
                    work_end=self._seed.work_end,
                    step_minutes=self._seed.slot_minutes,
                )
                if slot is None:
                    raise CalendarError(409, "no_mutual_slot")
                mine = self._create_meeting(body, slot)
                span.set_attribute(ATTR_RESULT_COUNT, 1)
                return self._proposal(mine, created=True)

    async def freebusy(self, persona_id: str, start: datetime, end: datetime) -> FreeBusy:
        self._require(persona_id)
        if start.tzinfo is None or end.tzinfo is None:
            raise CalendarError(422, "naive_datetime")
        start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        if end <= start or end - start > MAX_FREEBUSY_WINDOW:
            raise CalendarError(422, "invalid_window")
        async with self._lock:
            busy = clip_intervals(self._busy(persona_id), start, end)
        return FreeBusy(
            persona_id=persona_id, start=start, end=end, busy=[BusyBlock(starts_at=s, ends_at=e) for s, e in busy]
        )

    async def export_ics(self, persona_id: str) -> str:
        self._require(persona_id)
        async with self._lock:
            events = [_out(e) for e in self._events[persona_id].values()]
        return ics.render_calendar(events, now=self.now(), name=f"Rapport: {self._names[persona_id]}")

    # ------------------------------------------------------------------ helpers (call with the lock held)
    def _require(self, persona_id: str) -> None:
        if persona_id not in self._names:
            raise CalendarError(404, "unknown_persona")

    def _find(self, persona_id: str, event_id: str) -> CalendarEvent:
        event = self._events[persona_id].get(event_id)
        if event is None:  # also covers another person's event: never reveal that it exists
            raise CalendarError(404, "event_not_found")
        return event

    def _active_count(self, persona_id: str) -> int:
        """Declined copies are hidden and can never be removed by their owner, so they must not fill the calendar."""
        return sum(1 for e in self._events[persona_id].values() if e.status != "declined")

    def _check_capacity(self, persona_id: str) -> None:
        if self._active_count(persona_id) >= MAX_EVENTS_PER_PERSONA:
            raise CalendarError(409, "calendar_full")

    def _prune_declined(self, persona_id: str) -> None:
        events = self._events[persona_id]
        for key in [k for k, e in events.items() if e.status == "declined"][:-MAX_DECLINED_KEPT]:
            del events[key]

    def _status_note(self, status: str, responder_id: str) -> str | None:
        """The note a meeting copy shows once it is settled (a templated name only, never free text)."""
        if status == "confirmed":
            return "Confirmed by both"
        if status == "declined":
            return f"Declined by {self._names[responder_id]}"
        return None

    def _talk_in_week(self, talk: TalkHit) -> bool:
        if talk.starts_at.tzinfo is None:
            return False
        start = talk.starts_at.astimezone(timezone.utc)
        end = start + timedelta(minutes=self._seed.talk_minutes)
        return self._seed.week_start_utc <= start and end <= self._seed.week_end_utc

    def _check_times(self, starts_at: datetime, ends_at: datetime) -> None:
        if ends_at <= starts_at:
            raise CalendarError(422, "invalid_time_range")
        if ends_at - starts_at > MAX_EVENT_DURATION:
            raise CalendarError(422, "event_too_long")
        if starts_at < self._seed.week_start_utc or ends_at > self._seed.week_end_utc:
            raise CalendarError(422, "outside_conference_week")

    def _conflicts(self, event: CalendarEvent) -> list[str]:
        clashing = [
            e
            for e in self._events[event.persona_id].values()
            if e.event_id != event.event_id
            and e.status != "declined"
            and overlaps(event.starts_at, event.ends_at, e.starts_at, e.ends_at)
        ]
        return [e.event_id for e in sorted(clashing, key=_sort_key)]

    def _busy(self, persona_id: str) -> list[tuple[datetime, datetime]]:
        return merge_intervals(
            (e.starts_at, e.ends_at)
            for e in self._events[persona_id].values()
            if e.status != "declined" and not (e.kind == "talk" and e.status == "proposed")  # a mere suggestion
        )

    def _talk_event(
        self,
        persona_id: str,
        talk: TalkHit,
        *,
        source: str,
        status: str,
        capture: bool,
        with_persona_ids: list[str] | None = None,
        note: str | None = None,
    ) -> CalendarEvent:
        start = talk.starts_at.astimezone(timezone.utc)
        return CalendarEvent(
            event_id=_new_event_id(),
            persona_id=persona_id,
            kind="talk",
            title=talk.title.strip()[:120] or _FALLBACK_TALK_TITLE,
            starts_at=start,
            ends_at=start + timedelta(minutes=self._seed.talk_minutes),
            location=talk.room.strip()[:80],
            status=status,
            capture=capture,
            source=source,
            talk_id=talk.talk_id,
            with_persona_ids=with_persona_ids or [],
            note=note,
        )

    def _existing_meeting(self, persona_id: str, other_id: str, now: datetime) -> CalendarEvent | None:
        shared = [
            e
            for e in self._events[persona_id].values()
            if e.kind == "meeting" and e.status != "declined" and other_id in e.with_persona_ids and e.ends_at > now
        ]
        return min(shared, key=_sort_key, default=None)

    def _create_meeting(self, body: ProposeBody, slot: tuple[datetime, datetime]) -> CalendarEvent:
        label, place = _MEETING_PLACES[body.purpose]
        meeting_id = _new_meeting_id()
        proposer, invitee = body.persona_id, body.with_persona_id
        responses = {proposer: "accepted", invitee: "pending"}
        notes = {
            proposer: f"Proposed by your agent · waiting for {self._names[invitee]}",
            invitee: f"{self._names[proposer]}'s agent proposed this · tap to confirm",
        }
        copies: dict[str, CalendarEvent] = {}
        for owner, other in ((proposer, invitee), (invitee, proposer)):
            copies[owner] = CalendarEvent(
                event_id=_new_event_id(),
                persona_id=owner,
                kind="meeting",
                title=f"{label} with {self._names[other]}",
                starts_at=slot[0],
                ends_at=slot[1],
                location=place,
                status="proposed",
                source="agent",
                meeting_id=meeting_id,
                with_persona_ids=[other],
                responses=dict(responses),
                note=notes[owner],
            )
            self._events[owner][copies[owner].event_id] = copies[owner]
        return copies[proposer]

    @staticmethod
    def _proposal(mine: CalendarEvent, *, created: bool) -> MeetingProposal:
        return MeetingProposal(
            meeting_id=mine.meeting_id or "",
            created=created,
            starts_at=mine.starts_at,
            ends_at=mine.ends_at,
            status=mine.status,
            event=_out(mine),
        )
