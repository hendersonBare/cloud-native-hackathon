"""POST /v1/context and GET /v1/profile: the upload pipeline, redaction before the LLM and before indexing."""

from __future__ import annotations

import json

import pytest
from briefer_support import FakeLLM, client, fresh_store, make_pdf

from rapport_briefer.context import MAX_UPLOAD_BYTES, _ProfileOut
from rapport_common.interfaces import InMemoryStore
from rapport_common.models import PersonaProfile

EMAIL, PHONE, STREET = "ava.synthetic@example.com", "+1 (555) 010-1234", "12 Oak Lane"
CV = f"""# Ava Example, Solutions Engineer

Contact: {EMAIL} | {PHONE}
{STREET}, Denver, CO 80202

Built eBPF tracing for Kubernetes platforms and OpenTelemetry pipelines for hospital networks.

I am looking for a healthcare design partner this quarter and want to meet platform teams.

- Wrote the zero-code observability case study (40% faster incidents).
"""
INDICES = ["rapport-acme-shareable", "rapport-acme-internal"]


def _all_stored_text(store: InMemoryStore) -> str:
    return json.dumps([r.model_dump(mode="json") for _idx, r in store._docs.values()])


async def _upload(c, visibility="shareable", persona="acme.ava", **kw):
    data = {"persona_id": persona, "visibility": visibility, **kw.pop("data", {})}
    if "text" in kw:
        data["text"] = kw.pop("text")
    return await c.post("/v1/context", data=data, **kw)


async def test_markdown_upload_without_llm_redacts_indexes_and_returns_the_profile():
    store, llm = fresh_store(), FakeLLM()
    async with client("acme", store, llm) as c:
        r = await _upload(c, files={"file": ("ava-cv.md", CV.encode(), "text/markdown")})
    assert r.status_code == 200, r.text
    profile = PersonaProfile.model_validate(r.json())
    assert profile.persona_id == "acme.ava" and profile.private is None
    s = profile.shareable
    assert s is not None and s.visibility == "shareable" and "Ava Example" in s.headline
    assert {"ebpf", "kubernetes", "opentelemetry"} <= set(s.interests)  # from the known tag vocabulary
    assert profile.source_files == ["ava-cv.md"]

    card = store.get("profile-acme.ava-shareable", indices=INDICES)
    assert card is not None and card.kind == "profile" and card.share_level == "public"
    assert card.owner_persona_id == "acme.ava" and card.profile is not None
    chunk = store.get("profile-acme.ava-shareable-0", indices=INDICES)
    assert chunk is not None and chunk.profile is None and chunk.owner_persona_id == "acme.ava"
    assert "[redacted]" in chunk.text

    stored = _all_stored_text(store)
    for secret in (EMAIL, "555) 010-1234", STREET, "80202"):
        assert secret not in stored
    assert llm.calls and all(c_.schema is _ProfileOut for c_ in llm.calls)
    assert not any(s_ in llm.prompts for s_ in (EMAIL, "010-1234", STREET, "80202"))  # redacted BEFORE the LLM


async def test_private_upload_is_internal_and_both_views_come_back():
    store = fresh_store()
    out = _ProfileOut(
        headline="SE at Acme",
        interests=["eBPF", "Platform Engineering"],
        goals=["Find a design partner"],
        highlights=["Case study"],
    )
    async with client("acme", store, FakeLLM({"_ProfileOut": out})) as c:
        await _upload(c, "shareable", text="Public pitch about eBPF.")
        r = await _upload(
            c,
            "private",
            data={},
            files={"file": ("notes.txt", f"Goal: healthcare partner. {EMAIL}".encode(), "text/plain")},
        )
        got = (await c.get("/v1/profile", params={"persona_id": "acme.ava"})).json()
    p = PersonaProfile.model_validate(r.json())
    assert p.private is not None and p.shareable is not None  # read the other view's card
    assert p.private.interests == ["ebpf", "platform-engineering"] and p.private.goals == ["Find a design partner"]
    assert PersonaProfile.model_validate(got).private == p.private
    card = store.get("profile-acme.ava-private", indices=INDICES)
    assert card.share_level == "internal"
    assert store._docs["profile-acme.ava-private"][0] == "rapport-acme-internal"
    assert store._docs["profile-acme.ava-shareable"][0] == "rapport-acme-shareable"


async def test_llm_output_is_redacted_too():
    out = _ProfileOut(headline=f"Reach me at {EMAIL}", interests=[], goals=[], highlights=[f"Call {PHONE}"])
    store = fresh_store()
    async with client("acme", store, FakeLLM({"_ProfileOut": out})) as c:
        r = await _upload(c, text="Some notes about Kubernetes.")
    assert EMAIL not in r.text and "010-1234" not in r.text
    assert EMAIL not in _all_stored_text(store)


async def test_long_text_is_truncated_to_20000_characters_and_chunked():
    store = fresh_store()
    big = "\n\n".join(f"Paragraph {i}. " + "kubernetes " * 40 for i in range(300))
    async with client("acme", store, FakeLLM()) as c:
        r = await _upload(c, text=big)
    assert r.status_code == 200
    chunks = [rec for _i, rec in store._docs.values() if rec.memory_id.startswith("profile-acme.ava-shareable-")]
    assert 10 <= len(chunks) <= 16
    assert sum(len(c_.text) for c_ in chunks) <= 20_000 + 2 * len(chunks)
    assert all(len(c_.text) <= 1600 for c_ in chunks)


async def test_reupload_overwrites_the_card():
    store = fresh_store()
    async with client("acme", store, FakeLLM()) as c:
        await _upload(c, text="First version about eBPF.")
        await _upload(c, text="Second version about security and compliance.")
    card = store.get("profile-acme.ava-shareable", indices=INDICES)
    assert "Second version" in card.profile.headline


async def test_pdf_with_text_is_extracted():
    async with client("acme", llm=FakeLLM()) as c:
        r = await _upload(
            c, files={"file": ("cv.pdf", make_pdf("Ava builds eBPF tracing for Kubernetes"), "application/pdf")}
        )
    assert r.status_code == 200, r.text
    assert "ebpf" in PersonaProfile.model_validate(r.json()).shareable.interests


async def test_pdf_without_text_gets_a_clear_422():
    async with client("acme") as c:
        r = await _upload(c, files={"file": ("scan.pdf", make_pdf(None), "application/pdf")})
    assert r.status_code == 422 and "no extractable text" in r.json()["detail"]


async def test_corrupt_pdf_is_422():
    async with client("acme") as c:
        r = await _upload(c, files={"file": ("bad.pdf", b"not a pdf at all", "application/pdf")})
    assert r.status_code == 422


async def test_rejections():
    async with client("acme") as c:
        r = await _upload(c, files={"file": ("cv.docx", b"x", "application/octet-stream")})
        assert r.status_code == 415
        r = await _upload(c, files={"file": ("cv.txt", b"x" * (MAX_UPLOAD_BYTES + 1), "text/plain")})
        assert r.status_code == 413
        r = await _upload(c)  # neither file nor text
        assert r.status_code == 422
        r = await _upload(c, text="   ")
        assert r.status_code == 422
        r = await _upload(c, visibility="public", text="hi")
        assert r.status_code == 422
        r = await _upload(c, persona="bluefin.bo", text="hi")
        assert r.status_code == 403
        r = await _upload(c, persona="who.dis", text="hi")
        assert r.status_code == 404


async def test_profile_falls_back_to_the_directory():
    async with client("acme") as c:
        r = await c.get("/v1/profile", params={"persona_id": "acme.ava"})
    p = PersonaProfile.model_validate(r.json())
    assert p.shareable.headline == "Solutions Engineer at Acme Observability"
    assert p.private.goals[1] == "Find a design partner in healthcare"


async def test_default_text_and_file_together_are_combined():
    store = fresh_store()
    async with client("acme", store, FakeLLM()) as c:
        r = await _upload(
            c,
            text="Pasted note about zero-trust.",
            files={"file": ("a.md", b"# Title\nKubernetes things.", "text/markdown")},
        )
    assert r.status_code == 200
    chunk = store.get("profile-acme.ava-shareable-0", indices=INDICES)
    assert "Kubernetes things" in chunk.text and "zero-trust" in chunk.text


@pytest.mark.parametrize("org,persona", [("bluefin", "bluefin.bo")])
async def test_other_company_briefer_writes_to_its_own_indices(org, persona):
    store = fresh_store()
    async with client(org, store, FakeLLM()) as c:
        r = await _upload(c, persona=persona, text="Platform lead; interested in kubernetes and cost.")
    assert r.status_code == 200
    assert store._docs["profile-bluefin.bo-shareable"][0] == "rapport-bluefin-shareable"
