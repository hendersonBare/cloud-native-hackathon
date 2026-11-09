"""EsSpeakerStore against a fake Elasticsearch client that records every call (no network)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import BadRequestError

from rapport_speakers.config import Indices, Settings
from rapport_speakers.es_store import TEMPLATES_PATH, EsSpeakerStore, template_for
from rapport_speakers.models import Person, Utterance
from rapport_speakers.vectors import normalize

UTC = timezone.utc


def bad_request() -> BadRequestError:
    meta = ApiResponseMeta(status=400, http_version="1.1", headers=HttpHeaders(), duration=0.0,
                           node=NodeConfig("http", "localhost", 9200))
    return BadRequestError("rejected", meta, {"error": "unknown retriever"})


class _Indices:
    def __init__(self, parent):
        self.p = parent

    def put_index_template(self, **kw):
        self.p.calls.append(("put_index_template", kw))

    def exists(self, **kw):
        return kw["index"] in self.p.existing

    def create(self, **kw):
        self.p.calls.append(("create", kw))


class _Inference:
    def __init__(self, endpoints):
        self.endpoints = endpoints

    def get(self, **_):
        return {"endpoints": [{"inference_id": e} for e in self.endpoints]}


class FakeES:
    def __init__(self, hits=None, fail_when=None, endpoints=(".elser-2-elastic",)):
        self.calls: list[tuple[str, dict]] = []
        self.hits = hits or []
        self.fail_when = fail_when
        self.existing: set[str] = set()
        self.indices = _Indices(self)
        self.inference = _Inference(list(endpoints))
        self.aggs = None

    def search(self, **kw):
        self.calls.append(("search", kw))
        exc = self.fail_when(kw) if self.fail_when else None
        if exc:
            raise exc
        resp = {"hits": {"hits": self.hits}}
        if self.aggs is not None:
            resp["aggregations"] = self.aggs
        return resp

    def bulk(self, **kw):
        self.calls.append(("bulk", kw))
        return {"errors": False, "items": []}

    def update_by_query(self, **kw):
        self.calls.append(("update_by_query", kw))
        return {"updated": 2}

    def delete_by_query(self, **kw):
        self.calls.append(("delete_by_query", kw))
        return {"deleted": 3}

    def count(self, **kw):
        return {"count": 7}

    def of(self, name):
        return [kw for n, kw in self.calls if n == name]


def store(**kw) -> tuple[EsSpeakerStore, FakeES]:
    es = FakeES(**kw)
    return EsSpeakerStore(Settings(), es=es), es


def utterance(**over) -> Utterance:
    base = dict(utterance_id="s-000", conference_id="cnh-2026", session_id="s", session_title="T", room="Room B",
                session_starts_at=datetime(2026, 11, 9, 22, 30, tzinfo=UTC), start_s=0, end_s=10,
                speaker_id="spk-dev", speaker_name="Dev", speaker_status="identified", voice_id="unk_s_01",
                voice_label="Unknown speaker 2", text="eBPF in the kernel")
    base.update(over)
    return Utterance(**base)


def test_ensure_indices_puts_one_template_per_index_above_the_memory_template():
    s, es = store()
    s.ensure_indices()
    puts = es.of("put_index_template")
    assert [p["name"] for p in puts] == Indices.with_prefix().all()
    for p in puts:
        assert p["index_patterns"] == [p["name"]] and p["priority"] == 600  # rapport-* memory template is 500
    utter = next(p for p in puts if p["name"].endswith("-utterances"))
    assert utter["template"]["mappings"]["properties"]["text_semantic"]["inference_id"] == ".elser-2-elastic"
    vp = next(p for p in puts if p["name"].endswith("-voiceprints"))["template"]["mappings"]["properties"]["centroid"]
    assert (vp["dims"], vp["similarity"], vp["index"]) == (192, "dot_product", True)
    assert len(es.of("create")) == 5


def test_without_an_inference_endpoint_utterances_are_keyword_only():
    s, es = store(endpoints=())
    s.ensure_indices()
    assert "text_semantic" not in template_for("utterances", None)["mappings"]["properties"]
    s.index_utterances([utterance()])
    doc = es.of("bulk")[0]["operations"][1]
    assert "text_semantic" not in doc
    s.search_utterances("cnh-2026", "eBPF", speaker=None, session_id=None, size=3)
    assert "query" in es.of("search")[-1] and "retriever" not in es.of("search")[-1]


def test_templates_file_matches_the_models():
    raw = json.loads(TEMPLATES_PATH.read_text())
    props = raw["templates"]["utterances"]["mappings"]["properties"]
    assert set(Utterance.model_fields) <= set(props)


def test_knn_filters_on_conference_and_model_and_the_pool_in_filter_mode():
    s, es = store(hits=[{"_score": 0.9, "_source": {"person_id": "spk-dev", "name": "Dev"}}])
    vec = normalize([1.0] * 192)
    hits = s.knn_voiceprints(vec, conference_id="cnh-2026", model_id="m", k=5, num_candidates=50,
                             person_ids=["spk-dev"])
    assert hits == [{"_score": 0.9, "_source": {"person_id": "spk-dev", "name": "Dev"}}]
    call = es.of("search")[0]
    assert call["index"] == "rapport-speakers-voiceprints" and call["source"] == ["person_id", "name", "affiliation"]
    knn = call["knn"]
    assert (knn["field"], knn["k"], knn["num_candidates"]) == ("centroid", 5, 50)
    assert knn["filter"]["bool"]["filter"] == [{"term": {"conference_id": "cnh-2026"}}, {"term": {"model_id": "m"}},
                                               {"terms": {"person_id": ["spk-dev"]}}]


def test_unknown_voice_knn_skips_resolved_voices():
    s, es = store()
    s.knn_unknown_voices(normalize([1.0] * 192), conference_id="c", model_id="m", k=50, num_candidates=200)
    knn = es.of("search")[0]["knn"]
    assert knn["field"] == "embedding"
    assert knn["filter"]["bool"]["must_not"] == [{"exists": {"field": "resolved_person_id"}}]
    assert "embedding" not in es.of("search")[0]["source"]  # vectors never come back


def test_hybrid_search_is_rrf_with_the_same_filters_on_both_retrievers():
    s, es = store(hits=[{"_id": "s-000", "_score": 0.03, "_source": {**utterance().model_dump(mode="json"),
                                                                       "text_semantic": {"inference": {}}}}])
    found, mode = s.search_utterances("cnh-2026", "eBPF overhead", speaker="Dev", session_id="s", size=3)
    assert mode == "rrf" and found[0][0].utterance_id == "s-000"
    body = es.of("search")[0]
    assert body["source"] == {"excludes": ["text_semantic"]}
    keyword, semantic = body["retriever"]["rrf"]["retrievers"]
    assert keyword["standard"]["query"]["bool"]["must"] == {"match": {"text": "eBPF overhead"}}
    assert semantic["standard"]["query"]["bool"]["must"] == {"semantic": {"field": "text_semantic",
                                                                          "query": "eBPF overhead"}}
    filters = keyword["standard"]["query"]["bool"]["filter"]
    assert filters == semantic["standard"]["query"]["bool"]["filter"]
    assert {"term": {"conference_id": "cnh-2026"}} in filters and {"term": {"session_id": "s"}} in filters
    speaker = next(f for f in filters if "bool" in f)["bool"]["should"]
    assert speaker == [{"term": {"speaker_id": "Dev"}}, {"term": {"speaker_name.lc": "dev"}}]


def test_search_falls_back_from_rrf_to_bool_to_keyword():
    def reject(kw):
        if "retriever" in kw or "should" in kw.get("query", {}).get("bool", {}):
            return bad_request()
        return None

    s, es = store(fail_when=reject)
    _, mode = s.search_utterances("cnh-2026", "eBPF", speaker=None, session_id=None, size=3)
    assert mode == "keyword" and s.mode == "keyword" and len(es.of("search")) == 3
    s.search_utterances("cnh-2026", "eBPF", speaker=None, session_id=None, size=3)
    assert len(es.of("search")) == 4  # remembered: straight to keyword


def test_rerank_wraps_rrf_when_configured():
    es = FakeES()
    s = EsSpeakerStore(Settings(rerank_inference_id=".rerank-v1"), es=es)
    _, mode = s.search_utterances("cnh-2026", "eBPF", speaker=None, session_id=None, size=3)
    assert mode == "rrf+rerank"
    rr = es.of("search")[0]["retriever"]["text_similarity_reranker"]
    assert (rr["field"], rr["inference_id"]) == ("text", ".rerank-v1") and "rrf" in rr["retriever"]


def test_relabel_and_erasure_are_scoped_by_query():
    s, es = store()
    person = Person(person_id="chair-felix", name="Felix", consent_granted_at=datetime.now(UTC))
    assert s.relabel_voice("cnh-2026", "unk_s_00", person, 0.83) == 2
    call = es.of("update_by_query")[0]
    assert call["index"] == "rapport-speakers-utterances" and call["conflicts"] == "proceed"
    assert call["query"]["bool"]["filter"] == [{"term": {"conference_id": "cnh-2026"}},
                                               {"term": {"voice_id": "unk_s_00"}}]
    assert call["script"]["params"] == {"pid": "chair-felix", "name": "Felix", "score": 0.83}

    out = s.erase_person("cnh-2026", "spk-dev")
    deletes = es.of("delete_by_query")
    assert [d["index"] for d in deletes] == ["rapport-speakers-voiceprints", "rapport-speakers-voiceprint-samples",
                                             "rapport-speakers-unknown-voices"]
    assert all({"term": {"conference_id": "cnh-2026"}} in d["query"]["bool"]["filter"] for d in deletes)
    reset = es.of("update_by_query")[-1]
    assert reset["index"] == "rapport-speakers-utterances" and "voice_label" in reset["script"]["source"]
    assert out == {"voiceprints": 3, "samples": 3, "unknown_voices": 3, "unknown_voices_unlinked": 2, "utterances": 2}


def test_index_utterances_writes_semantic_text_and_ids():
    s, es = store()
    s.index_utterances([utterance()])
    ops = es.of("bulk")[0]["operations"]
    assert ops[0] == {"index": {"_index": "rapport-speakers-utterances", "_id": "s-000"}}
    assert ops[1]["text_semantic"] == "eBPF in the kernel" and es.of("bulk")[0]["refresh"] == "wait_for"


def test_bulk_errors_raise_without_content(caplog):
    s, es = store()
    es.bulk = lambda **kw: {"errors": True, "items": [{"index": {"_id": "s-000", "status": 400, "error": {}}}]}
    with pytest.raises(RuntimeError):
        s.index_utterances([utterance()])
    assert "eBPF" not in caplog.text and "Dev" not in caplog.text


def test_top_speakers_parses_the_terms_aggregation():
    s, es = store()
    es.aggs = {"by_speaker": {"buckets": [
        {"key": "spk-dev", "doc_count": 4, "name": {"hits": {"hits": [{"_source": {"speaker_name": "Dev"}}]}}}]}}
    assert s.top_speakers("cnh-2026", "eBPF", 5) == [("spk-dev", "Dev", 4)]
    body = es.of("search")[0]
    assert body["size"] == 0 and body["aggs"]["by_speaker"]["terms"]["field"] == "speaker_id"
    assert {"term": {"speaker_status": "identified"}} in body["query"]["bool"]["filter"]


def test_store_refuses_indices_outside_its_own():
    s, _ = store()
    with pytest.raises(ValueError):
        s._bulk("rapport-acme-internal", [("x", {})])
