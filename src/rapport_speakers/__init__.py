"""Speaker identification on Elasticsearch (speaker_identification_spec.md, milestones M2 and M3).

Who spoke when at the conference, and search by who said what, with jump-to timestamps.

- `vectors` and `decide`: unit vectors, centroids and the spec's kNN decision rule (§5.4).
- `store`: the store protocol plus an in-memory fake; `es_store`: the Elasticsearch implementation.
- `pipeline`: schedule enrollment (§5.3), identification (§5.4), relabeling (§5.5) and erasure (§8).
- `search`: hybrid search by who said what (§6). `api`: FastAPI routers. `cli`: seed and ask locally.
- `audio`: the offline WhisperX + ECAPA step (M1). Optional; never imported by the service.

Voiceprints are biometric data. Logs, spans and metrics carry IDs and counts only: never transcript text,
names, queries or vectors.
"""
