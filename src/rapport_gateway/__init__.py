"""Rapport gateway: the public API, SSE fan-out, mock mode and the cluster-only /internal/events app.

Modules each do one job (see docs/API.md for the frontend reference):
settings, schemas, bus, ratelimit, briefers, k8s, launcher_local, encounters, remember, connect,
discover, backend, mock, deps, app, internal, routers/*.
"""
