#!/usr/bin/env bash
# Creates the Rapport index template and the five indices on Elastic Cloud.
# Needs ES_URL and ES_ADMIN_API_KEY (export them or put them in .env, which is gitignored).
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
if [[ -f .env ]]; then set -a; source .env; set +a; fi
: "${ES_URL:?set ES_URL (Elasticsearch endpoint)}"
: "${ES_ADMIN_API_KEY:?set ES_ADMIN_API_KEY (laptop-only admin key)}"

es() { curl -sS --fail-with-body -H "Authorization: ApiKey ${ES_ADMIN_API_KEY}" -H "Content-Type: application/json" "$@"; }

echo "Connected to: $(es "${ES_URL}/" | jq -r '.cluster_name // .name // "elasticsearch"')"

# semantic_text needs one inference endpoint for ALL rapport indices (they are searched together).
if [[ -z "${ES_INFERENCE_ID:-}" ]]; then
  ids=$(es "${ES_URL}/_inference/_all" | jq -r '.. | .inference_id? // empty')
  for candidate in .jina-embeddings-v5-text-small .elser-2-elastic .elser-2-elasticsearch; do
    if grep -qx -- "$candidate" <<<"$ids"; then ES_INFERENCE_ID="$candidate"; break; fi
  done
fi
: "${ES_INFERENCE_ID:?no known default inference endpoint; pick one from GET _inference/_all and export ES_INFERENCE_ID}"
echo "Inference endpoint: ${ES_INFERENCE_ID}"

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
sed "s/__INFERENCE_ID__/${ES_INFERENCE_ID}/" deploy/elastic/index-template.json >"$tmp"
es -X PUT "${ES_URL}/_index_template/rapport-memory" -d @"$tmp" >/dev/null
echo "Index template rapport-memory: OK"

for idx in rapport-conference rapport-acme-shareable rapport-acme-internal rapport-bluefin-shareable rapport-bluefin-internal; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -I -H "Authorization: ApiKey ${ES_ADMIN_API_KEY}" "${ES_URL}/${idx}")
  if [[ "$code" == "200" ]]; then
    echo "exists:  ${idx}"
  else
    es -X PUT "${ES_URL}/${idx}" >/dev/null
    echo "created: ${idx}"
  fi
done

echo
echo "Next: create the 4 restricted API keys in Kibana with deploy/elastic/role-descriptors/*.json"
echo "(docs/SETUP.md, step 3), put them in .env, then run: make secrets"
