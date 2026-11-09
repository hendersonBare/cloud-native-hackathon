"""Logging filters that keep request logs useful without leaking content.

AGENTS.md allows IDs in logs, never content. Search text travels in query strings (``GET /api/talks?q=...``,
``/api/calendar/agenda?q=...`` and the briefer calls they make), so every log line that prints a URL keeps the path
and drops the query. Both loggers also feed Dash0 through the OTel log handler that ``init_telemetry`` installs.
"""

from __future__ import annotations

import logging


def _without_query(value: object) -> str:
    return str(value).split("?", 1)[0]


class _QueryFreeArg(logging.Filter):
    """Strip the query string from the positional log argument at ``index`` when it carries one."""

    index = 0

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        i = self.index
        if isinstance(args, tuple) and len(args) > i and "?" in str(args[i]):
            record.args = (*args[:i], _without_query(args[i]), *args[i + 1 :])
        return True


class PathOnlyAccessLog(_QueryFreeArg):
    """uvicorn's access log: ``'%s - "%s %s HTTP/%s" %d'`` with the path and query as the third argument."""

    index = 2


class QueryFreeHttpxLog(_QueryFreeArg):
    """httpx's request log: ``'HTTP Request: %s %s "%s %d %s"'`` with the URL as the second argument."""

    index = 1


FILTERS: dict[str, type[_QueryFreeArg]] = {"uvicorn.access": PathOnlyAccessLog, "httpx": QueryFreeHttpxLog}


def install_log_filters() -> None:
    """Attach each filter to its logger once. Call it after building uvicorn's Config (which configures logging)."""
    for name, kind in FILTERS.items():
        logger = logging.getLogger(name)
        if not any(isinstance(f, kind) for f in logger.filters):
            logger.addFilter(kind())
