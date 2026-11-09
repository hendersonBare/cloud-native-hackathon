"""Pure pieces: the seed, the slot finder and the ICS writer."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from rapport_calendar import ics, seed as seed_module, slots
from rapport_calendar.models import CalendarEvent

from calendar_support import MST, NOW, UTC, local

SEED_FILE = Path(seed_module.__file__).parent / "data" / "seed.json"
MOCK_FILE = Path(__file__).resolve().parents[2] / "web" / "mock" / "calendar-seed.json"


# ----------------------------------------------------------------------------- seed
def test_seed_converts_local_times_to_utc(seed):
    by_id = {e.event_id: e for e in seed.events}
    assert by_id["evt-ava-ebpf"].starts_at == datetime(2026, 11, 9, 22, 30, tzinfo=UTC)
    assert by_id["evt-ava-ebpf"].ends_at == datetime(2026, 11, 9, 23, 0, tzinfo=UTC)
    assert by_id["evt-ava-priya"].starts_at == datetime(2026, 11, 10, 22, 0, tzinfo=UTC)  # day 1, 15:00 MST
    assert seed.week_start == date(2026, 11, 9)
    assert seed.timezone_name == "America/Denver"
    assert (seed.work_start, seed.work_end) == (time(9, 0), time(18, 0))


def test_seed_agenda_and_meetings_are_consistent(seed):
    assert len(seed.agenda) == 15
    assert all(t.starts_at.tzinfo is not None for t in seed.agenda)
    assert seed.conference_mode == {"acme.ava": True, "bluefin.bo": True}
    meetings = [e for e in seed.events if e.kind == "meeting"]
    assert {e.meeting_id for e in meetings} == {"mtg-ava-priya", "mtg-ava-bo", "mtg-bo-sofia"}
    assert len({e.event_id for e in seed.events}) == len(seed.events)


def _write_seed(tmp_path, mutate) -> Path:
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_seed_rejects_duplicate_event_ids(tmp_path):
    path = _write_seed(tmp_path, lambda d: d["events"].append(dict(d["events"][0])))
    with pytest.raises(ValueError, match="duplicate"):
        seed_module.load_seed(path)


def test_seed_rejects_unknown_persona_and_bad_times(tmp_path):
    path = _write_seed(tmp_path, lambda d: d["events"][0].update(persona_id="nobody.here"))
    with pytest.raises(ValueError):
        seed_module.load_seed(path)
    path = _write_seed(tmp_path, lambda d: d["events"][0].update(start="25:00"))
    with pytest.raises(ValueError):
        seed_module.load_seed(path)


def test_seed_rejects_meeting_copies_that_disagree(tmp_path):
    def mutate(data):
        next(e for e in data["events"] if e["event_id"] == "evt-bo-ava")["start"] = "11:00"
        next(e for e in data["events"] if e["event_id"] == "evt-bo-ava")["end"] = "11:30"

    with pytest.raises(ValueError, match="disagree"):
        seed_module.load_seed(_write_seed(tmp_path, mutate))


def test_web_mock_seed_is_byte_identical():
    if not MOCK_FILE.exists():
        pytest.skip("web/mock/calendar-seed.json does not exist on this branch")
    assert MOCK_FILE.read_bytes() == SEED_FILE.read_bytes()


def test_offset_and_local_to_utc_helpers():
    assert seed_module.parse_offset("-07:00").utcoffset(None) == timedelta(hours=-7)
    assert seed_module.parse_offset("+05:30").utcoffset(None) == timedelta(hours=5, minutes=30)
    assert seed_module.local_to_utc(date(2026, 11, 9), 2, "10:15", MST) == datetime(2026, 11, 11, 17, 15, tzinfo=UTC)


# ----------------------------------------------------------------------------- slots
def test_overlap_is_half_open():
    a, b, c = local(0, 9), local(0, 10), local(0, 11)
    assert slots.overlaps(a, c, b, c)
    assert not slots.overlaps(a, b, b, c)  # back to back
    assert not slots.overlaps(b, c, a, b)


def test_merge_intervals_joins_overlapping_and_touching():
    iv = [(local(0, 11), local(0, 12)), (local(0, 9), local(0, 10)), (local(0, 10), local(0, 10, 30)),
          (local(0, 9, 30), local(0, 9, 45))]
    assert slots.merge_intervals(iv) == [(local(0, 9), local(0, 10, 30)), (local(0, 11), local(0, 12))]
    assert slots.merge_intervals([]) == []


def test_clip_intervals_trims_and_drops():
    iv = [(local(0, 8), local(0, 10)), (local(0, 11), local(0, 12)), (local(0, 13), local(0, 14))]
    assert slots.clip_intervals(iv, local(0, 9), local(0, 11)) == [(local(0, 9), local(0, 10))]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (local(0, 10, 7), local(0, 10, 15)),
        (local(0, 10, 15), local(0, 10, 15)),
        (local(0, 10, 15) + timedelta(seconds=1), local(0, 10, 30)),
        (local(0, 9), local(0, 9)),
        (local(0, 23, 50), local(1, 0)),
    ],
)
def test_ceil_to_grid(given, expected):
    assert slots.ceil_to_grid(given, MST) == expected.astimezone(UTC)


def _first(busy_a, busy_b, earliest, *, minutes=30):
    return slots.first_mutual_slot(
        busy_a, busy_b, earliest=earliest, duration=timedelta(minutes=minutes),
        days=[date(2026, 11, 9) + timedelta(days=i) for i in range(7)], tz=MST, work_start=time(9), work_end=time(18),
    )


def test_first_slot_skips_both_people_and_working_hours():
    assert _first([], [], local(0, 6)) == (local(0, 9).astimezone(UTC), local(0, 9, 30).astimezone(UTC))
    busy_a = [(local(0, 9), local(0, 10))]
    busy_b = [(local(0, 10), local(0, 10, 20))]
    assert _first(busy_a, busy_b, local(0, 8))[0] == local(0, 10, 30).astimezone(UTC)  # grid after 10:20


def test_slot_must_end_by_closing_time_and_skips_weekends():
    assert _first([], [], local(4, 17, 30))[0] == local(4, 17, 30).astimezone(UTC)  # Friday 17:30-18:00 fits
    assert _first([], [], local(4, 17, 45)) is None  # 17:45 would end at 18:15; Sat/Sun are skipped
    assert _first([], [], local(5, 10)) is None


# ----------------------------------------------------------------------------- ics
def _event(**kw) -> CalendarEvent:
    base = dict(event_id="evt-1", persona_id="acme.ava", kind="personal", title="Lunch", starts_at=local(0, 12),
                ends_at=local(0, 13), source="user")
    return CalendarEvent(**{**base, **kw})


def _unfold(text: str) -> str:
    return text.replace("\r\n ", "")


def test_ics_structure_crlf_and_utc_stamps():
    out = ics.render_calendar([_event(location="Lobby café")], now=NOW)
    assert out.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Rapport//Calendar//EN\r\n")
    assert out.endswith("END:VCALENDAR\r\n")
    assert out.count("\n") == out.count("\r\n")  # no bare LF
    assert "DTSTAMP:20261109T150000Z\r\n" in out
    assert "DTSTART:20261109T190000Z\r\n" in out and "DTEND:20261109T200000Z\r\n" in out
    assert "UID:evt-1@rapport.dev\r\n" in out
    assert "STATUS:CONFIRMED\r\n" in out
    assert "LOCATION:Lobby café\r\n" in out


def test_ics_proposed_is_tentative_and_declined_is_left_out():
    events = [_event(event_id="evt-p", status="proposed"), _event(event_id="evt-d", status="declined")]
    out = ics.render_calendar(events, now=NOW)
    assert "STATUS:TENTATIVE" in out
    assert "evt-p@rapport.dev" in out and "evt-d@rapport.dev" not in out


BS = chr(92)  # a single backslash
NL = chr(10)
CRLF = chr(13) + chr(10)
EXPECTED = "a" + BS + ";b" + BS + ",c" + BS + BS + "d" + BS + "ne" + BS + "nf"


def test_ics_escapes_text_values():
    assert ics.escape_text("a;b,c"+BS+"d"+NL+"e"+CRLF+"f") == EXPECTED
    out = ics.render_calendar([_event(title="Tea; milk, sugar\\more", location="Room\nB", note="n")], now=NOW)
    assert ("SUMMARY:Tea" + BS + "; milk" + BS + ", sugar" + BS + BS + "more" + CRLF) in out
    assert "LOCATION:Room\\nB\r\n" in out


def test_ics_folds_at_75_octets_and_unfolds_back():
    long_title = "x" * 119
    out = ics.render_calendar([_event(title=long_title)], now=NOW)
    lines = out.split("\r\n")
    assert all(len(line.encode()) <= 75 for line in lines)
    assert any(line.startswith(" ") for line in lines)
    assert f"SUMMARY:{long_title}\r\n" in _unfold(out)


def test_ics_folding_never_splits_a_multibyte_character():
    title = "é" * 60  # 120 octets
    folded = ics.fold_line(f"SUMMARY:{title}")
    parts = folded.split("\r\n")
    assert all(len(p.encode()) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert "".join([parts[0], *[p[1:] for p in parts[1:]]]) == f"SUMMARY:{title}"
    assert ics.fold_line("short") == "short"


def test_ics_includes_events_sorted_by_start():
    late, early = _event(event_id="evt-late", starts_at=local(1, 9), ends_at=local(1, 10)), _event(event_id="evt-early")
    out = ics.render_calendar([late, early], now=NOW)
    assert out.index("evt-early") < out.index("evt-late")


def test_utc_helpers_are_timezone_aware():
    assert ics.format_utc(datetime(2026, 11, 9, 9, 5, 7, tzinfo=timezone(timedelta(hours=-7)))) == "20261109T160507Z"
