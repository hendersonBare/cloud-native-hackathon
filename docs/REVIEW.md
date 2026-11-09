# Spec review: concerns and the fast path to a working demo

Written 9 Nov 2026 against the v1.1 kit (`docs/SPEC.md`, `docs/FEATURE-DISCOVER.md`). Read this before launching the subagents. Each concern has a fix sized for today.

## TL;DR

1. **The laptop can't run the kit yet.** Docker, kind, OPA, Helm and Radar aren't installed, and there's no kube context. Fix that first (§1, item 1).
2. **Build in layers that each demo on their own** (§2). Mock-mode UI → real Elasticsearch → real exchange as local processes → Kubernetes. If the clock runs out, you still demo the deepest layer you reached.
3. **The cheapest track points are still on the table:** Elastic's reranker, Agent Builder and MCP; Dash0 RUM and the K8s operator; Gitar review instructions; one *real* investigation each in Radar and Agent0 (`docs/TRACKS.md`).
4. **Document as you go, not at 5 PM.** Each bug you hit goes in `docs/evidence/LOG.md` with its trace ID or PR link. Those entries become your Agent0, Radar and Gitar stories.

---

## 1. Concerns, most serious first

| # | Concern | Why it matters | Fix for today |
|---|---|---|---|
| 1 | **No container runtime or cluster tools on this Mac** (`docker`, `kind`, `opa`, `helm`, `kubectl-radar` are missing; `kubectl` has no context) | Without these, `make cluster image deploy` and `make test`'s OPA step don't run, and Radar has nothing to show | `brew install --cask orbstack` (starts faster than Docker Desktop), then `brew install kind helm opa jq kubectl-radar`. Give the VM 6 GB or more. **Plan B:** the Radar team vcluster (`join.cnh.radarhq.io`). It needs a public GHCR image instead of `kind load`, so make `IMAGE` a Makefile variable now. |
| 2 | **Scope versus time.** Six workstreams plus Discover, with integration starting at 2:15 | The riskiest seam (operator → Jobs → NetworkPolicy → delegate → OPA → gateway) is the last to be tested | Use the layered plan in §2. Every layer can be demoed alone. Hold the 3:30 cut line from SPEC §12. |
| 3 | **Radar's AI investigation may need Radar Cloud or an LLM key** | Judging criterion 3 is "at least one AI investigation on a real issue". Local `kubectl radar` gives you the UI and MCP; check whether investigations work locally with your key. | At the Radar table, ask whether a kind cluster can join Radar Cloud. If not, run the investigation on the team vcluster with the same image. Screenshot **Checks** in the first hour (your "before"). |
| 4 | **The Elastic features judges named aren't used:** Agent Builder, MCP, Jina reranker, ES\|QL | Hybrid RRF is good, but "smart use of search" is where you score | (a) Wrap talk search in `text_similarity_reranker` with the preconfigured Jina reranker. One JSON change, owned by the memory workstream. (b) An Agent Builder agent over `rapport-conference` with one ES\|QL tool, connected to Claude Code over MCP: about 15 min of clicking, no app code. (c) The importance gate in `docs/research/oss-and-light-models.md`. |
| 5 | **`/internal/events` is unauthenticated** | Any pod, including the malicious delegate, can post a `shared_brief` or `policy_decision` for the *other* company's persona. That weakens the "safe by design" pitch. | The gateway already watches delegate pods. Map source pod IP → (org, encounter, side) and reject events whose `org_id` or `persona_id` don't match. About 20 lines in the gateway. Add a "Security review needed" note to that PR. |
| 6 | **Dash0 wants a real issue found with Agent0 or MCP**, not a staged one | A canned chaos button scores lower than a genuine bug from today | Log every bug in `docs/evidence/LOG.md` with its trace ID. Pick the best one at 3:30. A good candidate: delegate cold start or OPA fail-closed (`opa_unavailable`) during the first deploy. |
| 7 | **Gitar has no review instructions file.** `.gitar/rules/` has 5 rules, which is the Pro limit per org; `.gitar/review/instructions.md` was missing | Gitar reads review instructions from `.gitar/review/*.md` on the PR branch. SETUP.md only says "paste AGENTS.md §5 if there's a place". | Added `.gitar/review/instructions.md` in this change. For the CI-fix criterion, open one PR that breaks a test on purpose and let Gitar diagnose it and auto-apply the fix. |
| 8 | **Elastic Serverless details to check before relying on them** | The live CV upload must be searchable right away, and RRF and inference IDs vary by tier | Write demo records with `refresh="wait_for"`. Run `GET _inference/_all` to confirm the rerank endpoint ID (Elastic's docs mention both `.jina-reranker-v3` and `.jina-reranker-v3.5`). Keep the documented bool/should fallback for RRF. |
| 9 | **Delegate pod cold start.** One fat image (kopf, kubernetes, openlit, elasticsearch) is imported in every Job | The initiator waits up to 30 s for the responder. The SLO "99% of exchanges complete within 30 s" can miss on a cold kind node. | `kind load` the image before the demo and run one warm-up encounter. Measure `exchange.run` in Dash0. If it's slow, import openlit lazily in the delegate. Warm pools via `kubernetes-sigs/agent-sandbox` are future work. |
| 10 | **Model ID and parameters haven't been checked against your key** | `gpt-6-luna` with `reasoning_effort=low` and structured outputs is in the spec, but nobody has run it here yet | Make one smoke call before launching subagents. The 8 s timeout with template fallback is already in the spec, so the demo won't hang. |
| 11 | **Content could reach telemetry through libraries** | The Dash0 rule says IDs only. OpenLIT runs with `capture_message_content=False`. elasticsearch-py emits its own OTel spans, and capturing the search query is off by default. | Keep `OTEL_PYTHON_INSTRUMENTATION_ELASTICSEARCH_CAPTURE_SEARCH_QUERY` unset. Before the demo, open one LLM span and one ES span in Dash0 and screenshot them as evidence that no content leaks. |
| 12 | **Times and time zones** | Talks are stored in UTC and shown in MST. A wrong offset on stage looks bad. | Display in `America/Denver` with a label. This also makes a good Gitar review instruction (see Sonar's example). |
| 13 | **Research notes are scattered** (`RADAR.md`, `SONAR.md` and `research/` at the root, `docs/dash0-research.md`) | Judges and teammates look in `docs/` | Optional: `git mv` them into `docs/research/` with this file's sibling. |

### What's already strong (say it in the pitch)

- **Deterministic first.** Asks are matched by tag before any LLM sees the text, so the prompt injection is denied by `pricing_needs_approval` without ever reaching a model. That's a better story than "the LLM resisted".
- **Three independent layers:** ES key scopes, NetworkPolicy and OPA. Each can be shown live: a 403 from ES, a blocked `curl` from the other namespace, and the red chip.
- **Cost discipline:** batched research, deep dive only on intent, hard caps. `docs/COSTS.md` makes it concrete.

---

## 2. Fast path: four layers, each demoable

Launch the subagents as the README says, but **merge and integrate in this order**. Stop at whatever layer 3:30 PM finds you on.

| Layer | What runs | Needs | Demo you can give | Tracks it proves |
|---|---|---|---|---|
| **L0: mock UI** | gateway with `RAPPORT_MOCK=1` + web | Python only | The full 3-minute story, scripted from `contracts/demo-events.json` | Merge Forward (a11y, Spanish), Gitar (PRs) |
| **L1: real memory** | briefer for acme and bluefin as local processes (`BRIEFER_URL_*` overrides), ES seeded | Elastic, OpenAI | Real CV upload, talk search, "What did we promise Bluefin?", Discover cards | Elastic, Dash0 (traces, OpenLIT) |
| **L2: real exchange, no K8s** | 2 × OPA binaries (8181, 8182), 2 delegate processes with `PEER_URL=http://localhost:<port>` | `opa` binary | Real rounds, real policy decisions, malicious deny | Dash0 (one trace across delegates), security story |
| **L3: Kubernetes** | operator, Encounter CRD, Jobs, per-encounter NetworkPolicy | kind | Pods appearing in the swarm panel and in Radar | Radar, Dash0 K8s, everything |

Why this order:

- L0 is the stage fallback the spec already asks for. Make it work first so there's always a demo.
- L1 and L2 use the same code that runs in pods, just configured through env vars. Bugs found here are cheaper than bugs found in pods.
- L3 changes only *where* processes run, so it's mostly manifests and RBAC.

### Things to cut if behind (in this order)

1. Deep-dive LLM call: use the template fallback, keep the guardrail checks.
2. Discover role and company filters (already P1).
3. Dash0 RUM (P1). Do it if the web PR lands early; it's a single script tag.
4. Operator TTL cleanup: `ownerReferences` plus `ttlSecondsAfterFinished` on the Job already clean up.

**Never cut:** the malicious-deny moment, the Spanish brief, and the trace that runs click → pods → brief.

---

## 3. Before the subagents launch (15 minutes, integrator)

- [ ] Install the runtime and tools (concern 1). Then `make cluster`.
- [ ] Decide on the `importance` contract change (`docs/research/oss-and-light-models.md` §3). It's cheaper to land **before** six agents build against `MemoryRecord`.
- [ ] Make one OpenAI smoke call with `RAPPORT_LLM_MODEL`.
- [ ] Install Gitar on the repo and confirm it picks up `.gitar/review/instructions.md`.
- [ ] Screenshot Radar **Checks** and the empty Dash0 service map. Those are your "before" shots.
