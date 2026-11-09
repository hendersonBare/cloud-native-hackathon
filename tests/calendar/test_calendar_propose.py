"""The scheduling engine: deterministic first mutual slot, privacy of the invitee's calendar, free/busy."""

from __future__ import annotations

from datetime import timedelta

import pytest
from calendar_support import NOW, UTC, local
from fastapi import HTTPException
from rapport_calendar.agenda import SeedTalkSource
from rapport_calendar.models import CreateEventBody, ProposeBody, RespondBody
from rapport_calendar.service import CalendarService


def utc(moment):
    return moment.astimezone(UTC)


def book(service: CalendarService, persona_id, start, end, title="Busy"):
    return service.create_event(CreateEventBody(persona_id=persona_id, title=title, starts_at=start, ends_at=end))


async def test_first_slot_after_the_proposers_own_commitments(service):
    # Ava has the keynote 09:00-10:00 on Monday; the clock reads Monday 08:00 local.
    proposal = await service.propose(ProposeBody(persona_id="acme.ava", with_persona_id="acme.sam"))
    assert proposal.created is True and proposal.status == "proposed"
    assert (proposal.starts_at, proposal.ends_at) == (utc(local(0, 10)), utc(local(0, 10, 30)))
    assert proposal.meeting_id.startswith("mtg-") and len(proposal.meeting_id) == 16


async def test_slot_skips_both_peoples_busy_blocks(service):
    await book(service, "acme.sam", local(0, 10), local(0, 11))  # invitee busy
    await book(service, "acme.ava", local(0, 11), local(0, 11, 20))  # proposer busy, off the quarter-hour grid
    proposal = await service.propose(ProposeBody(persona_id="acme.ava", with_persona_id="acme.sam"))
    assert proposal.starts_at == utc(local(0, 11, 30))


async def test_declined_events_do_not_block_a_slot(service):
    await service.respond("evt-ava-bo", RespondBody(persona_id="acme.ava", response="decline"))
    await book(service, "bluefin.bo", local(2, 9), local(2, 9, 30))
    proposal = await service.propose(
        ProposeBody(persona_id="acme.ava", with_persona_id="bluefin.bo", not_before=local(2, 9))
    )
    assert proposal.created is True and proposal.starts_at == utc(local(2, 9, 30))


async def test_not_before_is_rounded_up_to_the_grid(service):
    proposal = await service.propose(
        ProposeBody(persona_id="bluefin.kai", with_persona_id="acme.sam", not_before=local(1, 10, 7))
    )
    assert proposal.starts_at == utc(local(1, 10, 15))


async def test_before_the_week_or_before_opening_time_starts_at_nine_monday(service):
    # nothing earlier than Monday 09:00 local, whatever not_before says
    proposal = await service.propose(
        ProposeBody(persona_id="lumenly.tom", with_persona_id="kestrel.raj", not_before=local(-3, 2))
    )
    assert proposal.starts_at == utc(local(0, 9))


async def test_duration_and_purpose(service):
    proposal = await service.propose(
        ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj", duration_minutes=45, purpose="meeting")
    )
    assert proposal.ends_at - proposal.starts_at == timedelta(minutes=45)
    assert (proposal.event.title, proposal.event.location) == ("Meeting with Raj", "Meeting room 2")


async def test_slot_must_end_by_six_pm_and_weekends_are_skipped(service):
    friday_late = local(4, 17, 45)
    with pytest.raises(HTTPException) as caught:
        await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj", not_before=friday_late))
    assert (caught.value.status_code, caught.value.detail) == (409, "no_mutual_slot")  # Sat and Sun are not offered
    ok = await service.propose(
        ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj", not_before=local(4, 17, 30))
    )
    assert (ok.starts_at, ok.ends_at) == (utc(local(4, 17, 30)), utc(local(4, 18)))


async def test_no_mutual_slot_when_the_week_is_full(service):
    for day in range(5):
        await book(service, "kestrel.raj", local(day, 9), local(day, 18))
    with pytest.raises(HTTPException) as caught:
        await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj"))
    assert (caught.value.status_code, caught.value.detail) == (409, "no_mutual_slot")
    assert (await service.view("acme.sam")).events == []  # nothing half-created


async def test_proposal_creates_a_templated_copy_for_each_person(service):
    proposal = await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj"))
    mine = proposal.event
    assert mine.persona_id == "acme.sam" and mine.kind == "meeting" and mine.source == "agent"
    assert (mine.title, mine.location, mine.status) == ("Coffee with Raj", "Lobby café", "proposed")
    assert mine.note == "Proposed by your agent · waiting for Raj"
    assert mine.with_persona_ids == ["kestrel.raj"]
    assert mine.responses == {"acme.sam": "accepted", "kestrel.raj": "pending"}

    theirs = next(e for e in (await service.view("kestrel.raj")).events if e.meeting_id == proposal.meeting_id)
    assert theirs.event_id != mine.event_id and theirs.persona_id == "kestrel.raj"
    assert (theirs.title, theirs.location, theirs.status) == ("Coffee with Sam", "Lobby café", "proposed")
    assert theirs.note == "Sam's agent proposed this · tap to confirm"
    assert theirs.responses == mine.responses
    assert (theirs.starts_at, theirs.ends_at) == (mine.starts_at, mine.ends_at)

    accepted = await service.respond(theirs.event_id, RespondBody(persona_id="kestrel.raj", response="accept"))
    assert accepted.status == "confirmed"
    assert (await service.view("acme.sam")).events[0].status == "confirmed"


async def test_proposing_again_returns_the_existing_meeting(service):
    first = await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj"))
    again = await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj"))
    reverse = await service.propose(ProposeBody(persona_id="kestrel.raj", with_persona_id="acme.sam"))
    assert again.created is False and again.meeting_id == first.meeting_id
    assert again.event.event_id == first.event.event_id
    assert reverse.created is False and reverse.meeting_id == first.meeting_id
    assert reverse.event.persona_id == "kestrel.raj"
    assert len((await service.view("acme.sam")).events) == 1


async def test_an_existing_seed_meeting_is_reused(service):
    existing = await service.propose(ProposeBody(persona_id="acme.ava", with_persona_id="lumenly.priya"))
    assert existing.created is False and existing.meeting_id == "mtg-ava-priya" and existing.status == "confirmed"


async def test_a_declined_meeting_can_be_proposed_again(service):
    first = await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj"))
    await service.respond(first.event.event_id, RespondBody(persona_id="acme.sam", response="decline"))
    second = await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj"))
    assert second.created is True and second.meeting_id != first.meeting_id
    assert second.starts_at == first.starts_at  # the declined slot was freed


async def test_a_past_meeting_does_not_block_a_new_one(seed):
    clock = [NOW]
    svc = CalendarService(seed=seed, talk_source=SeedTalkSource(seed.agenda), now=lambda: clock[0])
    body = ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj")
    first = await svc.propose(body)
    clock[0] = first.ends_at + timedelta(hours=1)  # the meeting is now in the past
    second = await svc.propose(body)
    assert second.created is True and second.meeting_id != first.meeting_id
    assert second.starts_at >= clock[0]


async def test_invalid_proposals(service):
    async def code(body):
        with pytest.raises(HTTPException) as caught:
            await service.propose(body)
        return caught.value.status_code, caught.value.detail

    assert await code(ProposeBody(persona_id="acme.sam", with_persona_id="acme.sam")) == (422, "same_person")
    assert await code(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj", duration_minutes=20)) == (
        422,
        "invalid_duration",
    )
    assert await code(ProposeBody(persona_id="nobody.here", with_persona_id="kestrel.raj")) == (404, "unknown_persona")
    assert await code(ProposeBody(persona_id="acme.sam", with_persona_id="nobody.here")) == (404, "unknown_persona")
    for minutes in (10, 121):
        with pytest.raises(ValueError):
            ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj", duration_minutes=minutes)
    with pytest.raises(ValueError):
        ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj", not_before="2026-11-09T10:00:00")


async def test_a_full_calendar_blocks_proposals(service):
    for _ in range(200):
        await book(service, "kestrel.raj", local(0, 6), local(0, 7))
    with pytest.raises(HTTPException) as caught:
        await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj"))
    assert (caught.value.status_code, caught.value.detail) == (409, "calendar_full")


async def test_the_invitees_event_details_never_reach_the_proposer(service):
    await book(service, "kestrel.raj", local(0, 9), local(0, 11), title="Confidential acquisition talks")
    proposal = await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj"))
    leaked = proposal.model_dump_json() + (await service.view("acme.sam")).model_dump_json()
    assert "Confidential" not in leaked and "acquisition" not in leaked
    assert proposal.starts_at == utc(local(0, 11))  # but the busy time was respected
    free = await service.freebusy("kestrel.raj", local(0, 0), local(1, 0))
    assert set(free.model_dump()) == {"persona_id", "timezone", "start", "end", "busy"}
    assert "Confidential" not in free.model_dump_json()


# ----------------------------------------------------------------------------- free/busy
async def test_freebusy_is_merged_clipped_and_title_free(service):
    await book(service, "acme.sam", local(0, 9), local(0, 10), "Secret one")
    await book(service, "acme.sam", local(0, 10), local(0, 11), "Secret two")  # touching: merged
    await book(service, "acme.sam", local(0, 10, 30), local(0, 11, 30), "Secret three")  # overlapping: merged
    await book(service, "acme.sam", local(0, 14), local(0, 15), "Secret four")
    await book(service, "acme.sam", local(1, 9), local(1, 10), "Next day")
    result = await service.freebusy("acme.sam", local(0, 9, 30), local(0, 14, 30))
    assert [(b.starts_at, b.ends_at) for b in result.busy] == [
        (utc(local(0, 9, 30)), utc(local(0, 11, 30))),
        (utc(local(0, 14)), utc(local(0, 14, 30))),
    ]
    assert "Secret" not in result.model_dump_json()
    assert (result.start, result.end) == (utc(local(0, 9, 30)), utc(local(0, 14, 30)))


async def test_freebusy_ignores_declined_events_and_validates_the_window(service):
    await service.respond("evt-ava-bo", RespondBody(persona_id="acme.ava", response="decline"))
    assert (await service.freebusy("acme.ava", local(2, 0), local(3, 0))).busy == []

    async def code(start, end, persona="acme.ava"):
        with pytest.raises(HTTPException) as caught:
            await service.freebusy(persona, start, end)
        return caught.value.status_code, caught.value.detail

    assert await code(local(1, 0), local(1, 0)) == (422, "invalid_window")
    assert await code(local(1, 0), local(0, 0)) == (422, "invalid_window")
    assert await code(local(0, 0), local(15, 0)) == (422, "invalid_window")
    two_weeks = await service.freebusy("acme.ava", local(0, 0), local(14, 0))  # exactly 14 days is allowed
    assert len(two_weeks.busy) == 5
    assert await code(local(0, 0), local(1, 0), "nobody.here") == (404, "unknown_persona")
    naive = local(0, 0).replace(tzinfo=None)
    assert await code(naive, local(1, 0)) == (422, "naive_datetime")


# ----------------------------------------------------------------------------- the clock and the cap
async def test_a_past_not_before_never_schedules_in_the_past(seed):
    now = local(2, 13)  # Wednesday 13:00 local
    svc = CalendarService(seed=seed, talk_source=SeedTalkSource(seed.agenda), now=lambda: now)
    body = ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj", not_before=local(0, 9))
    first = await svc.propose(body)
    assert first.created is True and first.starts_at >= utc(now)
    again = await svc.propose(body)  # idempotent: the earlier request's meeting is found
    assert again.created is False and again.meeting_id == first.meeting_id
    assert len((await svc.view("acme.sam", local(0, 0).date(), 7)).events) == 1


async def test_propose_and_decline_loops_cannot_fill_anothers_calendar(service):
    sam = ProposeBody(persona_id="acme.sam", with_persona_id="acme.ava")
    for _ in range(250):  # more than the cap, from a person at another desk
        proposal = await service.propose(sam)
        await service.respond(proposal.event.event_id, RespondBody(persona_id="acme.sam", response="decline"))
    assert len(service._events["acme.ava"]) < 50  # old declined copies are pruned
    made = await book(service, "acme.ava", local(3, 9), local(3, 10))
    assert made.event.persona_id == "acme.ava"
