# Rapport gateway API (frontend reference)

The gateway is the only API the web page talks to. Bodies and events use the models in `src/rapport_common/models.py`; this page shows their JSON. The live schema is always at `/docs` (Swagger UI) and `/openapi.json`.

## Base URLs

| Where | Base URL |
|---|---|
| Deployed | `https://rapport.cnh.radarhq.io` (same origin as the page, so no CORS) |
| Local | `http://localhost:8080` (`PORT` changes it) |
| Separate dev server | the page runs on its own origin (for example `http://localhost:5180`); start the gateway with `RAPPORT_CORS_ORIGINS=http://localhost:5180` |

`/internal/*` is **never** served on this port (404). Delegates use the cluster-only port 8081.

## Errors

Every error is JSON `{"detail": "<message>"}`. Validation errors from FastAPI have a list in `detail`.

| Status | When |
|---|---|
| 401 / 403 | `/api/demo/reset` without / with the wrong `Authorization: Bearer <token>` (only when `RAPPORT_ADMIN_TOKEN` is set); accept by someone other than the person asked |
| 404 | unknown persona, unknown connect request |
| 413 | upload over 2 MB |
| 415 | upload that is not `.pdf`, `.md` or `.txt` |
| 422 | body or query does not validate; persona has no agent (`kestrel.*`, `harborline.*`, ...); connecting two people of one company; neither `file` nor `text` |
| 429 | more than 30 LLM-backed calls per minute from one client (ask, research, right swipes, context uploads, accept). `Retry-After` header, in seconds |
| 502 / 504 | the person's briefer failed / timed out |
| 503 | a briefer is unreachable, or Kubernetes is not available (accept) |

## Endpoints

### `GET /healthz`
```json
{"ok": true, "version": "89886ea"}
```

### `GET /api/personas`
`{"orgs": [Org], "personas": [Persona]}`: 6 companies and 12 people. Only `acme` and `bluefin` have `agents_enabled: true`. The demo phones are `acme.ava` (left, English) and `bluefin.bo` (right, Spanish).
```json
{"orgs": [{"org_id": "acme", "name": "Acme Observability", "namespace": "org-acme", "blurb": "...", "color": "#3b6cf6", "agents_enabled": true}],
 "personas": [{"persona_id": "acme.ava", "org_id": "acme", "name": "Ava", "title": "Solutions Engineer", "language": "en", "interests": ["ebpf"], "goals": [], "demo_phone": "left"}]}
```

### `POST /api/context` (multipart)
Fields: `persona_id`, `visibility` (`shareable` | `private`), `file` (`.pdf`, `.md`, `.txt`, at most 2 MB) and/or `text`. Returns a `PersonaProfile` and emits `profile_updated` to that person's phone.
```json
{"persona_id": "acme.ava",
 "shareable": {"visibility": "shareable", "headline": "Solutions engineer helping platform teams adopt eBPF tracing", "interests": ["ebpf", "kubernetes"], "goals": [], "highlights": ["Led a hospital rollout"]},
 "private": {"visibility": "private", "headline": "Wants a healthcare design partner this quarter", "interests": ["healthcare"], "goals": ["Find a design partner in healthcare"], "highlights": []},
 "source_files": ["ava-cv-synthetic.pdf"], "updated_at": "2026-11-09T21:00:00Z"}
```

### `GET /api/profile?persona_id=acme.ava`
A `PersonaProfile` (same shape as above).

### `POST /api/connect`
```json
{"from_persona_id": "acme.ava", "to_persona_id": "bluefin.bo", "malicious": true}
```
`malicious` makes the responder's delegate try a prompt injection (default false). `initiated_by` is `"human"` (default); only the gateway sets `"agent"`. Returns `{"request_id": "req-1a2b3c4d"}` and sends `connect_request` to the target's phone.

### `POST /api/connect/{request_id}/accept`
Only the person who was asked can accept. Repeating the call returns the same Encounter.
```json
{"persona_id": "bluefin.bo"}
```
Returns `{"encounter_id": "enc-1a2b3c4d"}`. In live mode this creates the Encounter; the events below follow. 403 for anyone else, 404 for an unknown request, 503 when Kubernetes is unavailable.

### `POST /api/ask`
```json
{"persona_id": "acme.ava", "question": "What did we promise Bluefin?"}
```
```json
{"answer": "Sam promised Kai the security questionnaire before the pilot starts.",
 "citations": [{"memory_id": "acme-note-0007", "title": "Call notes: Bluefin pilot (March)", "kind": "account_note", "snippet": "Sam promised Kai the security questionnaire before the pilot starts."}]}
```

### `GET /api/talks?persona_id=acme.ava&q=ebpf`
`TalkSearchResult`. Times are UTC. Show them in `America/Denver` with the label (for example `3:30 PM MST`).
```json
{"query": "ebpf", "talks": [{"talk_id": "talk-ebpf-zero-code", "title": "Zero-code tracing with eBPF on Kubernetes", "starts_at": "2026-11-09T22:30:00Z", "room": "Room B", "track": "Observability", "speakers": ["R. Alvarez"], "reason": "3:30 PM MST in Room B"}]}
```

### `POST /api/research` (Discover)
`ResearchRequest` in, `ResearchResult` out (swipe cards, private to the viewer).
```json
{"persona_id": "acme.ava", "filters": {"interests": ["ebpf"], "has_agent": null}, "exclude_persona_ids": ["kestrel.mia"], "limit": 10}
```
Each card: `persona_id, name, title, org_id, org_name, language, headline, interests, looking_for, agent_available, match_score, shared_interests, why_meet, their_talks, company_history` (see `contracts/demo-research.json`).

### `POST /api/swipe` (Discover)
```json
{"persona_id": "acme.ava", "target_persona_id": "bluefin.bo", "direction": "right", "autonomy": true, "malicious": false}
```
Returns `202 {"accepted": true}` at once; the results arrive on the stream.
- `left`: remembered, nothing else happens.
- `right`: `deep_dive_started`, then `deep_dive_ready` (summary, plan, decision), then `agent_decision`. The decision is `agent_handshake` only when the target's company runs agents, `autonomy` is true and the viewer has used fewer than 5 handshakes this hour; the gateway then also creates a connect request with `initiated_by: "agent"` and sends `connect_request` to the target (after `agent_decision`, with the same `request_id`). Otherwise it is `human_intro` or `skip`, and `deep_dive_ready.data.decision` shows the same action and the guardrail lines.
- If the deep dive fails: an `error` event on the viewer's phone, then `agent_decision` with `human_intro`.

### `POST /api/demo/reset`
Clears connect requests, encounters, the replay buffer, rate limits and (mock) cached profiles. Returns `{"ok": true}`. Needs `Authorization: Bearer <RAPPORT_ADMIN_TOKEN>` when that variable is set. Open streams stay connected.

## Server-Sent Events

```js
new EventSource('/api/stream?persona_id=acme.ava', { withCredentials: true })  // a phone
new EventSource('/api/stream?view=swarm', { withCredentials: true })           // the swarm panel
```
Exactly one of `persona_id` or `view=swarm`. Unknown persona: 404; both or neither: 422.

Wire format (LF line endings):
```
event: agent_decision
data: {"type":"agent_decision","ts":"2026-11-09T21:00:03.600000Z","encounter_id":null,"persona_id":"acme.ava","trace_id":null,"data":{"target_persona_id":"bluefin.bo","action":"agent_handshake","request_id":"req-1a2b3c4d"}}

: keepalive
```
`data` is a `GatewayEvent`: `type, ts, encounter_id, persona_id, trace_id, data`. A `: keepalive` comment arrives every 15 s (every half of `RAPPORT_SSE_MAX_SECONDS` when that is shorter). The gateway replays recent events (the last 200 that match the stream) to a new connection, so a reload mid-demo catches up. **Dedupe on `type + ts + encounter_id`**: replays resend the same events, and the gateway guarantees distinct events never share that key.

Reconnecting (the platform's edge proxy cuts any stream after about 15 s, so the gateway ends each stream cleanly about every 12 s and `EventSource` reconnects by itself):
- Every event frame starts with an `id:` line (`id: 1731186003600123`). Ids increase across all events in the gateway process (and keep increasing after a restart); treat them as opaque numbers. A replayed event keeps its id.
- Every stream begins with `retry: 1000`, so the browser reconnects within a second.
- On a reconnect `EventSource` sends the `Last-Event-ID` header automatically. The gateway then replays only the buffered events with a greater id that match the stream's routing (phone or swarm; the swarm still never sees `private_brief`, `profile_updated`, `deep_dive_started` or `deep_dive_ready`). Without it, a new connection gets today's full replay. For a client that cannot set the header, `?last_event_id=<id>` does the same; the header wins when both are present.
- `RAPPORT_SSE_MAX_SECONDS` (default `12`, `0` turns rotation off) sets how long a stream lives before the gateway closes it. A close followed by an immediate reconnect is normal: keep the dedupe key above and do not show a "disconnected" state for it.

| Event | `data` model | Phone stream | Swarm stream |
|---|---|---|---|
| `connect_request` | `ConnectRequestData` | the target (`persona_id`) | yes |
| `encounter_started` | `EncounterStartedData` | both people in the encounter | yes |
| `pod_status` | `PodStatusData` | no | yes |
| `exchange_message` | `ExchangeMessageData` | no | yes |
| `policy_decision` | `PolicyDecisionData` | no | yes |
| `private_brief` | `PrivateBrief` | its owner (`persona_id`) | **never** |
| `shared_brief` | `SharedBrief` | its owner (`persona_id`) | yes |
| `encounter_completed` | `EncounterCompletedData` (`completed` or `failed`, with `detail`, for example `timeout`) | both people in the encounter | yes |
| `profile_updated` | `PersonaProfile` | its owner | **never** |
| `deep_dive_started` | `DeepDiveStartedData` | the viewer | **never** |
| `deep_dive_ready` | `DeepDive` | the viewer | **never** |
| `agent_decision` | `AgentDecisionData` (no reason) | the viewer | yes |
| `error` | `{"message": "..."}` | the person it names (`persona_id`) | only when it names nobody |

Private content (briefs, profiles, research, reasons) only ever goes to its owner's phone.

## Demo flow as calls

1. `GET /api/personas`, open `/api/stream?persona_id=acme.ava`, `/api/stream?persona_id=bluefin.bo` and `/api/stream?view=swarm`.
2. `POST /api/context` (Ava's CV): `profile_updated` on Ava's phone.
3. Discover: `POST /api/research`, then `POST /api/swipe` left on Mia, right on Priya (`human_intro`: she has no agent), right on Bo (`agent_handshake`): Bo's phone gets `connect_request` with `initiated_by: "agent"`.
   Or without Discover: `POST /api/connect` from Ava to Bo.
4. `POST /api/connect/{request_id}/accept` as Bo: `encounter_started`, 4x `pod_status`, `private_brief` on each phone, then `exchange_message` / `policy_decision` (the `pricing_needs_approval` deny when `malicious`), `shared_brief` on each phone, `encounter_completed`.
5. `POST /api/ask` ("What did we promise Bluefin?") and `GET /api/talks?persona_id=acme.ava&q=ebpf`.
6. `POST /api/demo/reset` between runs.

## Mock mode (`RAPPORT_MOCK=1`)

No Kubernetes, no briefers, no keys: every endpoint above works, replaying `contracts/demo-events.json` and `contracts/demo-research.json` with their `at_ms` timing. Timestamps are re-stamped to the moment of each event, and each run gets new `req-...` and `enc-...` IDs that are consistent within the run.

| Call | Mock behaviour |
|---|---|
| `GET /api/personas` | the real directory |
| `POST /api/context` | returns the fixture `PersonaProfile` for that persona (`source_files` = the uploaded file name); `upload` phase: `profile_updated` |
| `GET /api/profile` | the last uploaded profile, else the fixture |
| `POST /api/connect` | stores the request, `connect_request` to the target at once |
| `POST /api/connect/{id}/accept` | `accept` phase: `encounter_started`, 4x `pod_status`, 2x `private_brief`, 6x `exchange_message`, 4x `policy_decision` (one red deny), 2x `shared_brief`, `encounter_completed` over about 9.5 s |
| `POST /api/swipe` right on `bluefin.bo` by `acme.ava` | `swipe` phase: `deep_dive_started` (1.0 s), `deep_dive_ready` (3.5 s), `agent_decision` with a fresh `request_id` (3.6 s), `connect_request` to Bo (3.7 s). `autonomy: false` gives `human_intro` and no request |
| `POST /api/swipe` right on anyone else | a canned deep dive; `agent_handshake` if the target's company runs agents (and the hourly limit allows), else `human_intro` |
| `POST /api/swipe` left | recorded in memory only |
| `POST /api/ask` | "What did we promise Bluefin?" cites `acme-note-0007`; anything else gets an answer with no citations |
| `GET /api/talks` | five agenda talks including `talk-ebpf-zero-code` (3:30 PM MST, stored as `22:30:00Z`), filtered by `q` |
| `POST /api/research` | `demo-research.json` minus `exclude_persona_ids`, the viewer's own company, filtered by `filters`, cut to `limit` |

`RAPPORT_MOCK_SPEED=10` plays the scripts 10x faster.

## Run it locally

```
RAPPORT_MOCK=1 PORT=8080 INTERNAL_PORT=8081 PYTHONPATH=src uv run python -m rapport_gateway
curl localhost:8080/api/personas
```
Open the page at `http://localhost:8080/` (the gateway serves `web/`). For a separate dev server add `RAPPORT_CORS_ORIGINS=http://localhost:5180` (comma-separated; `*` is ignored because the page opens the stream with credentials).

| Variable | Default | Meaning |
|---|---|---|
| `RAPPORT_MOCK` | off | mock mode |
| `PORT`, `INTERNAL_PORT` | 8080, 8081 | public and cluster-only ports |
| `RAPPORT_CORS_ORIGINS` | none | comma-separated origins allowed with credentials |
| `RAPPORT_ADMIN_TOKEN` | none | when set, `/api/demo/reset` needs `Authorization: Bearer <token>` |
| `RAPPORT_VERSION` | `dev` | reported by `/healthz` (the image sets it to the commit) |
| `RAPPORT_LLM_CALLS_PER_MINUTE` | 30 | per-client limit on LLM-backed calls |
| `RAPPORT_CHECK_DELEGATE_IP` | on | `/internal/events` also checks the caller's IP is a delegate pod of that encounter |
| `RAPPORT_LAUNCHER` | `kubernetes` | `local` starts delegate subprocesses instead of creating an Encounter |
| `BRIEFER_URL_ACME`, `BRIEFER_URL_BLUEFIN` | cluster URLs | point at local briefers |
