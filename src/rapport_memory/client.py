"""Elasticsearch implementation of rapport_common.interfaces.MemoryStore (SPEC section 4.2).

Synchronous on purpose: MemoryStore is a sync protocol shared with InMemoryStore. Async services call it with
`await asyncio.to_thread(store.search, ...)`.

Logging and spans carry IDs, index names and counts only. Never query text or record content.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from elasticsearch import ApiError, BadRequestError, Elasticsearch

from rapport_common import names, telemetry
from rapport_common.models import MemoryKind, MemoryRecord

log = logging.getLogger("rapport.memory")

SEMANTIC_FIELD = "text_semantic"
SEARCH_FIELDS = ["title^2", "summary", "text", "tags"]
RANK_WINDOW = 50
RERANK_ENV = "ES_RERANK_INFERENCE_ID"
REQUEST_TIMEOUT_S = 10

# Query strategies, best first. A rejected strategy is remembered so later calls skip straight to the next one.
MODE_RRF = "rrf"
MODE_BOOL = "bool"  # one bool query with the keyword and semantic clauses under `should`
MODE_KEYWORD = "keyword"  # keyword only (the index has no usable semantic_text field)
_MODES = (MODE_RRF, MODE_BOOL, MODE_KEYWORD)

_RECORD_FIELDS = frozenset(MemoryRecord.model_fields)


def semantic_text(record: MemoryRecord) -> str:
    """The value written to the semantic_text field (SPEC section 4.2)."""
    return f"{record.title}\n{record.summary}\n{record.text}"


def to_record(source: dict[str, Any]) -> MemoryRecord:
    """Validate an ES `_source` as a MemoryRecord. text_semantic and any other non-contract field are dropped
    because the models forbid extra fields."""
    return MemoryRecord.model_validate({k: v for k, v in source.items() if k in _RECORD_FIELDS})


class MemoryClient:
    def __init__(
        self,
        es_url: str,
        api_key: str,
        *,
        allowed_indices: list[str] | None = None,
        es: Any | None = None,
        rerank_inference_id: str | None = None,
    ) -> None:
        # `es` lets tests inject a fake with the same search/bulk/count methods.
        self._es = es if es is not None else Elasticsearch(es_url, api_key=api_key, request_timeout=REQUEST_TIMEOUT_S)
        self._allowed = frozenset(allowed_indices) if allowed_indices is not None else None
        self._rerank_id = rerank_inference_id or os.environ.get(RERANK_ENV) or None
        self._mode = MODE_RRF

    @property
    def mode(self) -> str:
        """The query strategy in use (rrf, bool or keyword)."""
        return self._mode

    # ------------------------------------------------------------------ guards
    def _check_indices(self, indices: list[str]) -> None:
        if self._allowed is None:
            return
        outside = sorted(set(indices) - self._allowed)
        if outside:
            raise ValueError(f"index not allowed for this client: {', '.join(outside)}")

    # ------------------------------------------------------------------ search
    @staticmethod
    def _filters(
        tags: list[str] | None,
        kinds: list[MemoryKind] | None,
        about_org_ids: list[str] | None,
        owner_persona_id: str | None,
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        if tags:
            filters.append({"terms": {"tags": list(tags)}})
        if kinds:
            filters.append({"terms": {"kind": list(kinds)}})
        if about_org_ids:
            filters.append({"terms": {"about_org_ids": list(about_org_ids)}})
        if owner_persona_id:
            filters.append({"term": {"owner_persona_id": owner_persona_id}})
        return filters

    @staticmethod
    def _keyword_clause(query: str) -> dict[str, Any]:
        return {"multi_match": {"query": query, "fields": SEARCH_FIELDS}}

    @staticmethod
    def _semantic_clause(query: str) -> dict[str, Any]:
        return {"semantic": {"field": SEMANTIC_FIELD, "query": query}}

    def build_body(
        self,
        query: str,
        *,
        filters: list[dict[str, Any]],
        size: int,
        mode: str | None = None,
        rerank: bool | None = None,
    ) -> dict[str, Any]:
        """The search request body (SPEC section 4.2). Public so tests and docs can show exactly what is sent."""
        mode = mode or self._mode
        body: dict[str, Any] = {"size": size, "source": {"excludes": [SEMANTIC_FIELD]}}
        if not query.strip():  # nothing to rank by: filters only
            body["query"] = {"bool": {"filter": filters}}
            return body
        if mode == MODE_RRF:
            retriever: dict[str, Any] = {
                "rrf": {
                    "rank_window_size": max(RANK_WINDOW, size),
                    "retrievers": [
                        {"standard": {"query": {"bool": {"must": self._keyword_clause(query), "filter": filters}}}},
                        {"standard": {"query": {"bool": {"must": self._semantic_clause(query), "filter": filters}}}},
                    ],
                }
            }
            use_rerank = bool(self._rerank_id) if rerank is None else rerank
            if use_rerank and self._rerank_id:
                retriever = {
                    "text_similarity_reranker": {
                        "retriever": retriever,
                        "field": "text",
                        "inference_id": self._rerank_id,
                        "inference_text": query,
                        "rank_window_size": max(RANK_WINDOW, size),
                    }
                }
            body["retriever"] = retriever
        elif mode == MODE_BOOL:
            body["query"] = {
                "bool": {
                    "should": [self._keyword_clause(query), self._semantic_clause(query)],
                    "minimum_should_match": 1,
                    "filter": filters,
                }
            }
        else:
            body["query"] = {"bool": {"must": self._keyword_clause(query), "filter": filters}}
        return body

    def _run(self, indices: list[str], body: dict[str, Any]) -> list[MemoryRecord]:
        resp = self._es.search(index=indices, ignore_unavailable=True, **body)
        records: list[MemoryRecord] = []
        for hit in resp["hits"]["hits"]:
            try:
                records.append(to_record(hit["_source"]))
            except ValueError:
                log.warning("skipping invalid memory document id=%s", hit.get("_id"))
        return records

    def search(
        self,
        query: str,
        *,
        indices: list[str],
        tags: list[str] | None = None,
        kinds: list[MemoryKind] | None = None,
        about_org_ids: list[str] | None = None,
        owner_persona_id: str | None = None,
        size: int = 5,
    ) -> list[MemoryRecord]:
        self._check_indices(indices)
        if not indices:  # an empty list would search every index
            return []
        filters = self._filters(tags, kinds, about_org_ids, owner_persona_id)
        with telemetry.tracer("rapport.memory").start_as_current_span("memory.search") as span:
            records = self._search_with_fallback(query, indices, filters, size)
            span.set_attribute(telemetry.ATTR_RESULT_COUNT, len(records))
        return records

    def _search_with_fallback(
        self, query: str, indices: list[str], filters: list[dict[str, Any]], size: int
    ) -> list[MemoryRecord]:
        if self._mode == MODE_RRF and self._rerank_id and query.strip():
            try:
                return self._run(indices, self.build_body(query, filters=filters, size=size, rerank=True))
            except ApiError as exc:
                if exc.status_code in (401, 403):
                    raise  # a permission problem is not a rerank problem
                log.warning("rerank failed (status=%s); continuing without rerank", exc.status_code)
                self._rerank_id = None
        while True:
            try:
                return self._run(indices, self.build_body(query, filters=filters, size=size))
            except BadRequestError as exc:
                next_mode = _MODES.index(self._mode) + 1
                if next_mode >= len(_MODES):
                    raise
                log.warning("query mode %s rejected (status=%s); using %s", self._mode, exc.status_code,
                            _MODES[next_mode])
                self._mode = _MODES[next_mode]

    # ------------------------------------------------------------------ get
    def get(self, memory_id: str, *, indices: list[str]) -> MemoryRecord | None:
        self._check_indices(indices)
        if not indices:
            return None
        body = {"query": {"ids": {"values": [memory_id]}}, "size": 1, "source": {"excludes": [SEMANTIC_FIELD]}}
        found = self._run(indices, body)
        return found[0] if found else None

    # ------------------------------------------------------------------ write
    def write(self, records: list[MemoryRecord]) -> int:
        if not records:
            return 0
        # Re-validate so a record mutated after construction cannot reach the wrong index or skip a rule.
        checked = [MemoryRecord.model_validate(r.model_dump()) for r in records]
        targets = [names.index_for(r) for r in checked]
        self._check_indices(targets)  # refuse the whole batch before writing any of it
        operations: list[dict[str, Any]] = []
        for record, index in zip(checked, targets):
            operations.append({"index": {"_index": index, "_id": record.memory_id}})
            doc = record.model_dump(mode="json", exclude_none=True)
            doc[SEMANTIC_FIELD] = semantic_text(record)
            operations.append(doc)
        resp = self._es.bulk(operations=operations, refresh="wait_for")
        if resp["errors"]:
            failed = [
                (item["index"].get("_id"), item["index"].get("status"))
                for item in resp["items"]
                if item["index"].get("error")
            ]
            log.error("bulk write failed for %d of %d documents: %s", len(failed), len(checked), failed[:10])
            raise RuntimeError(f"Elasticsearch rejected {len(failed)} of {len(checked)} documents")
        return len(checked)

    # ------------------------------------------------------------------ admin helper (seed loader)
    def count(self, indices: list[str]) -> dict[str, int]:
        """Document count per index (the seed loader prints this)."""
        self._check_indices(indices)
        return {index: int(self._es.count(index=index)["count"]) for index in indices}
