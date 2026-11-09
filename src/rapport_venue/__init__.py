"""Rapport venue: find a person at the conference venue.

Turns a phone's GPS fix into floor-plan metres, keeps it only while the person consents to be found, and gives
walking directions between two people (out of a room, along the concourse, into the other room). The package exposes
a FastAPI router (``rapport_venue.api.router``) that the gateway mounts in-process, plus a standalone dev server
(``python -m rapport_venue``). State is in memory and seeded from ``data/venue.json``.
"""

from __future__ import annotations

__all__ = ["api", "app", "geometry", "models", "service"]
