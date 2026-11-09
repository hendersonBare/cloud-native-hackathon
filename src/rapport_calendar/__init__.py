"""Rapport calendar: a per-person agenda for the conference week.

Talks, meetings that agents propose between people, and personal events. The package exposes a FastAPI router
(``rapport_calendar.api.router``) that the gateway mounts in-process, plus a standalone dev server
(``python -m rapport_calendar``). State is in memory and seeded from ``data/seed.json``.
"""

from __future__ import annotations

__all__ = ["api", "agenda", "app", "ics", "models", "seed", "service", "slots"]
