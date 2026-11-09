# How the Rapport team works

Six workstreams build Rapport in parallel. Each one works on its own `ws/<name>` branch and opens a PR, and only the integrator merges to `main`. A merge to `main` deploys, so every change reaches it through a reviewed PR. `AGENTS.md` has the house rules and `docs/SPEC.md` is the source of truth. Cite the section when you flag something.

## Ownership (docs/SPEC.md §3)

A PR from a `ws/<name>` branch may change only the paths that workstream owns:

| Branch | Owns |
|---|---|
| `ws/policy-ci` | `policy/`, `deploy/policy/`, `.github/` |
| `ws/memory` | `src/rapport_memory/`, `src/rapport_briefer/`, `seed/`, `deploy/briefer/`, `tests/memory/`, `tests/briefer/` |
| `ws/operator` | `src/rapport_operator/`, `deploy/operator/`, `tests/operator/` |
| `ws/delegate` | `src/rapport_delegate/`, `tests/delegate/` |
| `ws/gateway` | `src/rapport_gateway/`, `deploy/gateway/`, `tests/gateway/` |
| `ws/web` | `web/` |

- Flag every changed file outside that list and name the workstream that owns it.
- `pyproject.toml` and `uv.lock` may change only to add a missing dependency with `uv add`, and the PR description must say which package and why (AGENTS.md §1).
- Branches that don't start with `ws/` are the integrator's. Skip the ownership check for them.

## Contracts are read-only (docs/SPEC.md §10)

- `src/rapport_common/**`, `deploy/crds/**`, `deploy/elastic/**` and `contracts/**` are contracts. In a `ws/` PR, any change to them is a blocking finding unless the PR description starts with "CONTRACT CHANGE REQUEST".
- Flag a pydantic model, enum, index name, label, Service name or URL that is defined locally instead of imported from `rapport_common.models` or `rapport_common.names`.

## Tests and CI

- New behaviour ships with a unit test in the workstream's own `tests/<name>/` folder. Flag a new code path that has no test.
- CI runs `make test`: `ruff check` (rules E and F, line length 120), `pytest -q` and `opa test policy`. Don't suggest turning off a lint rule, skipping a test, marking it xfail or loosening an assertion to get CI green. Fix the cause.

## Service conventions (AGENTS.md §3)

- Services run as `python -m rapport_<component>`, listen on `0.0.0.0:8080`, expose `GET /healthz`, and are configured only through environment variables.
- Use `httpx.AsyncClient`, not `requests`, and `logging`, never `print`.
- Kubernetes manifests use image `rapport:dev` with `imagePullPolicy: IfNotPresent`, the labels `app.kubernetes.io/part-of: rapport` and `rapport.dev/role: <role>`, and requests of 50m CPU and 128Mi memory.
