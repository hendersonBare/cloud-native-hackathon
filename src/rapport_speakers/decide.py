"""The identification decision rule (spec §5.4) and candidate-pool narrowing.

`hits` are Elasticsearch kNN hits on the voiceprints index (`_score` = (1 + cosine) / 2 for dot_product on
unit vectors), best first. The in-memory store returns the same shape.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .config import POOL_BOOST, Thresholds
from .vectors import cosine_from_score, es_score

IDENTIFIED = "identified"
AMBIGUOUS = "ambiguous"
UNKNOWN = "unknown"


def decide(hits, cluster_speech_s, T_ACCEPT=0.55, MARGIN=0.10, MIN_SPEECH_S=3.0):
    """Spec §5.4, verbatim (parameter names included). Returns (status, person_id or None, top cosine or None)."""
    if cluster_speech_s < MIN_SPEECH_S or not hits:
        return "unknown", None, None
    cos = [2 * h["_score"] - 1 for h in hits]
    top, second = cos[0], (cos[1] if len(cos) > 1 else -1.0)
    if top >= T_ACCEPT and (top - second) >= MARGIN:
        return "identified", hits[0]["_source"]["person_id"], top
    if top >= T_ACCEPT:
        return "ambiguous", hits[0]["_source"]["person_id"], top
    return "unknown", None, top


def decide_with(hits: list[dict[str, Any]], cluster_speech_s: float, thresholds: Thresholds):
    return decide(
        hits, cluster_speech_s,
        T_ACCEPT=thresholds.t_accept, MARGIN=thresholds.margin, MIN_SPEECH_S=thresholds.min_speech_s,
    )


def apply_pool(hits: list[dict[str, Any]], pool: Iterable[str], mode: str, bonus: float) -> list[dict[str, Any]]:
    """Narrow toward the session's scheduled speakers (and known attendees), §5.4.

    `boost` (default) adds `bonus` to the cosine of pool members and re-sorts: a Q&A question from a speaker
    of another session can still match. `filter` is applied in the kNN query itself, so this is a no-op for
    `filter` and `off`. Returns new hit dicts; the input is not changed.
    """
    pool = set(pool)
    if mode != POOL_BOOST or not pool or bonus == 0:
        return list(hits)
    boosted = []
    for hit in hits:
        cos = cosine_from_score(hit["_score"])
        if hit["_source"]["person_id"] in pool:
            cos = min(1.0, cos + bonus)
        boosted.append({**hit, "_score": es_score(cos)})
    boosted.sort(key=lambda h: h["_score"], reverse=True)
    return boosted


def top_two(hits: list[dict[str, Any]]) -> tuple[tuple[str | None, float | None], tuple[str | None, float | None]]:
    """(best id, best cosine), (runner-up id, runner-up cosine) for the review fields on unknown voices."""
    out: list[tuple[str | None, float | None]] = [
        (h["_source"]["person_id"], round(cosine_from_score(h["_score"]), 4)) for h in hits[:2]
    ]
    while len(out) < 2:
        out.append((None, None))
    return out[0], out[1]
