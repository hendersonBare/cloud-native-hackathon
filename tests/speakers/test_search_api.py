"""Who said what (§6): search service, jump-to timestamps and the FastAPI routers."""

from __future__ import annotations

from datetime import timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rapport_speakers.api import make_admin_router, make_public_router


def test_who_said_x_about_ebpf_returns_speaker_and_timestamp(search):
    result = search.search("who asked about eBPF overhead on edge robots", size=3)
    top = result.hits[0]
    assert (top.speaker_name, top.speaker_id, top.session_id) == ("Mia", "kestrel.mia", "talk-ebpf-zero-code")
    assert top.start_s == 1450 and top.jump_url == "recordings/talk-ebpf-zero-code.mp4#t=1450"
    assert top.spoken_at.tzinfo is not None and top.spoken_at.utcoffset() == timezone.utc.utcoffset(None)
    assert top.spoken_at_label == "3:54 PM MST"  # 3:30 PM talk + 24m10s


def test_speaker_filter_accepts_an_id_or_a_name(search):
    by_name = search.search("kernel", speaker="dev", size=10)
    by_id = search.search("kernel", speaker="spk-dev", size=10)
    assert by_name.hits and [h.utterance_id for h in by_name.hits] == [h.utterance_id for h in by_id.hits]
    assert {h.speaker_id for h in by_name.hits} == {"spk-dev"}
    sessions = {h.session_id for h in by_name.hits}
    assert {"talk-ebpf-zero-code", "talk-ebpf-cost"} <= sessions  # his talk and his Q&A question elsewhere


def test_session_filter_and_empty_query(search):
    result = search.search("", session="talk-ebpf-edge", size=50)
    assert {h.session_id for h in result.hits} == {"talk-ebpf-edge"}
    assert [h.start_s for h in result.hits] == sorted(h.start_s for h in result.hits)


def test_top_speakers_counts_identified_speakers_only(search):
    rows = search.top_speakers("eBPF").speakers
    assert rows[0].speaker_id == "spk-dev"
    assert {r.speaker_id for r in rows} >= {"spk-dev", "lumenly.priya", "kestrel.mia"}
    assert not any(r.speaker_id.startswith("unk_") for r in rows)


def test_everything_a_speaker_said_is_in_time_order(search):
    said = search.speaker_utterances("kestrel.mia").utterances
    assert said[0].session_id == "talk-ebpf-zero-code"  # her question at 3:54 PM comes before her own talk
    assert [h.spoken_at for h in said] == sorted(h.spoken_at for h in said)


def _client(search, pipeline=None) -> TestClient:
    app = FastAPI()
    app.include_router(make_public_router(search), prefix="/api/speakers")
    if pipeline is not None:
        app.include_router(make_admin_router(pipeline), prefix="/internal/speakers")
    return TestClient(app)


def test_public_router_never_returns_vectors(search):
    client = _client(search)
    resp = client.get("/api/speakers/search", params={"q": "eBPF", "size": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["hits"] and body["mode"] == "keyword"
    for hit in body["hits"]:
        assert not {"embedding", "centroid", "voice_id", "match_score"} & set(hit)
    assert client.get("/api/speakers/speakers/kestrel.mia/utterances").json()["utterances"]
    assert client.get("/api/speakers/top-speakers", params={"q": "eBPF"}).json()["speakers"][0]["speaker_name"] == "Dev"
    assert "textContent" in client.get("/api/speakers/ui").text


def test_public_router_validates_input(search):
    client = _client(search)
    assert client.get("/api/speakers/search", params={"q": "x" * 201}).status_code == 422
    assert client.get("/api/speakers/search", params={"q": "x", "size": 0}).status_code == 422
    assert client.get("/api/speakers/search", params={"q": "x", "session": "bad id!"}).status_code == 422
    assert client.delete("/api/speakers/people/spk-dev").status_code in (404, 405)  # no erasure on public


def test_admin_router_erases(search, pipeline):
    client = _client(search, pipeline)
    resp = client.delete("/internal/speakers/people/spk-dev")
    assert resp.status_code == 200 and resp.json()["voiceprints_deleted"] == 1
    after = client.get("/api/speakers/search", params={"q": "kernel", "speaker": "Dev"}).json()
    assert after["hits"] == []
