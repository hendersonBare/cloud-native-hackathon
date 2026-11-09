"""Pipelines (spec §5): schedule enrollment, identification, retroactive relabeling and erasure.

Telemetry carries session IDs, statuses and counts only. Never names, transcript text or vectors.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from rapport_common import telemetry

from .chunking import chunk_turns, clean_speech_s
from .config import POOL_FILTER, Settings
from .decide import AMBIGUOUS, IDENTIFIED, UNKNOWN, apply_pool, decide_with, top_two
from .fixtures import Fixtures, Recording, RegistrationClip
from .fixtures import load as load_fixtures
from .models import EraseResult, Person, SessionDoc, UnknownVoice, Utterance, Voiceprint, VoiceprintSample
from .schedule import sessions_from_seed
from .store import SpeakerStore
from .vectors import cosine_from_score, es_score, recompute_centroid

log = logging.getLogger("rapport.speakers.pipeline")

ATTR_SESSION = "rapport.speakers.session_id"
ATTR_STATUS = "rapport.speakers.status"
METRIC_DECISIONS = "rapport.speakers.decisions"  # counter, attr: status
RELABEL_K = 50
RELABEL_NUM_CANDIDATES = 200

_counter = None


def _decisions_counter():
    global _counter
    if _counter is None:
        _counter = telemetry.meter("rapport.speakers").create_counter(
            METRIC_DECISIONS, description="Speaker identification decisions by status")
    return _counter


def voice_ids(session_id: str, label: str) -> tuple[str, str]:
    """Stable unknown-voice ID and label for a session-local cluster: (unk_<session>_<nn>, "Unknown speaker N")."""
    digits = re.sub(r"\D", "", label) or "0"
    nn = int(digits)
    return f"unk_{session_id}_{nn:02d}", f"Unknown speaker {nn + 1}"


@dataclass
class ClusterDecision:
    label: str
    voice_id: str
    voice_label: str
    status: str
    person_id: str | None
    name: str
    score: float | None
    speech_s: float


@dataclass
class EnrollReport:
    enrolled: list[tuple[str, str]] = field(default_factory=list)  # (session_id, person_id)
    flagged: list[tuple[str, str]] = field(default_factory=list)  # (session_id, reason): needs human review
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (session_id, reason): rule says never


@dataclass
class IdentifyReport:
    session_id: str
    decisions: list[ClusterDecision]
    utterances: int

    def counts(self) -> dict[str, int]:
        return dict(Counter(d.status for d in self.decisions))


@dataclass
class RelabelReport:
    person_id: str
    voices: list[str] = field(default_factory=list)  # unknown voice IDs now resolved to person_id
    utterances: int = 0


@dataclass
class SeedReport:
    sessions: int
    enroll: EnrollReport
    identify: list[IdentifyReport]
    counts: dict[str, int]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Pipeline:
    def __init__(self, store: SpeakerStore, settings: Settings, *, now: Callable[[], datetime] = _utcnow) -> None:
        self.store = store
        self.s = settings
        self.now = now
        self.tracer = telemetry.tracer("rapport.speakers")

    # ------------------------------------------------------------------ §5.1 schedule ingest
    def ingest_schedule(self, sessions: list[SessionDoc]) -> int:
        return self.store.upsert_sessions(sessions)

    # ------------------------------------------------------------------ voiceprints
    def _rebuild_voiceprint(self, person: Person) -> Voiceprint:
        if person.consent_granted_at is None:
            raise PermissionError("no consent recorded; refusing to build a voiceprint")
        samples = self.store.samples_for(self.s.conference_id, person.person_id, self.s.model_id)
        if not samples:
            raise ValueError("no samples to build a voiceprint from")
        voiceprint = Voiceprint(
            person_id=person.person_id, name=person.name, affiliation=person.affiliation,
            conference_id=self.s.conference_id, model_id=self.s.model_id,
            centroid=recompute_centroid([s.embedding for s in samples]),
            sample_count=len(samples), total_speech_s=round(sum(s.duration_s for s in samples), 2),
            consent_granted_at=person.consent_granted_at, updated_at=self.now(),
        )
        self.store.upsert_voiceprint(voiceprint)
        return voiceprint

    def add_sample(self, person: Person, sample: VoiceprintSample) -> tuple[Voiceprint, RelabelReport]:
        """§5.3 step 4: store the sample, recompute the centroid, then relabel past unknown voices (§5.5)."""
        if person.consent_granted_at is None:
            raise PermissionError("no consent recorded; refusing to store a voice sample")
        self.store.add_samples([sample])
        voiceprint = self._rebuild_voiceprint(person)
        return voiceprint, self.relabel_for(voiceprint)

    # ------------------------------------------------------------------ §5.3 auto-enrollment from the schedule
    def enroll_from_schedule(
        self, sessions: list[SessionDoc], recordings: dict[str, Recording], people: dict[str, Person],
    ) -> EnrollReport:
        report = EnrollReport()
        g = self.s.guards
        with self.tracer.start_as_current_span("speakers.enroll") as span:
            for session in sessions:
                sid = session.session_id
                if session.session_type != "talk" or len(session.scheduled_speaker_ids) != 1:
                    report.skipped.append((sid, f"{session.session_type}: only single-speaker talks auto-enroll"))
                    continue
                person = people.get(session.scheduled_speaker_ids[0])
                if person is None or person.consent_granted_at is None:
                    report.skipped.append((sid, "no consent recorded"))
                    continue
                rec = recordings.get(sid)
                if rec is None or not rec.clusters:
                    report.skipped.append((sid, "no recording"))
                    continue
                speech = {c.label: clean_speech_s(rec.segments, c.label) for c in rec.clusters}
                total = sum(speech.values())
                dominant = max(rec.clusters, key=lambda c: speech[c.label])
                dom_s = speech[dominant.label]
                share = dom_s / total if total else 0.0
                if share < g.min_share or dom_s < g.min_speech_s:
                    report.flagged.append((sid, f"dominant cluster {share:.0%} of speech, {dom_s:.0f}s "
                                                f"(needs {g.min_share:.0%} and {g.min_speech_s:.0f}s)"))
                    continue
                name = re.compile(rf"\b{re.escape(person.name)}\b", re.IGNORECASE)
                corroborated = any(seg.start_s < g.corroboration_window_s and name.search(seg.text)
                                   for seg in rec.segments)
                sample = VoiceprintSample(
                    sample_id=f"{self.s.conference_id}:{person.person_id}:schedule:{sid}",
                    person_id=person.person_id, conference_id=self.s.conference_id, model_id=self.s.model_id,
                    source="schedule", session_id=sid, duration_s=round(min(dom_s, g.max_embed_s), 2),
                    audio_uri=f"{rec.recording_uri}#speaker={dominant.label}", embedding=dominant.embedding,
                    corroborated=corroborated, created_at=self.now(),
                )
                self.add_sample(person, sample)
                report.enrolled.append((sid, person.person_id))
            span.set_attribute(telemetry.ATTR_RESULT_COUNT, len(report.enrolled))
            span.set_attribute("rapport.speakers.flagged", len(report.flagged))
        log.info("schedule enrollment: enrolled=%d flagged=%d skipped=%d", len(report.enrolled),
                 len(report.flagged), len(report.skipped))
        return report

    def enroll_registration(self, person: Person, clip: RegistrationClip) -> tuple[Voiceprint, RelabelReport]:
        """POST /enroll (§6): a registration clip plus recorded consent."""
        sample = VoiceprintSample(
            sample_id=f"{self.s.conference_id}:{person.person_id}:registration:{clip.audio_uri}",
            person_id=person.person_id, conference_id=self.s.conference_id, model_id=self.s.model_id,
            source="registration", duration_s=clip.duration_s, audio_uri=clip.audio_uri, embedding=clip.embedding,
            created_at=self.now(),
        )
        return self.add_sample(person, sample)

    # ------------------------------------------------------------------ §5.4 identification
    def identify(self, session: SessionDoc, recording: Recording,
                 known_attendees: list[str] | None = None) -> IdentifyReport:
        conf, sid = self.s.conference_id, session.session_id
        pool = list(dict.fromkeys([*session.scheduled_speaker_ids, *(known_attendees or [])]))
        decisions: dict[str, ClusterDecision] = {}
        unknown: list[UnknownVoice] = []
        with self.tracer.start_as_current_span("speakers.identify") as span:
            span.set_attribute(ATTR_SESSION, sid)
            for cluster in recording.clusters:
                speech = clean_speech_s(recording.segments, cluster.label)
                hits = self.store.knn_voiceprints(
                    cluster.embedding, conference_id=conf, model_id=self.s.model_id, k=self.s.knn_k,
                    num_candidates=self.s.knn_num_candidates,
                    person_ids=pool if self.s.pool_mode == POOL_FILTER else None,
                )
                ranked = apply_pool(hits, pool, self.s.pool_mode, self.s.pool_bonus)
                status, person_id, score = decide_with(ranked, speech, self.s.thresholds)
                voice_id, voice_label = voice_ids(sid, cluster.label)
                name = voice_label
                if status == IDENTIFIED:
                    name = next(h["_source"]["name"] for h in ranked if h["_source"]["person_id"] == person_id)
                decisions[cluster.label] = ClusterDecision(
                    cluster.label, voice_id, voice_label, status, person_id, name,
                    None if score is None else round(score, 4), round(speech, 2),
                )
                _decisions_counter().add(1, {ATTR_STATUS: status})
                if status in (UNKNOWN, AMBIGUOUS):
                    (best_id, best), (second_id, second) = top_two(hits)
                    unknown.append(UnknownVoice(
                        unknown_id=voice_id, conference_id=conf, session_id=sid, model_id=self.s.model_id,
                        embedding=cluster.embedding, duration_s=round(speech, 2), status=status,
                        best_candidate_id=best_id, best_score=best, runner_up_id=second_id, runner_up_score=second,
                        created_at=self.now(),
                    ))
            utterances = []
            for i, window in enumerate(chunk_turns(recording.segments)):
                d = decisions.get(window.label)
                if d is None:  # a segment label without an embedding: keep the turn, label it unknown
                    vid, vlabel = voice_ids(sid, window.label)
                    d = ClusterDecision(window.label, vid, vlabel, UNKNOWN, None, vlabel, None, 0.0)
                identified = d.status == IDENTIFIED
                utterances.append(Utterance(
                    utterance_id=f"{sid}-{i:03d}", conference_id=conf, session_id=sid,
                    session_title=session.title, room=session.room, session_starts_at=session.start_time,
                    recording_uri=session.recording_uri or recording.recording_uri,
                    start_s=window.start_s, end_s=window.end_s,
                    speaker_id=d.person_id if identified and d.person_id else d.voice_id,
                    speaker_name=d.name, speaker_status=d.status,  # type: ignore[arg-type]
                    match_score=d.score if d.status != UNKNOWN else None,
                    voice_id=d.voice_id, voice_label=d.voice_label, text=window.text,
                ))
            self.store.index_utterances(utterances)
            self.store.replace_unknown_voices(conf, sid, unknown)
            report = IdentifyReport(sid, list(decisions.values()), len(utterances))
            for status, n in report.counts().items():
                span.set_attribute(f"rapport.speakers.{status}", n)
            span.set_attribute(telemetry.ATTR_RESULT_COUNT, len(utterances))
        log.info("identified session=%s clusters=%d utterances=%d", sid, len(decisions), len(utterances))
        return report

    # ------------------------------------------------------------------ §5.5 retroactive relabeling
    def relabel_for(self, voiceprint: Voiceprint) -> RelabelReport:
        """Resolve past unknown voices that now match this voiceprint, and relabel their utterances.

        Candidates come from kNN on unknown voices. Each must then pass the same decision rule, with the
        unknown voice's stored best and runner-up candidates as the competition, so the margin still counts.
        """
        report = RelabelReport(voiceprint.person_id)
        person = Person(person_id=voiceprint.person_id, name=voiceprint.name, affiliation=voiceprint.affiliation,
                        consent_granted_at=voiceprint.consent_granted_at)
        with self.tracer.start_as_current_span("speakers.relabel") as span:
            hits = self.store.knn_unknown_voices(
                voiceprint.centroid, conference_id=self.s.conference_id, model_id=self.s.model_id,
                k=RELABEL_K, num_candidates=RELABEL_NUM_CANDIDATES,
            )
            for hit in hits:
                src = hit["_source"]
                if cosine_from_score(hit["_score"]) < self.s.thresholds.t_accept:
                    continue
                competitors = [(src.get("best_candidate_id"), src.get("best_score")),
                               (src.get("runner_up_id"), src.get("runner_up_score"))]
                rival = next(((pid, s) for pid, s in competitors
                              if pid and pid != voiceprint.person_id and s is not None), None)
                candidates = [{"_score": hit["_score"], "_source": {"person_id": voiceprint.person_id}}]
                if rival:
                    candidates.append({"_score": es_score(rival[1]), "_source": {"person_id": rival[0]}})
                candidates.sort(key=lambda h: h["_score"], reverse=True)
                status, pid, score = decide_with(candidates, float(src.get("duration_s") or 0.0), self.s.thresholds)
                if status != IDENTIFIED or pid != voiceprint.person_id:
                    continue
                self.store.resolve_unknown_voice(self.s.conference_id, src["unknown_id"], pid)
                report.utterances += self.store.relabel_voice(
                    self.s.conference_id, src["unknown_id"], person, None if score is None else round(score, 4))
                report.voices.append(src["unknown_id"])
            span.set_attribute(telemetry.ATTR_RESULT_COUNT, len(report.voices))
        if report.voices:
            log.info("relabel: resolved %d unknown voices, %d utterances", len(report.voices), report.utterances)
        return report

    # ------------------------------------------------------------------ §8 erasure and retention
    def erase_person(self, person_id: str) -> EraseResult:
        with self.tracer.start_as_current_span("speakers.erase") as span:
            counts = self.store.erase_person(self.s.conference_id, person_id)
            span.set_attribute(telemetry.ATTR_RESULT_COUNT, sum(counts.values()))
        log.info("erasure: voiceprints=%d samples=%d unknown_voices=%d utterances_reset=%d",
                 counts["voiceprints"], counts["samples"], counts["unknown_voices"], counts["utterances"])
        return EraseResult(
            person_id=person_id, voiceprints_deleted=counts["voiceprints"], samples_deleted=counts["samples"],
            unknown_voices_deleted=counts["unknown_voices"],
            unknown_voices_unlinked=counts["unknown_voices_unlinked"], utterances_reset=counts["utterances"],
        )

    def purge_biometrics(self) -> dict[str, int]:
        """Retention (§8): drop every voiceprint, sample and unknown voice for the conference. Transcripts stay."""
        counts = self.store.purge_biometrics(self.s.conference_id)
        log.info("retention purge: %s", counts)
        return counts


def seed(store: SpeakerStore, settings: Settings, *, fixtures: Fixtures | None = None,
         now: datetime | None = None) -> SeedReport:
    """Two-pass seed (§5.2): schedule -> enroll from every session -> identify every session."""
    fx = fixtures or load_fixtures()
    pipeline = Pipeline(store, settings)
    sessions = sessions_from_seed(settings.conference_id, now)
    store.ensure_indices()
    pipeline.ingest_schedule(sessions)
    enroll = pipeline.enroll_from_schedule(sessions, fx.recordings, fx.people)
    reports = [pipeline.identify(s, fx.recordings[s.session_id]) for s in sessions if s.session_id in fx.recordings]
    return SeedReport(len(sessions), enroll, reports, store.counts(settings.conference_id))
