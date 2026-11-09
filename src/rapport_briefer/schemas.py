"""The few HTTP envelopes SPEC 7.2 names that have no model in rapport_common.models.

Every payload that crosses a component boundary and HAS a contract model (BriefRequest, AskAnswer, ...) is
imported from rapport_common.models; these three are only the `{"ok": true}`, `{"records": [...]}` and
`{"written": n}` wrappers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from rapport_common.models import MemoryRecord


class Health(BaseModel):
    ok: bool = True


class RememberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[MemoryRecord]


class Written(BaseModel):
    written: int
