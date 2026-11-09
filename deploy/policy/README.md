# Rapport policy (OPA, one instance per company)

What may leave a company's building. SPEC section 6 is the rule table; `rapport.rego` implements
it as one `else` chain, so the first matching rule wins and anything unmatched is denied.

| File | What it is |
|---|---|
| `rapport.rego` | `package rapport`, exposes `decision` = `{decision, rule_id, reason}` |
| `data/acme/data.json`, `data/bluefin/data.json` | Company data, becomes `data.org` |
| `acme/opa.yaml`, `bluefin/opa.yaml` | Deployment `opa` and Service `opa` (port 8181) per org namespace |
| `kustomization.yaml` | Generates one `opa-policy` ConfigMap per org (keys `rapport.rego`, `data.json`) |
| `../../policy/rapport_test.rego` | Rego tests: every SPEC section 6 vector, Bluefin answering Acme, missing data |

Missing or partial company data never allows anything: absent `nda_with` and `pricing_approved_for`
count as empty lists, and an unknown `share_level` ends in `default_deny`.

## Test

```bash
opa test deploy/policy policy -v     # also run by `make test` and CI
kubectl kustomize deploy/policy      # the two ConfigMaps, Deployments and Services
```

Why the odd directory layout: `opa test deploy/policy` loads every `.json` and `.yaml` file under
`deploy/policy` as data, namespaced by directory. Two files in one directory that share a top-level
key (`org`, `apiVersion`) fail with a merge conflict, so each org has its own directory, and the
tests pass `data.org` with `with`.

## Run both OPAs locally (SPEC layer L2)

Load the Rego plus ONE org's data file; a file given on the command line lands at the data root, so
`{"org": ...}` becomes `data.org`. OPA 1.x binds to localhost unless told otherwise, which is fine
for local use.

```bash
opa run --server --addr=127.0.0.1:8181 deploy/policy/rapport.rego deploy/policy/data/acme/data.json
opa run --server --addr=127.0.0.1:8182 deploy/policy/rapport.rego deploy/policy/data/bluefin/data.json
```

Then point the delegate at them: `OPA_URL_ACME=http://localhost:8181 OPA_URL_BLUEFIN=http://localhost:8182`
(`names.opa_url(org)` reads these).

### The pricing vector (Acme offers its pricing overview to Bluefin)

```bash
curl -s localhost:8181/v1/data/rapport/decision -d '{"input": {
  "action": "offer", "org_id": "acme", "self_persona_id": "acme.ava",
  "counterparty_org_id": "bluefin", "encounter_id": "enc-test0001",
  "item": {"item_id": "acme-doc-0004", "kind": "document", "share_level": "partner", "tags": ["pricing"]}}}'
```

```json
{"result":{"decision":"deny","reason":"Pricing needs approval for this counterparty.","rule_id":"pricing_needs_approval"}}
```

Change `tags` to `["security"]` (`acme-doc-0003`) and it returns `allow` / `partner_with_nda`.
Bluefin answering Acme goes to port 8182 with `org_id: bluefin`, `counterparty_org_id: acme`.

## On the cluster

Argo CD syncs `deploy/` on every merge to `main`, so there is no separate policy deploy step. To
check a live OPA from your laptop (needs the team kubeconfig):

```bash
kubectl -n org-acme port-forward svc/opa 8181:8181
```

and use the same curl. The image is pinned (`openpolicyagent/opa:1.22.2`); the container runs as UID
10001, read-only root filesystem, with requests and limits from `names.RESOURCES_SMALL`.
