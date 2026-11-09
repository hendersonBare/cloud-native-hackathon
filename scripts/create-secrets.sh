#!/usr/bin/env bash
# Creates or updates the Kubernetes Secrets from your local .env (gitignored). Idempotent.
# Values are never printed. Needs kubectl pointed at the team vcluster (docs/CNH-STARTER.md, "kubectl");
# without it, create the same Secrets in Radar's resource editor instead. Never put them in git.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
if [[ -f .env ]]; then set -a; source .env; set +a; fi

required="OPENAI_API_KEY ES_URL ES_BRIEFER_KEY_ACME ES_BRIEFER_KEY_BLUEFIN ES_DELEGATE_KEY_ACME ES_DELEGATE_KEY_BLUEFIN DASH0_OTLP_ENDPOINT DASH0_AUTH_TOKEN"
for v in $required; do
  if [[ -z "${!v:-}" ]]; then echo "missing ${v} (see .env.example)"; exit 1; fi
done

apply_secret() { # namespace name key=value...
  local ns=$1 name=$2
  shift 2
  local args=()
  for kv in "$@"; do args+=("--from-literal=${kv}"); done
  kubectl -n "$ns" create secret generic "$name" "${args[@]}" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "secret ${ns}/${name}"
}

# The `openai` Secret holds every LLM key: pods load it with envFrom, so an optional Claude key needs no manifest change.
llm_keys=("OPENAI_API_KEY=${OPENAI_API_KEY}")
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then llm_keys+=("ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"); fi

otlp_headers="Authorization=Bearer ${DASH0_AUTH_TOKEN}"
for ns in team-rapport org-acme org-bluefin; do
  apply_secret "$ns" openai "${llm_keys[@]}"
  apply_secret "$ns" dash0-otlp "OTEL_EXPORTER_OTLP_ENDPOINT=${DASH0_OTLP_ENDPOINT}" "OTEL_EXPORTER_OTLP_HEADERS=${otlp_headers}"
done
# Optional website monitoring for the gateway's page. Its token reaches every browser, so it must be its own
# ingest-only token: refuse the backend token here.
if [[ -n "${DASH0_RUM_AUTH_TOKEN:-}" ]]; then
  if [[ "${DASH0_RUM_AUTH_TOKEN}" == "${DASH0_AUTH_TOKEN}" ]]; then
    echo "DASH0_RUM_AUTH_TOKEN must be a separate ingest-only token, not DASH0_AUTH_TOKEN"; exit 1
  fi
  rum=("DASH0_RUM_ENDPOINT=${DASH0_RUM_ENDPOINT:-${DASH0_OTLP_ENDPOINT}}" "DASH0_RUM_AUTH_TOKEN=${DASH0_RUM_AUTH_TOKEN}")
  if [[ -n "${DASH0_RUM_DATASET:-}" ]]; then rum+=("DASH0_RUM_DATASET=${DASH0_RUM_DATASET}"); fi
  apply_secret team-rapport dash0-rum "${rum[@]}"
fi
apply_secret org-acme es-briefer "ES_URL=${ES_URL}" "ES_API_KEY=${ES_BRIEFER_KEY_ACME}"
apply_secret org-acme es-delegate "ES_URL=${ES_URL}" "ES_API_KEY=${ES_DELEGATE_KEY_ACME}"
apply_secret org-bluefin es-briefer "ES_URL=${ES_URL}" "ES_API_KEY=${ES_BRIEFER_KEY_BLUEFIN}"
apply_secret org-bluefin es-delegate "ES_URL=${ES_URL}" "ES_API_KEY=${ES_DELEGATE_KEY_BLUEFIN}"
