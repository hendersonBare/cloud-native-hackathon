"""Speaker search (src/rapport_speakers) mounted read-only in the gateway."""

import pytest
from gateway_support import make_stack

from rapport_gateway import deps as gateway_deps


@pytest.fixture
async def mock_stack():
    s = await make_stack(mock=True)
    yield s
    await s.close()


async def test_who_said_what_is_served_by_the_gateway(mock_stack):
    r = await mock_stack.client.get("/api/speakers/search", params={"q": "eBPF overhead on edge robots", "size": 3})
    assert r.status_code == 200
    top = r.json()["hits"][0]
    assert (top["speaker_id"], top["session_id"]) == ("kestrel.mia", "talk-ebpf-zero-code")
    assert top["spoken_at_label"].endswith("MST")
    assert "vector" not in r.text  # the public router never returns voiceprints


async def test_top_speakers_and_ui_are_served(mock_stack):
    r = await mock_stack.client.get("/api/speakers/top-speakers", params={"q": "eBPF"})
    assert r.status_code == 200 and r.json()["speakers"]
    ui = await mock_stack.client.get("/api/speakers/ui")
    assert ui.status_code == 200 and ui.headers["content-type"].startswith("text/html")


async def test_speaker_utterances_are_served(mock_stack):
    r = await mock_stack.client.get("/api/speakers/speakers/kestrel.mia/utterances")
    assert r.status_code == 200
    body = r.json()
    assert body["speaker"] == "kestrel.mia" and body["utterances"]
    assert {u["speaker_id"] for u in body["utterances"]} == {"kestrel.mia"}
    assert all(u["spoken_at"].endswith("Z") and u["spoken_at_label"].endswith("MST") for u in body["utterances"])
    starts = [u["spoken_at"] for u in body["utterances"]]
    assert starts == sorted(starts)  # by time
    assert "vector" not in r.text  # the public router never returns voiceprints

    long_id = await mock_stack.client.get(f"/api/speakers/speakers/{'x' * 81}/utterances")
    assert long_id.status_code == 422


async def test_erasure_is_not_reachable_on_the_public_port(mock_stack):
    for path in ("/api/speakers/people/kestrel.mia", "/internal/speakers/people/kestrel.mia"):
        assert (await mock_stack.client.delete(path)).status_code == 404


async def test_query_length_is_capped(mock_stack):
    assert (await mock_stack.client.get("/api/speakers/search", params={"q": "x" * 201})).status_code == 422


async def test_gateway_starts_without_speaker_search(monkeypatch):
    def broken():
        raise RuntimeError("no fixtures")

    monkeypatch.setattr(gateway_deps, "build_speakers_runtime", broken)
    s = await make_stack(mock=True)
    try:
        assert s.deps.speakers is None
        assert (await s.client.get("/healthz")).status_code == 200
        assert (await s.client.get("/api/speakers/search", params={"q": "ebpf"})).status_code == 404
    finally:
        await s.close()
