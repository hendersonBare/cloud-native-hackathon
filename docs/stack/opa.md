# Open Policy Agent

## What we use it for

OPA decides what may leave a company. One OPA runs in each company namespace (`org-acme`, `org-bluefin`), and a delegate asks its own company's OPA about every item before it goes out: each offer in round 2 and each answer in round 3. The model never decides what leaves; it can only propose known item IDs, and OPA has the last word. The policy is a short ordered rule chain that ends in `default_deny`, the delegate treats an unreachable or slow OPA as a deny, and every decision, allow or deny, is reported three ways: an event on the stage, a `policy.check` span and a `rapport.policy.decisions` metric. OPA is one of three independent walls, alongside scoped Elasticsearch keys and per-encounter NetworkPolicies.

## Where it lives

| Path | What it is |
|---|---|
| `deploy/policy/rapport.rego` | The policy (Rego v1, `package rapport`), exposing `decision` = `{decision, rule_id, reason}` |
| `deploy/policy/data/acme/data.json`, `deploy/policy/data/bluefin/data.json` | Company data, loaded as `data.org` (`nda_with`, `pricing_approved_for`) |
| `deploy/policy/acme/opa.yaml`, `deploy/policy/bluefin/opa.yaml` | Deployment and Service `opa` (port 8181) in each company namespace |
| `deploy/policy/kustomization.yaml` | Generates one `opa-policy` ConfigMap per company (keys `rapport.rego`, `data.json`) |
| `deploy/policy/README.md` | How to run both OPAs locally and query them |
| `policy/rapport_test.rego` | 21 Rego tests |
| `src/rapport_delegate/policy.py` | `OpaPolicy` (HTTP client, fails closed) and `FakePolicy` (the SPEC §6 table for tests) |
| `src/rapport_delegate/agent.py` | `check()`: builds the `PolicyInput`, calls OPA, records the span, metric and event |
| `src/rapport_delegate/instruments.py` | The `rapport.policy.decisions` counter |
| `src/rapport_gateway/encounters.py` | Validates and routes `policy_decision` events from delegates |
| `web/swarm/model.js`, `web/swarm/view.js` | Shows each decision on the swarm panel, denials in red |
| `tests/delegate/test_delegate_policy.py` | Client tests: the rule table, fail-closed cases, the timeout |
| `docs/SPEC.md` §6 | The rule table and test vectors |

## How it works here

- **The call.** `POST {names.opa_url(org)}/v1/data/rapport/decision` with `{"input": PolicyInput}`; OPA replies `{"result": PolicyDecision}`. The input carries the action (`offer` or `answer`), the org, the delegate's own persona, the counterparty org, the encounter ID and the item's ID, kind, share level, tags and owner, never its text (`src/rapport_delegate/agent.py:141-146`).
- **The rules, first match wins** (`deploy/policy/rapport.rego:50-92`, one `else` chain):

  | # | rule_id | When | Decision |
  |---|---|---|---|
  | 1 | `internal_never_leaves` | `share_level == "internal"` | deny |
  | 2 | `profile_owner_only` | a profile whose owner isn't the delegate's own persona | deny |
  | 3 | `pricing_needs_approval` | tag `pricing` and the counterparty not in `pricing_approved_for` | deny |
  | 4 | `partner_needs_nda` | `share_level == "partner"` and the counterparty not in `nda_with` | deny |
  | 5 | `public_ok` | `share_level == "public"` | allow |
  | 6 | `partner_with_nda` | `share_level == "partner"` and the counterparty in `nda_with` | allow |
  | 7 | `default_deny` | anything else | deny |

- **Missing data never allows.** `data.org` defaults to `{}`, and absent `nda_with` or `pricing_approved_for` count as empty lists, so only rules that need no company data can allow; an unknown `share_level` ends in `default_deny` (`deploy/policy/rapport.rego:13-29`). The shipped data: Acme has an NDA with Bluefin and Bluefin with Acme, and neither has pricing approved for anyone.
- **Fail closed.** `OpaPolicy.decide` wraps the call in a 2 s timeout. Any HTTP error, timeout, non-JSON body, missing `result` or result that fails `PolicyDecision` validation returns `deny · opa_unavailable` (`src/rapport_delegate/policy.py:17-48`). Seven failure shapes and the timeout are tested in `tests/delegate/test_delegate_policy.py`.
- **Only allowed items go out.** In round 2 an offer is added only when the decision is `allow` (`src/rapport_delegate/agent.py:188-192`). In round 3, a denied answer becomes `declined · policy_deny` with the rule ID, and the asking side sees only that (`agent.py:239-245`).
- **One decision, three signals.** `Agent.check` (`src/rapport_delegate/agent.py:139-158`) opens a `policy.check` span with the action, item ID, decision and rule ID; adds 1 to `rapport.policy.decisions` with `decision`, `rule_id` and `org_id`; and sends a `policy_decision` event (org, action, item ID and title, decision, rule ID) to the gateway's cluster-only `/internal/events`. The gateway rejects a `policy_decision` whose `org_id` isn't the reporting delegate's party (`src/rapport_gateway/encounters.py:155-157`) and forwards the rest to the swarm stream (`:182-183`). The swarm panel renders it as text, with `is-deny` styling for denials (`web/swarm/model.js:147-156`). So the red line on the stage, the metric and the span are the same fact.
- **Deployment.** Each OPA runs the pinned `openpolicyagent/opa:1.22.2` image with `--addr=0.0.0.0:8181` and `--ignore=.*`, which skips the hidden `..data` entries kubelet creates in a ConfigMap mount. It runs as UID 10001 with a read-only root filesystem and requests and limits from `names.RESOURCES_SMALL`. kustomize adds a content hash to the ConfigMap name, so a policy change rolls the pod.
- **Tests in CI.** `opa fmt`, `opa check --strict` and `opa test deploy/policy policy -v` run on every PR. The 21 tests cover every SPEC §6 vector, Bluefin answering Acme, the rule order (pricing beats `public_ok`, internal beats everything), missing company data, empty input and the shipped data files.

## What a reviewer should check in a PR

- Every item a delegate sends to another company goes through `Agent.check()` first; nothing is sent on a deny.
- The rule chain stays ordered and ends in `default_deny`; missing or partial data never allows.
- Any OPA error, timeout or malformed result is a deny with `rule_id: opa_unavailable`; the timeout stays at 2 s or less.
- Policy input carries IDs, kind, share level, tags and owner; never record text.
- Spans and metrics carry the action, item ID, decision and rule ID; never memory text, asks or briefs.
- Every decision, allow or deny, is still reported as a `policy_decision` event, counted and traced.
- A new rule or data change comes with `opa test` cases in `policy/rapport_test.rego`, and SPEC §6 is updated to match.
- Changes under `policy/` or `deploy/policy/` have a "Security review needed" section; Gitar's auto-apply does not edit them (`.gitar/config/apply.md`).
- The OPA containers keep a pinned image, requests and limits, and the restricted `securityContext`.

## Evidence

- [PR #5](https://github.com/hendersonBare/cloud-native-hackathon/pull/5) (policy-ci): the policy, its tests, per-company OPA deployments and CI. Gitar found that OPA would never get ready because kubelet's hidden `..data` and `..<timestamp>` entries made it load `rapport.rego` three times; fixed in `a3957b7` with `--ignore=.*` (LOG 13:55 MST).
- [PR #9](https://github.com/hendersonBare/cloud-native-hackathon/pull/9) (delegate): the OPA client, fail-closed handling and malicious mode.
- LOG 14:03 MST, local L2 exchange with two OPA servers and two delegate processes: Bo's injected pricing ask was denied with `pricing_needs_approval`, and `acme-doc-0008` and the internal account note never left Acme (20 delegate events).
- LOG 14:16 MST, full local stack, encounter `enc-b3293785`: the red `pricing_needs_approval` deny on the swarm, and no private brief on the swarm stream.
- `opa test deploy/policy policy -v` runs 21 tests on every PR (`.github/workflows/ci.yml`, step 5).
