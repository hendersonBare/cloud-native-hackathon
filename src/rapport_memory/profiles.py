"""Profile cards and chunks (SPEC 4.3): chunking, record building and reading a PersonaProfile back.

Pure functions plus two store helpers. No network access, no LLM.
"""

from __future__ import annotations

import re
from datetime import datetime

from rapport_common import names
from rapport_common.interfaces import MemoryStore
from rapport_common.models import (
    MemoryRecord,
    Persona,
    PersonaProfile,
    ProfileInfo,
    SourceRef,
    Visibility,
)

CHUNK_CHARS = 1500
MAX_TEXT_CHARS = 20_000
_TAG = re.compile(r"[^a-z0-9]+")


def card_id(persona_id: str, visibility: Visibility) -> str:
    return f"profile-{persona_id}-{visibility}"


def chunk_id(persona_id: str, visibility: Visibility, n: int) -> str:
    return f"profile-{persona_id}-{visibility}-{n}"


def to_tag(value: str) -> str | None:
    """A lower-case slug that satisfies models.TAG, or None."""
    slug = _TAG.sub("-", value.strip().lower()).strip("-")[:41].strip("-")
    return slug if slug and slug[0].isalnum() else None


def clean_tags(values: list[str], limit: int = 8) -> list[str]:
    seen: list[str] = []
    for value in values:
        tag = to_tag(value)
        if tag and tag not in seen:
            seen.append(tag)
    return seen[:limit]


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split on paragraph boundaries into chunks of about `size` characters; hard-split very long paragraphs."""
    chunks: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        while len(para) > size:  # a single huge paragraph: cut at whitespace
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if current and len(current) + len(para) + 2 > size:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def build_records(
    persona: Persona,
    visibility: Visibility,
    info: ProfileInfo,
    chunks: list[str],
    *,
    filename: str | None,
    created_at: datetime,
) -> list[MemoryRecord]:
    """The card (`profile-<persona>-<visibility>`) plus one record per chunk (`...-<n>`)."""
    share_level = "public" if visibility == "shareable" else "internal"
    source = SourceRef(type="upload", filename=filename)
    tags = clean_tags(info.interests)
    card_text = "\n".join([info.headline, *info.highlights, *info.goals])
    records = [
        MemoryRecord(
            memory_id=card_id(persona.persona_id, visibility),
            org_id=persona.org_id,
            share_level=share_level,
            kind="profile",
            title=f"{persona.name} profile ({visibility})"[:200],
            text=card_text,
            summary=info.headline[:400],
            tags=tags,
            owner_persona_id=persona.persona_id,
            created_at=created_at,
            source=source,
            profile=info,
        )
    ]
    for n, chunk in enumerate(chunks):
        records.append(
            MemoryRecord(
                memory_id=chunk_id(persona.persona_id, visibility, n),
                org_id=persona.org_id,
                share_level=share_level,
                kind="profile",
                title=f"{persona.name} context {n + 1} ({visibility})"[:200],
                text=chunk,
                summary=chunk[:240],
                tags=tags,
                owner_persona_id=persona.persona_id,
                created_at=created_at,
                source=source,
            )
        )
    return records


def directory_profile(persona: Persona, visibility: Visibility) -> ProfileInfo:
    """What we know about a person without any upload: their directory entry."""
    org = names.orgs().get(persona.org_id)
    headline = f"{persona.title} at {org.name}" if org else persona.title
    return ProfileInfo(
        visibility=visibility,
        headline=headline[:160],
        interests=persona.interests[:8],
        goals=persona.goals[:5],
    )


def read_profile(store: MemoryStore, persona: Persona, indices: list[str]) -> PersonaProfile:
    """Both views from their card records. Missing views stay None."""
    views: dict[str, MemoryRecord | None] = {
        v: store.get(card_id(persona.persona_id, v), indices=indices)  # type: ignore[arg-type]
        for v in ("shareable", "private")
    }
    return profile_from_cards(persona.persona_id, views["shareable"], views["private"])


def profile_from_cards(persona_id: str, shareable: MemoryRecord | None, private: MemoryRecord | None) -> PersonaProfile:
    cards = [c for c in (shareable, private) if c is not None]
    files = [c.source.filename for c in cards if c.source.filename]
    extra = {"updated_at": max(c.created_at for c in cards)} if cards else {}
    return PersonaProfile(
        persona_id=persona_id,
        shareable=shareable.profile if shareable else None,
        private=private.profile if private else None,
        source_files=list(dict.fromkeys(files)),
        **extra,
    )
