"""Documents and API payloads for speaker identification (spec §4 and §6).

These belong in `rapport_common.models` once the integrator accepts the CONTRACT CHANGE REQUEST in the PR.
Until then they live here so nothing else in the repo changes. Nothing here redefines an existing contract.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import EMBEDDING_DIMS
from .vectors import is_unit

SessionType = Literal["talk", "panel", "keynote", "workshop"]
SpeakerStatus = Literal["identified", "ambiguous", "unknown"]
SampleSource = Literal["schedule", "registration", "manual", "retro"]


class Doc(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetimes must be timezone-aware (store UTC)")
    return value


def _embedding(value: list[float], *, unit: bool) -> list[float]:
    if len(value) != EMBEDDING_DIMS:
        raise ValueError(f"embedding must have {EMBEDDING_DIMS} dims, got {len(value)}")
    if not all(math.isfinite(x) for x in value):
        raise ValueError("embedding has non-finite values")
    if unit and not is_unit(value):
        raise ValueError("dot_product needs unit-length vectors: L2-normalize first")
    return value


# --------------------------------------------------------------------------- Elasticsearch documents
class SessionDoc(Doc):
    """§4.1: one program slot."""

    session_id: str
    conference_id: str
    title: str
    abstract: str = ""
    room: str
    start_time: datetime
    end_time: datetime
    scheduled_speaker_ids: list[str] = Field(default_factory=list)
    session_type: SessionType = "talk"
    recording_uri: str | None = None

    check_aware = field_validator("start_time", "end_time")(_aware)


class Person(Doc):
    """A program or registration directory entry. Only people with `consent_granted_at` are ever enrolled."""

    person_id: str
    name: str
    affiliation: str | None = None
    consent_granted_at: datetime | None = None

    @field_validator("consent_granted_at")
    @classmethod
    def _consent_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)


class VoiceprintSample(Doc):
    """§4.2: one enrollment clip. Stored for recompute and audit; never searched with kNN."""

    sample_id: str
    person_id: str
    conference_id: str
    model_id: str
    source: SampleSource
    session_id: str | None = None
    duration_s: float = Field(ge=0)
    audio_uri: str | None = None
    embedding: list[float]
    corroborated: bool | None = None  # §5.3 step 3: the chair's intro named the scheduled speaker
    created_at: datetime

    check_aware = field_validator("created_at")(_aware)

    @field_validator("embedding")
    @classmethod
    def _dims(cls, value: list[float]) -> list[float]:
        return _embedding(value, unit=False)


class Voiceprint(Doc):
    """§4.3: one per (person, conference, model). The index the matcher searches.

    `consent_granted_at` is required: a voiceprint cannot be built for someone who has not opted in (§8).
    """

    person_id: str
    name: str
    affiliation: str | None = None
    conference_id: str
    model_id: str
    centroid: list[float]
    sample_count: int = Field(ge=1)
    total_speech_s: float = Field(ge=0)
    consent_granted_at: datetime
    updated_at: datetime

    check_aware = field_validator("consent_granted_at", "updated_at")(_aware)

    @field_validator("centroid")
    @classmethod
    def _unit(cls, value: list[float]) -> list[float]:
        return _embedding(value, unit=True)

    @property
    def doc_id(self) -> str:
        """Re-enrollment overwrites instead of duplicating (§4.3)."""
        return f"{self.conference_id}:{self.person_id}:{self.model_id}"


class Utterance(Doc):
    """§4.4: one speaker turn chunk (30-60 s).

    Beyond the spec's mapping: `voice_id` / `voice_label` keep the session-local voice so relabel (§5.5) and
    erasure (§8) can find and reset a turn, and `session_starts_at` / `recording_uri` give jump-to links
    without a join.
    """

    utterance_id: str
    conference_id: str
    session_id: str
    session_title: str
    room: str
    session_starts_at: datetime
    recording_uri: str | None = None
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    speaker_id: str  # a person_id, or the unknown voice ID (voice_id)
    speaker_name: str  # a consenting person's name, or "Unknown speaker N"
    speaker_status: SpeakerStatus
    match_score: float | None = None  # cosine of the accepted (or best ambiguous) match
    voice_id: str  # e.g. unk_talk-ebpf-zero-code_02; stable for the conference
    voice_label: str  # e.g. "Unknown speaker 3"
    text: str

    check_aware = field_validator("session_starts_at")(_aware)


class UnknownVoice(Doc):
    """§4.5: an unresolved (unknown or ambiguous) cluster. Searched when a new voiceprint arrives (§5.5)."""

    unknown_id: str
    conference_id: str
    session_id: str
    model_id: str
    embedding: list[float]
    duration_s: float = Field(ge=0)
    status: Literal["unknown", "ambiguous"] = "unknown"
    best_candidate_id: str | None = None
    best_score: float | None = None
    runner_up_id: str | None = None  # kept so relabel can still check the margin (§5.5)
    runner_up_score: float | None = None
    resolved_person_id: str | None = None
    created_at: datetime

    check_aware = field_validator("created_at")(_aware)

    @field_validator("embedding")
    @classmethod
    def _unit(cls, value: list[float]) -> list[float]:
        return _embedding(value, unit=True)


# --------------------------------------------------------------------------- API payloads (no vectors, ever)
class UtteranceHit(Doc):
    utterance_id: str
    session_id: str
    session_title: str
    room: str
    speaker_id: str
    speaker_name: str
    speaker_status: SpeakerStatus
    start_s: float
    end_s: float
    spoken_at: datetime  # UTC
    spoken_at_label: str  # America/Denver with its label, e.g. "3:41 PM MST"
    jump_url: str | None = None  # recording_uri#t=<start_s>
    text: str
    score: float | None = None

    check_aware = field_validator("spoken_at")(_aware)


class SearchResult(Doc):
    query: str
    speaker: str | None = None
    session: str | None = None
    mode: str  # rrf, bool or keyword: which query strategy answered
    hits: list[UtteranceHit] = Field(default_factory=list)


class SpeakerCount(Doc):
    speaker_id: str
    speaker_name: str
    utterances: int


class TopSpeakersResult(Doc):
    query: str
    speakers: list[SpeakerCount] = Field(default_factory=list)


class SpeakerUtterances(Doc):
    speaker: str
    utterances: list[UtteranceHit] = Field(default_factory=list)


class EraseResult(Doc):
    person_id: str
    voiceprints_deleted: int
    samples_deleted: int
    unknown_voices_deleted: int
    unknown_voices_unlinked: int
    utterances_reset: int
