SHELL := /bin/bash
CLUSTER := rapport
IMAGE := rapport:dev
NAMESPACES := rapport-system org-acme org-bluefin

.PHONY: help cluster elastic secrets image policy deploy reload seed test radar status

help: ## list targets
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*## / - /'

cluster: ## kind cluster + namespaces + NetworkPolicies + CRD, then checks enforcement
	bash scripts/setup-cluster.sh

elastic: ## index template + 5 indices on Elastic Cloud (needs ES_URL, ES_ADMIN_API_KEY)
	bash scripts/setup-elastic.sh

secrets: ## Kubernetes Secrets from .env
	bash scripts/create-secrets.sh

image: ## build the single image and load it into kind
	docker build -t $(IMAGE) .
	kind load docker-image $(IMAGE) --name $(CLUSTER)

policy: ## OPA policy + per-company data as ConfigMaps (policy/rapport.rego, policy/data/<org>.json)
	@for org in acme bluefin; do \
	  kubectl -n org-$$org create configmap opa-policy --from-file=rapport.rego=policy/rapport.rego \
	    --from-file=data.json=policy/data/$$org.json --dry-run=client -o yaml | kubectl apply -f - ; \
	done

deploy: policy ## apply base, CRD and every component's manifests
	kubectl apply -f deploy/base -f deploy/crds
	@for d in policy operator briefer gateway; do \
	  if [ -d deploy/$$d ]; then kubectl apply -R -f deploy/$$d; fi; \
	done

reload: image ## rebuild, load into kind and restart all Rapport deployments
	@for ns in $(NAMESPACES); do \
	  kubectl -n $$ns rollout restart deployment -l app.kubernetes.io/part-of=rapport || true; \
	done

seed: ## load the synthetic demo data (uses ES_URL + ES_ADMIN_API_KEY from .env)
	@set -a; [ -f .env ] && source .env; set +a; PYTHONPATH=src uv run python -m rapport_memory.seed

test: ## what CI runs
	uv run ruff check src tests
	uv run pytest -q
	@if ls policy/*_test.rego >/dev/null 2>&1; then opa test policy -v; else echo "no policy tests yet"; fi

radar: ## open Radar on the kind cluster
	kubectl radar

status: ## encounters and pods at a glance
	kubectl get encounters
	kubectl get pods -A -l app.kubernetes.io/part-of=rapport -o wide
