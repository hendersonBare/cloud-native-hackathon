"""Schedule ingest (spec §5.1): the conference program becomes the `sessions` index.

The program is the seed agenda in `rapport_memory.seed_talks` (fictional talks and speakers), so the speaker
feature and the agenda search always agree on session IDs, rooms and times.
"""

from __future__ import annotations

import re
from datetime import datetime

from rapport_common import names
from rapport_memory.seed_talks import talk_records

from .models import SessionDoc

RECORDING_PREFIX = "recordings"


def person_id_for(speaker_name: str, about_persona_ids: list[str]) -> str:
    """A talk's speaker ID: the directory persona when the agenda links exactly one, else `spk-<name>`."""
    if len(about_persona_ids) == 1:
        return about_persona_ids[0]
    slug = re.sub(r"[^a-z0-9]+", "-", speaker_name.lower()).strip("-")
    return f"spk-{slug}"


def affiliation_for(person_id: str) -> str | None:
    if person_id in names.personas():
        return names.orgs()[names.org_of(person_id)].name
    return None


def recording_uri(session_id: str) -> str:
    return f"{RECORDING_PREFIX}/{session_id}.mp4"


def sessions_from_seed(conference_id: str, now: datetime | None = None) -> list[SessionDoc]:
    sessions = []
    for talk in talk_records(now):
        info = talk.talk
        if info is None:
            continue
        speaker_ids = [person_id_for(s, talk.about_persona_ids) for s in info.speakers]
        sessions.append(SessionDoc(
            session_id=talk.memory_id, conference_id=conference_id, title=talk.title, abstract=talk.summary,
            room=info.room, start_time=info.starts_at, end_time=info.ends_at,
            scheduled_speaker_ids=speaker_ids,
            session_type="keynote" if "keynote" in talk.memory_id else ("panel" if len(speaker_ids) > 1 else "talk"),
            recording_uri=recording_uri(talk.memory_id),
        ))
    return sessions


def scheduled_speakers() -> list[tuple[str, str, str | None]]:
    """(person_id, name, affiliation) for every speaker on the program."""
    out: dict[str, tuple[str, str, str | None]] = {}
    for talk in talk_records():
        if talk.talk is None:
            continue
        for name in talk.talk.speakers:
            pid = person_id_for(name, talk.about_persona_ids)
            out.setdefault(pid, (pid, name, affiliation_for(pid)))
    return list(out.values())
