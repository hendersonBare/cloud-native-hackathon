# Kubernetes, Argo CD and Radar

## What we use it for

Kubernetes isn't only where Rapport is hosted; it's how two agents meet. Each meeting is an `Encounter` custom resource. A kopf operator turns it into a delegate Job in each company's namespace, plus the responder's Service and a NetworkPolicy that admits only this encounter's initiator, all owned by the Encounter and garbage-collected with it. The app runs in a team vcluster: the gateway and operator in `team-rapport`, and each company's briefer, OPA and delegate pods in `org-acme` and `org-bluefin`. Deploys are GitOps: merging to `main` builds the image to GHCR and Argo CD syncs `deploy/`. Radar Cloud is how we watched and debugged the cluster: its MCP server from Claude Code, a Radar issue on a crash-looping Deployment, and an AI investigation of that crash loop.

## Where it lives

| Path | What it is |
|---|---|
| `deploy/crds/encounter-crd.yaml` | CRD `encounters.rapport.dev`, version `v1alpha1`, cluster-scoped so it can own namespaced children in both company namespaces (a contract) |
| `src/rapport_operator/` | The kopf operator: handlers, manifest builders, status and TTL logic |
| `deploy/operator/` | Operator Deployment, ServiceAccount, RBAC and a sample Encounter |
| `src/rapport_gateway/k8s.py` | Encounter creation and the delegate pod watch |
| `deploy/gateway/rbac.yaml` | Gateway may create and watch Encounters, and only get, list and watch pods in `org-acme` and `org-bluefin` |
| `deploy/base/namespaces.yaml`, `deploy/base/network-policies.yaml` | Company namespaces; default-deny ingress plus same-namespace and gateway-to-briefer allows |
| `deploy/kustomization.yaml` | What Argo CD applies; the Action sets the `app` image tag here |
| `argocd/application.yaml` | Argo CD Application `app` in `team-rapport`, automated sync with `prune` and `selfHeal` |
| `.github/workflows/deploy.yaml` | build-and-deploy: build and push the image to GHCR, then commit `deploy: <sha> [skip ci]` |
| `.agents/skills/` | The `ship`, `debug-failure`, `canary-release`, `get-started` and `demo-story` procedures that drive Radar's MCP tools |
| `AGENTS.md` | How agents use Radar here: pass the team cluster on every call, fix Argo CD-owned resources in git |

## How it works here

- **Encounter to pods.** The gateway creates a cluster-scoped Encounter on accept, with the trace context as the `rapport.dev/traceparent` annotation (`src/rapport_gateway/k8s.py:34-36`). The operator's `@kopf.on.create` handler (`src/rapport_operator/handlers.py:56-69`) builds a Job `delegate-<encounter>` in each party's namespace, a Service in the responder's namespace, and a NetworkPolicy (`src/rapport_operator/builders.py:122-210`). Every child carries an `ownerReference` to the Encounter with `controller: true` and `blockOwnerDeletion: true` (`builders.py:62-73`), so deleting the Encounter garbage-collects both namespaces.
- **Delegate Jobs.** Each Job has `backoffLimit: 0`, `activeDeadlineSeconds: 120` and `ttlSecondsAfterFinished: 600` (`builders.py:21-23`), `automountServiceAccountToken: false`, image `app`, requests and limits from `names.RESOURCES_DELEGATE`, `names.SECURITY_CONTEXT`, and the `openai`, `dash0-otlp` and `es-delegate` Secrets mounted as optional.
- **Per-encounter NetworkPolicy.** The policy selects this encounter's responder pod and admits ingress only from a pod that has this encounter's initiator labels and is in the initiator's namespace. The `namespaceSelector` and `podSelector` sit in one `from` entry so they are ANDed; two entries would admit every pod in the initiator namespace (`builders.py:177-210`). Each company namespace also denies ingress by default and admits only its own pods and the gateway's pods to the briefer (`deploy/base/network-policies.yaml`).
- **Status and clean-up.** A kopf event handler on delegate Jobs syncs the Encounter's phase (`Pending`, `Running`, `Completed`, `Failed`), and a 15 s timer deletes an Encounter once `spec.ttlSeconds` (60 to 3600, default 600) have passed (`handlers.py:72-83`, `src/rapport_operator/status.py:19`). Rejected Encounters are marked `Failed` and are TTL-deleted too.
- **Operator identity.** kopf runs cluster-wide and standalone with an explicit identity (the pod name, else the hostname) and a liveness endpoint (`src/rapport_operator/__main__.py:22-43`). Without that identity kopf calls `getpass.getuser()`, which fails for UID 10001 with no passwd entry; this was the crash loop Radar investigated.
- **Pod watch.** The gateway watches pods labelled `rapport.dev/role=delegate` in both company namespaces (`src/rapport_gateway/k8s.py:160-166`). The watch feeds the `pod_status` events on the swarm panel, and the gateway uses the pod IPs to check that an `/internal/events` report comes from a delegate pod of that encounter.
- **GitOps.** On a push to `main`, `.github/workflows/deploy.yaml` builds the image, pushes it to `ghcr.io/hendersonbare/cloud-native-hackathon:<sha>`, sets that tag in `deploy/kustomization.yaml` and commits `deploy: <sha> [skip ci]`. Argo CD Application `app` (`argocd/application.yaml`) syncs `deploy/` with `prune` and `selfHeal`, so changes to app resources go through git, not through the cluster. The gateway's `/healthz` reports the running build's version.
- **Shared budget.** The vcluster has one budget for every namespace (2 CPU and 4 GiB of requests). Every container sets requests and limits from `rapport_common.names.RESOURCES_*` so delegate pods can come and go without leaving a pod `Pending`.
- **Radar.** Claude Code talks to Radar Cloud's MCP server, passing the team cluster on every call (AGENTS.md). We used `list_clusters`, `fleet_list_gitops` and `fleet_search` while building, a Radar issue (critical, CrashLoopBackOff) that flagged the operator's crash loop, and a Radar AI investigation on the failing Deployment.

## What a reviewer should check in a PR

- Every manifest uses image `app`, `imagePullPolicy: IfNotPresent`, an explicit `namespace`, labels `app.kubernetes.io/part-of: rapport` and `rapport.dev/role`, requests and limits from `names.RESOURCES_*`, and `names.SECURITY_CONTEXT`, and is listed in `deploy/<component>/kustomization.yaml`. A container without limits is a blocking finding.
- Every child the operator creates carries an `ownerReference` to its Encounter, so deleting the Encounter cleans up both namespaces.
- The per-encounter NetworkPolicy keeps `namespaceSelector` and `podSelector` in one `from` entry, selecting this encounter's initiator only.
- Delegate pods keep `automountServiceAccountToken: false`, an `activeDeadlineSeconds`, a `ttlSecondsAfterFinished`, and Secrets mounted as optional.
- RBAC grants stay minimal: the gateway creates and watches Encounters and reads pods only in the company namespaces; no Secrets, no wildcards. A PR that changes RBAC or a NetworkPolicy has a "Security review needed" section.
- Changes to the CRD go through a "CONTRACT CHANGE REQUEST" (`deploy/crds/**` is a contract).
- App changes reach the cluster through git and Argo CD; no PR relies on applying or patching app manifests on the cluster.
- No kubeconfig, token or cluster ID is committed; the repo is public.
- `/internal/*` is served only on the gateway's cluster-only port 8081, never on 8080.

## Evidence

From `docs/evidence/LOG.md` (times MST):

| LOG time | What happened | Evidence | Fix |
|---|---|---|---|
| 13:20 | Radar's MCP `list_clusters` showed the session was signed in to the wrong organization (no `rapport`, no `cnh`) | Radar MCP | Signed in again and picked Cloud Native Hackathon (14:04) |
| 14:02 | Operator verified on a local kind cluster: an Encounter becomes two Jobs plus the responder's Service and NetworkPolicy within 1 s, goes `Failed` after `activeDeadlineSeconds`, and deleting it garbage-collects both namespaces | `kubectl --context kind-rapport`, [PR #6](https://github.com/hendersonBare/cloud-native-hackathon/pull/6) | — |
| 14:04 | The site still served the platform's starter app because the cluster had no Argo CD Application yet | Radar MCP `fleet_list_gitops` (0 applications), `fleet_search ns:team-rapport` | Applied `argocd/application.yaml` at 14:30 |
| 14:30 | First Argo CD sync green; gateway, briefers and OPA Ready; the site reported `358078f`, then `2eb7a86` on its own after the next build | kubectl, Radar MCP | — |
| 14:31 | Operator `CrashLoopBackOff` on the vcluster: kopf's `getpass.getuser()` raised `KeyError: getpwuid(): uid not found: 10001`. The local kind test ran as the laptop's user, so it never hit this | Radar issue `f5f0ca9f2e8b7558` (critical, CrashLoopBackOff), `kubectl logs --previous` | [PR #13](https://github.com/hendersonBare/cloud-native-hackathon/pull/13): explicit kopf identity; operator 1/1 with 0 restarts since 14:41 |
| 14:35 | Radar AI investigation on Deployment `team-rapport/operator` found the root cause in about 2 minutes (the `getpwuid` KeyError, confidence 0.75) and ruled out resource pressure. Its rollback suggestion would not have helped, because the previous tag had the same bug, so we fixed it in code | Investigation `chat_1BSCtsVKiQ5ioDSw` | PR #13 |
| 14:41 | First encounter on Kubernetes through the public URL: two delegate Jobs plus the responder's Service and per-encounter NetworkPolicy, then `Completed` with both Jobs `Succeeded`; the gateway's pod-IP check worked inside the vcluster and 6 follow-up records were written to each briefer | Encounter `enc-f629a19e`, kubectl, gateway logs | — |
| 14:45 | The platform's edge cuts every SSE stream 15 to 19 s after it opens | curl probes against the public URL | [PR #20](https://github.com/hendersonBare/cloud-native-hackathon/pull/20): event IDs, `Last-Event-ID`, `retry: 1000`, rotation before the cut |

The stage screenshot `docs/assets/stage-live.png` (live mode, captured at 2:54 PM) shows the two delegate pods of `enc-f629a19e`, `delegate-enc-f629a19e-5sdk6` in `org-acme` and `delegate-enc-f629a19e-tttgf` in `org-bluefin`, both `Succeeded`, as reported by the gateway's pod watch.
