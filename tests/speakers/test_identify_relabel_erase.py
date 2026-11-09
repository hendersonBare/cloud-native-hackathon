"""Identification (§5.4), retroactive relabeling (§5.5), erasure and retention (§8)."""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from rapport_speakers.config import POOL_FILTER
from rapport_speakers.fixtures import load
from rapport_speakers.models import UnknownVoice
from rapport_speakers.pipeline import Pipeline, seed, voice_ids
from rapport_speakers.store import InMemorySpeakerStore


def decisions(report, session_id):
    rep = next(r for r in report.identify if r.session_id == session_id)
    return {d.label: d for d in rep.decisions}


def test_two_pass_identifies_a_question_from_a_later_sessions_speaker(seeded):
    _, report = seeded
    d = decisions(report, "talk-ebpf-zero-code")  # 3:30 PM; Mia only speaks herself at 4:00 PM
    assert (d["SPEAKER_01"].status, d["SPEAKER_01"].person_id) == ("identified", "spk-dev")
    assert (d["SPEAKER_02"].status, d["SPEAKER_02"].person_id) == ("identified", "kestrel.mia")
    assert d["SPEAKER_03"].person_id == "lumenly.priya"


def test_unknown_ambiguous_and_too_short_voices_are_never_named(seeded):
    store, report = seeded
    d = decisions(report, "talk-ebpf-zero-code")
    assert d["SPEAKER_00"].status == "unknown"  # the chair has not enrolled
    assert d["SPEAKER_04"].status == "unknown"  # an attendee who never enrolled
    assert d["SPEAKER_05"].status == "ambiguous"  # handheld mic between two enrolled voices
    assert d["SPEAKER_06"].status == "unknown" and d["SPEAKER_06"].speech_s == 0  # "Thank you!" over applause
    named = {u.speaker_name for u in store.utterances.values()
             if u.session_id == "talk-ebpf-zero-code" and u.speaker_status != "identified"}
    assert named == {"Unknown speaker 1", "Unknown speaker 5", "Unknown speaker 6", "Unknown speaker 7"}
    amb = store.unknown_voices["unk_talk-ebpf-zero-code_05"]
    assert amb.status == "ambiguous" and {amb.best_candidate_id, amb.runner_up_id} == {"spk-arjun", "harborline.lena"}


def test_utterances_are_chunked_to_at_most_60_seconds_on_sentence_boundaries(seeded):
    store, _ = seeded
    talk = sorted((u for u in store.utterances.values() if u.session_id == "talk-ebpf-zero-code"),
                  key=lambda u: u.start_s)
    assert all(u.end_s - u.start_s <= 60 or u.text.count(".") <= 1 for u in talk)
    first = talk[1]  # three back-to-back sentences from Dev merge into one window
    assert (first.start_s, first.end_s, first.speaker_id) == (20, 75, "spk-dev")
    assert {u.voice_id for u in talk if u.speaker_id == "spk-dev"} == {"unk_talk-ebpf-zero-code_01"}


def test_filter_mode_trades_recall_for_a_smaller_pool(settings, conf_day):
    store = InMemorySpeakerStore()
    report = seed(store, replace(settings, pool_mode=POOL_FILTER), now=conf_day)
    d = decisions(report, "talk-ebpf-zero-code")
    assert d["SPEAKER_01"].person_id == "spk-dev"
    assert d["SPEAKER_02"].status == "unknown"  # Mia is not scheduled here, so a hard filter cannot name her


def test_registration_relabels_every_past_intro_by_that_chair(pipeline, seeded):
    store, _ = seeded
    fx = load()
    _, relabel = pipeline.enroll_registration(fx.people["chair-felix"], fx.registration_clips["chair-felix"])
    room_b = sorted(sid for sid, rec in fx.recordings.items()
                    if store.get_session(pipeline.s.conference_id, sid).room == "Room B")
    assert sorted(relabel.voices) == sorted(voice_ids(sid, "SPEAKER_00")[0] for sid in room_b)
    assert relabel.utterances == len(room_b)
    intro = store.utterances["talk-ebpf-zero-code-000"]
    assert (intro.speaker_id, intro.speaker_name, intro.speaker_status) == ("chair-felix", "Felix", "identified")
    assert store.unknown_voices["unk_talk-ebpf-zero-code_00"].resolved_person_id == "chair-felix"
    other_room = store.utterances["talk-ebpf-edge-000"]  # Room C chair is someone else
    assert other_room.speaker_status == "unknown"


def test_relabel_respects_the_margin_against_the_stored_runner_up(pipeline, seeded, settings, conf_day):
    store, _ = seeded
    fx = load()
    felix = fx.registration_clips["chair-felix"]
    # A fake unknown voice that sounds like Felix but whose best earlier candidate was nearly as close.
    store.unknown_voices["unk_x_00"] = UnknownVoice(
        unknown_id="unk_x_00", conference_id=settings.conference_id, session_id="x", model_id=settings.model_id,
        embedding=felix.embedding, duration_s=10, best_candidate_id="spk-dev", best_score=0.97,
        created_at=conf_day,
    )
    _, relabel = pipeline.enroll_registration(fx.people["chair-felix"], felix)
    assert "unk_x_00" not in relabel.voices
    assert store.unknown_voices["unk_x_00"].resolved_person_id is None


def test_erasure_deletes_voice_data_and_resets_labels(pipeline, seeded, settings):
    store, _ = seeded
    result = pipeline.erase_person("spk-dev")
    assert result.voiceprints_deleted == 1 and result.samples_deleted == 1
    assert result.utterances_reset > 0
    assert not any(v.person_id == "spk-dev" for v in store.voiceprints.values())
    assert not any(s.person_id == "spk-dev" for s in store.samples.values())
    dev_q = next(u for u in store.utterances.values()
                 if u.session_id == "talk-ebpf-cost" and u.voice_id == "unk_talk-ebpf-cost_03")
    assert (dev_q.speaker_id, dev_q.speaker_name, dev_q.speaker_status, dev_q.match_score) == (
        "unk_talk-ebpf-cost_03", "Unknown speaker 4", "unknown", None)
    assert not any(u.speaker_id == "spk-dev" or u.speaker_name == "Dev" for u in store.utterances.values())


def test_erasure_removes_relabeled_unknown_voices_and_candidate_links(pipeline, seeded):
    store, _ = seeded
    fx = load()
    pipeline.enroll_registration(fx.people["chair-felix"], fx.registration_clips["chair-felix"])
    result = pipeline.erase_person("chair-felix")
    assert result.unknown_voices_deleted == 5 and result.utterances_reset == 5
    assert not any(v.resolved_person_id == "chair-felix" for v in store.unknown_voices.values())
    linked_before = sum(1 for v in store.unknown_voices.values() if "spk-arjun" in (v.best_candidate_id,
                                                                                     v.runner_up_id))
    assert linked_before >= 1
    pipeline.erase_person("spk-arjun")
    assert not any("spk-arjun" in (v.best_candidate_id, v.runner_up_id) for v in store.unknown_voices.values())


def test_retention_purge_keeps_transcripts(pipeline, seeded, settings):
    store, _ = seeded
    before = len(store.utterances)
    counts = pipeline.purge_biometrics()
    assert counts == {"voiceprints": 15, "samples": 15, "unknown_voices": 27}
    assert store.counts(settings.conference_id)["utterances"] == before


def test_conferences_never_mix(settings, conf_day):
    store = InMemorySpeakerStore()
    seed(store, settings, now=conf_day)
    other = replace(settings, conference_id="other-2027")
    hits = store.knn_voiceprints(next(iter(store.voiceprints.values())).centroid, conference_id=other.conference_id,
                                 model_id=other.model_id, k=5, num_candidates=50)
    assert hits == []
    assert Pipeline(store, other).erase_person("spk-dev").voiceprints_deleted == 0
    assert any(v.person_id == "spk-dev" for v in store.voiceprints.values())


def test_logs_carry_ids_and_counts_only(settings, conf_day, caplog):
    caplog.set_level(logging.DEBUG, logger="rapport.speakers")
    store = InMemorySpeakerStore()
    seed(store, settings, now=conf_day)
    fx = load()
    pipeline = Pipeline(store, settings)
    pipeline.enroll_registration(fx.people["chair-felix"], fx.registration_clips["chair-felix"])
    pipeline.erase_person("chair-felix")
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert logged  # something was logged
    for person in fx.people.values():
        assert person.name not in logged
    for text in ("eBPF", "Welcome", "warehouse"):
        assert text not in logged


@pytest.mark.parametrize("label,expected", [("SPEAKER_00", ("unk_s1_00", "Unknown speaker 1")),
                                            ("SPEAKER_12", ("unk_s1_12", "Unknown speaker 13"))])
def test_voice_ids_are_stable(label, expected):
    assert voice_ids("s1", label) == expected
