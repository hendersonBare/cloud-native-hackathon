# How Rapport uses its stack

Rapport gives every conference attendee a personal agent with a private memory. When two people connect, their agents meet on Kubernetes, one short-lived delegate pod per company, and swap only what each company's policy allows. Each page below explains one part of the stack: what we use it for, where it lives in the repo, how it works here, what a reviewer should check in a PR, and the evidence from the day (PRs, evidence-log entries, encounter and investigation IDs).

The source of truth for contracts is [`docs/SPEC.md`](../SPEC.md). House rules are in [`AGENTS.md`](../../AGENTS.md). Review rules are in [`.gitar/`](../../.gitar/). The running record of the day is [`docs/evidence/LOG.md`](../evidence/LOG.md).

## Gitar and SonarQube Cloud

Every change reaches `main` through a pull request, and merging to `main` is the deploy. Gitar reviews each PR against review instructions and five repository rules that encode Rapport's security model. SonarQube Cloud runs alongside it as a rule-based quality gate. [Read more](gitar-sonar.md).

## OpenTelemetry, OpenLIT and Dash0

One function, `init_telemetry()` in `src/rapport_common/telemetry.py`, sets up traces, metrics and logs over OTLP/HTTP for every service, and OpenLIT adds LLM token and cost data with message content capture off. The Encounter carries a `traceparent` so one trace runs from the click to both delegate pods. [Read more](dash0.md).

## Kubernetes, Argo CD and Radar

Kubernetes is how two agents meet: an `Encounter` custom resource becomes a delegate Job in each company's namespace plus the responder's Service and a per-encounter NetworkPolicy. Argo CD syncs `deploy/` into the team vcluster on every merge, and Radar Cloud (its MCP server, a Radar issue and an AI investigation) was how we watched and debugged the cluster. [Read more](radar.md).

## Elasticsearch

Elasticsearch is the memory. Five indices hold the agenda, attendee cards, profiles, documents, notes and follow-ups; search is BM25 plus `semantic_text` merged with RRF, with an optional reranker. Per-company indices and scoped API keys are a security boundary. Speaker identification adds kNN over voiceprint vectors. [Read more](elasticsearch.md).

## Open Policy Agent

One OPA runs in each company namespace and checks every item a delegate wants to send. The rules are an ordered chain that ends in `default_deny`, and the delegate treats an unreachable or slow OPA as a deny. Every decision becomes an event on the stage, a `policy.check` span and a `rapport.policy.decisions` metric. [Read more](opa.md).

## Repository map

| Path | What it is |
|---|---|
| `src/rapport_common/` | The contracts every part builds against: models, names, telemetry, the memory interface and an in-memory fake. Read-only for workstreams |
| `src/rapport_gateway/` | FastAPI gateway: REST, SSE fan-out, Encounter creation, the pod watch, mock mode |
| `src/rapport_operator/` | The kopf operator: Encounter → delegate Jobs, Service, NetworkPolicy, TTL clean-up |
| `src/rapport_delegate/` | The public agent: `rapport.exchange/v1`, the OPA client, malicious mode |
| `src/rapport_briefer/` | The private agent: briefs, ask, talks, context upload, research, deep dive |
| `src/rapport_memory/` | Elasticsearch hybrid search, redaction, seed data |
| `src/rapport_speakers/` | Speaker identification on Elasticsearch: voiceprints, kNN decision rule, relabeling, erasure, search by who said what ([spec](../../speaker_identification_spec.md)) |
| `src/rapport_calendar/` | The per-person agenda: conference talks and meetings that agents propose, served by the gateway at `/api/calendar` |
| `policy/`, `deploy/policy/` | OPA policy (Rego v1), its tests, one OPA per company |
| `deploy/` | Kustomize for Argo CD: namespaces and NetworkPolicies, the CRD, each component, Elastic template and key scopes |
| `web/` | The two-phone stage, the phone app and the swarm panel (no build step) |
| `contracts/demo-events.json` | The scripted event stream for mock mode and the stage fallback |
| `.gitar/` | Gitar review instructions, repository rules and auto-apply limits |
| `.claude/agents/`, `.agents/skills/` | One Claude Code subagent per workstream; the ship, debug and canary procedures |
| `docs/` | [Spec](../SPEC.md), [pitch](../PITCH.md), [demo](../DEMO.md), [setup](../SETUP.md), [costs](../COSTS.md), [track evidence](../TRACKS.md), the [evidence log](../evidence/LOG.md) and these stack pages |

House rules for every agent and human: [`AGENTS.md`](../../AGENTS.md). The starter template we built on: [`docs/CNH-STARTER.md`](../CNH-STARTER.md).
