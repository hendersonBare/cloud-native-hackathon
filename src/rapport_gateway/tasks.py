"""Keep strong references to background tasks, log their failures (IDs only) and cancel them on reset."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger("rapport.gateway.tasks")


class BackgroundTasks:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
        task = asyncio.get_running_loop().create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("background task %s failed: %s", task.get_name(), type(task.exception()).__name__)

    def cancel_all(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()

    async def drain(self, timeout: float = 5.0) -> None:
        """Wait for running tasks (used by tests and shutdown)."""
        pending = tuple(self._tasks)
        if pending:
            await asyncio.wait(pending, timeout=timeout)

    def __len__(self) -> int:
        return len(self._tasks)
