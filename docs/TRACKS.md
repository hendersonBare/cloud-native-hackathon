# Track evidence: what we claim, where it lives, how we prove it

This is the documentation backbone for the submission. Every row is a claim the judges will check. Fill in **Proof** as soon as it exists: a screenshot path, a PR link or a trace ID. Screenshots go in `docs/evidence/screenshots/` named `<track>-<nn>-<what>.png`. The running story of the day goes in `docs/evidence/LOG.md`.

Status: ⬜ not started · 🟨 built, no proof yet · ✅ proof captured

## Open items (updated 3:36 PM)

What evidence is still missing, and what is still in flight. How each technology is used is in [`docs/stack/`](stack/README.md); the demo script and verified results are in [`docs/DEMO.md`](DEMO.md).

- **Mock vs live.** The public site defaults to mock mode; `?live=1` drives the cluster. The phone screens in `docs/assets/screens.png` and the GIFs of the encounter and Discover were captured in mock mode. Since PR #18 (real rule IDs in the phone mock, Discover deep dive in live mode, merged at 3:22 PM), the mock shows the policy's own rule IDs (`public_ok`, `partner_with_nda`, `pricing_needs_approval`), and `screens.png` was retaken after it; these are scripted decisions, not live OPA answers.
- **Dash0.** The telemetry is in the code and is exported wherever the `dash0-otlp` Secret is set. No Dash0 trace ID is in the evidence log yet. The SLO, the dashboard, an Agent0 investigation and a RUM session view aren't captured in this repo. RUM is built (`web/app/rum.js`, PR #27) and runs when the `dash0-rum` Secret is set. LOG 15:36 is open: the gateway's auto-instrumented FastAPI server span carries the full `http.url`, including talk-search text.
- **Radar.** Checks before and after, and the day's Timeline, aren't captured yet.
- **Gitar.** The fixes were committed by us after Gitar's findings; we haven't captured an auto-apply CI fix. On PR #10, Gitar's summary still lists 2 of its 6 findings open (two files outside `ws/gateway`'s paths); after the integrator's reply, Gitar answered on both threads that the finding does not apply. On PR #14, Gitar's final summary run didn't complete; all 7 of its inline findings got a reply: 4 fixed in `3a2c711`, 2 already stale (the tests and the description's "Security review needed" and "Track evidence" sections had been added after Gitar's first pass), and 1 (models defined outside `rapport_common`) kept on purpose as a contract change request.
- **Elasticsearch.** The local runs in the evidence log used the in-memory seed store; the Elastic path runs when the `es-briefer` Secret is set. No Kibana screenshot and no `403` from the delegate key on an internal index are captured yet. The importance gate, Agent Builder and ES|QL aren't built.
- **Costs** in `docs/COSTS.md` are modelled from token estimates, not metered.
- **Speaker identification** is on `main` with tests ([PR #14](https://github.com/hendersonBare/cloud-native-hackathon/pull/14)). [PR #23](https://github.com/hendersonBare/cloud-native-hackathon/pull/23) (gateway serves speaker search read-only at `/api/speakers`) merged at 3:25 PM, with its route test following in [PR #25](https://github.com/hendersonBare/cloud-native-hackathon/pull/25) (3:33 PM). At 3:36 PM `/healthz` reported `b609583` (PR #25's merge, which includes #23) and `GET /api/speakers/search` answered `200`. Which store backs it on the cluster (Elasticsearch or the in-memory fixture) isn't captured.
- **Calendar and People tab.** [PR #17](https://github.com/hendersonBare/cloud-native-hackathon/pull/17) (web) merged at 3:17 PM. [PR #16](https://github.com/hendersonBare/cloud-native-hackathon/pull/16) (calendar API) merged at 3:19 PM; its own build-and-deploy run failed on the GHCR push, but later builds include it, and at 3:36 PM `GET /api/calendar` answered `200` on the public site.
- **GHCR pushes were refused intermittently** (LOG 15:03): `denied: permission_denied: write_package`. Run `42710892142` for `9b7bceb` (PR #16) failed this way. Re-runs succeeded (run `42708273110` for `03e0d51` on its third attempt, run `42711345424` for `1bb2665` on its second), and the runs for `c3ae9f5` (PR #23) and `b609583` (PR #25) passed on their first attempt. The cause isn't known, and LOG 15:03 still lists it as open.

## Elasticsearch: Find the Right Talk

Judges want: ES as the core data layer, and smart keyword, semantic or hybrid search.

| Claim | Where in code | How to show it live | Proof | Status |
|---|---|---|---|---|
| All memory, profiles, agenda and follow-ups live in ES (5 indices) | `deploy/elastic/`, `rapport_memory` | Kibana Discover on `rapport-*`, filtered by `kind` | Built: `deploy/elastic/index-template.json`, `names.index_for()`; no Kibana capture yet | 🟨 |
| Hybrid search: BM25 + `semantic_text` (Jina via EIS), merged with RRF | `rapport_memory` search | "something on eBPF and security" finds `talk-ebpf-zero-code` without exact words | Built: `src/rapport_memory/client.py` (`rrf` over BM25 + `semantic`), [PR #7](https://github.com/hendersonBare/cloud-native-hackathon/pull/7); evidence-log runs used the seed store | 🟨 |
| Semantic rerank with the preconfigured Jina reranker (`text_similarity_reranker`) | `rapport_memory` talk search | Same query, before and after rerank | Built: `text_similarity_reranker` when `ES_RERANK_INFERENCE_ID` is set, [PR #7](https://github.com/hendersonBare/cloud-native-hackathon/pull/7) | 🟨 |
| Importance gate: a small hosted model scores memory before it's stored or used | `docs/research/oss-and-light-models.md` | Upload the CV: chunks with low importance are dropped and the count is shown | | ⬜ |
| Per-company indices + scoped API keys as a security boundary | `deploy/elastic/role-descriptors/` | `curl` with the delegate key on `rapport-acme-internal` returns 403 | Built: `deploy/elastic/role-descriptors/delegate-*.json` read only own shareable + conference; no curl capture yet | 🟨 |
| Agent Builder agent + ES\|QL tool, used from Claude Code over MCP | Kibana (no app code) | Ask "which eBPF talks are after 3 PM?" in Claude Code | | ⬜ |

## Dash0: Stop Flying Blind

Judges want: deep OTel (traces, metrics, logs, RUM); Agent0 or MCP used on a real issue; a dashboard or SLO.

| Claim | Where in code | How to show it live | Proof | Status |
|---|---|---|---|---|
| One trace: click → gateway → Encounter → both delegate pods → OPA → brief | `rapport_common/telemetry.py`, `TRACEPARENT` env | Open the trace for the demo encounter | Built: traceparent annotation → `TRACEPARENT` env → `exchange.run`; no trace ID captured yet | 🟨 |
| LLM cost and tokens per encounter (OpenLIT, `gen_ai.*`) with no content captured | `telemetry.py` (`capture_message_content=False`) | LLM span attributes: tokens and model, no prompt text | Built: `openlit.init(capture_message_content=False)`; no span captured yet | 🟨 |
| Custom metrics: brief latency, exchange duration, policy decisions by rule | SPEC §8 | Dashboard panels | Built: instruments in `rapport_gateway/observability.py`, `rapport_delegate/instruments.py` ([PR #9](https://github.com/hendersonBare/cloud-native-hackathon/pull/9), [PR #10](https://github.com/hendersonBare/cloud-native-hackathon/pull/10)); no dashboard yet | 🟨 |
| SLO: 95% of private briefs within 5 s | Dash0 UI | SLO page | | ⬜ |
| RUM on the two-phone page | `web/app/rum.js`, `GET /api/rum-config` (Dash0 Web SDK; token from the `dash0-rum` Secret) | Session view for the demo run; a browser fetch span as the parent of the gateway span | | 🟨 |
| Agent0 or Dash0 MCP found a **real** bug from today | `docs/evidence/LOG.md` entry | Agent0 transcript, then the fix commit | | ⬜ |
| K8s infrastructure telemetry (optional: Dash0 operator) | Helm | Pod and node view | | ⬜ |

## Radar: AI SRE

Judges want: runs on K8s with Radar connected; Radar UI and MCP used all day; an AI investigation of a real issue.

| Claim | Where | How to show it live | Proof | Status |
|---|---|---|---|---|
| The swarm on K8s: Encounter CRD → Jobs, Services, per-encounter NetworkPolicies | `rapport_operator`, `deploy/` | Radar Topology during an encounter | LOG 14:41, `enc-f629a19e`: two delegate Jobs, Service and NetworkPolicy, `Completed`; `docs/assets/stage-live.png` | ✅ |
| Radar MCP used while building (deploy checks, diagnosing) | Claude Code session | `issues` / `diagnose` calls in the transcript | LOG 13:20 (`list_clusters`), 14:04 (`fleet_list_gitops`, `fleet_search`), 14:30 | ✅ |
| AI investigation of a real failure, plus what we changed | `docs/evidence/LOG.md` entry | Investigation page, then the fix | LOG 14:31 and 14:35: issue `f5f0ca9f2e8b7558`, investigation `chat_1BSCtsVKiQ5ioDSw`, fix [PR #13](https://github.com/hendersonBare/cloud-native-hackathon/pull/13) | ✅ |
| Checks before and after | Radar | Two screenshots | | ⬜ |
| Timeline of the day | Radar Timeline | Screenshot at 5 PM | | ⬜ |

## Sonar / Gitar: Never Merge Broken

Judges want: features landing through Gitar-reviewed PRs all day; setup that fits the project; a CI fix.

| Claim | Where | How to show it live | Proof | Status |
|---|---|---|---|---|
| Every workstream landed as a Gitar-reviewed PR | GitHub PR list | Filter by `ws/*` branches | Gitar commented on every `ws/*` PR: [#4](https://github.com/hendersonBare/cloud-native-hackathon/pull/4), [#5](https://github.com/hendersonBare/cloud-native-hackathon/pull/5), [#6](https://github.com/hendersonBare/cloud-native-hackathon/pull/6), [#7](https://github.com/hendersonBare/cloud-native-hackathon/pull/7), [#8](https://github.com/hendersonBare/cloud-native-hackathon/pull/8), [#9](https://github.com/hendersonBare/cloud-native-hackathon/pull/9), [#10](https://github.com/hendersonBare/cloud-native-hackathon/pull/10), [#11](https://github.com/hendersonBare/cloud-native-hackathon/pull/11), [#14](https://github.com/hendersonBare/cloud-native-hackathon/pull/14), [#16](https://github.com/hendersonBare/cloud-native-hackathon/pull/16), [#17](https://github.com/hendersonBare/cloud-native-hackathon/pull/17), [#23](https://github.com/hendersonBare/cloud-native-hackathon/pull/23) | ✅ |
| Project-specific review instructions | `.gitar/review/instructions.md` | A Gitar comment that cites one of them | [PR #8](https://github.com/hendersonBare/cloud-native-hackathon/pull/8): Gitar cites the house rules for a missing test folder and a missing "Track evidence" section | ✅ |
| 5 repository rules that encode our security model | `.gitar/rules/*.md` | A rule firing on a PR (for example no-content-in-telemetry) | security-review-flag fired on [PR #8](https://github.com/hendersonBare/cloud-native-hackathon/pull/8) and [PR #10](https://github.com/hendersonBare/cloud-native-hackathon/pull/10) | ✅ |
| Gitar diagnosed a failing CI run and auto-apply fixed it | One PR | PR timeline | | ⬜ |
| A Gitar comment we disagreed with, and our reply | Any PR | Reply thread (AGENTS.md §2.5) | [PR #10](https://github.com/hendersonBare/cloud-native-hackathon/pull/10): integrator reply on the two out-of-path findings | ✅ |

## Merge Forward: Conferences for Everyone

| Claim | Where | How to show it live | Proof | Status |
|---|---|---|---|---|
| Briefs in each person's language (Bo gets Spanish) | delegate and briefer | Right phone | LOG 14:03 and 14:16 (`enc-b3293785`): Bo's brief in Spanish; follow-ups too in [PR #15](https://github.com/hendersonBare/cloud-native-hackathon/pull/15) (LOG 14:43) | ✅ |
| Conversation starters and opening lines for people who find networking hard | `PrivateBrief`, `ConversationPlan` | Brief card | Built: deep dive `ConversationPlan` with an opening line; no capture yet | 🟨 |
| Keyboard-only swiping (← →, ✕ ✓), screen-reader labels, contrast | `web/` | Tab through the Discover deck; run Lighthouse a11y | Built: ← → keys and ✕ ✓ buttons (`web/app/screens/home.js`); no Lighthouse run yet | 🟨 |
| You don't need to remember names or context | Ask my memory | "What did we promise Bluefin?" | LOG 14:12 (cites `acme-note-0007`) and 14:16 (`enc-b3293785`, also cites the encounter summary); `docs/assets/screens.png` shows the screen (captured in mock mode) | ✅ |

---

## How we document (rules for humans and subagents)

1. **Every PR description** has a "Track evidence" section: which rows above it moves forward, and what to screenshot once it's merged (see AGENTS.md §7).
2. **Every bug** gets an entry in `docs/evidence/LOG.md` within 5 minutes of noticing it, even before it's understood. Include the time, the symptom, where you looked first (Radar, Dash0 or Gitar) and the trace ID or PR link.
3. **Screenshot at the moment it happens.** You can't recreate a real investigation later.
4. **At 4:15 PM**, turn the green rows into the submission README: one paragraph and one image per track.
