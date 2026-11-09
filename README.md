# Rapport: your agent meets their agent

A hackathon kit for the Cloud Native Hackathon (theme: make conferences easier). Every attendee gets a personal agent with private memory and personal context, such as a CV. When two people connect, their agents meet on Kubernetes and swap only what each side allows. Both people get briefs, follow-ups and a talk to attend together.

**Start here:**

| Doc | What it is |
|---|---|
| `docs/PITCH.md` | What we're building, the demo and the track mapping |
| `docs/SPEC.md` | The build spec: architecture, contracts, protocol, APIs and timeline |
| `docs/SETUP.md` | Setting up kind, Elastic Cloud, Dash0, OpenAI, Radar and Gitar (about 45 min) |
| `docs/FEATURE-DISCOVER.md` | v1.1: filter → research → swipe cards → deep dive → agent decides |
| `docs/COSTS.md` | What it costs to run (OpenAI, Elastic) |
| `docs/REVIEW.md` | Spec concerns and the layered fast path to a working demo |
| `docs/TRACKS.md` | Track evidence: each claim, where it lives and its proof (`docs/evidence/`) |
| `docs/research/oss-and-light-models.md` | Open-source helpers and light-model importance gating |
| `AGENTS.md` | House rules every agent follows |
| `docs/workstreams/*.md` | One brief per parallel workstream |

## How the parallel build works

Six workstreams build at the same time against the contracts in `src/rapport_common/`. Those contracts are already written and tested, and include in-memory fakes, so no one waits on anyone.

| Subagent | Builds |
|---|---|
| `rapport-policy-ci` | OPA policy and CI (merges first) |
| `rapport-memory` | Elasticsearch, seed data and the briefer (with CV upload) |
| `rapport-operator` | The Encounter → delegate pods controller |
| `rapport-delegate` | The agent-to-agent protocol |
| `rapport-gateway` | API, SSE and Encounter creation |
| `rapport-web` | The two-phone demo page |

Each subagent runs in its own git worktree (`isolation: worktree`), opens a PR, and Gitar reviews it. You merge.

## Quick start

1. Follow `docs/SETUP.md` steps 1–2, which push this kit to `main`. The worktrees branch from `main`.
2. In Claude Code at the repo root, paste:

   > Read AGENTS.md and docs/SPEC.md. Then launch these six subagents in parallel, in the background: rapport-policy-ci, rapport-memory, rapport-operator, rapport-delegate, rapport-gateway, rapport-web. Each works in its own worktree on branch ws/<name>, opens a PR and reports back with the PR URL. Don't merge anything. Tell me as each one reports.

3. While they build, finish `docs/SETUP.md` steps 3–7.
4. Merge PRs as CI and Gitar go green. Then run `make image deploy seed` and open http://localhost:8080.

Approve `git`, `gh`, `uv` and `make` commands when the subagents ask, or allow them with `/permissions`.

## Repo map

```
src/rapport_common/        contracts (models, names, telemetry, interfaces); integrator-owned, tested in CI
contracts/demo-events.json scripted event stream: web mock mode and the stage fallback
deploy/                    kind config, namespaces + NetworkPolicies, CRD, Elastic template + key scopes
scripts/                   setup-cluster, setup-elastic, create-secrets
.claude/agents/            one subagent per workstream
.gitar/rules/              Gitar repository rules
```

All data in this repo is synthetic. Personal context uploads are redacted (emails, phone numbers and addresses) before any LLM call or indexing.
