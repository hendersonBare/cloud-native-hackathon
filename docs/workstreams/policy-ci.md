# Workstream: policy-ci (OPA policy, OPA deployment and CI)

**Mission.** Each company's rules for what may leave the building, enforced by OPA, plus a CI that Gitar can use to diagnose failures. You're the smallest workstream, so **merge first** (target 12:45 PM).

**You own:**

- `policy/`: `rapport.rego`, `rapport_test.rego`, `data/acme.json` and `data/bluefin.json`.
- `deploy/policy/`: an `opa` Deployment and Service in **each** org namespace.
- `.github/`.

**Read first:** `AGENTS.md`, SPEC §6, and `PolicyInput` and `PolicyDecision` in `rapport_common/models.py`.

## Build (P0)

1. **`policy/rapport.rego`:**
   - `package rapport`, written in Rego v1 (OPA 1.x syntax: `if` and `contains`).
   - It exposes `decision := {"decision", "rule_id", "reason"}`, evaluating the SPEC §6 rules **in order, first match wins**.
   - It reads company data from `data.org`.
2. **`policy/rapport_test.rego`:** every test vector in SPEC §6, plus one where Bluefin answers Acme.
3. **`policy/data/<org>.json`** exactly as in SPEC §6. `make policy` turns these into the `opa-policy` ConfigMap, with keys `rapport.rego` and `data.json`.
4. **`deploy/policy/`:** for each org namespace:
   - A Deployment `opa` with image `openpolicyagent/opa` pinned to a current release tag from Docker Hub, and args `run --server --addr=0.0.0.0:8181 /policy`.
   - The ConfigMap `opa-policy` mounted at `/policy`.
   - A readiness probe of `GET /health` on port 8181 and the label `rapport.dev/role: opa`.
   - A Service `opa` on port 8181.
5. **CI:** keep `.github/workflows/ci.yml` under 2 minutes; add uv caching if it's easy. Make failure output readable, because Gitar diagnoses CI failures from it.

## Done when

- `opa test policy -v` passes locally and in CI.
- After `make policy deploy`:

  ```bash
  kubectl -n org-acme port-forward svc/opa 8181:8181
  curl -s localhost:8181/v1/data/rapport/decision -d '{"input": {...pricing vector...}}'
  ```

  returns `deny` / `pricing_needs_approval`.

## Gotchas

- OPA 1.x binds to localhost by default, so you need `--addr=0.0.0.0:8181`.
- `data.json` at the bundle root maps to `data`, so `{"org": {...}}` becomes `data.org`.

**Out of scope:** Gatekeeper and admission control, and policy UIs.
