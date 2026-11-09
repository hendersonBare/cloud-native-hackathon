#!/usr/bin/env bash
# Creates or updates the Kubernetes Secrets from your local .env (gitignored). Idempotent.
# Values are never printed.
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

otlp_headers="Authorization=Bearer ${DASH0_AUTH_TOKEN}"
for ns in rapport-system org-acme org-bluefin; do
  apply_secret "$ns" openai "OPENAI_API_KEY=${OPENAI_API_KEY}"
  apply_secret "$ns" dash0-otlp "OTEL_EXPORTER_OTLP_ENDPOINT=${DASH0_OTLP_ENDPOINT}" "OTEL_EXPORTER_OTLP_HEADERS=${otlp_headers}"
done
apply_secret org-acme es-briefer "ES_URL=${ES_URL}" "ES_API_KEY=${ES_BRIEFER_KEY_ACME}"
apply_secret org-acme es-delegate "ES_URL=${ES_URL}" "ES_API_KEY=${ES_DELEGATE_KEY_ACME}"
apply_secret org-bluefin es-briefer "ES_URL=${ES_URL}" "ES_API_KEY=${ES_BRIEFER_KEY_BLUEFIN}"
apply_secret org-bluefin es-delegate "ES_URL=${ES_URL}" "ES_API_KEY=${ES_DELEGATE_KEY_BLUEFIN}"
