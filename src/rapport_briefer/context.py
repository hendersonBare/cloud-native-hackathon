"""POST /v1/context and GET /v1/profile: the personal-context pipeline (SPEC 4.3).

extract -> redact (BEFORE any LLM call or indexing) -> truncate -> chunk -> LLM fills a ProfileInfo
(or a deterministic fallback does) -> write the card and chunk records -> return both views.
"""

from __future__ import annotations

import io
import logging
import re
from collections import Counter
from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import BaseModel

from rapport_common import names
from rapport_common.models import PersonaProfile, ProfileInfo, Visibility, utcnow
from rapport_common.telemetry import ATTR_ORG, ATTR_PERSONA, ATTR_RESULT_COUNT, tracer
from rapport_memory.profiles import (
    MAX_TEXT_CHARS,
    build_records,
    chunk_text,
    clean_tags,
    directory_profile,
    profile_from_cards,
    read_profile,
)
from rapport_memory.redact import redact

from .core import Briefer, fit
from .llm import data_block

log = logging.getLogger("rapport.briefer.context")

SPAN_INGEST = "context.ingest"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_SUFFIXES = (".pdf", ".md", ".txt")
_PRE_REDACT_CAP = 200_000  # bounds regex work on huge PDFs; the stored text is cut to 20,000 after redaction

EXTRA_VOCABULARY = [
    "ebpf", "observability", "opentelemetry", "kubernetes", "platform-engineering", "healthcare", "hipaa",
    "security", "compliance", "cost", "finops", "edge", "robotics", "ai-agents", "zero-trust", "accessibility",
    "community", "elasticsearch", "search", "data", "tracing", "monitoring", "devops", "sre", "cloud",
]  # fmt: skip

SYSTEM = (
    "Read the uploaded CV or notes in the data block and fill the profile: a one-line headline (at most 150 "
    "characters), up to 8 interests as short lowercase slugs such as ebpf or platform-engineering, up to 5 goals "
    "(what the person is looking for), and up to 5 highlights. Use only what the text says. Never include contact "
    "details. Write in the language of the text."
)


class _ProfileOut(BaseModel):
    headline: str
    interests: list[str]
    goals: list[str]
    highlights: list[str]


@dataclass
class Extracted:
    text: str
    filename: str | None


def extract_text(filename: str | None, data: bytes) -> str:
    """Text of an uploaded file. 415 for other types, 422 for unreadable or text-less PDFs."""
    name = (filename or "").lower()
    if not name.endswith(ALLOWED_SUFFIXES):
        raise HTTPException(status_code=415, detail="only .pdf, .md and .txt files are accepted")
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = [(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:
            log.warning("pdf unreadable (%s)", type(exc).__name__)
            raise HTTPException(status_code=422, detail="could not read this PDF") from exc
        text = "\n\n".join(pages)
        if not text.strip():
            raise HTTPException(
                status_code=422,
                detail="this PDF has no extractable text (it may be a scan); paste the text or upload a .txt/.md",
            )
        return text
    return data.decode("utf-8", errors="replace")


def prepare_text(raw: str) -> str:
    """Redact first (so a truncation can never leave half an email behind), then truncate to 20,000 characters."""
    return redact(raw[:_PRE_REDACT_CAP]).strip()[:MAX_TEXT_CHARS]


async def ingest(
    b: Briefer, persona_id: str, visibility: Visibility, *, filename: str | None, data: bytes | None, text: str | None
) -> PersonaProfile:
    persona = b.own(persona_id)
    if data is None and not (text and text.strip()):
        raise HTTPException(status_code=422, detail="send a file, text, or both")
    parts: list[str] = []
    if data is not None:
        parts.append(extract_text(filename, data))
    if text and text.strip():
        parts.append(text)
    clean = prepare_text("\n\n".join(parts))
    if not clean:
        raise HTTPException(status_code=422, detail="no text found in the upload")

    with tracer("rapport.briefer").start_as_current_span(SPAN_INGEST) as span:
        span.set_attribute(ATTR_PERSONA, persona.persona_id)
        span.set_attribute(ATTR_ORG, b.org_id)
        chunks = chunk_text(clean)
        info = await _profile_info(b, visibility, clean)
        safe_name = redact(filename)[:200] if filename else None
        records = build_records(persona, visibility, info, chunks, filename=safe_name, created_at=utcnow())
        await b.write(records)
        span.set_attribute(ATTR_RESULT_COUNT, len(records))
        log.info("context ingested persona=%s visibility=%s chunks=%d", persona.persona_id, visibility, len(chunks))

    other: Visibility = "private" if visibility == "shareable" else "shareable"
    other_card = await b.get(f"profile-{persona.persona_id}-{other}", indices=[b.shareable, b.internal])
    mine = records[0]
    cards = {visibility: mine, other: other_card}
    return profile_from_cards(persona.persona_id, cards["shareable"], cards["private"])


async def _profile_info(b: Briefer, visibility: Visibility, clean: str) -> ProfileInfo:
    out = await b.llm.parse(system=SYSTEM, user=data_block("upload", {"text": clean}), schema=_ProfileOut)
    if out is not None and out.headline.strip():
        return ProfileInfo(
            visibility=visibility,
            headline=fit(redact(out.headline), 160),
            interests=clean_tags(out.interests),
            goals=[fit(redact(g), 200) for g in out.goals if g.strip()][:5],
            highlights=[fit(redact(h), 200) for h in out.highlights if h.strip()][:5],
        )
    return fallback_info(visibility, clean)


def fallback_info(visibility: Visibility, clean: str) -> ProfileInfo:
    """No LLM: first line as the headline, interests from the known tag vocabulary, goals/highlights from cues."""
    lines = [re.sub(r"^[#>*\-\s]+", "", ln).strip() for ln in clean.splitlines()]
    lines = [ln for ln in lines if ln]
    headline = fit(lines[0], 160) if lines else "Uploaded context"
    lowered = clean.lower().replace("-", " ")
    vocab = {
        v: v.replace("-", " ")
        for v in {*EXTRA_VOCABULARY, *(i for p in names.personas().values() for i in p.interests)}
    }
    counts = Counter({tag: lowered.count(phrase) for tag, phrase in vocab.items() if phrase in lowered})
    interests = clean_tags([tag for tag, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))])
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", clean) if s.strip()]
    cues = re.compile(r"\b(looking for|seeking|goal|want|wants|hoping|aim)\b", re.IGNORECASE)
    goals = [fit(s, 200) for s in sentences if cues.search(s)][:3]
    highlights = [fit(s, 200) for s in sentences[1:] if s not in goals and len(s) > 20][:3]
    return ProfileInfo(
        visibility=visibility, headline=headline, interests=interests, goals=goals, highlights=highlights
    )


async def get_profile(b: Briefer, persona_id: str) -> PersonaProfile:
    persona = b.own(persona_id)
    profile = await b._call(read_profile, b.store, persona, [b.shareable, b.internal])
    if profile.shareable is None and profile.private is None:  # nothing uploaded yet: the directory entry
        return PersonaProfile(
            persona_id=persona.persona_id,
            shareable=directory_profile(persona, "shareable"),
            private=directory_profile(persona, "private"),
        )
    return profile
