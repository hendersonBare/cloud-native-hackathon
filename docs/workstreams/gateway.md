# Workstream: gateway (the hub)

**Mission.** One FastAPI service in `rapport-system`. It serves the web page and the API, turns "Accept" into an `Encounter`, fans events out to the two phones and the swarm panel over SSE, and routes delegate reports.

**You own:**

- `src/rapport_gateway/`: `__main__.py` runs uvicorn on `0.0.0.0:8080`.
- `deploy/gateway/`: ServiceAccount, RBAC, a Deployment and a Service of type NodePort with `nodePort: 30080`.
- `tests/gateway/`.

**Read first:** `AGENTS.md`, SPEC §2, §4.4, §4.5, §7 and §8, and `rapport_common/models.py` (events).

## Build (P0)

1. **API skeleton** with every route in SPEC §7.1. Validate every body with `rapport_common.models`.
2. **Event bus:** an in-memory set of subscribers, each an `asyncio.Queue`. SSE uses `sse_starlette.EventSourceResponse` with a keepalive every 15 s. Routing rules are in SPEC §7.1: **private content never goes to the swarm stream**.
3. **Mock mode** (`RAPPORT_MOCK=1`): no Kubernetes and no briefers. `accept` replays `contracts/demo-events.json` by `at_ms`. Build this early; the web workstream and the stage fallback depend on it.
4. **Connect and accept:**
   - Keep pending requests in memory.
   - On accept, start the span `connect.accept`, then create the cluster-scoped Encounter with `CustomObjectsApi.create_cluster_custom_object` (`rapport.dev`, `v1alpha1`, `encounters`). Put the `rapport.dev/traceparent` annotation from `current_traceparent()` on it.
   - Emit `encounter_started`.
   - **Concurrently** call both briefers' `POST /v1/brief` (`httpx`, 15 s timeout). Emit each `private_brief` to its own phone and record `rapport.brief.latency`.
5. **Pod watch:** a background thread running a `kubernetes.watch` on pods labelled `rapport.dev/role=delegate` in `org-acme` and `org-bluefin`. Emit `pod_status` using the pod's labels for encounter, org and side. Hand events to the asyncio loop with `loop.call_soon_threadsafe`.
6. **`POST /internal/events`:**
   - Validate the `DelegateEvent` and map it to a `GatewayEvent`.
   - On `shared_brief`, push it to that person's phone. Then call that company's briefer `POST /v1/remember` with one `encounter_summary` record and one `followup` record per follow-up. All are `share_level=internal`, in the briefer's own company, with `source.encounter_id` set.
   - Emit `encounter_completed` when both shared briefs have arrived, or when either delegate reports `failed`.
7. **Proxies:** `/api/context` (pass the multipart through unchanged), `/api/profile`, `/api/ask` and `/api/talks` go to `names.briefer_url(org_of(persona_id))`. Emit `profile_updated` after a successful upload.
8. **Static files:** mount `web/` at `/` with `StaticFiles(html=True)` **after** the API routes.
9. **Kubernetes config:** `load_incluster_config()`, falling back to `load_kube_config()` for local runs.

## Interfaces

- **You provide:** the public API, `/internal/events` and the SSE events.
- **You consume:** the briefer API (SPEC §7.2), the Kubernetes API and `DelegateEvent`.

## Done when

- Pytest covers the routes, with briefers mocked by `respx` and the Kubernetes client faked. Include a routing test proving a `private_brief` never reaches the swarm stream.
- `RAPPORT_MOCK=1 PYTHONPATH=src uv run python -m rapport_gateway`, then opening `http://localhost:8080/?mock=1`, plays the demo once web lands.
- In kind: `curl localhost:8080/healthz` works, and connect plus accept creates an Encounter that shows up in `kubectl get enc`.

## Gotchas

- RBAC: create, get, list and watch `encounters` (cluster-scoped, so you need a ClusterRole), and get, list and watch `pods` in the two org namespaces.
- Never block the event loop with the Kubernetes watch.
- Keep the gateway at one replica (in-memory state). That's fine for today.

**Out of scope:** auth (personas are a demo picker), persistence, real phones.

## Discover (v1.1, added 12:00 PM): read `docs/FEATURE-DISCOVER.md`

1. **`POST /api/research`** proxies to the viewer's briefer.
2. **`POST /api/swipe`:**
   - A left swipe is only recorded.
   - A right swipe emits `deep_dive_started`, calls `/v1/deep-dive` (20 s timeout) and emits `deep_dive_ready`. If the decision is `agent_handshake`, `autonomy` is true and the hourly limit allows it (`names.MAX_AGENT_HANDSHAKES_PER_HOUR`), it creates the connect request with `initiated_by="agent"`. It always emits `agent_decision`.
3. **Routing:** `deep_dive_*` goes to the viewer's phone only. `agent_decision` goes to the viewer's phone and the swarm.
4. **Mock mode:** replays `contracts/demo-events.json` by phase: `upload` after an upload, `swipe` after a right swipe, `accept` after Accept. `/api/research` returns `contracts/demo-research.json`.

**Done when:** tests cover the decision branches (handshake, human intro, skip, rate-limited, autonomy off) and prove that `deep_dive_ready` never reaches the swarm stream.
