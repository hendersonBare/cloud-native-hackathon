# OpenTelemetry, OpenLIT and Dash0

## What we use it for

Observability is part of the product. Each meeting spans several processes: the gateway, the kopf operator, and two short-lived delegate pods in two company namespaces, each calling its own OPA and an LLM. We instrument every service with OpenTelemetry and export traces, metrics and logs over OTLP/HTTP to Dash0, so one encounter reads as one trace from the click to both pods. OpenLIT adds LLM token and cost data to the same traces with message content capture off. The swarm panel on the stage shows the same facts Dash0 receives (pod status, every exchange message, every policy decision), and spans, metrics and logs never carry memory text, prompts or briefs.

## Where it lives

| Path | What it is |
|---|---|
| `src/rapport_common/telemetry.py` | `init_telemetry()`, span attribute and metric name constants, `current_traceparent()`, `context_from_traceparent()`, `shutdown_telemetry()` (a contract, read-only for workstreams) |
| `src/rapport_gateway/connect.py` | `connect.accept`, `encounter.create` and `brief.request` spans |
| `src/rapport_gateway/observability.py` | `rapport.brief.latency` and `rapport.encounters.started` |
| `src/rapport_gateway/k8s.py` | Writes the `rapport.dev/traceparent` annotation on the Encounter |
| `src/rapport_operator/builders.py` | Copies the annotation into each delegate's `TRACEPARENT` env; mounts the optional `dash0-otlp` Secret |
| `src/rapport_delegate/initiator.py`, `src/rapport_delegate/responder.py` | The `exchange.run` root span, parented on `TRACEPARENT` |
| `src/rapport_delegate/agent.py` | `exchange.round` and `policy.check` spans |
| `src/rapport_delegate/instruments.py` | `rapport.policy.decisions` and `rapport.exchange.duration` |
| `src/rapport_delegate/runtime.py` | Calls `shutdown_telemetry()` before the pod exits |
| `src/rapport_memory/client.py` | `memory.search` span |
| `src/rapport_briefer/brief.py`, `src/rapport_briefer/context.py` | `brief.generate` and `context.ingest` spans |
| `src/rapport_speakers/pipeline.py`, `src/rapport_speakers/search.py` | `speakers.*` spans and the `rapport.speakers.decisions` counter |
| `deploy/gateway/deployment.yaml`, `deploy/operator/deployment.yaml`, `deploy/briefer/briefer-*.yaml` | `envFrom` the `dash0-otlp` Secret with `optional: true` |
| `web/app/rum.js`, `src/rapport_gateway/routers/rum.py` | Dash0 website monitoring (RUM) for the stage and phone pages; settings from `GET /api/rum-config`, filled from the optional `dash0-rum` Secret |
| `docs/SPEC.md` §8 | Span names, attributes, metrics, SLO targets and the dashboard layout |

## How it works here

- **One setup call.** Every process calls `init_telemetry("rapport-<component>", org_id=..., fastapi_app=app)` at startup. It builds a `Resource` with `service.name`, `service.namespace=rapport`, `deployment.environment.name`, and the pod's namespace and name when set (`src/rapport_common/telemetry.py:56-71`). Exporters are created only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (`:75-80`, `:86-97`), so local runs and tests are a quiet no-op (`tests/common/test_contracts.py::test_telemetry_is_noop_without_endpoint`). Configuration comes only from the standard `OTEL_EXPORTER_OTLP_*` variables in the `dash0-otlp` Secret. httpx and FastAPI are auto-instrumented (`:101-110`).
- **OpenLIT without content.** `openlit.init(..., capture_message_content=False)` runs after our providers exist and reuses them, so LLM spans and `gen_ai.*` token and cost attributes land in the same traces with no prompt or response text (`src/rapport_common/telemetry.py:112-119`).
- **One trace per encounter.** On accept, the gateway opens `connect.accept` and `encounter.create` and passes `current_traceparent()` to the launcher (`src/rapport_gateway/connect.py:137-142`), which writes it as the `rapport.dev/traceparent` annotation on the cluster-scoped Encounter (`src/rapport_gateway/k8s.py:36`). The operator copies it into each delegate Job's `TRACEPARENT` env (`src/rapport_operator/builders.py:111-113`). Each delegate opens `exchange.run` with `context_from_traceparent()` (`src/rapport_delegate/initiator.py:107-108`; the responder does the same at `src/rapport_delegate/responder.py:49`). The local launcher sets the same env (`src/rapport_gateway/launcher_local.py:92`), so local runs keep the link.
- **Spans and attributes** (SPEC §8). Gateway: `connect.accept`, `encounter.create`, `brief.request`. Delegate: `exchange.run`, `exchange.round` (round, side, encounter), `policy.check` (action, item ID, decision, rule ID; `src/rapport_delegate/agent.py:147-151`). Memory: `memory.search` with the result count only (`src/rapport_memory/client.py:178-180`). Briefer: `brief.generate`, `context.ingest`. Attribute keys are the `ATTR_*` constants, not string literals.
- **Metrics.** `rapport.brief.latency` (ms histogram, gateway, accept until the private brief is pushed), `rapport.encounters.started` (counter, gateway), `rapport.exchange.duration` (ms histogram, initiator delegate) and `rapport.policy.decisions` (counter with `decision`, `rule_id` and `org_id`; `src/rapport_delegate/instruments.py:21-22`). Instruments are created lazily so they bind to whichever meter provider is installed.
- **Short-lived pods flush.** A delegate Job is short-lived (`activeDeadlineSeconds: 120`), so `runtime.py` calls `shutdown_telemetry()` in a `finally` block before exit (`src/rapport_delegate/runtime.py:42`); it force-flushes and shuts down the tracer, meter and logger providers.
- **A missing Secret degrades, it doesn't break.** The gateway, operator and briefer Deployments and every delegate Job (`DELEGATE_SECRETS` in `src/rapport_operator/builders.py:25`) mount `dash0-otlp` through `envFrom` with `optional: true`, so a pod without it starts with no telemetry rather than failing.
- **Browser to pod in one trace.** `web/app/rum.js` loads Dash0's web SDK (pinned, with Subresource Integrity) only when `GET /api/rum-config` returns settings from the `dash0-rum` Secret, so no token is in git. Same-origin fetches carry a `traceparent`, so a click in the browser becomes the parent of the gateway's span; LOG 15:36 shows browser span `294c05…` as the parent of the gateway's `GET /api/talks` span. No session replay is loaded, and URL query values that can carry typed text (such as the talk search `q`) are replaced with `REDACTED` before they become span attributes ([PR #27](https://github.com/hendersonBare/cloud-native-hackathon/pull/27)).
- **No content.** The spans, metrics and log lines Rapport writes itself carry IDs, counts, decisions and rule IDs. Where an error could carry content, the code logs the exception type or document ID instead (for example `src/rapport_delegate/policy.py:47`, and the bulk-failure path tested by `tests/memory/test_memory_client.py::test_write_raises_on_partial_bulk_failure_without_leaking_content`).
- **SLO targets and dashboard** are defined in SPEC §8: 95% of private briefs within 5 s of accept, 99% of exchanges complete within 30 s; panels for encounters per minute, p95 brief latency, policy decisions by rule (denials in red) and LLM cost per encounter.

## What a reviewer should check in a PR

- Every new service calls `init_telemetry(...)` at startup and serves `GET /healthz`.
- Spans carry IDs, counts, decisions and rule IDs; never memory text, prompts, LLM responses, asks, briefs, CV text, Elasticsearch query text, emails or keys. The same holds for metric attributes and log lines.
- Span attribute keys and metric names come from `rapport_common.telemetry` constants; span names match SPEC §8.
- OpenLIT stays initialised with `capture_message_content=False`.
- Anything that starts a delegate keeps the `traceparent` chain intact: gateway annotation, operator env, delegate `context_from_traceparent()`.
- A delegate or other short-lived process calls `shutdown_telemetry()` before it exits.
- Exporter configuration comes only from `OTEL_EXPORTER_OTLP_*`; no endpoint or token in code, manifests or tests. The `dash0-otlp` Secret is mounted with `optional: true`.
- Telemetry setup failures are logged and never block startup.

## Evidence

- Telemetry has been in the contracts since the kit commit (`4407b76`), and the delegate and gateway instruments landed in [PR #9](https://github.com/hendersonBare/cloud-native-hackathon/pull/9) and [PR #10](https://github.com/hendersonBare/cloud-native-hackathon/pull/10).
- `docs/evidence/LOG.md`, 14:03 MST: local L2 exchange (two OPA servers, two delegate processes, no Kubernetes) recorded 20 delegate events, including the `pricing_needs_approval` deny.
- LOG 14:16 MST: full local stack, encounter `enc-b3293785`. One accept produced 25 swarm events, including the red `pricing_needs_approval` deny, with no private brief on the swarm stream.
- LOG 14:41 MST: first encounter on Kubernetes, `enc-f629a19e`. The gateway accepted every delegate event from both pods.
- LOG 14:45 MST: the platform's edge cuts every SSE stream 15 to 19 s after it opens (curl probes against the public URL). The gateway now sends event IDs, honours `Last-Event-ID`, sends `retry: 1000` and rotates streams before the cut ([PR #20](https://github.com/hendersonBare/cloud-native-hackathon/pull/20)).
