"""Search by who said what (spec §6), with jump-to timestamps.

Spans carry result counts and the query mode only: never the query, names or transcript text.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rapport_common import telemetry

from .config import Settings
from .models import SearchResult, SpeakerCount, SpeakerUtterances, TopSpeakersResult, Utterance, UtteranceHit
from .store import SpeakerStore

try:
    DENVER: timezone | ZoneInfo = ZoneInfo("America/Denver")
except ZoneInfoNotFoundError:  # a minimal image without tzdata
    DENVER = timezone(timedelta(hours=-7), "MST")

MAX_SIZE = 50


def local_label(moment: datetime) -> str:
    """'3:54 PM MST' (house rule: show America/Denver with its label)."""
    local = moment.astimezone(DENVER)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} {local.tzname()}"


def to_hit(u: Utterance, score: float | None = None) -> UtteranceHit:
    spoken_at = (u.session_starts_at + timedelta(seconds=u.start_s)).astimezone(timezone.utc)
    return UtteranceHit(
        utterance_id=u.utterance_id, session_id=u.session_id, session_title=u.session_title, room=u.room,
        speaker_id=u.speaker_id, speaker_name=u.speaker_name, speaker_status=u.speaker_status,
        start_s=u.start_s, end_s=u.end_s, spoken_at=spoken_at, spoken_at_label=local_label(spoken_at),
        jump_url=f"{u.recording_uri}#t={int(u.start_s)}" if u.recording_uri else None,
        text=u.text, score=score,
    )


class SpeakerSearch:
    def __init__(self, store: SpeakerStore, settings: Settings) -> None:
        self.store = store
        self.s = settings
        self.tracer = telemetry.tracer("rapport.speakers")

    def search(self, q: str, *, speaker: str | None = None, session: str | None = None, size: int = 5) -> SearchResult:
        """§6.1: hybrid topic search, optionally narrowed to one speaker (ID or name) or one session."""
        size = max(1, min(size, MAX_SIZE))
        with self.tracer.start_as_current_span("speakers.search") as span:
            found, mode = self.store.search_utterances(
                self.s.conference_id, q, speaker=speaker or None, session_id=session or None, size=size)
            span.set_attribute(telemetry.ATTR_RESULT_COUNT, len(found))
            span.set_attribute("rapport.speakers.query_mode", mode)
        return SearchResult(query=q, speaker=speaker, session=session, mode=mode,
                            hits=[to_hit(u, s) for u, s in found])

    def speaker_utterances(self, speaker: str, *, size: int = MAX_SIZE) -> SpeakerUtterances:
        """GET /speakers/{person_id}/utterances: everything a person said, by time."""
        size = max(1, min(size, MAX_SIZE))
        with self.tracer.start_as_current_span("speakers.by_speaker") as span:
            found = self.store.utterances_by_speaker(self.s.conference_id, speaker, size)
            span.set_attribute(telemetry.ATTR_RESULT_COUNT, len(found))
        return SpeakerUtterances(speaker=speaker, utterances=[to_hit(u) for u in found])

    def top_speakers(self, q: str, *, size: int = 10) -> TopSpeakersResult:
        """§6.2: who talked most about X (identified speakers only)."""
        size = max(1, min(size, MAX_SIZE))
        with self.tracer.start_as_current_span("speakers.top") as span:
            rows = self.store.top_speakers(self.s.conference_id, q, size)
            span.set_attribute(telemetry.ATTR_RESULT_COUNT, len(rows))
        return TopSpeakersResult(query=q, speakers=[SpeakerCount(speaker_id=i, speaker_name=n, utterances=c)
                                                    for i, n, c in rows])
