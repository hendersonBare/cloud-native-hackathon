"""Schedule auto-enrollment (§5.3), consent (§8) and the models that guard them."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from rapport_speakers.chunking import Segment
from rapport_speakers.fixtures import Cluster, Recording, load
from rapport_speakers.models import Person, SessionDoc, Voiceprint
from rapport_speakers.pipeline import Pipeline, seed
from rapport_speakers.store import InMemorySpeakerStore
from rapport_speakers.vectors import dot, normalize

UTC = timezone.utc


def test_every_consenting_single_speaker_talk_is_enrolled_once(seeded, settings):
    store, report = seeded
    enrolled = dict(report.enroll.enrolled)
    assert len(enrolled) == 15
    assert enrolled["talk-ebpf-zero-code"] == "spk-dev"
    assert enrolled["talk-ebpf-edge"] == "kestrel.mia"  # a directory persona keeps its ID
    vp = store.voiceprints[f"{settings.conference_id}:spk-dev:{settings.model_id}"]
    assert vp.sample_count == 1 and vp.name == "Dev"
    assert dot(vp.centroid, vp.centroid) == pytest.approx(1.0)


def test_guards_flag_a_talk_where_the_speaker_does_not_dominate(seeded):
    _, report = seeded
    flagged = dict(report.enroll.flagged)
    assert "talk-search-ops-data" in flagged and "54%" in flagged["talk-search-ops-data"]


def test_no_consent_and_non_talk_sessions_are_never_enrolled(seeded, settings):
    store, report = seeded
    skipped = dict(report.enroll.skipped)
    assert skipped["talk-finops-showback"] == "no consent recorded"
    assert "keynote" in skipped["talk-closing-keynote"]
    assert not any(v.person_id in ("spk-rosa", "spk-marcus", "spk-ken") for v in store.voiceprints.values())


def test_panels_are_never_auto_enrolled(settings):
    fx = load()
    start = datetime(2026, 11, 9, 20, tzinfo=UTC)
    panel = SessionDoc(session_id="panel-1", conference_id=settings.conference_id, title="Panel", room="Room A",
                       start_time=start, end_time=start, scheduled_speaker_ids=["spk-dev", "kestrel.mia"],
                       session_type="panel")
    rec = fx.recordings["talk-ebpf-zero-code"]
    report = Pipeline(InMemorySpeakerStore(), settings).enroll_from_schedule(
        [panel], {"panel-1": rec}, fx.people)
    assert report.enrolled == [] and "panel" in report.skipped[0][1]


def test_enrollment_records_corroboration_from_the_chair_intro(seeded):
    store, _ = seeded
    sample = next(s for s in store.samples.values() if s.session_id == "talk-ebpf-zero-code")
    assert sample.source == "schedule" and sample.corroborated is True
    assert sample.duration_s <= 60.0  # about 60 s of clean speech per embedding


def test_minimum_speech_guard(settings):
    fx = load()
    start = datetime(2026, 11, 9, 20, tzinfo=UTC)
    session = SessionDoc(session_id="short", conference_id=settings.conference_id, title="Lightning", room="Room A",
                         start_time=start, end_time=start, scheduled_speaker_ids=["spk-dev"])
    emb = fx.recordings["talk-ebpf-zero-code"].clusters[1].embedding
    rec = Recording("short", "recordings/short.mp4", [Cluster("SPEAKER_00", emb)],
                    [Segment(0, 45, "SPEAKER_00", "A short talk.")])
    report = Pipeline(InMemorySpeakerStore(), settings).enroll_from_schedule([session], {"short": rec}, fx.people)
    assert report.enrolled == [] and "45s" in report.flagged[0][1]


def test_registration_adds_a_sample_and_recomputes_the_centroid(pipeline, seeded, settings):
    store, _ = seeded
    fx = load()
    clip = fx.registration_clips["chair-noor"]
    first, _ = pipeline.enroll_registration(fx.people["chair-noor"], clip)
    assert first.sample_count == 1
    other = fx.recordings["talk-platform-golden-paths"].clusters[0]  # Noor's intro in Room A
    second, _ = pipeline.enroll_registration(
        fx.people["chair-noor"], clip.__class__("chair-noor", 12.0, "registration/second.wav", other.embedding))
    assert second.sample_count == 2 and second.total_speech_s == pytest.approx(32.0)
    expected = normalize([a + b for a, b in zip(clip.embedding, other.embedding)])
    assert second.centroid == pytest.approx(expected, abs=1e-9)


def test_voices_without_consent_are_refused(pipeline):
    fx = load()
    nobody = Person(person_id="spk-rosa", name="Rosa")
    with pytest.raises(PermissionError):
        pipeline.enroll_registration(nobody, fx.registration_clips["chair-noor"])


def test_voiceprint_model_requires_consent_and_unit_vectors(settings):
    base = dict(person_id="p", name="P", conference_id="c", model_id="m", sample_count=1, total_speech_s=1.0,
                updated_at=datetime.now(UTC))
    unit = normalize([1.0] * 192)
    with pytest.raises(ValidationError):
        Voiceprint(**base, centroid=unit)  # no consent_granted_at
    with pytest.raises(ValidationError):
        Voiceprint(**base, centroid=[1.0] * 192, consent_granted_at=datetime.now(UTC))  # not unit length
    with pytest.raises(ValidationError):
        Voiceprint(**base, centroid=unit[:100], consent_granted_at=datetime.now(UTC))  # wrong dims
    with pytest.raises(ValidationError):
        Voiceprint(**base, centroid=unit, consent_granted_at=datetime(2026, 1, 1))  # naive datetime
    assert Voiceprint(**base, centroid=unit, consent_granted_at=datetime.now(UTC)).doc_id == "c:p:m"


def test_seeding_twice_is_idempotent(settings, conf_day):
    store = InMemorySpeakerStore()
    first = seed(store, settings, now=conf_day)
    labels = {k: (u.speaker_id, u.speaker_status) for k, u in store.utterances.items()}
    second = seed(store, settings, now=conf_day)
    assert second.counts == first.counts
    assert {k: (u.speaker_id, u.speaker_status) for k, u in store.utterances.items()} == labels
