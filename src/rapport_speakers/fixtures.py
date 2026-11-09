"""Load the committed, synthetic, precomputed fixtures (`data/fixtures.json`).

They stand in for the offline audio step (M1, `audio.py`): diarized and transcribed segments plus one
L2-normalized ECAPA-sized embedding per local speaker cluster, for every seed talk. Every voice is random
noise and every person is fictional. Regenerate with `python -m rapport_speakers.fixture_build`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .chunking import Segment
from .models import Person
from .vectors import normalize

FIXTURES_PATH = Path(__file__).parent / "data" / "fixtures.json"


@dataclass(frozen=True)
class Cluster:
    label: str  # local diarization label, e.g. SPEAKER_01
    embedding: list[float]
    truth: str | None = None  # ground truth for evaluation (§7) only; the pipeline never reads it


@dataclass(frozen=True)
class Recording:
    session_id: str
    recording_uri: str
    clusters: list[Cluster]
    segments: list[Segment]


@dataclass(frozen=True)
class RegistrationClip:
    person_id: str
    duration_s: float
    audio_uri: str
    embedding: list[float]


@dataclass(frozen=True)
class Fixtures:
    conference_id: str
    model_id: str
    people: dict[str, Person]
    roles: dict[str, str]
    registration_clips: dict[str, RegistrationClip]
    recordings: dict[str, Recording]


def parse(raw: dict) -> Fixtures:
    people, roles = {}, {}
    for p in raw["people"]:
        consent = p.get("consent_granted_at")
        people[p["person_id"]] = Person(
            person_id=p["person_id"], name=p["name"], affiliation=p.get("affiliation"),
            consent_granted_at=datetime.fromisoformat(consent) if consent else None,
        )
        roles[p["person_id"]] = p.get("role", "speaker")
    clips = {
        c["person_id"]: RegistrationClip(c["person_id"], float(c["duration_s"]), c["audio_uri"],
                                         normalize(c["embedding"]))
        for c in raw.get("registration_clips", [])
    }
    recordings = {}
    for r in raw["recordings"]:
        recordings[r["session_id"]] = Recording(
            session_id=r["session_id"], recording_uri=r["recording_uri"],
            clusters=[Cluster(c["label"], normalize(c["embedding"]), c.get("truth")) for c in r["clusters"]],
            segments=[Segment(float(s["start_s"]), float(s["end_s"]), s["label"], s["text"], bool(s.get("overlap")))
                      for s in r["segments"]],
        )
    return Fixtures(raw["conference_id"], raw["model_id"], people, roles, clips, recordings)


@lru_cache(maxsize=1)
def load(path: str | None = None) -> Fixtures:
    return parse(json.loads(Path(path or FIXTURES_PATH).read_text()))
