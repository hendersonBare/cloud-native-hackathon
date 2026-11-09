# Rapport review instructions

Rapport is a conference networking app: each company's agents meet on Kubernetes and swap only what policy allows. Review every PR against the house rules:

@../../AGENTS.md

## Report a blocking finding when a change

- Sends a `MemoryRecord.text` (rather than `summary`) to another company, or lets a delegate read anything other than `shareable_index(self_org)` and `rapport-conference`.
- Puts memory text, prompts, asks, briefs, CV content or Elasticsearch query text on spans, metrics or logs. IDs, counts, decisions and rule IDs are fine.
- Places counterparty strings (`Ask.text`, `Card.headline`) in system instructions, or uses them to choose a tool, index or URL.
- Accepts an LLM output that references an `item_id` not in the candidate list.
- Redefines a model locally instead of importing from `rapport_common.models`, or edits a contract path (`src/rapport_common/**`, `deploy/crds/**`, `deploy/elastic/**`, `contracts/**`) without a "CONTRACT CHANGE REQUEST".
- Lets the gateway accept an `/internal/events` event for a persona or org that doesn't match the reporting delegate.
- Stores or displays a talk time without a time zone. Store UTC; display America/Denver with its label.
- Renders server strings with `innerHTML`.
- Makes an LLM call without a timeout and a deterministic fallback.

## Also check

- Every new service calls `init_telemetry(...)` and serves `GET /healthz`.
- Kubernetes manifests use image `app` (kustomize sets the GHCR tag), an explicit `namespace`, labels `app.kubernetes.io/part-of: rapport` and `rapport.dev/role`, requests **and** limits from `rapport_common.names.RESOURCES_*`, and `names.SECURITY_CONTEXT`. They're listed in `deploy/<component>/kustomization.yaml`. Report a blocking finding for a container without limits: the team vcluster has one shared budget, and an over-budget pod stays `Pending`.
- `/internal/*` is served only on the gateway's cluster-only port 8081, never on the public port 8080.
- The PR description has a "Track evidence" section and, where needed, "Security review needed".

## Stack context

How Rapport uses each technology, where it lives and the invariants a PR must keep:

@../../docs/stack/README.md
@../../docs/stack/gitar-sonar.md
@../../docs/stack/dash0.md
@../../docs/stack/radar.md
@../../docs/stack/elasticsearch.md
@../../docs/stack/opa.md

Do not suppress or downgrade standard reliability or security findings.
