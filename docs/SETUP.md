# Setup guide: Kubernetes, Elasticsearch, Dash0, OpenAI, Radar and Gitar

**Time:** about 45 minutes. Do it while the subagents build, since nothing here blocks them.

**Target:** a kind cluster on your Mac, Elastic Cloud Serverless, Dash0, OpenAI, Radar on your laptop and Gitar on GitHub.

**Secrets rule:** every key goes in `.env` (gitignored) or a Kubernetes Secret. Never put one in code, a PR or a chat.

| Step | What | Minutes |
|---|---|---|
| 1 | Tools | 5 |
| 2 | Repo, kit, Gitar | 5 |
| 3 | Elastic Cloud | 10 |
| 4 | Dash0 | 5 |
| 5 | Kubernetes (kind) | 5 |
| 6 | OpenAI and Secrets | 2 |
| 7 | Radar | 5 |
| 8 | Build, deploy, seed (after the PRs merge) | 10 |

---

## 1. Tools (macOS)

```bash
brew install kind kubectl helm jq uv gh opa kubectl-radar
gh auth login
```

You also need **Docker Desktop or OrbStack** running. In Docker Desktop, go to Settings → Resources and give it at least 6 GB of memory.

Check everything is in place:

```bash
docker info >/dev/null && kind version && kubectl version --client && uv --version && opa version
```

## 2. Repo, kit and Gitar

```bash
gh repo create rapport --public --clone && cd rapport   # skip if you already created it
unzip -o ~/Downloads/rapport-kit.zip -d ..              # the kit unpacks into ./rapport
cp .env.example .env                                    # fill this in during steps 3, 4 and 6
uv sync && make test                                    # should print: 9 passed
git add -A && git commit -m "Rapport kit: contracts, spec, setup" && git push -u origin main
```

**Gitar.** Do this before any feature code is pushed. Gitar (Sonar's code review agent) reviews pull requests, so anything pushed straight to `main` never gets a review.

1. The repo owner signs in at [app.gitar.ai](https://app.gitar.ai) with GitHub, clicks **Connect GitHub** and picks this repo. Installing a GitHub App needs admin rights, so a collaborator with write access can't do it.
2. Nothing to paste into Gitar's settings. On every PR Gitar reads `AGENTS.md` and `CLAUDE.md`, the review instructions in `.gitar/review/*.md` (ownership, contracts, tests) and the rules in `.gitar/rules/*.md` (`title`, `description`, `when` and `actions` frontmatter, the [gitarcode/rules](https://github.com/gitarcode/rules) format).
3. Custom rules and auto-apply are Pro features. A new Gitar organization gets a 14-day Pro trial.
4. Gitar reads GitHub Actions results with no extra setup. On a PR, comment `gitar auto-apply:on` to let it push fixes, or ask in plain words (`Gitar fix CI`). `.gitar/config/apply.md` limits what it may commit; Gitar reads that file from `main`.
5. Check that Gitar comments on the first PR. The Sonar track wants features landing through Gitar-reviewed PRs, not one PR at the end.

**Lock `main`.** The repo owner runs this once from the repo folder. It requires a pull request to change `main` and blocks force-pushes and deleting it. Required approvals stay at 0 so the integrator can merge PRs opened from their own account. GitHub Actions (app ID 15368) is on the bypass list because `build-and-deploy` pushes its `deploy: <sha> [skip ci]` commit straight to `main`.

```bash
gh api -X POST 'repos/{owner}/{repo}/rulesets' --input - <<'EOF'
{
  "name": "protect-main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false
    }}
  ],
  "bypass_actors": [{"actor_id": 15368, "actor_type": "Integration", "bypass_mode": "always"}]
}
EOF
```

Then test the bypass straight away: run `gh workflow run build-and-deploy`, let it finish, and check that `gh run list -w build-and-deploy -L 1` shows success and that a new `deploy:` commit landed on `main`. Don't wait for a merge to test it, because merges that only change `.md` files don't start that workflow. If the deploy push is rejected, edit the ruleset under Settings → Rules → Rulesets.

## 3. Elastic Cloud (Serverless Elasticsearch)

**a. Create the project.** In Elastic Cloud (trial), create a **Serverless Elasticsearch project** named `rapport`. Then:

1. From the project's connection details, copy the **Elasticsearch endpoint** into `.env` as `ES_URL`.
2. Create an **unrestricted API key** and put it in `.env` as `ES_ADMIN_API_KEY`. It stays on your laptop and is only used for setup and seeding.

**b. Index template and indices:**

```bash
make elastic
```

This picks the default `semantic_text` inference endpoint and creates the `rapport-memory` template plus these 5 indices:

- `rapport-conference`
- `rapport-acme-shareable` and `rapport-acme-internal`
- `rapport-bluefin-shareable` and `rapport-bluefin-internal`

The script tries `.jina-embeddings-v5-text-small` (the Serverless default), then `.elser-2-elastic`, then `.elser-2-elasticsearch`. If none exists, run `GET _inference/_all` in Dev Tools, pick one, and set `ES_INFERENCE_ID` in `.env`.

**c. Four restricted API keys.** These keys are the security boundary. Create them in the Kibana UI, because an API key can't mint restricted keys through the API.

1. Kibana → search "API keys" → **Create API key**.
2. Name it, turn on **Control security privileges**, paste the JSON from the file in the table, and create it.
3. Copy the **encoded** value into `.env`.

| Name | JSON file | `.env` variable |
|---|---|---|
| `rapport-briefer-acme` | `deploy/elastic/role-descriptors/briefer-acme.json` | `ES_BRIEFER_KEY_ACME` |
| `rapport-briefer-bluefin` | `deploy/elastic/role-descriptors/briefer-bluefin.json` | `ES_BRIEFER_KEY_BLUEFIN` |
| `rapport-delegate-acme` | `deploy/elastic/role-descriptors/delegate-acme.json` | `ES_DELEGATE_KEY_ACME` |
| `rapport-delegate-bluefin` | `deploy/elastic/role-descriptors/delegate-bluefin.json` | `ES_DELEGATE_KEY_BLUEFIN` |

If Kibana rejects `monitor_inference`, delete the `"cluster"` line from that JSON and try again.

**d. Prove the boundary.** Screenshot this for the judges:

```bash
set -a; source .env; set +a
curl -s -o /dev/null -w 'shareable: %{http_code}\n' -H "Authorization: ApiKey $ES_DELEGATE_KEY_ACME" "$ES_URL/rapport-acme-shareable/_search"   # 200
curl -s -o /dev/null -w 'internal:  %{http_code}\n' -H "Authorization: ApiKey $ES_DELEGATE_KEY_ACME" "$ES_URL/rapport-acme-internal/_search"    # 403
```

## 4. Dash0

**a. Get your details.** In Dash0, find your **OTLP over HTTP ingress endpoint**, which looks like `https://ingress.<region>.aws.dash0.com:4318`. Create an **auth token**. Put them in `.env` as `DASH0_OTLP_ENDPOINT` and `DASH0_AUTH_TOKEN`.

**b. Send a test span from your laptop:**

```bash
set -a; source .env; set +a
OTEL_EXPORTER_OTLP_ENDPOINT="$DASH0_OTLP_ENDPOINT" OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer $DASH0_AUTH_TOKEN" \
PYTHONPATH=src uv run python -c "
from rapport_common.telemetry import init_telemetry, tracer, shutdown_telemetry
init_telemetry('rapport-setup-check')
with tracer().start_as_current_span('setup.check'):
    pass
shutdown_telemetry(); print('sent')"
```

In Dash0's tracing view, look for the service `rapport-setup-check`. If you get a 401, check the token. If it still fails, try `Authorization=Bearer%20<token>` in `OTEL_EXPORTER_OTLP_HEADERS`.

**c. Optional, but judges reward it:**

- Connect **Dash0's MCP server** to Claude Code ([Dash0 docs: MCP](https://www.dash0.com/docs/dash0/ai/mcp)) so you and the subagents can query traces while debugging.
- **Agent0** is in the Dash0 UI. Use it on a real issue you hit today and screenshot the answer.
- **Website monitoring (RUM)** for the web page uses Dash0's web SDK ([setup docs](https://www.dash0.com/docs/dash0/miscellaneous/tooling/web-sdk/setup)). This is the web workstream's P1.

## 5. Kubernetes (kind)

```bash
make cluster
```

This creates the single-node cluster `rapport` and applies the namespaces, the baseline NetworkPolicies and the `Encounter` CRD. It then **proves NetworkPolicy is enforced**: a pod in `org-acme` must not reach a pod in `org-bluefin`. Expect this output:

```
OK: NetworkPolicy enforced (same company allowed, other company blocked).
```

Check the CRD is installed:

```bash
kubectl get crd encounters.rapport.dev
```

The gateway will be at **http://localhost:8080**, via NodePort 30080 mapped in `deploy/kind/kind-config.yaml`.

### If NetworkPolicy is not enforced

The check fails when the cluster's network plugin ignores NetworkPolicy. Recreate the cluster with Calico:

1. Delete the cluster yourself; this destroys only the local cluster: `kind delete cluster --name rapport`.
2. In `deploy/kind/kind-config.yaml`, uncomment the `networking:` block (`disableDefaultCNI: true`).
3. Create the cluster: `kind create cluster --config deploy/kind/kind-config.yaml`.
4. Apply the current Calico manifest from Calico's "Quickstart for Calico on kind" docs.
5. Wait for it: `kubectl -n kube-system wait --for=condition=Ready pods -l k8s-app=calico-node --timeout=180s`.
6. Run `make cluster` again; it reuses the cluster and repeats the check.

## 6. OpenAI and Kubernetes Secrets

Put your OpenAI key (from the $50 credits) in `.env` as `OPENAI_API_KEY`. Keep `RAPPORT_LLM_MODEL=gpt-6-luna` (OpenAI's most efficient model for high-volume tasks, $0.10 in and $0.50 out per 1M tokens) and `RAPPORT_LLM_REASONING_EFFORT=low`. `gpt-5-mini` is marked deprecated. Then:

```bash
make secrets
```

This creates `openai` and `dash0-otlp` in all three namespaces, and `es-briefer` and `es-delegate` in each org namespace. Values are never printed.

## 7. Radar

```bash
kubectl radar      # or: make radar
```

This opens Radar's UI (http://localhost:9280) on your current kube context, `kind-rapport`.

- **Radar MCP:** Radar has a built-in MCP server. Connect it to Claude Code following Radar's MCP guide (`docs/mcp.md` in [skyhook-io/radar](https://github.com/skyhook-io/radar)) so agents can read cluster state while you debug.
- **AI investigations:** the Radar track wants you to use Radar's AI investigations on a real issue. Use the Radar Cloud account the hackathon asked you to create; [radarhq.io/docs](https://radarhq.io/docs) explains how to connect a cluster, and the Radar team at the venue can help.
- **What to show:** the `org-acme` and `org-bluefin` namespaces, the `delegate-enc-…` Jobs appearing per encounter, and the NetworkPolicies.

## 8. Build, deploy and seed (once the PRs are merged)

```bash
make image         # docker build rapport:dev + kind load
make deploy        # OPA policy ConfigMaps + base + CRD + policy/operator/briefer/gateway manifests
make seed          # synthetic demo data into Elasticsearch (admin key, from your laptop)
make status        # encounters and pods
open http://localhost:8080
```

After a merge, `make reload` rebuilds the image, loads it into kind and restarts all Rapport Deployments. Delegate Jobs pick up the new image on the next encounter.

### Smoke test, in demo order

1. Both phones load, Ava on the left and Bo on the right.
2. On Ava's **My agent** tab, upload `seed/ava-cv-synthetic.md`. The profile card appears, with no email or phone number in it.
3. Ava connects to Bo, and Bo accepts. Running `kubectl get enc` shows `Running`, and two `delegate-enc-…` pods appear in Radar.
4. Private briefs appear on both phones within about 5 s. Bo's is in Spanish.
5. The swarm panel shows rounds 1–3. With **Malicious responder** on, a red `pricing_needs_approval` chip appears.
6. Shared briefs appear and the encounter completes. Ava asks "What did we promise Bluefin?" and gets an answer with citations.
7. In Dash0, one trace covers `connect.accept` → `exchange.run` (both pods) → `policy.check`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ErrImageNeverPull` or `ImagePullBackOff` on `rapport:dev` | Run `make image` (it loads the image into kind). Manifests need `imagePullPolicy: IfNotPresent`. |
| `CreateContainerConfigError` | A Secret is missing in that namespace. Run `make secrets`. |
| ES 401 | Use the key's **encoded** value. ES 403 on an internal index with a delegate key is expected. |
| Semantic search errors | Inference endpoint mismatch. Set `ES_INFERENCE_ID` and re-run `make elastic` on fresh indices. |
| Nothing in Dash0 | Check the Secret has both keys: `kubectl -n org-acme get secret dash0-otlp -o json \| jq '.data \| keys'`. Delegate spans also need `shutdown_telemetry()` before exit. |
| Delegates can't reach each other | The operator's per-encounter NetworkPolicy labels don't match SPEC §4.4. Compare with `kubectl -n org-bluefin get netpol -o yaml`. |
| Port 8080 already in use on the Mac | Stop the other process, or change `hostPort` in the kind config and recreate the cluster. |
| Everything is broken at 3:30 PM | Run the gateway with `RAPPORT_MOCK=1` and open `/?mock=1` for the UI. Show real pods, ES and Dash0 alongside, and tell the judges. |

## After the hackathon (you run these)

- Delete the local cluster: `kind delete cluster --name rapport`.
- Revoke the five Elastic API keys and the Dash0 token.
- Delete the Elastic project if you don't need it.
- Rotate your OpenAI key if it was ever pasted anywhere.
