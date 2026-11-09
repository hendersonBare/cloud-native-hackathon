# Workstream: operator (Kubernetes controller for Encounter)

**Mission.** When an `Encounter` appears, create each company's delegate Job, plus the responder's Service and the NetworkPolicy that lets **only** this encounter's initiator reach it. Track the status and clean up after the TTL. This is the "swarm" judges will see in Radar.

**You own:**

- `src/rapport_operator/`: `__main__.py`, `builders.py` (pure functions) and `handlers.py` (kopf).
- `deploy/operator/`: ServiceAccount, ClusterRole, ClusterRoleBinding, a Deployment in `team-rapport` (image `app`, resources `names.RESOURCES_OPERATOR`, `names.SECURITY_CONTEXT`, Downward API `POD_NAME`/`POD_NAMESPACE`), listed in `deploy/operator/kustomization.yaml`, and `sample-encounter.yaml` (**not** listed there: Argo CD would keep re-creating it).
- `tests/operator/`.

**Read first:** `AGENTS.md`, SPEC §4.4–§4.5 and §9, and `deploy/crds/encounter-crd.yaml`.

## Build (P0)

1. **Pure builders, unit-tested first:**
   - `build_job(enc, side)`, `build_service(enc)` and `build_network_policy(enc)` return dicts that match SPEC §4.4 exactly: names, namespaces, labels, env, `envFrom` secrets, `ownerReferences` (with the Encounter's `uid`), `automountServiceAccountToken: false`, `imagePullPolicy: IfNotPresent`, resources `names.RESOURCES_DELEGATE` and `securityContext` `names.SECURITY_CONTEXT`.
   - **Image:** `os.environ[names.IMAGE_ENV]` if set, else read the operator's own pod (`POD_NAME`, `POD_NAMESPACE`) once at startup and reuse its container image. Kustomize sets that image to the current GHCR tag, so delegates always match the deployed commit.
   - Pass `RAPPORT_LLM_MODEL` through from the operator's env, and copy the `rapport.dev/traceparent` annotation into `TRACEPARENT`.
2. **Handlers:**
   - `@kopf.on.create("rapport.dev", "v1alpha1", "encounters")` creates the objects with the Kubernetes Python client and sets `status.phase=Running` and `status.delegates`.
   - A handler on delegate Jobs (label `rapport.dev/role=delegate`) patches the Encounter status: `Completed` when both Jobs succeed, `Failed` if either fails.
   - A timer or daemon deletes the Encounter after `spec.ttlSeconds`; garbage collection removes the rest.
3. **Entrypoint:** `python -m rapport_operator` runs kopf **cluster-wide** and **standalone** (no peering). Check kopf's docs for the exact flags or `kopf.run` arguments.
4. **RBAC** per SPEC §4.5, plus whatever kopf needs for cluster-wide watching (CRD and namespace list/watch, and events).

## Done when

- The builder unit tests pass and assert the NetworkPolicy selectors exactly.
- On the team vcluster, after merge (create the sample with Radar's `apply_resource`, or kubectl if you set up the kubeconfig):
  - `kubectl apply -f deploy/operator/sample-encounter.yaml` creates `delegate-<enc>` Jobs in both org namespaces, plus the Service and NetworkPolicy in the responder's namespace.
  - `kubectl get enc` shows the phase.
  - Ask the integrator to run `kubectl delete enc <name>` (a delete is the human's call); everything owned disappears.

## Gotchas

- Cluster-scoped owners can own namespaced objects. Set `namespace` explicitly on each child, because `kopf.adopt` won't infer it from a cluster-scoped owner.
- The CRD keeps unknown status fields, so kopf's progress storage works.
- The pods need the `openai`, `dash0-otlp` and `es-delegate` Secrets in their namespace; `make secrets` creates them.

**Out of scope:** warm pools, per-encounter API keys, admission webhooks.
