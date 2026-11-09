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
- Kubernetes manifests use image `rapport:dev`, `imagePullPolicy: IfNotPresent`, labels `app.kubernetes.io/part-of: rapport` and `rapport.dev/role`, and requests of 50m CPU and 128Mi memory.
- The PR description has a "Track evidence" section and, where needed, "Security review needed".

Do not suppress or downgrade standard reliability or security findings.
