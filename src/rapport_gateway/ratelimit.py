"""Sliding-window rate limiting, in memory (the gateway runs as one replica)."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

from .errors import GatewayError


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        hits = self._hits[key]
        cutoff = self._clock() - self.window_s
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            self._hits.pop(key, None)
            return deque()
        return hits

    def used(self, key: str) -> int:
        return len(self._prune(key))

    def retry_after(self, key: str) -> float:
        """Seconds until the key may hit again; 0 when it may hit now."""
        hits = self._prune(key)
        if len(hits) < self.limit:
            return 0.0
        return max(hits[0] + self.window_s - self._clock(), 0.0)

    def record(self, key: str) -> None:
        self._prune(key)
        self._hits[key].append(self._clock())

    def hit(self, key: str) -> float:
        """Record a hit if allowed and return 0, else return the seconds to wait (nothing is recorded)."""
        wait = self.retry_after(key)
        if wait == 0.0:
            self.record(key)
        return wait

    def clear(self) -> None:
        self._hits.clear()


def client_ip(request: Request) -> str:
    """The caller's IP. Behind the platform router the TCP peer is the router, so use the address the
    router appended last to X-Forwarded-For (the one it observed); a client cannot forge that entry."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def too_many(wait_s: float, detail: str = "rate limit exceeded") -> GatewayError:
    return GatewayError(429, detail, headers={"Retry-After": str(max(math.ceil(wait_s), 1))})
