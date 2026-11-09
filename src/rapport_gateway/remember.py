"""Turn a delegate's SharedBrief into the records the person's own briefer remembers (SPEC step 8).

Records are internal to the party's company (share_level "internal", org_id = that party's org) and are
written by the briefer with names.index_for(). Every record is validated as a MemoryRecord here first.
"""

from __future__ import annotations

import re

from rapport_common import names
from rapport_common.models import (
    FollowupInfo,
    MemoryRecord,
    SharedBrief,
    SourceRef,
)

_TAG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def _tags(*groups: list[str]) -> list[str]:
    out: list[str] = []
    for tag in (t for group in groups for t in group):
        if _TAG.match(tag) and tag not in out:
            out.append(tag)
    return out


def build_records(
    brief: SharedBrief, *, org_id: str, counterparty_org_id: str, counterparty_persona_id: str
) -> list[MemoryRecord]:
    """One encounter_summary plus one followup per follow-up, for `brief.for_persona_id` of `org_id`."""
    persona = brief.for_persona_id
    counterparty = names.personas().get(counterparty_persona_id)
    who = counterparty.name if counterparty else counterparty_persona_id
    source = SourceRef(type="encounter", encounter_id=brief.encounter_id)
    shared = "; ".join(item.title for item in brief.shared_items) or "nothing"
    declined = "; ".join(f"{d.topic} ({d.reason_code})" for d in brief.declined) or "nothing"
    text = f"{brief.summary}\nShared: {shared}.\nDeclined: {declined}."
    records = [
        MemoryRecord(
            memory_id=f"encounter-{brief.encounter_id}-{persona}",
            org_id=org_id,
            share_level="internal",
            kind="encounter_summary",
            title=f"Conversation with {who} ({counterparty_org_id})"[:200],
            text=text,
            summary=brief.summary[:400],
            tags=_tags(["encounter"], brief.mutual_interests),
            about_org_ids=[counterparty_org_id],
            about_persona_ids=[counterparty_persona_id],
            owner_persona_id=persona,
            source=source,
        )
    ]
    for followup in brief.followups:
        records.append(
            MemoryRecord(
                memory_id=f"followup-{brief.encounter_id}-{followup.followup_id}-{persona}",
                org_id=org_id,
                share_level="internal",
                kind="followup",
                title=followup.text[:200],
                text=followup.text,
                summary=followup.text[:400],
                tags=_tags(["followup"]),
                about_org_ids=[counterparty_org_id],
                about_persona_ids=[counterparty_persona_id],
                owner_persona_id=persona,
                source=source,
                followup=FollowupInfo(
                    status=followup.status,
                    owner_org_id=followup.owner_org_id,
                    counterparty_org_id=counterparty_org_id,
                ),
            )
        )
    return records


def skip_record(*, viewer_persona_id: str, target_persona_id: str) -> MemoryRecord:
    """A left swipe is remembered in the viewer's own company memory (internal), so a card is not re-shown."""
    viewer, target = names.persona(viewer_persona_id), names.persona(target_persona_id)
    text = f"{viewer.name} skipped {target.name} ({target.org_id}) in Discover."
    return MemoryRecord(
        memory_id=f"skip-{viewer_persona_id}-{target_persona_id}",
        org_id=viewer.org_id,
        share_level="internal",
        kind="note",
        title=f"Skipped {target.name}"[:200],
        text=text,
        summary=text[:400],
        tags=["skipped"],
        about_org_ids=[target.org_id],
        about_persona_ids=[target_persona_id],
        owner_persona_id=viewer_persona_id,
        source=SourceRef(type="conference"),
    )
