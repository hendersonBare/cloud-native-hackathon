SHELL := /bin/bash
IMAGE ?= rapport:local
NAMESPACES := team-rapport org-acme org-bluefin

# Deploying = merging to main. The Action builds ghcr.io/<repo>:<sha>, commits the tag into
# deploy/kustomization.yaml, and Argo CD syncs deploy/ into the team vcluster.

.PHONY: help cluster elastic secrets image manifests seed test radar status

help: ## list targets
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*## / - /'

cluster: ## FALLBACK ONLY: a local cluster set up like the team vcluster (needs OrbStack/Docker)
	./scripts/local-cluster.sh rapport

elastic: ## index template + 5 indices on Elastic Cloud (needs ES_URL, ES_ADMIN_API_KEY)
	bash scripts/setup-elastic.sh

secrets: ## Kubernetes Secrets from .env
	bash scripts/create-secrets.sh

image: ## build the image locally to check the Dockerfile (CI builds the real one)
	docker build -t $(IMAGE) .

manifests: ## render deploy/ exactly as Argo CD will (fails on broken kustomize)
	kubectl kustomize deploy > /dev/null && echo "deploy/ renders"

seed: ## load the synthetic demo data (uses ES_URL + ES_ADMIN_API_KEY from .env)
	@set -a; [ -f .env ] && source .env; set +a; PYTHONPATH=src uv run python -m rapport_memory.seed

test: ## what CI runs
	uv run ruff check src tests
	uv run pytest -q
	@if ls policy/*_test.rego >/dev/null 2>&1; then opa test deploy/policy policy -v; else echo "no policy tests yet"; fi
	@if command -v kubectl >/dev/null; then kubectl kustomize deploy > /dev/null && echo "deploy/ renders"; fi

radar: ## open local Radar (the team cluster is in Radar Cloud)
	kubectl radar

status: ## encounters and pods at a glance
	kubectl get encounters
	kubectl get pods -A -l app.kubernetes.io/part-of=rapport -o wide
