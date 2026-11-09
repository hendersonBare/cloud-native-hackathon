"""Demo seed data and its loader.

`seed_records()` builds every record in SPEC section 11 and docs/FEATURE-DISCOVER.md in memory (no network).
`python -m rapport_memory.seed` upserts them into Elasticsearch (idempotent: documents are keyed by memory_id) and
logs the document count per index. It needs ES_URL and ES_ADMIN_API_KEY (`make seed` sources .env).
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

from rapport_common import names
from rapport_common.models import MemoryRecord

from .seed_docs import doc_records
from .seed_people import attendee_records, profile_records
from .seed_talks import talk_records

log = logging.getLogger("rapport.memory.seed")


def seed_records(now: datetime | None = None) -> list[MemoryRecord]:
    """Every seed record. "Today" is computed in America/Denver from `now` (default: the current time)."""
    return [*talk_records(now), *doc_records(now), *profile_records(now), *attendee_records(now)]


def all_indices() -> list[str]:
    """The five Rapport indices, derived from names (never hard-coded)."""
    orgs = [o for o, org in names.orgs().items() if org.agents_enabled]
    return [
        names.CONFERENCE_INDEX,
        *(i for o in orgs for i in (names.shareable_index(o), names.internal_index(o))),
    ]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    es_url = os.environ.get("ES_URL")
    api_key = os.environ.get("ES_ADMIN_API_KEY")
    missing = [n for n, v in (("ES_URL", es_url), ("ES_ADMIN_API_KEY", api_key)) if not v]
    if missing:
        sys.stderr.write(f"Cannot seed: set {' and '.join(missing)} (see .env.example). Nothing was written.\n")
        return 2

    from .client import MemoryClient  # imported late so `seed_records()` users do not need a live client

    records = seed_records()
    indices = all_indices()
    client = MemoryClient(es_url, api_key, allowed_indices=indices)
    written = client.write(records)
    log.info("upserted %d records", written)
    for index, count in client.count(indices).items():
        log.info("%-28s %d documents", index, count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
