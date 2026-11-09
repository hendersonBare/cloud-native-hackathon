"""Elasticsearch implementation of the speaker store (spec §4-§8).

Synchronous like `rapport_memory.client.MemoryClient` (the same elasticsearch-py client, timeouts and the same
RRF -> bool -> keyword fallback); async callers use `asyncio.to_thread`.

Every call goes to one of the five configured indices and filters on `conference_id`. Logs carry index
names, document IDs and counts only: never transcript text, names, queries or vectors.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from elasticsearch import ApiError, BadRequestError, Elasticsearch

from rapport_memory.client import MODE_BOOL, MODE_KEYWORD, MODE_RRF, RANK_WINDOW, REQUEST_TIMEOUT_S

from .config import Settings
from .models import Person, SessionDoc, UnknownVoice, Utterance, Voiceprint, VoiceprintSample

log = logging.getLogger("rapport.speakers.es")

TEMPLATES_PATH = Path(__file__).parent / "elastic" / "index-templates.json"
SEMANTIC_FIELD = "text_semantic"
INFERENCE_PLACEHOLDER = "__INFERENCE_ID__"
# Same preference order as scripts/setup-elastic.sh, so utterances use the memory indices' endpoint.
INFERENCE_CANDIDATES = (".jina-embeddings-v5-text-small", ".elser-2-elastic", ".elser-2-elasticsearch")
_MODES = (MODE_RRF, MODE_BOOL, MODE_KEYWORD)
_UTTERANCE_FIELDS = frozenset(Utterance.model_fields)
_UNKNOWN_SOURCE = ["unknown_id", "session_id", "duration_s", "status", "best_candidate_id", "best_score",
                   "runner_up_id", "runner_up_score"]

RELABEL_SCRIPT = (
    "ctx._source.speaker_id = params.pid; ctx._source.speaker_name = params.name; "
    "ctx._source.speaker_status = 'identified'; ctx._source.match_score = params.score;"
)
RESET_SCRIPT = (
    "ctx._source.speaker_id = ctx._source.voice_id; ctx._source.speaker_name = ctx._source.voice_label; "
    "ctx._source.speaker_status = 'unknown'; ctx._source.remove('match_score');"
)
UNLINK_SCRIPT = (
    "if (ctx._source.best_candidate_id == params.pid) { ctx._source.remove('best_candidate_id'); "
    "ctx._source.remove('best_score'); } "
    "if (ctx._source.runner_up_id == params.pid) { ctx._source.remove('runner_up_id'); "
    "ctx._source.remove('runner_up_score'); }"
)


def load_templates() -> dict[str, Any]:
    return json.loads(TEMPLATES_PATH.read_text())


def template_for(logical: str, inference_id: str | None) -> dict[str, Any]:
    """The `template` block for one index. Without an inference endpoint the utterances index has no
    semantic_text field and search runs keyword-only."""
    tpl = copy.deepcopy(load_templates()["templates"][logical])
    props = tpl["mappings"]["properties"]
    if SEMANTIC_FIELD in props:
        if inference_id:
            props[SEMANTIC_FIELD]["inference_id"] = inference_id
        else:
            del props[SEMANTIC_FIELD]
    return tpl


def to_utterance(source: dict[str, Any]) -> Utterance:
    return Utterance.model_validate({k: v for k, v in source.items() if k in _UTTERANCE_FIELDS})


class EsSpeakerStore:
    def __init__(self, settings: Settings, *, es: Any | None = None) -> None:
        self._s = settings
        self._ix = settings.indices
        # `es` lets tests inject a fake with the same methods.
        self._es = es if es is not None else Elasticsearch(
            settings.es_url, api_key=settings.es_api_key, request_timeout=REQUEST_TIMEOUT_S,
        )
        self._allowed = frozenset(self._ix.all())
        self._mode = MODE_RRF
        self._rerank_id = settings.rerank_inference_id
        self._semantic = True  # whether utterances carry text_semantic; ensure_indices settles it

    @property
    def mode(self) -> str:
        return self._mode

    def _check(self, index: str) -> str:
        if index not in self._allowed:
            raise ValueError(f"index not allowed for the speaker store: {index}")
        return index

    # ------------------------------------------------------------------ setup
    def detect_inference_id(self) -> str | None:
        if self._s.inference_id:
            return self._s.inference_id
        try:
            resp = self._es.inference.get()
        except ApiError as exc:
            log.warning("cannot list inference endpoints (status=%s); utterances will be keyword-only",
                        exc.status_code)
            return None
        ids = {e.get("inference_id") for e in resp.get("endpoints", [])}
        return next((c for c in INFERENCE_CANDIDATES if c in ids), None)

    def ensure_indices(self) -> None:
        """Put one index template per index (priority above the rapport-* memory template), then create any
        missing index. Idempotent."""
        inference_id = self.detect_inference_id()
        self._semantic = inference_id is not None
        priority = int(load_templates()["priority"])
        logical = {
            "sessions": self._ix.sessions, "voiceprint_samples": self._ix.samples,
            "voiceprints": self._ix.voiceprints, "utterances": self._ix.utterances,
            "unknown_voices": self._ix.unknown_voices,
        }
        for name, index in logical.items():
            self._es.indices.put_index_template(
                name=index, index_patterns=[index], priority=priority,
                template=template_for(name, inference_id),
                meta={"owner": "rapport", "component": "speakers"},
            )
            if not self._es.indices.exists(index=index):
                self._es.indices.create(index=index)
                log.info("created index %s", index)
        log.info("speaker indices ready (semantic=%s)", self._semantic)

    # ------------------------------------------------------------------ write helpers
    def _bulk(self, index: str, docs: list[tuple[str, dict[str, Any]]]) -> int:
        self._check(index)
        if not docs:
            return 0
        operations: list[dict[str, Any]] = []
        for doc_id, doc in docs:
            operations.append({"index": {"_index": index, "_id": doc_id}})
            operations.append(doc)
        resp = self._es.bulk(operations=operations, refresh="wait_for")
        if resp.get("errors"):
            failed = [(i["index"].get("_id"), i["index"].get("status"))
                      for i in resp["items"] if i["index"].get("error")]
            log.error("bulk write to %s failed for %d of %d documents: %s", index, len(failed), len(docs), failed[:10])
            raise RuntimeError(f"Elasticsearch rejected {len(failed)} of {len(docs)} documents in {index}")
        return len(docs)

    @staticmethod
    def _dump(model: Any) -> dict[str, Any]:
        return model.model_dump(mode="json", exclude_none=True)

    def _by_query(self, op: str, index: str, query: dict[str, Any], script: dict[str, Any] | None = None) -> int:
        self._check(index)
        kwargs: dict[str, Any] = {"index": index, "query": query, "refresh": True, "conflicts": "proceed"}
        if script is not None:
            kwargs["script"] = script
        resp = getattr(self._es, op)(**kwargs)
        return int(resp.get("updated" if op == "update_by_query" else "deleted", 0))

    @staticmethod
    def _conf(conference_id: str, *more: dict[str, Any]) -> dict[str, Any]:
        return {"bool": {"filter": [{"term": {"conference_id": conference_id}}, *more]}}

    # ------------------------------------------------------------------ sessions and samples
    def upsert_sessions(self, sessions: list[SessionDoc]) -> int:
        return self._bulk(self._ix.sessions, [(f"{s.conference_id}:{s.session_id}", self._dump(s)) for s in sessions])

    def get_session(self, conference_id: str, session_id: str) -> SessionDoc | None:
        resp = self._es.search(
            index=self._check(self._ix.sessions), size=1,
            query=self._conf(conference_id, {"term": {"session_id": session_id}}),
        )
        hits = resp["hits"]["hits"]
        return SessionDoc.model_validate(hits[0]["_source"]) if hits else None

    def add_samples(self, samples: list[VoiceprintSample]) -> int:
        return self._bulk(self._ix.samples, [(s.sample_id, self._dump(s)) for s in samples])

    def samples_for(self, conference_id: str, person_id: str, model_id: str) -> list[VoiceprintSample]:
        resp = self._es.search(
            index=self._check(self._ix.samples), size=500, sort=[{"sample_id": "asc"}],
            query=self._conf(conference_id, {"term": {"person_id": person_id}}, {"term": {"model_id": model_id}}),
        )
        return [VoiceprintSample.model_validate(h["_source"]) for h in resp["hits"]["hits"]]

    # ------------------------------------------------------------------ voiceprints and kNN (§5.4)
    def upsert_voiceprint(self, voiceprint: Voiceprint) -> None:
        self._bulk(self._ix.voiceprints, [(voiceprint.doc_id, self._dump(voiceprint))])

    def _knn(self, index: str, field: str, vector: list[float], k: int, num_candidates: int,
             filter_query: dict[str, Any], source: list[str]) -> list[dict[str, Any]]:
        resp = self._es.search(
            index=self._check(index), size=k, source=source,
            knn={"field": field, "query_vector": list(vector), "k": k, "num_candidates": num_candidates,
                 "filter": filter_query},
        )
        return [{"_score": h["_score"], "_source": h["_source"]} for h in resp["hits"]["hits"]]

    def knn_voiceprints(
        self, vector: list[float], *, conference_id: str, model_id: str, k: int, num_candidates: int,
        person_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        extra = [{"term": {"model_id": model_id}}]
        if person_ids is not None:
            extra.append({"terms": {"person_id": list(person_ids)}})
        return self._knn(self._ix.voiceprints, "centroid", vector, k, num_candidates,
                         self._conf(conference_id, *extra), ["person_id", "name", "affiliation"])

    # ------------------------------------------------------------------ utterances and unknown voices
    def index_utterances(self, utterances: list[Utterance]) -> int:
        docs = []
        for u in utterances:
            doc = self._dump(u)
            if self._semantic:
                doc[SEMANTIC_FIELD] = u.text
            docs.append((u.utterance_id, doc))
        return self._bulk(self._ix.utterances, docs)

    def replace_unknown_voices(self, conference_id: str, session_id: str, voices: list[UnknownVoice]) -> int:
        self._by_query("delete_by_query", self._ix.unknown_voices,
                       self._conf(conference_id, {"term": {"session_id": session_id}}))
        return self._bulk(self._ix.unknown_voices, [(v.unknown_id, self._dump(v)) for v in voices])

    def knn_unknown_voices(
        self, vector: list[float], *, conference_id: str, model_id: str, k: int, num_candidates: int,
    ) -> list[dict[str, Any]]:
        filter_query = self._conf(conference_id, {"term": {"model_id": model_id}})
        filter_query["bool"]["must_not"] = [{"exists": {"field": "resolved_person_id"}}]
        return self._knn(self._ix.unknown_voices, "embedding", vector, k, num_candidates, filter_query,
                         _UNKNOWN_SOURCE)

    def resolve_unknown_voice(self, conference_id: str, unknown_id: str, person_id: str) -> None:
        self._by_query(
            "update_by_query", self._ix.unknown_voices,
            self._conf(conference_id, {"term": {"unknown_id": unknown_id}}),
            {"source": "ctx._source.resolved_person_id = params.pid", "lang": "painless",
             "params": {"pid": person_id}},
        )

    def relabel_voice(self, conference_id: str, voice_id: str, person: Person, score: float | None) -> int:
        """§5.5: `_update_by_query` on utterances of one voice."""
        return self._by_query(
            "update_by_query", self._ix.utterances,
            self._conf(conference_id, {"term": {"voice_id": voice_id}}),
            {"source": RELABEL_SCRIPT, "lang": "painless",
             "params": {"pid": person.person_id, "name": person.name, "score": score}},
        )

    # ------------------------------------------------------------------ erasure and retention (§8)
    def erase_person(self, conference_id: str, person_id: str) -> dict[str, int]:
        person = {"term": {"person_id": person_id}}
        out = {
            "voiceprints": self._by_query("delete_by_query", self._ix.voiceprints, self._conf(conference_id, person)),
            "samples": self._by_query("delete_by_query", self._ix.samples, self._conf(conference_id, person)),
            "unknown_voices": self._by_query(
                "delete_by_query", self._ix.unknown_voices,
                self._conf(conference_id, {"term": {"resolved_person_id": person_id}}),
            ),
        }
        unlink_query = self._conf(conference_id)
        unlink_query["bool"]["should"] = [{"term": {"best_candidate_id": person_id}},
                                          {"term": {"runner_up_id": person_id}}]
        unlink_query["bool"]["minimum_should_match"] = 1
        out["unknown_voices_unlinked"] = self._by_query(
            "update_by_query", self._ix.unknown_voices, unlink_query,
            {"source": UNLINK_SCRIPT, "lang": "painless", "params": {"pid": person_id}},
        )
        out["utterances"] = self._by_query(
            "update_by_query", self._ix.utterances,
            self._conf(conference_id, {"term": {"speaker_id": person_id}}),
            {"source": RESET_SCRIPT, "lang": "painless"},
        )
        return out

    def purge_biometrics(self, conference_id: str) -> dict[str, int]:
        return {
            "voiceprints": self._by_query("delete_by_query", self._ix.voiceprints, self._conf(conference_id)),
            "samples": self._by_query("delete_by_query", self._ix.samples, self._conf(conference_id)),
            "unknown_voices": self._by_query("delete_by_query", self._ix.unknown_voices, self._conf(conference_id)),
        }

    # ------------------------------------------------------------------ search (§6)
    @staticmethod
    def _filters(conference_id: str, speaker: str | None, session_id: str | None,
                 identified_only: bool = False) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [{"term": {"conference_id": conference_id}}]
        if speaker:
            filters.append({"bool": {"should": [{"term": {"speaker_id": speaker}},
                                                {"term": {"speaker_name.lc": speaker.lower()}}],
                                     "minimum_should_match": 1}})
        if session_id:
            filters.append({"term": {"session_id": session_id}})
        if identified_only:
            filters.append({"term": {"speaker_status": "identified"}})
        return filters

    @staticmethod
    def _keyword(query: str) -> dict[str, Any]:
        return {"match": {"text": query}}

    @staticmethod
    def _semantic_clause(query: str) -> dict[str, Any]:
        return {"semantic": {"field": SEMANTIC_FIELD, "query": query}}

    def build_search_body(self, query: str, filters: list[dict[str, Any]], size: int, mode: str | None = None,
                          rerank: bool = False) -> dict[str, Any]:
        """The §6.1 request. Public so tests and the PR can show exactly what is sent."""
        mode = mode or self._mode
        body: dict[str, Any] = {"size": size, "source": {"excludes": [SEMANTIC_FIELD]}}
        if not query.strip():
            body["query"] = {"bool": {"filter": filters}}
            body["sort"] = [{"session_starts_at": "asc"}, {"start_s": "asc"}]
            return body
        if mode == MODE_RRF:
            retriever: dict[str, Any] = {"rrf": {"rank_window_size": max(RANK_WINDOW, size), "retrievers": [
                {"standard": {"query": {"bool": {"must": self._keyword(query), "filter": filters}}}},
                {"standard": {"query": {"bool": {"must": self._semantic_clause(query), "filter": filters}}}},
            ]}}
            if rerank and self._rerank_id:
                retriever = {"text_similarity_reranker": {
                    "retriever": retriever, "field": "text", "inference_id": self._rerank_id,
                    "inference_text": query, "rank_window_size": max(RANK_WINDOW, size),
                }}
            body["retriever"] = retriever
        elif mode == MODE_BOOL:
            body["query"] = {"bool": {"should": [self._keyword(query), self._semantic_clause(query)],
                                      "minimum_should_match": 1, "filter": filters}}
        else:
            body["query"] = {"bool": {"must": self._keyword(query), "filter": filters}}
        return body

    def _run(self, body: dict[str, Any]) -> list[tuple[Utterance, float | None]]:
        resp = self._es.search(index=self._check(self._ix.utterances), **body)
        out: list[tuple[Utterance, float | None]] = []
        for hit in resp["hits"]["hits"]:
            try:
                out.append((to_utterance(hit["_source"]), hit.get("_score")))
            except ValueError:
                log.warning("skipping invalid utterance id=%s", hit.get("_id"))
        return out

    def search_utterances(
        self, conference_id: str, query: str, *, speaker: str | None, session_id: str | None, size: int,
    ) -> tuple[list[tuple[Utterance, float | None]], str]:
        filters = self._filters(conference_id, speaker, session_id)
        if self._mode == MODE_RRF and self._rerank_id and query.strip():
            try:
                return self._run(self.build_search_body(query, filters, size, rerank=True)), "rrf+rerank"
            except ApiError as exc:
                if exc.status_code in (401, 403):
                    raise
                if exc.status_code in (400, 404):
                    self._rerank_id = None
                log.warning("rerank failed (status=%s); continuing without rerank", exc.status_code)
        if not self._semantic and self._mode != MODE_KEYWORD:
            self._mode = MODE_KEYWORD
        while True:
            try:
                return self._run(self.build_search_body(query, filters, size)), self._mode
            except BadRequestError as exc:
                nxt = _MODES.index(self._mode) + 1
                if nxt >= len(_MODES):
                    raise
                log.warning("utterance query mode %s rejected (status=%s); using %s", self._mode,
                            exc.status_code, _MODES[nxt])
                self._mode = _MODES[nxt]

    def utterances_by_speaker(self, conference_id: str, speaker: str, size: int) -> list[Utterance]:
        body = self.build_search_body("", self._filters(conference_id, speaker, None), size)
        return [u for u, _ in self._run(body)]

    def top_speakers(self, conference_id: str, query: str, size: int) -> list[tuple[str, str, int]]:
        """§6.2: who talked most about X (identified speakers only)."""
        filters = self._filters(conference_id, None, None, identified_only=True)
        mode = MODE_BOOL if self._mode == MODE_RRF and self._semantic else self._mode
        while True:
            body = self.build_search_body(query, filters, 0, mode=mode)
            body.pop("sort", None)
            body["aggs"] = {"by_speaker": {"terms": {"field": "speaker_id", "size": size}, "aggs": {
                "name": {"top_hits": {"size": 1, "_source": {"includes": ["speaker_name"]}}}}}}
            try:
                resp = self._es.search(index=self._check(self._ix.utterances), **body)
                break
            except BadRequestError:
                if mode == MODE_KEYWORD:
                    raise
                mode = MODE_KEYWORD
        out = []
        for b in resp["aggregations"]["by_speaker"]["buckets"]:
            hits = b["name"]["hits"]["hits"]
            name = hits[0]["_source"].get("speaker_name", b["key"]) if hits else b["key"]
            out.append((b["key"], name, int(b["doc_count"])))
        return out

    def counts(self, conference_id: str) -> dict[str, int]:
        names = {"sessions": self._ix.sessions, "voiceprint_samples": self._ix.samples,
                 "voiceprints": self._ix.voiceprints, "utterances": self._ix.utterances,
                 "unknown_voices": self._ix.unknown_voices}
        out = {}
        for key, index in names.items():
            resp = self._es.count(index=index, query={"term": {"conference_id": conference_id}},
                                  ignore_unavailable=True)
            out[key] = int(resp["count"])
        return out
