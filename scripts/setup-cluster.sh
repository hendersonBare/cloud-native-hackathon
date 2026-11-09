#!/usr/bin/env bash
# Creates the kind cluster, namespaces, baseline NetworkPolicies and the Encounter CRD,
# then proves NetworkPolicy is actually enforced. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER=rapport

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  kind create cluster --config deploy/kind/kind-config.yaml
fi
kubectl config use-context "kind-${CLUSTER}" >/dev/null
kubectl apply -f deploy/base/namespaces.yaml
kubectl apply -f deploy/base/network-policies.yaml
kubectl apply -f deploy/crds/encounter-crd.yaml
kubectl wait --for condition=established --timeout=60s crd/encounters.rapport.dev

echo "Checking that NetworkPolicy is enforced (about 1 minute)..."
cleanup() {
  kubectl -n org-bluefin delete pod np-target --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kubectl -n org-bluefin delete svc np-target --ignore-not-found >/dev/null 2>&1 || true
}
cleanup
kubectl -n org-bluefin run np-target --image=nginx:alpine --port=80 >/dev/null
kubectl -n org-bluefin expose pod np-target --port=80 >/dev/null
kubectl -n org-bluefin wait --for=condition=Ready pod/np-target --timeout=180s >/dev/null

probe() { # $1 = namespace to probe from; succeeds if the target answered
  kubectl -n "$1" run "np-probe-${RANDOM}" --rm -i --restart=Never --image=busybox:1.36 --command -- \
    wget -q -T 3 -O /dev/null http://np-target.org-bluefin.svc.cluster.local >/dev/null 2>&1
}
if probe org-bluefin; then same=allowed; else same=blocked; fi
if probe org-acme; then cross=allowed; else cross=blocked; fi
cleanup

if [[ "$same" == allowed && "$cross" == blocked ]]; then
  echo "OK: NetworkPolicy enforced (same company allowed, other company blocked)."
else
  echo "WARNING: NetworkPolicy check failed (same company: $same, other company: $cross)."
  echo "See 'If NetworkPolicy is not enforced' in docs/SETUP.md."
  exit 1
fi
