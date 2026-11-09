"""The speaker store: what the pipeline and search need from Elasticsearch, plus an in-memory fake.

`EsSpeakerStore` (es_store.py) is the real one. `InMemorySpeakerStore` mirrors its behaviour closely enough for
unit tests and for a local demo with no Elasticsearch keys: brute-force kNN with the same `_score` formula,
and a small TF-IDF keyword scorer standing in for hybrid search.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Protocol

from .models import Person, SessionDoc, UnknownVoice, Utterance, Voiceprint, VoiceprintSample
from .vectors import dot, es_score

UNKNOWN_RESET = "unknown"


class SpeakerStore(Protocol):
    def ensure_indices(self) -> None: ...

    def upsert_sessions(self, sessions: list[SessionDoc]) -> int: ...

    def get_session(self, conference_id: str, session_id: str) -> SessionDoc | None: ...

    def add_samples(self, samples: list[VoiceprintSample]) -> int: ...

    def samples_for(self, conference_id: str, person_id: str, model_id: str) -> list[VoiceprintSample]: ...

    def upsert_voiceprint(self, voiceprint: Voiceprint) -> None: ...

    def knn_voiceprints(
        self, vector: list[float], *, conference_id: str, model_id: str, k: int, num_candidates: int,
        person_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...

    def index_utterances(self, utterances: list[Utterance]) -> int: ...

    def replace_unknown_voices(self, conference_id: str, session_id: str, voices: list[UnknownVoice]) -> int: ...

    def knn_unknown_voices(
        self, vector: list[float], *, conference_id: str, model_id: str, k: int, num_candidates: int,
    ) -> list[dict[str, Any]]: ...

    def resolve_unknown_voice(self, conference_id: str, unknown_id: str, person_id: str) -> None: ...

    def relabel_voice(self, conference_id: str, voice_id: str, person: Person, score: float | None) -> int: ...

    def erase_person(self, conference_id: str, person_id: str) -> dict[str, int]: ...

    def purge_biometrics(self, conference_id: str) -> dict[str, int]: ...

    def search_utterances(
        self, conference_id: str, query: str, *, speaker: str | None, session_id: str | None, size: int,
    ) -> tuple[list[tuple[Utterance, float | None]], str]: ...

    def utterances_by_speaker(self, conference_id: str, speaker: str, size: int) -> list[Utterance]: ...

    def top_speakers(self, conference_id: str, query: str, size: int) -> list[tuple[str, str, int]]: ...

    def counts(self, conference_id: str) -> dict[str, int]: ...


# --------------------------------------------------------------------------- keyword scoring for the fake
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be but by can do does for from how i in is it its of on or so that the this to was we what"
    " when where which who with you your about said say says did".split()
)


def tokens(text: str) -> list[str]:
    out = []
    for tok in _TOKEN.findall(text.lower()):
        if tok in _STOP:
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


def _speaker_matches(u: Utterance, speaker: str | None) -> bool:
    if not speaker:
        return True
    return u.speaker_id == speaker or u.speaker_name.lower() == speaker.lower()


class InMemorySpeakerStore:
    """Dict-backed store. Not thread-safe; for tests and the local demo only."""

    def __init__(self) -> None:
        self.sessions: dict[str, SessionDoc] = {}
        self.samples: dict[str, VoiceprintSample] = {}
        self.voiceprints: dict[str, Voiceprint] = {}
        self.utterances: dict[str, Utterance] = {}
        self.unknown_voices: dict[str, UnknownVoice] = {}

    def ensure_indices(self) -> None:
        return None

    # ------------------------------------------------------------------ sessions and samples
    def upsert_sessions(self, sessions: list[SessionDoc]) -> int:
        for s in sessions:
            self.sessions[f"{s.conference_id}:{s.session_id}"] = s
        return len(sessions)

    def get_session(self, conference_id: str, session_id: str) -> SessionDoc | None:
        return self.sessions.get(f"{conference_id}:{session_id}")

    def add_samples(self, samples: list[VoiceprintSample]) -> int:
        for s in samples:
            self.samples[s.sample_id] = s
        return len(samples)

    def samples_for(self, conference_id: str, person_id: str, model_id: str) -> list[VoiceprintSample]:
        return sorted(
            (s for s in self.samples.values()
             if s.conference_id == conference_id and s.person_id == person_id and s.model_id == model_id),
            key=lambda s: s.sample_id,
        )

    # ------------------------------------------------------------------ voiceprints and kNN
    def upsert_voiceprint(self, voiceprint: Voiceprint) -> None:
        self.voiceprints[voiceprint.doc_id] = voiceprint

    @staticmethod
    def _knn(candidates: list[tuple[dict[str, Any], list[float]]], vector: list[float], k: int):
        scored = [({"_score": es_score(dot(vector, emb)), "_source": src}) for src, emb in candidates]
        scored.sort(key=lambda h: h["_score"], reverse=True)
        return scored[:k]

    def knn_voiceprints(
        self, vector: list[float], *, conference_id: str, model_id: str, k: int, num_candidates: int,
        person_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        pool = set(person_ids) if person_ids is not None else None
        candidates = [
            ({"person_id": v.person_id, "name": v.name, "affiliation": v.affiliation}, v.centroid)
            for v in self.voiceprints.values()
            if v.conference_id == conference_id and v.model_id == model_id
            and (pool is None or v.person_id in pool)
        ]
        return self._knn(candidates, vector, k)

    # ------------------------------------------------------------------ utterances and unknown voices
    def index_utterances(self, utterances: list[Utterance]) -> int:
        for u in utterances:
            self.utterances[u.utterance_id] = u
        return len(utterances)

    def replace_unknown_voices(self, conference_id: str, session_id: str, voices: list[UnknownVoice]) -> int:
        for key in [k for k, v in self.unknown_voices.items()
                    if v.conference_id == conference_id and v.session_id == session_id]:
            del self.unknown_voices[key]
        for v in voices:
            self.unknown_voices[v.unknown_id] = v
        return len(voices)

    def knn_unknown_voices(
        self, vector: list[float], *, conference_id: str, model_id: str, k: int, num_candidates: int,
    ) -> list[dict[str, Any]]:
        candidates = [
            (v.model_dump(exclude={"embedding"}), v.embedding)
            for v in self.unknown_voices.values()
            if v.conference_id == conference_id and v.model_id == model_id and v.resolved_person_id is None
        ]
        return self._knn(candidates, vector, k)

    def resolve_unknown_voice(self, conference_id: str, unknown_id: str, person_id: str) -> None:
        voice = self.unknown_voices.get(unknown_id)
        if voice is not None and voice.conference_id == conference_id:
            self.unknown_voices[unknown_id] = voice.model_copy(update={"resolved_person_id": person_id})

    def relabel_voice(self, conference_id: str, voice_id: str, person: Person, score: float | None) -> int:
        n = 0
        for key, u in list(self.utterances.items()):
            if u.conference_id == conference_id and u.voice_id == voice_id:
                self.utterances[key] = u.model_copy(update={
                    "speaker_id": person.person_id, "speaker_name": person.name,
                    "speaker_status": "identified", "match_score": score,
                })
                n += 1
        return n

    # ------------------------------------------------------------------ erasure and retention (§8)
    def erase_person(self, conference_id: str, person_id: str) -> dict[str, int]:
        vp = [k for k, v in self.voiceprints.items() if v.conference_id == conference_id and v.person_id == person_id]
        for k in vp:
            del self.voiceprints[k]
        sm = [k for k, s in self.samples.items() if s.conference_id == conference_id and s.person_id == person_id]
        for k in sm:
            del self.samples[k]
        uv = [k for k, v in self.unknown_voices.items()
              if v.conference_id == conference_id and v.resolved_person_id == person_id]
        for k in uv:
            del self.unknown_voices[k]
        unlinked = 0
        for k, v in list(self.unknown_voices.items()):
            if v.conference_id != conference_id:
                continue
            update: dict[str, Any] = {}
            if v.best_candidate_id == person_id:
                update.update(best_candidate_id=None, best_score=None)
            if v.runner_up_id == person_id:
                update.update(runner_up_id=None, runner_up_score=None)
            if update:
                self.unknown_voices[k] = v.model_copy(update=update)
                unlinked += 1
        reset = 0
        for k, u in list(self.utterances.items()):
            if u.conference_id == conference_id and u.speaker_id == person_id:
                self.utterances[k] = u.model_copy(update={
                    "speaker_id": u.voice_id, "speaker_name": u.voice_label,
                    "speaker_status": UNKNOWN_RESET, "match_score": None,
                })
                reset += 1
        return {"voiceprints": len(vp), "samples": len(sm), "unknown_voices": len(uv),
                "unknown_voices_unlinked": unlinked, "utterances": reset}

    def purge_biometrics(self, conference_id: str) -> dict[str, int]:
        out = {}
        for name, table in (("voiceprints", self.voiceprints), ("samples", self.samples),
                            ("unknown_voices", self.unknown_voices)):
            keys = [k for k, v in table.items() if v.conference_id == conference_id]
            for k in keys:
                del table[k]
            out[name] = len(keys)
        return out

    # ------------------------------------------------------------------ search
    def _scored(self, conference_id: str, query: str, speaker: str | None, session_id: str | None):
        pool = [u for u in self.utterances.values()
                if u.conference_id == conference_id and _speaker_matches(u, speaker)
                and (session_id is None or u.session_id == session_id)]
        q = set(tokens(query))
        if not q:
            return [(u, None) for u in sorted(pool, key=lambda u: (u.session_starts_at, u.start_s))]
        docs = {u.utterance_id: Counter(tokens(f"{u.text} {u.session_title}")) for u in pool}
        n = max(len(docs), 1)
        df = {t: sum(1 for c in docs.values() if t in c) for t in q}
        scored = []
        for u in pool:
            tf = docs[u.utterance_id]
            score = sum((1 + math.log(tf[t])) * (math.log((n + 1) / (df[t] + 0.5)) + 1) for t in q if tf[t])
            if score > 0:
                scored.append((u, round(score, 4)))
        scored.sort(key=lambda p: (-p[1], p[0].session_starts_at, p[0].start_s))
        return scored

    def search_utterances(
        self, conference_id: str, query: str, *, speaker: str | None, session_id: str | None, size: int,
    ) -> tuple[list[tuple[Utterance, float | None]], str]:
        return self._scored(conference_id, query, speaker, session_id)[:size], "keyword"

    def utterances_by_speaker(self, conference_id: str, speaker: str, size: int) -> list[Utterance]:
        found = [u for u in self.utterances.values()
                 if u.conference_id == conference_id and _speaker_matches(u, speaker)]
        found.sort(key=lambda u: (u.session_starts_at, u.start_s))
        return found[:size]

    def top_speakers(self, conference_id: str, query: str, size: int) -> list[tuple[str, str, int]]:
        counts: Counter[str] = Counter()
        names: dict[str, str] = {}
        for u, _ in self._scored(conference_id, query, None, None):
            if u.speaker_status != "identified":
                continue
            counts[u.speaker_id] += 1
            names[u.speaker_id] = u.speaker_name
        return [(pid, names[pid], n) for pid, n in counts.most_common(size)]

    def counts(self, conference_id: str) -> dict[str, int]:
        def c(table: dict[str, Any]) -> int:
            return sum(1 for v in table.values() if v.conference_id == conference_id)

        return {"sessions": c(self.sessions), "voiceprint_samples": c(self.samples),
                "voiceprints": c(self.voiceprints), "utterances": c(self.utterances),
                "unknown_voices": c(self.unknown_voices)}
