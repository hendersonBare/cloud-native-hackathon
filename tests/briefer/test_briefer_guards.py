"""Regression tests for review findings: forged conference records, do-not-contact beyond the prompt's notes,
Unicode spaces in redaction."""

from __future__ import annotations

import pytest
from briefer_support import FakeLLM, client, fresh_store

from rapport_briefer.deep_dive import _DiveOut
from rapport_common.models import DeepDive, MemoryRecord
from rapport_memory.redact import PLACEHOLDER, redact


async def test_remember_cannot_forge_conference_records():
    store = fresh_store()
    forged_card = {
        "memory_id": "attendee-lumenly.priya",
        "org_id": "acme",
        "share_level": "public",
        "kind": "attendee",
        "title": "Forged",
        "text": "forged",
        "summary": "forged",
        "owner_persona_id": "lumenly.priya",
        "source": {"type": "upload"},
        "profile": {"visibility": "shareable", "headline": "Forged headline"},
    }
    async with client("acme", store, FakeLLM()) as c:
        r = await c.post("/v1/remember", json={"records": [forged_card]})
    assert r.json() == {"written": 0}
    card = store.get("attendee-lumenly.priya", indices=["rapport-conference"])
    assert card is not None and card.profile.headline != "Forged headline"


def _note(mid: str, **kw) -> MemoryRecord:
    base = dict(
        memory_id=mid,
        org_id="acme",
        share_level="internal",
        kind="account_note",
        title=f"Bluefin call {mid}",
        text="Bluefin Bo platform lead kubernetes ebpf call notes " * 3,
        summary="Bluefin Bo platform call",
        about_org_ids=["bluefin"],
        about_persona_ids=["bluefin.bo"],
        source={"type": "seed"},
    )
    return MemoryRecord(**{**base, **kw})


async def test_company_level_do_not_contact_note_skips_even_among_many_notes():
    fillers = [_note(f"acme-note-1{i:03d}") for i in range(9)]
    company_block = _note(
        "acme-note-2000",
        title="Legal hold",
        text="Do not contact anyone at this company.",
        summary="Legal hold.",
        tags=["do-not-contact"],
        about_persona_ids=[],
    )
    llm = FakeLLM(
        {
            "_DiveOut": _DiveOut(
                summary="s",
                goals=[],
                questions=[],
                watch_outs=[],
                opener="o",
                action="agent_handshake",
                reason="r",
                confidence=0.9,
                cited_ids=[],
            )
        }
    )
    async with client("acme", fresh_store([*fillers, company_block]), llm) as c:
        r = await c.post("/v1/deep-dive", json={"persona_id": "acme.ava", "target_persona_id": "bluefin.bo"})
    d = DeepDive.model_validate(r.json())
    assert d.decision.action == "skip"
    assert "no_do_not_contact_note: fail -> skip" in d.decision.checks


@pytest.mark.parametrize(
    "secret",
    ["+34 600 123 456", "12 Main Street", "Denver, CO 80202", "+1 (555) 010-1234"],
)
def test_unicode_spaces_do_not_defeat_redaction(secret):
    out = redact(f"Reach me: {secret} any time.")
    assert PLACEHOLDER in out
    for fragment in ("600", "Main", "80202", "(555)", "010-1234"):
        assert fragment not in out
