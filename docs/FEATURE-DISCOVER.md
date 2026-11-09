# Feature: Discover (filter → research → swipe → deep dive → agent decides)

**Added at 12:00 PM. Additive: nothing already built breaks.**

| Workstream | Impact |
|---|---|
| **memory** | 2 new briefer endpoints and more seed data |
| **gateway** | 2 new routes and the agent decision logic |
| **web** | A new Discover tab |
| delegate, operator, policy-ci | Unchanged |

## User flow (Ava's phone)

1. **Filter.** On the **Discover** tab, Ava picks interest chips (`ebpf`), a role keyword, a company, or **Has an agent**.
2. **Research.** Her agent ranks the opt-in attendee directory, and each person becomes a **swipe card** with:
   - a headline, interests and what they're looking for;
   - a match score and shared interests;
   - **why you should meet**, written by the agent;
   - the talks they're giving;
   - **your company's history with them**, private to Ava.
3. **Swipe.** Left means skip. Right means interested. There are also ✕ and ✓ buttons and ← and → keys, so swiping is never gesture-only.
4. **Deep dive** (right swipe only). Ava's agent prepares the conversation: a summary, goals, what she can offer, questions to ask, watch-outs and an opening line, with citations.
5. **The agent decides**, and shows its reasoning and the guardrail checks:
   - **`agent_handshake`:** if Ava allows her agent to act on its own, it sends a connect request to Bo, marked *"Ava's agent wants to connect"*. **Bo still has to accept.** Then the existing Encounter flow runs.
   - **`human_intro`:** the person has no agent, or confidence is low. For example: *"Catch Priya after her 2:30 PM talk in Room A."*
   - **`skip`:** not worth it, with the reason shown.

## Privacy rules (non-negotiable)

- Research uses **only**:
  - the **opt-in conference directory** (`kind=attendee` cards in `rapport-conference`);
  - the public agenda;
  - **the viewer's own company memory**.

  No web scraping, no social media, and no reading another company's indices.
- Swipe cards and deep dives are **private to the viewer**. They go only to the viewer's phone. The swarm panel gets only `agent_decision` (who and what action), never the reason or the research.
- The target always consents. An agent can *request* a handshake; only the human on the other side can accept it.
- Rate limit: at most `MAX_AGENT_HANDSHAKES_PER_HOUR` (5) agent-initiated requests per person, enforced by the gateway.

## Contracts (already in `rapport_common`; tests pass)

- `Org.agents_enabled`: only `acme` and `bluefin` run agents. The directory now has 6 companies and 12 people (`personas.json`).
- `MemoryKind` adds `"attendee"`: a public directory card in `rapport-conference`, with `owner_persona_id`, `share_level=public` and a shareable `profile`. Its ID is `names.attendee_card_id(persona_id)`. `index_for` routes it to the conference index.
- New models:
  - `DiscoverFilters`, `ResearchRequest`, `PersonCard`, `ResearchResult`;
  - `SwipeBody` (with `autonomy` and `malicious`);
  - `ConversationPlan`, `AgentDecision`, `DeepDiveRequest`, `DeepDive`;
  - event data `DeepDiveStartedData` and `AgentDecisionData`.
- `ConnectBody.initiated_by` and `ConnectRequestData.initiated_by` take `"human"` or `"agent"`.
- New SSE event types: `deep_dive_started` and `deep_dive_ready` (viewer's phone only), and `agent_decision` (viewer's phone and the swarm).
- **Fixtures:**
  - `contracts/demo-research.json`: Ava's deck (Bo, Priya, Mia, Lena).
  - `contracts/demo-events.json`: now has phases `upload` → `swipe` → `accept`.
- **LLM default:** now `gpt-6-luna` with `RAPPORT_LLM_REASONING_EFFORT=low`. Use `names.llm_model()` and `names.llm_reasoning_effort()`. `gpt-5-mini` is marked deprecated by OpenAI.

## APIs

| Component | Method | Path | Body | Returns |
|---|---|---|---|---|
| gateway | POST | `/api/research` | `ResearchRequest` | `ResearchResult` (proxied to the viewer's briefer) |
| gateway | POST | `/api/swipe` | `SwipeBody` | `202 {"accepted": true}`; a right swipe starts the deep dive asynchronously |
| briefer | POST | `/v1/research` | `ResearchRequest` | `ResearchResult` |
| briefer | POST | `/v1/deep-dive` | `DeepDiveRequest` | `DeepDive` |

## Algorithms

### Research (briefer `/v1/research`): one batched LLM call per deck

1. Query `rapport-conference` for `kind=attendee`, using the filters as `terms` on `profile.interests`/`tags` and `org_id`, and `match` on title for roles. Run the hybrid RRF query with `looking_for`, or the viewer's goals and interests, as query text. Exclude the viewer, their own company and `exclude_persona_ids`. Apply `has_agent` and `language` afterwards with `names.agents_enabled()` and the directory.
2. Fill in deterministically:
   - `shared_interests`;
   - `their_talks`: talk records whose `about_persona_ids` contains the person;
   - `company_history`: viewer's internal notes with `about_persona_ids` or `about_org_ids` matching;
   - `agent_available`.
3. `match_score = round(100 * (0.5 * interest_overlap + 0.3 * relevance + 0.2 * has_history))`, where:
   - `interest_overlap` = shared ÷ the viewer's interests, capped at 1;
   - `relevance` = 1.0 for the top hybrid hit, falling linearly to 0.3 for the last;
   - `has_history` = 1 or 0.
4. **One** structured-output LLM call writes `why_meet` (240 characters or fewer, in the viewer's language) for all cards in the batch. If it fails, use a template: *"You both care about X and Y; they're looking for Z."*
5. Cache by (viewer, target) in memory for the session. Re-showing a card costs nothing.

### Deep dive (briefer `/v1/deep-dive`): one LLM call

1. **Gather:**
   - the target's attendee card and talks;
   - the viewer's internal notes about the target or their company (up to 5);
   - the viewer's shareable items matching the target's interests (up to 5; these become `plan.offers`);
   - the viewer's private goals;
   - past `encounter_summary` and `followup` records about that company.
2. **One** structured-output call returns `summary`, `plan` and a *recommended* `decision`.
3. **Guardrails (deterministic, applied after the LLM; every outcome goes into `decision.checks`):**
   - The target's company runs agents, otherwise downgrade `agent_handshake` to `human_intro`.
   - `match_score >= 40`, otherwise `skip`.
   - No internal note about the person tagged `do-not-contact`, otherwise `skip`.
   - `confidence >= 0.5`, otherwise `human_intro`.

### Agent decision (gateway `/api/swipe`)

- **Left:** remember the skip in memory and do nothing else.
- **Right:**
  1. Emit `deep_dive_started` to the viewer.
  2. Call the briefer's `/v1/deep-dive` (20 s timeout) and emit `deep_dive_ready` to the viewer.
  3. If the decision is `agent_handshake`, **and** `autonomy` is true, **and** the hourly limit allows it: create a connect request exactly like `/api/connect`, with `initiated_by="agent"` and `malicious` taken from the body. Emit `connect_request` to the target.
  4. Always emit `agent_decision`, with `request_id` when a request was sent.

## Seed additions (memory workstream)

- Attendee cards (`kind=attendee`) for all 12 personas, built from `personas.json`. Headlines must match `contracts/demo-research.json` for Bo, Priya, Mia and Lena.
- Talks linked to speakers with `about_persona_ids`:

  | Talk ID | Title | Time and room | Speaker |
  |---|---|---|---|
  | `talk-ebpf-cost` | Cutting the cloud bill with eBPF | 2:30 PM, Room A | lumenly.priya |
  | `talk-ebpf-edge` | eBPF on warehouse robots | 4:00 PM, Room C | kestrel.mia |
  | `talk-otel-regulated` | OpenTelemetry in regulated industries | 1:30 PM, Room B | harborline.lena |
  | `talk-inclusive-confs` | Designing conferences for everyone | 4:30 PM, Room A | lumenly.tom |

- **Demo check:** filtering Ava's deck by `ebpf` returns Bo first (with Acme history), then Priya and Mia.

## Tasks for running subagents (paste into Claude Code)

> Contract update v1.1 has landed on main (Discover). Pull main into your worktree (`git pull origin main`), then read docs/FEATURE-DISCOVER.md.
>
> - **rapport-memory:** add `/v1/research`, `/v1/deep-dive` and the seed additions.
> - **rapport-gateway:** add `/api/research`, `/api/swipe`, the agent decision, the rate limit and the new events. The swarm stream must exclude `deep_dive_*`.
> - **rapport-web:** add the Discover tab (filters, swipe deck with buttons and keys, deep dive panel, agent decision). Mock mode uses `contracts/demo-research.json` and the `upload`, `swipe` and `accept` phases in `contracts/demo-events.json`.
> - **Everyone else:** no change.
>
> Keep your existing PRs; add commits.

## Updated demo (3 minutes)

1. Ava uploads her CV. Her profile card appears.
2. **Discover:** filter by `ebpf` and research. Swipe left on Mia. Swipe right on Priya: the deep dive suggests *"catch her after her 2:30 talk"* (she has no agent). Swipe right on Bo: the deep dive and decision say agent handshake, with the reason and checks shown.
3. Bo's phone shows *"Ava's agent wants to connect"*, with **Malicious responder** on. Bo accepts.
4. The swarm runs: pods appear, rounds 1–3 run, and the red `pricing_needs_approval` chip appears.
5. Briefs arrive: private and shared, with Bo's in Spanish.
6. Ava asks *"What did we promise Bluefin?"*, and you show the Dash0 trace and the Radar view.

## Scope today

- **P0:** interest and has-agent filters, the deck with buttons, keys and drag, the deep dive and the decision.
- **P1:** role and company filters, and a drag animation.
- **P2:** feeding the plan's questions into the delegate's asks (needs an Encounter CRD change), and auto-accept on the target side.
