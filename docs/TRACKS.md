# Track evidence: what we claim, where it lives, how we prove it

This is the documentation backbone for the submission. Every row is a claim the judges will check. Fill in **Proof** as soon as it exists: a screenshot path, a PR link or a trace ID. Screenshots go in `docs/evidence/screenshots/` named `<track>-<nn>-<what>.png`. The running story of the day goes in `docs/evidence/LOG.md`.

Status: ⬜ not started · 🟨 built, no proof yet · ✅ proof captured

## Elasticsearch: Find the Right Talk

Judges want: ES as the core data layer, and smart keyword, semantic or hybrid search.

| Claim | Where in code | How to show it live | Proof | Status |
|---|---|---|---|---|
| All memory, profiles, agenda and follow-ups live in ES (5 indices) | `deploy/elastic/`, `rapport_memory` | Kibana Discover on `rapport-*`, filtered by `kind` | | ⬜ |
| Hybrid search: BM25 + `semantic_text` (Jina via EIS), merged with RRF | `rapport_memory` search | "something on eBPF and security" finds `talk-ebpf-zero-code` without exact words | | ⬜ |
| Semantic rerank with the preconfigured Jina reranker (`text_similarity_reranker`) | `rapport_memory` talk search | Same query, before and after rerank | | ⬜ |
| Importance gate: a small hosted model scores memory before it's stored or used | `docs/research/oss-and-light-models.md` | Upload the CV: chunks with low importance are dropped and the count is shown | | ⬜ |
| Per-company indices + scoped API keys as a security boundary | `deploy/elastic/role-descriptors/` | `curl` with the delegate key on `rapport-acme-internal` returns 403 | | ⬜ |
| Agent Builder agent + ES\|QL tool, used from Claude Code over MCP | Kibana (no app code) | Ask "which eBPF talks are after 3 PM?" in Claude Code | | ⬜ |

## Dash0: Stop Flying Blind

Judges want: deep OTel (traces, metrics, logs, RUM); Agent0 or MCP used on a real issue; a dashboard or SLO.

| Claim | Where in code | How to show it live | Proof | Status |
|---|---|---|---|---|
| One trace: click → gateway → Encounter → both delegate pods → OPA → brief | `rapport_common/telemetry.py`, `TRACEPARENT` env | Open the trace for the demo encounter | | ⬜ |
| LLM cost and tokens per encounter (OpenLIT, `gen_ai.*`) with no content captured | `telemetry.py` (`capture_message_content=False`) | LLM span attributes: tokens and model, no prompt text | | ⬜ |
| Custom metrics: brief latency, exchange duration, policy decisions by rule | SPEC §8 | Dashboard panels | | ⬜ |
| SLO: 95% of private briefs within 5 s | Dash0 UI | SLO page | | ⬜ |
| RUM on the two-phone page | `web/` (Dash0 Web SDK) | Session view for the demo run | | ⬜ |
| Agent0 or Dash0 MCP found a **real** bug from today | `docs/evidence/LOG.md` entry | Agent0 transcript, then the fix commit | | ⬜ |
| K8s infrastructure telemetry (optional: Dash0 operator) | Helm | Pod and node view | | ⬜ |

## Radar: AI SRE

Judges want: runs on K8s with Radar connected; Radar UI and MCP used all day; an AI investigation of a real issue.

| Claim | Where | How to show it live | Proof | Status |
|---|---|---|---|---|
| The swarm on K8s: Encounter CRD → Jobs, Services, per-encounter NetworkPolicies | `rapport_operator`, `deploy/` | Radar Topology during an encounter | | ⬜ |
| Radar MCP used while building (deploy checks, diagnosing) | Claude Code session | `issues` / `diagnose` calls in the transcript | | ⬜ |
| AI investigation of a real failure, plus what we changed | `docs/evidence/LOG.md` entry | Investigation page, then the fix | | ⬜ |
| Checks before and after | Radar | Two screenshots | | ⬜ |
| Timeline of the day | Radar Timeline | Screenshot at 5 PM | | ⬜ |

## Sonar / Gitar: Never Merge Broken

Judges want: features landing through Gitar-reviewed PRs all day; setup that fits the project; a CI fix.

| Claim | Where | How to show it live | Proof | Status |
|---|---|---|---|---|
| Every workstream landed as a Gitar-reviewed PR | GitHub PR list | Filter by `ws/*` branches | | ⬜ |
| Project-specific review instructions | `.gitar/review/instructions.md` | A Gitar comment that cites one of them | | ⬜ |
| 5 repository rules that encode our security model | `.gitar/rules/*.md` | A rule firing on a PR (for example no-content-in-telemetry) | | ⬜ |
| Gitar diagnosed a failing CI run and auto-apply fixed it | One PR | PR timeline | | ⬜ |
| A Gitar comment we disagreed with, and our reply | Any PR | Reply thread (AGENTS.md §2.5) | | ⬜ |

## Merge Forward: Conferences for Everyone

| Claim | Where | How to show it live | Proof | Status |
|---|---|---|---|---|
| Briefs in each person's language (Bo gets Spanish) | delegate and briefer | Right phone | | ⬜ |
| Conversation starters and opening lines for people who find networking hard | `PrivateBrief`, `ConversationPlan` | Brief card | | ⬜ |
| Keyboard-only swiping (← →, ✕ ✓), screen-reader labels, contrast | `web/` | Tab through the Discover deck; run Lighthouse a11y | | ⬜ |
| You don't need to remember names or context | Ask my memory | "What did we promise Bluefin?" | | ⬜ |

---

## How we document (rules for humans and subagents)

1. **Every PR description** has a "Track evidence" section: which rows above it moves forward, and what to screenshot once it's merged (see AGENTS.md §7).
2. **Every bug** gets an entry in `docs/evidence/LOG.md` within 5 minutes of noticing it, even before it's understood. Include the time, the symptom, where you looked first (Radar, Dash0 or Gitar) and the trace ID or PR link.
3. **Screenshot at the moment it happens.** You can't recreate a real investigation later.
4. **At 4:15 PM**, turn the green rows into the submission README: one paragraph and one image per track.
