"""The committed fixtures cover the seed agenda, and the local CLI answers who-said-what with no keys."""

from __future__ import annotations

from rapport_memory.seed_talks import talk_records
from rapport_speakers import audio, cli
from rapport_speakers.chunking import Segment, chunk_turns
from rapport_speakers.config import EMBEDDING_DIMS
from rapport_speakers.fixtures import load
from rapport_speakers.schedule import person_id_for, sessions_from_seed
from rapport_speakers.vectors import norm


def test_fixtures_cover_every_seed_talk_with_unit_embeddings():
    fx = load()
    assert set(fx.recordings) == {t.memory_id for t in talk_records()}
    for rec in fx.recordings.values():
        labels = {c.label for c in rec.clusters}
        assert {s.label for s in rec.segments} <= labels
        for c in rec.clusters:
            assert len(c.embedding) == EMBEDDING_DIMS and abs(norm(c.embedding) - 1) < 1e-9


def test_every_scheduled_speaker_and_chair_is_in_the_fixture_directory():
    fx = load()
    for session in sessions_from_seed(fx.conference_id):
        assert set(session.scheduled_speaker_ids) <= set(fx.people)
    assert {pid for pid, role in fx.roles.items() if role == "chair"} == {"chair-noor", "chair-felix", "chair-ines"}
    assert fx.people["spk-rosa"].consent_granted_at is None


def test_person_ids_reuse_directory_personas():
    assert person_id_for("Mia", ["kestrel.mia"]) == "kestrel.mia"
    assert person_id_for("Dev", []) == "spk-dev"


def test_chunking_merges_back_to_back_sentences_up_to_the_window():
    segs = [Segment(0, 20, "A", "One."), Segment(20.5, 40, "A", "Two."), Segment(40.5, 70, "A", "Three."),
            Segment(71, 75, "B", "Question?")]
    windows = chunk_turns(segs)
    assert [(w.label, w.start_s, w.end_s, w.text) for w in windows] == [
        ("A", 0, 40, "One. Two."), ("A", 40.5, 70, "Three."), ("B", 71, 75, "Question?")]


def test_cli_answers_who_said_x_about_ebpf_without_keys(capsys, monkeypatch):
    for var in ("ES_URL", "ES_API_KEY", "ES_ADMIN_API_KEY", "SPEAKERS_ES_API_KEY", "SPEAKERS_STORE"):
        monkeypatch.delenv(var, raising=False)
    cli.main(["who", "who asked about eBPF overhead on edge robots", "--size", "1"])
    out = capsys.readouterr().out
    assert "A: Mia, at" in out and "Zero-code tracing with eBPF on Kubernetes" in out and "#t=1450" in out


def test_cli_demo_runs_the_whole_story(capsys, monkeypatch):
    for var in ("ES_URL", "ES_API_KEY", "ES_ADMIN_API_KEY", "SPEAKERS_ES_API_KEY", "SPEAKERS_STORE"):
        monkeypatch.delenv(var, raising=False)
    cli.main(["demo"])
    out = capsys.readouterr().out
    assert "relabeled 5 past unknown voices" in out and "A: Felix, at" in out and '"utterances_reset": 5' in out


def test_audio_step_imports_without_heavy_dependencies():
    turns = [(0.0, 10.0, "SPEAKER_00"), (9.0, 12.0, "SPEAKER_01")]
    assert audio._overlaps(9.5, 10.5, "SPEAKER_00", turns)
    assert not audio._overlaps(0.0, 8.0, "SPEAKER_00", turns)
