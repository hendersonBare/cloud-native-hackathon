"""Seed records match the storyline in SPEC section 11 and docs/FEATURE-DISCOVER.md."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rapport_common import names
from rapport_common.models import TAG, MemoryRecord
from rapport_memory.seed import all_indices, main, seed_records
from rapport_memory.seed_talks import DENVER, conference_day

ROOT = Path(__file__).resolve().parents[2]
RECORDS = seed_records()
BY_ID = {r.memory_id: r for r in RECORDS}


def test_ids_are_unique_and_records_validate():
    assert len(BY_ID) == len(RECORDS)
    for r in RECORDS:
        MemoryRecord.model_validate(r.model_dump())
        assert len(r.summary) <= 400
        assert r.created_at.tzinfo is not None
        assert all(re.match(TAG, t) for t in r.tags), r.memory_id


def test_all_five_indices_get_records():
    counts = Counter(names.index_for(r) for r in RECORDS)
    assert set(counts) == set(all_indices()) == {
        names.CONFERENCE_INDEX, names.shareable_index("acme"), names.internal_index("acme"),
        names.shareable_index("bluefin"), names.internal_index("bluefin"),
    }
    assert all(n > 0 for n in counts.values())


SPEC_DOCS = {
    # id: (org, level, kind, tags)
    "acme-doc-0001": ("acme", "public", "document", {"ebpf", "observability", "product"}),
    "acme-doc-0002": ("acme", "public", "document", {"healthcare", "ebpf", "case-study"}),
    "acme-doc-0003": ("acme", "partner", "document", {"security", "hipaa", "compliance"}),
    "acme-doc-0004": ("acme", "partner", "document", {"pricing"}),
    "acme-doc-0005": ("acme", "public", "document", {"conference"}),
    "acme-note-0007": ("acme", "internal", "account_note", None),
    "acme-doc-0008": ("acme", "internal", "document", {"pricing"}),
    "bluefin-doc-0001": ("bluefin", "partner", "document", {"platform-engineering", "kubernetes", "requirements"}),
    "bluefin-doc-0002": ("bluefin", "public", "document", {"kubernetes", "platform-engineering"}),
    "bluefin-note-0003": ("bluefin", "internal", "account_note", None),
}


@pytest.mark.parametrize("memory_id", SPEC_DOCS)
def test_company_documents_match_the_spec(memory_id):
    org, level, kind, tags = SPEC_DOCS[memory_id]
    r = BY_ID[memory_id]
    assert (r.org_id, r.share_level, r.kind) == (org, level, kind)
    if tags is not None:
        assert set(r.tags) == tags


def test_storyline_notes():
    note = BY_ID["acme-note-0007"]
    assert note.title == "Call notes: Bluefin pilot (March)"
    assert note.about_org_ids == ["bluefin"]
    assert set(note.about_persona_ids) == {"bluefin.kai", "bluefin.bo"}
    assert note.text == (
        "Sam promised Kai the security questionnaire before the pilot starts. "
        "Bluefin is also evaluating a competitor. Budget decision in Q1."
    )
    evaluation = BY_ID["bluefin-note-0003"]
    assert evaluation.title == "Vendor evaluation: Acme" and evaluation.about_org_ids == ["acme"]
    assert evaluation.text == (
        "Likes Acme's zero-code eBPF approach; Kai must sign off on HIPAA; cost is the main concern."
    )
    assert names.index_for(BY_ID["acme-doc-0008"]) == names.internal_index("acme")


def test_enough_talks_inside_the_conference_window():
    talks = [r for r in RECORDS if r.kind == "talk"]
    assert len(talks) >= 15
    day = conference_day()
    for t in talks:
        info = t.talk
        for moment in (info.starts_at, info.ends_at):
            assert moment.tzinfo is not None and moment.utcoffset() == timedelta(0)  # aware UTC
        start, end = info.starts_at.astimezone(DENVER), info.ends_at.astimezone(DENVER)
        assert start.date() == day == end.date()
        assert (start.hour, start.minute) >= (13, 0), t.memory_id
        assert (end.hour, end.minute) <= (17, 30), t.memory_id
    assert {t.talk.track for t in talks} >= {
        "Observability", "Platform Engineering", "Security and HIPAA", "Cost and FinOps", "OpenTelemetry",
        "AI Agents", "Accessibility",
    }


def test_headline_talk_is_exactly_as_specified():
    t = BY_ID["talk-ebpf-zero-code"]
    local = t.talk.starts_at.astimezone(DENVER)
    assert t.title == "Zero-code tracing with eBPF on Kubernetes"
    assert (local.hour, local.minute, local.tzname()) == (15, 30, "MST")
    assert t.talk.room == "Room B" and t.talk.track == "Observability"
    assert t.tags == ["ebpf", "observability", "kubernetes"]
    assert (t.org_id, t.share_level) == ("conference", "public")


@pytest.mark.parametrize(
    "memory_id,title,hour,minute,room,speaker",
    [
        ("talk-ebpf-cost", "Cutting the cloud bill with eBPF", 14, 30, "Room A", "lumenly.priya"),
        ("talk-ebpf-edge", "eBPF on warehouse robots", 16, 0, "Room C", "kestrel.mia"),
        ("talk-otel-regulated", "OpenTelemetry in regulated industries", 13, 30, "Room B", "harborline.lena"),
        ("talk-inclusive-confs", "Designing conferences for everyone", 16, 30, "Room A", "lumenly.tom"),
    ],
)
def test_speaker_linked_talks(memory_id, title, hour, minute, room, speaker):
    t = BY_ID[memory_id]
    local = t.talk.starts_at.astimezone(DENVER)
    assert t.title == title and t.talk.room == room
    assert (local.hour, local.minute) == (hour, minute)
    assert t.about_persona_ids == [speaker]
    assert t.talk.speakers == [names.persona(speaker).name]


def test_talk_times_follow_today_in_denver():
    late_utc = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)  # still Nov 9 evening in Denver
    talks = [r for r in seed_records(late_utc) if r.kind == "talk"]
    assert {t.talk.starts_at.astimezone(DENVER).date().isoformat() for t in talks} == {"2026-11-09"}
    zero = next(t for t in talks if t.memory_id == "talk-ebpf-zero-code")
    assert zero.talk.starts_at == datetime(2026, 11, 9, 22, 30, tzinfo=timezone.utc)  # 3:30 PM MST = 22:30Z


def test_profile_cards():
    for persona_id in ("acme.ava", "acme.sam", "bluefin.bo", "bluefin.kai"):
        shareable = BY_ID[f"profile-{persona_id}-shareable"]
        private = BY_ID[f"profile-{persona_id}-private"]
        assert (shareable.kind, shareable.share_level, shareable.profile.visibility) == (
            "profile", "public", "shareable"
        )
        assert (private.kind, private.share_level, private.profile.visibility) == ("profile", "internal", "private")
        assert shareable.owner_persona_id == private.owner_persona_id == persona_id
        assert shareable.org_id == private.org_id == names.org_of(persona_id)
        assert names.index_for(shareable) == names.shareable_index(names.org_of(persona_id))
        assert names.index_for(private) == names.internal_index(names.org_of(persona_id))
        assert 1 <= len(shareable.profile.goals[:3]) <= 3
    assert "Find a healthcare design partner this quarter" in BY_ID["profile-acme.ava-private"].profile.goals
    # private goals never appear in the shareable view
    assert "healthcare design partner" not in json.dumps(BY_ID["profile-acme.ava-shareable"].model_dump(mode="json"))


def test_attendee_cards_cover_all_twelve_personas_and_match_the_discover_fixture():
    assert len(names.personas()) == 12
    for persona_id, person in names.personas().items():
        card = BY_ID[names.attendee_card_id(persona_id)]
        assert (card.kind, card.share_level, card.org_id) == ("attendee", "public", person.org_id)
        assert card.owner_persona_id == persona_id
        assert card.profile.visibility == "shareable"
        assert names.index_for(card) == names.CONFERENCE_INDEX
        assert card.profile.interests == person.interests
    fixture = json.loads((ROOT / "contracts" / "demo-research.json").read_text())
    for expected in fixture["cards"]:
        card = BY_ID[names.attendee_card_id(expected["persona_id"])]
        assert card.profile.headline == expected["headline"]
        assert card.profile.interests == expected["interests"]
        assert card.profile.goals[: len(expected["looking_for"])] == expected["looking_for"]


def test_no_contact_details_anywhere():
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    phone = re.compile(r"\+?\d[\d\s().-]{7,}\d")
    texts = [json.dumps(r.model_dump(mode="json", exclude={"created_at", "talk"})) for r in RECORDS]
    texts.append((ROOT / "seed" / "ava-cv-synthetic.md").read_text())
    for text in texts:
        assert not email.search(text) and not phone.search(text)


def test_cv_is_present_and_synthetic():
    cv = (ROOT / "seed" / "ava-cv-synthetic.md").read_text()
    assert "synthetic" in cv.lower() and len(cv) < 2_000_000


def test_seed_loader_upserts_everything_and_reports_counts(monkeypatch, caplog):
    import rapport_memory.client as client_module

    seen = {}

    class StubClient:
        def __init__(self, es_url, api_key, *, allowed_indices=None, **_):
            seen.update(url=es_url, allowed=allowed_indices)

        def write(self, records):
            seen["written"] = records
            return len(records)

        def count(self, indices):
            return {i: 1 for i in indices}

    monkeypatch.setattr(client_module, "MemoryClient", StubClient)
    monkeypatch.setenv("ES_URL", "https://es.invalid:443")
    monkeypatch.setenv("ES_ADMIN_API_KEY", "not-a-real-key")
    with caplog.at_level("INFO", logger="rapport.memory.seed"):
        assert main() == 0
    assert {r.memory_id for r in seen["written"]} == set(BY_ID)
    assert set(seen["allowed"]) == set(all_indices())
    logged = "\n".join(rec.getMessage() for rec in caplog.records)
    assert all(index in logged for index in all_indices()) and "not-a-real-key" not in logged


def test_seed_loader_exits_nonzero_without_credentials(monkeypatch, capsys):
    monkeypatch.delenv("ES_URL", raising=False)
    monkeypatch.delenv("ES_ADMIN_API_KEY", raising=False)
    assert main() == 2
    err = capsys.readouterr().err
    assert "ES_URL" in err and "ES_ADMIN_API_KEY" in err
