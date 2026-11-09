"""Settings for speaker identification. Environment variables only (AGENTS.md §3).

| Variable | Default | Meaning |
|---|---|---|
| `SPEAKERS_CONFERENCE_ID` | `cnh-2026` | Every document and query is scoped to this conference (§8) |
| `SPEAKERS_MODEL_ID` | `speechbrain/spkrec-ecapa-voxceleb` | Embedding model; every kNN query filters on it (§3) |
| `SPEAKERS_INDEX_PREFIX` | `rapport-speakers` | Index names are `<prefix>-sessions`, `<prefix>-voiceprints`, ... |
| `SPEAKERS_T_ACCEPT`, `SPEAKERS_MARGIN`, `SPEAKERS_MIN_SPEECH_S` | 0.55, 0.10, 3.0 | Decision rule (§5.4) |
| `SPEAKERS_POOL_MODE` | `boost` | Scheduled-speaker narrowing: `boost`, `filter` or `off` (§5.4, §10) |
| `SPEAKERS_POOL_BONUS` | 0.05 | Cosine bonus for scheduled speakers in `boost` mode |
| `SPEAKERS_STORE` | auto | `es` or `memory`; auto = `es` when `ES_URL` and `SPEAKERS_ES_API_KEY` are set |
| `ES_URL`, `SPEAKERS_ES_API_KEY` | | Elasticsearch; `ES_API_KEY` is used only with `SPEAKERS_STORE=es` |
| `ES_INFERENCE_ID` | auto-detected | `semantic_text` endpoint, as for the memory indices (§10 open question) |
| `ES_RERANK_INFERENCE_ID` | unset | Optional Jina reranker over the RRF result, as in `rapport_memory` |
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

MODEL_ID_DEFAULT = "speechbrain/spkrec-ecapa-voxceleb"
EMBEDDING_DIMS = 192  # ECAPA-TDNN
CONFERENCE_ID_DEFAULT = "cnh-2026"
INDEX_PREFIX_DEFAULT = "rapport-speakers"

POOL_BOOST = "boost"
POOL_FILTER = "filter"
POOL_OFF = "off"
POOL_MODES = (POOL_BOOST, POOL_FILTER, POOL_OFF)

STORE_ES = "es"
STORE_MEMORY = "memory"


@dataclass(frozen=True)
class Indices:
    sessions: str
    samples: str
    voiceprints: str
    utterances: str
    unknown_voices: str

    @classmethod
    def with_prefix(cls, prefix: str = INDEX_PREFIX_DEFAULT) -> Indices:
        return cls(
            sessions=f"{prefix}-sessions",
            samples=f"{prefix}-voiceprint-samples",
            voiceprints=f"{prefix}-voiceprints",
            utterances=f"{prefix}-utterances",
            unknown_voices=f"{prefix}-unknown-voices",
        )

    def all(self) -> list[str]:
        return [self.sessions, self.samples, self.voiceprints, self.utterances, self.unknown_voices]

    def biometric(self) -> list[str]:
        """Indices that hold voice embeddings (deleted on erasure and at the end of retention)."""
        return [self.samples, self.voiceprints, self.unknown_voices]


@dataclass(frozen=True)
class Thresholds:
    """Decision rule placeholders from §5.4, in cosine terms. Calibrate with `cli eval` (§7)."""

    t_accept: float = 0.55
    margin: float = 0.10
    min_speech_s: float = 3.0


@dataclass(frozen=True)
class EnrollGuards:
    """Schedule auto-enrollment guards (§5.3 step 2) and the corroboration window (step 3)."""

    min_share: float = 0.60
    min_speech_s: float = 60.0
    corroboration_window_s: float = 90.0
    max_embed_s: float = 60.0  # about 60 s of clean speech per embedding (§5.2 step 3)


@dataclass(frozen=True)
class Settings:
    conference_id: str = CONFERENCE_ID_DEFAULT
    model_id: str = MODEL_ID_DEFAULT
    indices: Indices = field(default_factory=Indices.with_prefix)
    thresholds: Thresholds = field(default_factory=Thresholds)
    guards: EnrollGuards = field(default_factory=EnrollGuards)
    pool_mode: str = POOL_BOOST
    pool_bonus: float = 0.05
    store: str = STORE_MEMORY
    es_url: str | None = None
    es_api_key: str | None = None
    inference_id: str | None = None
    rerank_inference_id: str | None = None
    knn_k: int = 5
    knn_num_candidates: int = 50

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        def num(name: str, default: float) -> float:
            raw = env.get(name)
            return float(raw) if raw not in (None, "") else default

        pool_mode = env.get("SPEAKERS_POOL_MODE", POOL_BOOST).strip().lower() or POOL_BOOST
        if pool_mode not in POOL_MODES:
            raise ValueError(f"SPEAKERS_POOL_MODE must be one of {', '.join(POOL_MODES)}")
        es_url = env.get("ES_URL") or None
        speakers_key = env.get("SPEAKERS_ES_API_KEY") or None
        store = (env.get("SPEAKERS_STORE") or "").strip().lower()
        if not store:
            # Only the dedicated key switches to Elasticsearch on its own: a pod that mounts this router may hold
            # another component's ES_API_KEY (a briefer's, say), which has no access to the speaker indices.
            store = STORE_ES if es_url and speakers_key else STORE_MEMORY
        es_api_key = speakers_key or (env.get("ES_API_KEY") if store == STORE_ES else None) or None
        if store not in (STORE_ES, STORE_MEMORY):
            raise ValueError("SPEAKERS_STORE must be es or memory")
        return cls(
            conference_id=env.get("SPEAKERS_CONFERENCE_ID") or CONFERENCE_ID_DEFAULT,
            model_id=env.get("SPEAKERS_MODEL_ID") or MODEL_ID_DEFAULT,
            indices=Indices.with_prefix(env.get("SPEAKERS_INDEX_PREFIX") or INDEX_PREFIX_DEFAULT),
            thresholds=Thresholds(
                t_accept=num("SPEAKERS_T_ACCEPT", Thresholds.t_accept),
                margin=num("SPEAKERS_MARGIN", Thresholds.margin),
                min_speech_s=num("SPEAKERS_MIN_SPEECH_S", Thresholds.min_speech_s),
            ),
            pool_mode=pool_mode,
            pool_bonus=num("SPEAKERS_POOL_BONUS", 0.05),
            store=store,
            es_url=es_url,
            es_api_key=es_api_key,
            inference_id=env.get("ES_INFERENCE_ID") or None,
            rerank_inference_id=env.get("ES_RERANK_INFERENCE_ID") or None,
        )
