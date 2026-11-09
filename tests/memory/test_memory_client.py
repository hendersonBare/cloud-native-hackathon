"""MemoryClient against a fake Elasticsearch object that records every call."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import ApiError, AuthorizationException, BadRequestError

from rapport_common.models import MemoryRecord
from rapport_common.names import CONFERENCE_INDEX, internal_index, shareable_index
from rapport_memory.client import MemoryClient, semantic_text, to_record
from rapport_memory.seed import seed_records


def _meta(status: int) -> ApiResponseMeta:
    return ApiResponseMeta(
        status=status, http_version="1.1", headers=HttpHeaders(), duration=0.0,
        node=NodeConfig("http", "localhost", 9200),
    )


def bad_request() -> BadRequestError:
    return BadRequestError("rejected", _meta(400), {"error": "unknown retriever"})


def forbidden() -> AuthorizationException:
    return AuthorizationException("forbidden", _meta(403), {"error": "security_exception"})


class FakeES:
    def __init__(self, hits=None, fail_when=None):
        self.hits = hits or []
        self.fail_when = fail_when  # callable(kwargs) -> exception | None
        self.searches: list[dict] = []
        self.bulks: list[dict] = []
        self.bulk_response = {"errors": False, "items": []}

    def search(self, **kw):
        self.searches.append(kw)
        exc = self.fail_when(kw) if self.fail_when else None
        if exc:
            raise exc
        return {"hits": {"hits": self.hits}}

    def bulk(self, **kw):
        self.bulks.append(kw)
        return self.bulk_response

    def count(self, **kw):
        return {"count": 3}


def doc(record: MemoryRecord, **extra) -> dict:
    source = record.model_dump(mode="json", exclude_none=True)
    source["text_semantic"] = {"text": semantic_text(record), "inference": {"chunks": []}}  # ES may return this
    source.update(extra)
    return {"_id": record.memory_id, "_index": "x", "_score": 1.0, "_source": source}


def a_record(memory_id="acme-doc-0001") -> MemoryRecord:
    return next(r for r in seed_records() if r.memory_id == memory_id)


ACME_SHAREABLE = shareable_index("acme")


def client(es, **kw) -> MemoryClient:
    return MemoryClient("http://es.invalid", "key", es=es, **kw)


def test_rrf_body_has_keyword_and_semantic_retrievers_with_same_filters():
    es = FakeES()
    client(es).search(
        "ebpf tracing", indices=[ACME_SHAREABLE, CONFERENCE_INDEX], tags=["ebpf"], kinds=["talk"],
        about_org_ids=["bluefin"], owner_persona_id="acme.ava", size=7,
    )
    call = es.searches[0]
    assert call["index"] == [ACME_SHAREABLE, CONFERENCE_INDEX]
    assert call["size"] == 7
    assert call["source"] == {"excludes": ["text_semantic"]}
    assert "query" not in call
    rrf = call["retriever"]["rrf"]
    assert rrf["rank_window_size"] >= 50
    keyword, semantic = (r["standard"]["query"]["bool"] for r in rrf["retrievers"])
    fields = ["title^2", "summary", "text", "tags"]
    assert keyword["must"] == {"multi_match": {"query": "ebpf tracing", "fields": fields}}
    assert semantic["must"] == {"semantic": {"field": "text_semantic", "query": "ebpf tracing"}}
    expected = [
        {"terms": {"tags": ["ebpf"]}},
        {"terms": {"kind": ["talk"]}},
        {"terms": {"about_org_ids": ["bluefin"]}},
        {"term": {"owner_persona_id": "acme.ava"}},
    ]
    assert keyword["filter"] == expected
    assert semantic["filter"] == expected


def test_rejected_retriever_falls_back_to_bool_should_and_is_remembered():
    es = FakeES(fail_when=lambda kw: bad_request() if "retriever" in kw else None)
    c = client(es)
    c.search("ebpf", indices=[CONFERENCE_INDEX], tags=["ebpf"])
    assert c.mode == "bool"
    assert len(es.searches) == 2
    query = es.searches[1]["query"]["bool"]
    assert [list(clause)[0] for clause in query["should"]] == ["multi_match", "semantic"]
    assert query["minimum_should_match"] == 1
    assert query["filter"] == [{"terms": {"tags": ["ebpf"]}}]
    c.search("ebpf", indices=[CONFERENCE_INDEX])
    assert len(es.searches) == 3  # the second call did not retry the retriever
    assert "retriever" not in es.searches[2]


def test_falls_back_to_keyword_only_when_semantic_is_also_rejected():
    es = FakeES(fail_when=lambda kw: bad_request() if "retriever" in kw or "'semantic':" in str(kw) else None)
    c = client(es)
    c.search("ebpf", indices=[CONFERENCE_INDEX])
    assert c.mode == "keyword"
    assert "'semantic':" not in str(es.searches[-1])
    assert "multi_match" in str(es.searches[-1])


def test_permission_errors_are_not_swallowed_by_the_fallback():
    es = FakeES(fail_when=lambda kw: forbidden())
    with pytest.raises(AuthorizationException):
        client(es).search("ebpf", indices=[CONFERENCE_INDEX])
    assert len(es.searches) == 1


def test_results_are_validated_and_text_semantic_is_stripped():
    record = a_record()
    es = FakeES(hits=[doc(record, _extra_metadata="x")])
    found = client(es).search("ebpf", indices=[ACME_SHAREABLE])
    assert found == [record]
    assert to_record(doc(record)["_source"]) == record


def test_invalid_documents_are_skipped_not_fatal():
    bad = {"_id": "broken", "_source": {"memory_id": "broken"}}
    es = FakeES(hits=[bad, doc(a_record())])
    found = client(es).search("ebpf", indices=[ACME_SHAREABLE])
    assert [r.memory_id for r in found] == ["acme-doc-0001"]


def test_empty_query_uses_filters_only_and_empty_indices_search_nothing():
    es = FakeES()
    c = client(es)
    c.search("  ", indices=[CONFERENCE_INDEX], kinds=["attendee"])
    assert es.searches[0]["query"] == {"bool": {"filter": [{"terms": {"kind": ["attendee"]}}]}}
    assert c.search("ebpf", indices=[]) == []
    assert c.get("acme-doc-0001", indices=[]) is None
    assert len(es.searches) == 1  # an empty index list would have searched every index


def test_get_uses_ids_query_across_the_given_indices():
    record = a_record()
    es = FakeES(hits=[doc(record)])
    c = client(es)
    assert c.get("acme-doc-0001", indices=[ACME_SHAREABLE]) == record
    assert es.searches[0]["query"] == {"ids": {"values": ["acme-doc-0001"]}}
    assert es.searches[0]["source"] == {"excludes": ["text_semantic"]}
    es.hits = []
    assert c.get("nope", indices=[ACME_SHAREABLE]) is None


def test_write_routes_by_index_for_sets_text_semantic_and_waits_for_refresh():
    wanted = ["acme-doc-0001", "acme-note-0007", "talk-ebpf-zero-code", "bluefin-doc-0001", "attendee-bluefin.bo"]
    records = [a_record(m) for m in wanted]
    es = FakeES()
    assert client(es).write(records) == 5
    (call,) = es.bulks
    assert call["refresh"] == "wait_for"
    ops = call["operations"]
    actions, docs = ops[0::2], ops[1::2]
    assert [a["index"]["_index"] for a in actions] == [
        shareable_index("acme"), internal_index("acme"), CONFERENCE_INDEX, shareable_index("bluefin"),
        CONFERENCE_INDEX,
    ]
    assert [a["index"]["_id"] for a in actions] == wanted
    for record, body in zip(records, docs):
        assert body["text_semantic"] == f"{record.title}\n{record.summary}\n{record.text}"
        assert body["memory_id"] == record.memory_id
        assert isinstance(body["created_at"], str)  # JSON-safe
        MemoryRecord.model_validate({k: v for k, v in body.items() if k != "text_semantic"})


def test_write_raises_on_partial_bulk_failure_without_leaking_content():
    es = FakeES()
    es.bulk_response = {
        "errors": True,
        "items": [{"index": {"_id": "acme-doc-0001", "status": 500, "error": {"type": "boom", "reason": "SECRET"}}}],
    }
    with pytest.raises(RuntimeError) as err:
        client(es).write([a_record()])
    assert "SECRET" not in str(err.value)


def test_write_nothing_makes_no_call():
    es = FakeES()
    assert client(es).write([]) == 0
    assert es.bulks == []


def test_allowed_indices_is_enforced_on_search_get_and_write():
    es = FakeES()
    c = client(es, allowed_indices=[ACME_SHAREABLE, CONFERENCE_INDEX])  # a delegate's view
    with pytest.raises(ValueError):
        c.search("pricing", indices=[ACME_SHAREABLE, internal_index("acme")])
    with pytest.raises(ValueError):
        c.get("acme-doc-0008", indices=[internal_index("acme")])
    with pytest.raises(ValueError):  # internal records route to the internal index
        c.write([a_record("acme-doc-0001"), a_record("acme-doc-0008")])
    with pytest.raises(ValueError):
        c.count([internal_index("acme")])
    assert es.searches == [] and es.bulks == []  # refused before touching Elasticsearch
    assert c.write([a_record("acme-doc-0001")]) == 1  # allowed index still works


def test_rerank_wraps_the_retriever_and_falls_back_on_error():
    def reject_rerank(kw):
        return bad_request() if "text_similarity_reranker" in str(kw.get("retriever")) else None

    es = FakeES(fail_when=reject_rerank)
    c = client(es, rerank_inference_id=".rerank-test")
    c.search("ebpf", indices=[CONFERENCE_INDEX])
    first, second = es.searches
    reranker = first["retriever"]["text_similarity_reranker"]
    assert reranker["inference_id"] == ".rerank-test"
    assert reranker["inference_text"] == "ebpf"
    assert reranker["field"] == "text"
    assert "rrf" in reranker["retriever"]
    assert "rrf" in second["retriever"]  # retried without rerank, still hybrid
    c.search("ebpf", indices=[CONFERENCE_INDEX])
    assert "text_similarity_reranker" not in str(es.searches[-1])  # remembered


def test_transient_rerank_error_skips_rerank_once_but_is_not_remembered():
    calls = {"n": 0}

    def fail_first(kw):
        calls["n"] += 1
        return ApiError("unavailable", _meta(503), {}) if calls["n"] == 1 else None

    es = FakeES(fail_when=fail_first)
    c = client(es, rerank_inference_id=".rerank-test")
    c.search("ebpf", indices=[CONFERENCE_INDEX])
    assert "text_similarity_reranker" in str(es.searches[0]["retriever"])
    assert "text_similarity_reranker" not in str(es.searches[1]["retriever"])  # retried plain, same call
    c.search("ebpf", indices=[CONFERENCE_INDEX])
    assert "text_similarity_reranker" in str(es.searches[2]["retriever"])  # next call tries rerank again


def test_rerank_is_configured_from_the_environment(monkeypatch):
    monkeypatch.setenv("ES_RERANK_INFERENCE_ID", ".rerank-env")
    es = FakeES()
    client(es).search("ebpf", indices=[CONFERENCE_INDEX])
    assert es.searches[0]["retriever"]["text_similarity_reranker"]["inference_id"] == ".rerank-env"


def test_no_rerank_without_configuration(monkeypatch):
    monkeypatch.delenv("ES_RERANK_INFERENCE_ID", raising=False)
    es = FakeES()
    client(es).search("ebpf", indices=[CONFERENCE_INDEX])
    assert "rrf" in es.searches[0]["retriever"] and "text_similarity_reranker" not in es.searches[0]["retriever"]


def test_count_per_index():
    c = client(FakeES(), allowed_indices=[CONFERENCE_INDEX])
    assert c.count([CONFERENCE_INDEX]) == {CONFERENCE_INDEX: 3}


def test_naive_datetimes_never_reach_elasticsearch():
    es = FakeES()
    client(es).write([a_record("talk-ebpf-zero-code")])
    talk = es.bulks[0]["operations"][1]["talk"]
    assert datetime.fromisoformat(talk["starts_at"]).utcoffset() == timezone.utc.utcoffset(None)
