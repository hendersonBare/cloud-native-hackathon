"""Unit vectors in pure Python (192 dims is small; no numpy in the shared image).

`dot_product` similarity in Elasticsearch needs unit-length vectors, and then equals cosine (spec §4.3).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Vector = Sequence[float]


def norm(v: Vector) -> float:
    return math.sqrt(sum(x * x for x in v))


def normalize(v: Vector) -> list[float]:
    n = norm(v)
    if n == 0 or not math.isfinite(n):
        raise ValueError("cannot normalize a zero or non-finite vector")
    return [x / n for x in v]


def dot(a: Vector, b: Vector) -> float:
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} != {len(b)}")
    return sum(x * y for x, y in zip(a, b))


def is_unit(v: Vector, tol: float = 1e-3) -> bool:
    return abs(norm(v) - 1.0) <= tol


def recompute_centroid(sample_embeddings: Sequence[Vector]) -> list[float]:
    """§5.3: the normalized mean of the normalized sample embeddings."""
    if not sample_embeddings:
        raise ValueError("a centroid needs at least one sample")
    unit = [normalize(e) for e in sample_embeddings]
    dims = len(unit[0])
    mean = [sum(e[i] for e in unit) / len(unit) for i in range(dims)]
    return normalize(mean)


def es_score(cosine: float) -> float:
    """What Elasticsearch reports for dot_product on unit vectors: (1 + cosine) / 2 (§5.4)."""
    return (1.0 + cosine) / 2.0


def cosine_from_score(score: float) -> float:
    return 2.0 * score - 1.0
