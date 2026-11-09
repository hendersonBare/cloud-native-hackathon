"""CalendarService rules: view, create, update, delete, respond, conference mode, talks and the encounter hook."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from calendar_support import NOW, UTC, local
from fastapi import HTTPException
from rapport_calendar.models import (
    AddTalkBody,
    ConferenceModeBody,
    CreateEventBody,
    RespondBody,
    UpdateEventBody,
)
from rapport_common.models import SharedBrief, TalkHit


def mine(persona_id="acme.sam", title="Focus time", start=None, end=None, **kw) -> CreateEventBody:
    return CreateEventBody(
        persona_id=persona_id, title=title, starts_at=start or local(0, 11), ends_at=end or local(0, 12), **kw
    )


async def code_of(awaitable) -> tuple[int, str]:
    with pytest.raises(HTTPException) as caught:
        await awaitable
    return caught.value.status_code, caught.value.detail


# ----------------------------------------------------------------------------- view
async def test_view_defaults_to_the_conference_week_sorted(service):
    view = await service.view("acme.ava")
    assert view.week_start == date(2026, 11, 9) and view.start == date(2026, 11, 9) and view.days == 7
    assert view.timezone == "America/Denver"
    assert view.now == NOW and view.conference_mode is True
    assert len(view.events) == 7
    assert view.events == sorted(view.events, key=lambda e: (e.starts_at, e.title))
    ebpf = next(e for e in view.events if e.event_id == "evt-ava-ebpf")
    assert ebpf.starts_at.isoformat() == "2026-11-09T22:30:00+00:00"


async def test_view_window_uses_local_days(service):
    monday = await service.view("acme.ava", date(2026, 11, 9), 1)
    assert [e.event_id for e in monday.events][-1] == "evt-ava-dinner"  # 18:30 MST is already Tuesday in UTC
    assert len(monday.events) == 5
    tuesday = await service.view("acme.ava", date(2026, 11, 10), 1)
    assert [e.event_id for e in tuesday.events] == ["evt-ava-priya"]
    assert (await service.view("acme.ava", date(2026, 11, 16), 3)).events == []


async def test_view_validates_inputs(service):
    assert await code_of(service.view("nobody.here")) == (404, "unknown_persona")
    assert await code_of(service.view("acme.ava", None, 0)) == (422, "invalid_days")
    assert await code_of(service.view("acme.ava", None, 15)) == (422, "invalid_days")
    assert await code_of(service.view("acme.ava", date.max, 7)) == (422, "invalid_start")


async def test_view_hides_declined_and_other_peoples_events(service):
    await service.respond("evt-ava-bo", RespondBody(persona_id="acme.ava", response="decline"))
    ids = {e.event_id for e in (await service.view("acme.ava")).events}
    assert "evt-ava-bo" not in ids and "evt-ava-priya" in ids
    assert (await service.view("acme.sam")).events == []  # a person with no seed events still has a calendar
    assert all(e.persona_id == "bluefin.bo" for e in (await service.view("bluefin.bo")).events)


async def test_returned_events_are_copies(service):
    view = await service.view("acme.ava")
    view.events[0].title = "Tampered"
    assert (await service.view("acme.ava")).events[0].title != "Tampered"


# ----------------------------------------------------------------------------- create
async def test_create_personal_event(service):
    result = await service.create_event(mine(title="  Focus time  ", location="Desk", capture=True))
    ev = result.event
    assert ev.event_id.startswith("evt-") and len(ev.event_id) == 16
    assert (ev.kind, ev.source, ev.status) == ("personal", "user", "confirmed")
    assert (ev.title, ev.capture) == ("Focus time", True)
    assert result.conflicts == []
    assert [e.event_id for e in (await service.view("acme.sam")).events] == [ev.event_id]


async def test_create_reports_conflicts_without_failing(service):
    result = await service.create_event(mine("acme.ava", start=local(0, 9, 30), end=local(0, 13, 45)))
    assert result.conflicts == ["evt-ava-keynote", "evt-ava-otel"]  # edge-touching events do not count
    touching = await service.create_event(mine("acme.ava", start=local(0, 14), end=local(0, 15)))
    assert touching.conflicts == []


@pytest.mark.parametrize(
    ("start", "end", "code"),
    [
        (local(0, 12), local(0, 12), "invalid_time_range"),
        (local(0, 12), local(0, 11), "invalid_time_range"),
        (local(0, 8), local(0, 20, 30), "event_too_long"),
        (local(-1, 12), local(-1, 13), "outside_conference_week"),
        (local(6, 23), local(7, 1), "outside_conference_week"),
    ],
)
async def test_create_rejects_bad_times(service, start, end, code):
    assert await code_of(service.create_event(mine(start=start, end=end))) == (422, code)


async def test_create_allows_exactly_twelve_hours_and_week_edges(service):
    await service.create_event(mine(start=local(0, 8), end=local(0, 20)))
    await service.create_event(mine(start=local(0, 0), end=local(0, 1)))
    await service.create_event(mine(start=local(6, 23), end=local(6, 23) + timedelta(hours=1)))


async def test_create_rejects_blank_title_and_naive_times():
    with pytest.raises(ValueError):
        CreateEventBody(persona_id="acme.sam", title="   ", starts_at=local(0, 9), ends_at=local(0, 10))
    with pytest.raises(ValueError):
        CreateEventBody(persona_id="acme.sam", title="x", starts_at="2026-11-09T09:00:00", ends_at=local(0, 10))


async def test_create_for_unknown_persona(service):
    assert await code_of(service.create_event(mine("nobody.here"))) == (404, "unknown_persona")


async def test_calendar_is_capped_at_200_events(service):
    for _ in range(200 - 7):  # Ava starts with 7
        await service.create_event(mine("acme.ava"))
    assert len(service._events["acme.ava"]) == 200
    assert await code_of(service.create_event(mine("acme.ava"))) == (409, "calendar_full")
    assert await code_of(service.add_talk(AddTalkBody(persona_id="acme.ava", talk_id="talk-hipaa-k8s"))) == (
        409,
        "calendar_full",
    )


# ----------------------------------------------------------------------------- update
async def test_capture_can_be_toggled_on_any_event(service):
    updated = await service.update_event("evt-ava-dinner", UpdateEventBody(persona_id="acme.ava", capture=True))
    assert updated.capture is True and updated.title == "Partner dinner"
    updated = await service.update_event("evt-ava-keynote", UpdateEventBody(persona_id="acme.ava", capture=False))
    assert updated.capture is False
    meeting = await service.update_event("evt-ava-priya", UpdateEventBody(persona_id="acme.ava", capture=True))
    assert meeting.capture is True


async def test_only_user_events_can_change_details(service):
    for body in (
        UpdateEventBody(persona_id="acme.ava", title="New"),
        UpdateEventBody(persona_id="acme.ava", location="Elsewhere"),
        UpdateEventBody(persona_id="acme.ava", starts_at=local(0, 9, 15)),
        UpdateEventBody(persona_id="acme.ava", capture=True, title="New"),
    ):
        assert await code_of(service.update_event("evt-ava-keynote", body)) == (409, "not_editable")
    assert (await service.view("acme.ava")).events[0].title == "Opening keynotes"


async def test_user_event_can_be_edited(service):
    ev = (await service.create_event(mine())).event
    body = UpdateEventBody(
        persona_id="acme.sam", title=" Deep work ", location="", starts_at=local(1, 9), ends_at=local(1, 10)
    )
    updated = await service.update_event(ev.event_id, body)
    assert (updated.title, updated.location) == ("Deep work", "")
    assert (updated.starts_at, updated.ends_at) == (local(1, 9).astimezone(UTC), local(1, 10).astimezone(UTC))
    only_end = await service.update_event(ev.event_id, UpdateEventBody(persona_id="acme.sam", ends_at=local(1, 11)))
    assert only_end.ends_at == local(1, 11).astimezone(UTC) and only_end.starts_at == local(1, 9).astimezone(UTC)


async def test_update_validates_resulting_times(service):
    ev = (await service.create_event(mine())).event
    # moving only the start past the existing end gives an empty range
    late_start = UpdateEventBody(persona_id="acme.sam", starts_at=local(0, 13))
    assert await code_of(service.update_event(ev.event_id, late_start)) == (422, "invalid_time_range")
    far_end = UpdateEventBody(persona_id="acme.sam", ends_at=local(8, 1))
    assert await code_of(service.update_event(ev.event_id, far_end)) == (422, "event_too_long")


def test_update_body_needs_a_field():
    with pytest.raises(ValueError):
        UpdateEventBody(persona_id="acme.sam")
    with pytest.raises(ValueError):
        UpdateEventBody(persona_id="acme.sam", title=None)


async def test_update_unknown_or_foreign_event_is_not_found(service):
    body = UpdateEventBody(persona_id="acme.sam", capture=True)
    assert await code_of(service.update_event("evt-nope", body)) == (404, "event_not_found")
    assert await code_of(service.update_event("evt-ava-keynote", body)) == (404, "event_not_found")  # Ava's, not Sam's
    assert await code_of(service.update_event("evt-ava-keynote", UpdateEventBody(persona_id="x.y", capture=True))) == (
        404,
        "unknown_persona",
    )


# ----------------------------------------------------------------------------- delete
async def test_delete_user_and_conference_events_only(service):
    ev = (await service.create_event(mine("acme.ava"))).event
    await service.delete_event(ev.event_id, "acme.ava")
    await service.delete_event("evt-ava-otel", "acme.ava")  # source "conference"
    ids = {e.event_id for e in (await service.view("acme.ava")).events}
    assert ev.event_id not in ids and "evt-ava-otel" not in ids
    for protected in ("evt-ava-keynote", "evt-ava-dinner", "evt-ava-priya"):  # seed, seed, agent meeting
        assert await code_of(service.delete_event(protected, "acme.ava")) == (409, "not_deletable")
    assert await code_of(service.delete_event(ev.event_id, "acme.ava")) == (404, "event_not_found")


async def test_delete_never_reveals_another_persons_event(service):
    assert await code_of(service.delete_event("evt-ava-otel", "acme.sam")) == (404, "event_not_found")
    assert any(e.event_id == "evt-ava-otel" for e in (await service.view("acme.ava")).events)


# ----------------------------------------------------------------------------- respond
async def test_meeting_is_confirmed_once_everyone_accepts(service):
    first = await service.respond("evt-ava-bo", RespondBody(persona_id="acme.ava", response="accept"))
    assert first.status == "proposed" and first.responses == {"acme.ava": "accepted", "bluefin.bo": "pending"}
    bo_copy = next(e for e in (await service.view("bluefin.bo")).events if e.event_id == "evt-bo-ava")
    assert bo_copy.responses == first.responses and bo_copy.status == "proposed"  # copies stay in sync

    second = await service.respond("evt-bo-ava", RespondBody(persona_id="bluefin.bo", response="accept"))
    assert second.status == "confirmed" and set(second.responses.values()) == {"accepted"}
    ava_copy = next(e for e in (await service.view("acme.ava")).events if e.event_id == "evt-ava-bo")
    assert ava_copy.status == "confirmed" and ava_copy.responses == second.responses
    assert second.note == ava_copy.note == "Confirmed by both"  # no longer asks anyone to confirm


async def test_declining_closes_the_meeting_for_both(service):
    declined = await service.respond("evt-bo-ava", RespondBody(persona_id="bluefin.bo", response="decline"))
    assert declined.status == "declined" and declined.responses["bluefin.bo"] == "declined"
    assert declined.note == "Declined by Bo" == service._events["acme.ava"]["evt-ava-bo"].note
    assert "evt-ava-bo" not in {e.event_id for e in (await service.view("acme.ava")).events}
    assert "evt-bo-ava" not in {e.event_id for e in (await service.view("bluefin.bo")).events}
    assert await code_of(service.respond("evt-ava-bo", RespondBody(persona_id="acme.ava", response="accept"))) == (
        409,
        "meeting_closed",
    )
    # the freed slot is free again for both people
    assert (await service.freebusy("acme.ava", local(2, 0), local(3, 0))).busy == []


async def test_a_confirmed_meeting_can_still_be_declined(service):
    declined = await service.respond("evt-ava-priya", RespondBody(persona_id="acme.ava", response="decline"))
    assert declined.status == "declined"
    assert "evt-priya-ava" not in {e.event_id for e in (await service.view("lumenly.priya")).events}


async def test_respond_rules(service):
    body = RespondBody(persona_id="acme.ava", response="accept")
    assert await code_of(service.respond("evt-ava-keynote", body)) == (409, "not_a_meeting")
    assert await code_of(service.respond("evt-nope", body)) == (404, "event_not_found")
    assert await code_of(service.respond("evt-bo-ava", body)) == (404, "event_not_found")  # Bo's copy, not Ava's
    # accepting twice is harmless
    await service.respond("evt-ava-bo", body)
    assert (await service.respond("evt-ava-bo", body)).status == "proposed"


# ----------------------------------------------------------------------------- conference mode and talks
async def test_conference_mode_sets_capture_for_talks_added_afterwards(service):
    assert (await service.view("acme.sam")).conference_mode is False
    off = await service.add_talk(AddTalkBody(persona_id="acme.sam", talk_id="talk-hipaa-k8s"))
    assert off.event.capture is False

    state = await service.set_conference_mode(ConferenceModeBody(persona_id="acme.sam", enabled=True))
    assert state.enabled is True and (await service.view("acme.sam")).conference_mode is True
    on = await service.add_talk(AddTalkBody(persona_id="acme.sam", talk_id="talk-finops-showback"))
    assert on.event.capture is True
    assert next(e for e in (await service.view("acme.sam")).events if e.event_id == off.event.event_id).capture is False

    await service.set_conference_mode(ConferenceModeBody(persona_id="acme.ava", enabled=False))
    ava = await service.add_talk(AddTalkBody(persona_id="acme.ava", talk_id="talk-hipaa-k8s"))
    assert ava.event.capture is False
    assert next(e for e in (await service.view("acme.ava")).events if e.event_id == "evt-ava-otel").capture is True


async def test_add_talk_builds_a_conference_event(service):
    result = await service.add_talk(AddTalkBody(persona_id="acme.sam", talk_id="talk-hipaa-k8s"))
    ev = result.event
    assert (ev.kind, ev.source, ev.status) == ("talk", "conference", "confirmed")
    assert (ev.location, ev.talk_id) == ("Room B", "talk-hipaa-k8s")
    assert ev.ends_at - ev.starts_at == timedelta(minutes=30)
    assert ev.starts_at == local(0, 13).astimezone(UTC)
    assert result.conflicts == []
    overlapping = await service.add_talk(AddTalkBody(persona_id="acme.sam", talk_id="talk-platform-golden-paths"))
    assert overlapping.conflicts == [ev.event_id]


async def test_add_talk_errors(service):
    unknown = AddTalkBody(persona_id="acme.sam", talk_id="talk-nope")
    assert await code_of(service.add_talk(unknown)) == (404, "unknown_talk")
    assert await code_of(service.add_talk(AddTalkBody(persona_id="nobody.here", talk_id="talk-hipaa-k8s"))) == (
        404,
        "unknown_persona",
    )
    assert await code_of(service.add_talk(AddTalkBody(persona_id="acme.ava", talk_id="talk-otel-regulated"))) == (
        409,
        "already_added",
    )
    await service.add_talk(AddTalkBody(persona_id="acme.sam", talk_id="talk-hipaa-k8s"))
    assert await code_of(service.add_talk(AddTalkBody(persona_id="acme.sam", talk_id="talk-hipaa-k8s"))) == (
        409,
        "already_added",
    )


# ----------------------------------------------------------------------------- encounter hook and reset
def brief_for(persona_id: str, talk: TalkHit | None) -> SharedBrief:
    return SharedBrief(
        encounter_id="enc-test0001", for_persona_id=persona_id, language="en", summary="Met at the booth.",
        suggested_talk=talk,
    )


KNOWN = "talk-hipaa-k8s"  # on the seed agenda, Monday 13:00 in Room B


def hit(talk_id="talk-new", title="A brand new talk") -> TalkHit:
    return TalkHit(
        talk_id=talk_id, title=title, starts_at=local(2, 14), room="Room C", track="AI Agents", speakers=["Zed"]
    )


async def test_shared_brief_adds_a_proposed_talk_once(service):
    event = await service.record_shared_brief(brief_for("acme.sam", hit(KNOWN)), "bluefin.bo")
    assert event is not None
    assert (event.kind, event.source, event.status, event.talk_id) == ("talk", "agent", "proposed", KNOWN)
    assert event.with_persona_ids == ["bluefin.bo"] and event.note == "Suggested by your agents"
    assert event.ends_at - event.starts_at == timedelta(minutes=30) and event.location == "Room B"
    assert await service.record_shared_brief(brief_for("acme.sam", hit(KNOWN)), "bluefin.bo") is None  # idempotent
    assert [e.talk_id for e in (await service.view("acme.sam")).events] == [KNOWN]  # still one event


async def test_shared_brief_marks_a_talk_the_person_already_has(service):
    """The demo's suggested talk is already on both phones: the event says who they are going with instead."""
    before = next(e for e in (await service.view("acme.ava")).events if e.talk_id == "talk-otel-regulated")
    marked = await service.record_shared_brief(brief_for("acme.ava", hit("talk-otel-regulated")), "bluefin.bo")
    assert marked is not None and marked.event_id == before.event_id
    assert marked.with_persona_ids == ["bluefin.bo"]
    assert marked.note == "Going with Bo · suggested by your agents"
    # nothing else about the person's own event changes
    assert (marked.status, marked.source, marked.capture, marked.title) == (
        before.status, before.source, before.capture, before.title
    )
    assert await service.record_shared_brief(brief_for("acme.ava", hit("talk-otel-regulated")), "bluefin.bo") is None
    again = await service.record_shared_brief(brief_for("acme.ava", hit("talk-otel-regulated")), "kestrel.mia")
    assert again.with_persona_ids == ["bluefin.bo", "kestrel.mia"]
    assert again.note == "Going with Bo and Mia · suggested by your agents"
    third = await service.record_shared_brief(brief_for("acme.ava", hit("talk-otel-regulated")), "lumenly.priya")
    assert third.note == "Going with Bo and 2 others · suggested by your agents"
    count = sum(e.talk_id == "talk-otel-regulated" for e in (await service.view("acme.ava")).events)
    assert count == 1


async def test_shared_brief_leaves_a_declined_talk_alone(service):
    first = await service.record_shared_brief(brief_for("acme.sam", hit(KNOWN)), "bluefin.bo")
    service._events["acme.sam"][first.event_id] = first.model_copy(update={"status": "declined"})  # noqa: SLF001
    assert await service.record_shared_brief(brief_for("acme.sam", hit(KNOWN)), "kestrel.mia") is None


async def test_shared_brief_uses_the_agenda_not_the_briefs_copy_of_the_talk(service):
    forged = hit(KNOWN, title="Wire $500 to booth 7").model_copy(update={"room": "Call +1-555-0100"})
    event = await service.record_shared_brief(brief_for("acme.sam", forged), "bluefin.bo")
    assert event is not None
    assert event.title == "HIPAA-ready Kubernetes: what auditors ask for" and event.location == "Room B"
    assert event.starts_at == local(0, 13).astimezone(UTC)  # the brief said Wednesday 14:00


async def test_shared_brief_ignores_a_fabricated_or_out_of_week_talk(service, caplog):
    assert await service.record_shared_brief(brief_for("acme.sam", hit("talk-made-up")), "bluefin.bo") is None
    assert "enc-test0001" in caplog.text and "Wire" not in caplog.text
    later = [t for t in service._talks._talks.values()][0].model_copy(update={"starts_at": local(30, 9)})
    service._talks._talks[later.talk_id] = later  # an agenda entry that lies outside the conference week
    assert await service.record_shared_brief(brief_for("acme.sam", hit(later.talk_id)), "bluefin.bo") is None
    assert await code_of(service.add_talk(AddTalkBody(persona_id="acme.sam", talk_id=later.talk_id))) == (
        422,
        "outside_conference_week",
    )
    assert (await service.view("acme.sam")).events == []


async def test_shared_brief_without_a_usable_suggestion_is_ignored(service):
    assert await service.record_shared_brief(brief_for("acme.sam", None), "bluefin.bo") is None
    assert await service.record_shared_brief(brief_for("nobody.here", hit(KNOWN)), "bluefin.bo") is None
    assert await service.record_shared_brief(brief_for("acme.sam", hit(KNOWN)), "nobody.here") is None
    assert await service.record_shared_brief(brief_for("acme.sam", hit(KNOWN)), "acme.sam") is None
    assert (await service.view("acme.sam")).events == []


async def test_shared_brief_respects_the_event_cap(service):
    for _ in range(200 - 7):
        await service.create_event(mine("acme.ava"))
    assert await service.record_shared_brief(brief_for("acme.ava", hit(KNOWN)), "acme.sam") is None


async def test_a_suggested_talk_can_be_accepted_or_dismissed(service):
    await service.set_conference_mode(ConferenceModeBody(persona_id="acme.sam", enabled=True))
    suggested = await service.record_shared_brief(brief_for("acme.sam", hit(KNOWN)), "bluefin.bo")
    # while it is only a suggestion it does not make the person busy
    assert (await service.freebusy("acme.sam", local(0, 0), local(1, 0))).busy == []
    accepted = (await service.add_talk(AddTalkBody(persona_id="acme.sam", talk_id=KNOWN))).event
    assert accepted.event_id == suggested.event_id
    assert (accepted.source, accepted.status, accepted.capture) == ("conference", "confirmed", True)
    assert accepted.note is None
    assert len((await service.view("acme.sam")).events) == 1
    assert len((await service.freebusy("acme.sam", local(0, 0), local(1, 0))).busy) == 1
    await service.delete_event(accepted.event_id, "acme.sam")  # now an ordinary conference event

    other = await service.record_shared_brief(brief_for("acme.sam", hit("talk-finops-showback")), "bluefin.bo")
    await service.delete_event(other.event_id, "acme.sam")  # dismissed
    assert (await service.view("acme.sam")).events == []
    assert await code_of(service.delete_event(other.event_id, "acme.sam")) == (404, "event_not_found")


async def test_reset_restores_the_seed(service):
    before = (await service.view("acme.ava")).events
    await service.create_event(mine("acme.ava"))
    await service.delete_event("evt-ava-otel", "acme.ava")
    await service.respond("evt-ava-bo", RespondBody(persona_id="acme.ava", response="decline"))
    await service.set_conference_mode(ConferenceModeBody(persona_id="acme.ava", enabled=False))
    await service.set_conference_mode(ConferenceModeBody(persona_id="acme.sam", enabled=True))
    service.reset()
    view = await service.view("acme.ava")
    assert view.events == before and view.conference_mode is True
    assert (await service.view("acme.sam")).conference_mode is False


async def test_pinned_clock_from_the_environment(monkeypatch, seed):
    from rapport_calendar.service import CalendarService

    monkeypatch.setenv("RAPPORT_CALENDAR_NOW", "2026-11-10T09:30:00-07:00")
    assert CalendarService(seed=seed).now() == local(1, 9, 30).astimezone(UTC)
    monkeypatch.setenv("RAPPORT_CALENDAR_NOW", "not a time")
    assert abs(CalendarService(seed=seed).now() - datetime.now(UTC)) < timedelta(seconds=5)  # the real clock
