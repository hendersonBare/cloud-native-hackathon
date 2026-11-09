"""Reports DelegateEvents to the gateway (POST /internal/events).

Events go through a queue with one worker, so order is kept and the exchange never waits on the gateway.
A failure is logged by event type only (never content) and never breaks the exchange.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

import httpx

from rapport_common import names
from rapport_common.models import DelegateEvent

log = logging.getLogger("rapport.delegate.reporter")

POST_TIMEOUT_S = 2.0
FLUSH_TIMEOUT_S = 5.0
MAX_CONSECUTIVE_FAILURES = 3  # then stop trying: the gateway is down, do not slow the exchange


class EventSink(Protocol):
    async def post(self, event: DelegateEvent) -> None: ...


class HttpEventSink:
    def __init__(self, client: httpx.AsyncClient, base_url: str | None = None) -> None:
        self._client = client
        self._url = (base_url or names.gateway_url()).rstrip("/") + "/internal/events"

    async def post(self, event: DelegateEvent) -> None:
        resp = await self._client.post(self._url, json=event.model_dump(mode="json"), timeout=POST_TIMEOUT_S)
        resp.raise_for_status()


class RecordingSink:
    """Test double: keeps every event in order."""

    def __init__(self) -> None:
        self.events: list[DelegateEvent] = []

    async def post(self, event: DelegateEvent) -> None:
        self.events.append(event)


class Reporter:
    def __init__(self, sink: EventSink, *, encounter_id: str, org_id: str, persona_id: str) -> None:
        self._sink = sink
        self._ids = {"encounter_id": encounter_id, "org_id": org_id, "persona_id": persona_id}
        self._queue: asyncio.Queue[DelegateEvent | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._failures = 0

    def send(self, type_: str, data: dict[str, Any]) -> None:
        """Queue one event. Never raises."""
        try:
            event = DelegateEvent(type=type_, data=data, **self._ids)  # type: ignore[arg-type]
        except Exception as exc:  # a malformed event is our bug, not a reason to stop the exchange
            log.error("dropping invalid %s event (%s)", type_, type(exc).__name__)
            return
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())
        self._queue.put_nowait(event)

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                if event is None:
                    return
                if self._failures >= MAX_CONSECUTIVE_FAILURES:
                    continue
                try:
                    await self._sink.post(event)
                    self._failures = 0
                except Exception as exc:
                    self._failures += 1
                    log.warning("event %s not delivered (%s)", event.type, type(exc).__name__)
            finally:
                self._queue.task_done()

    async def flush(self) -> None:
        """Wait (bounded) until everything queued has been attempted."""
        if self._worker is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), FLUSH_TIMEOUT_S)
        except TimeoutError:
            log.warning("event flush timed out")

    async def aclose(self) -> None:
        await self.flush()
        if self._worker is not None and not self._worker.done():
            self._queue.put_nowait(None)
            try:
                await asyncio.wait_for(self._worker, 1.0)
            except (TimeoutError, asyncio.CancelledError):
                self._worker.cancel()
