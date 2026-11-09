# Rapport: your agent meets their agent

**Cloud Native Hackathon, Salt Lake City. Theme: make conferences easier.**

**One line:** every attendee gets a personal agent with a private memory. When two people connect at a conference, their agents meet on Kubernetes and swap only what each side allows. Both people then get a brief, shared follow-ups and a talk to attend together.

## The problem

You meet 30 people at a conference, remember 5 and follow up with 2. The useful context is scattered across CVs, CRMs, call notes and people's heads. Sharing it is either too slow (an email a week later) or too risky (oversharing with a prospect).

## The demo (one web page, two phones side by side)

Ava (Acme Observability, a vendor) is on the left phone. Bo (Bluefin Health, a prospect) is on the right. Both are fictional, with synthetic data.

1. **Personal context.** Ava drops her CV into the **My agent** tab and marks it *share with people I meet*. She adds a private note: *looking for a healthcare design partner*. Her profile card updates.
2. **Discover.** Ava filters attendees by `ebpf`. Her agent researches each person and builds a swipe card with a summary, why they should meet, the talks the person is giving and her company's history with them. She swipes left on Mia. When she swipes right on Bo, her agent does a **deep dive** (goals, what to offer, questions and an opening line). It then **decides** to start an agent-to-agent handshake and shows its reasoning. Bo's phone says *"Ava's agent wants to connect"*, and Bo taps **Accept**. Both people consent.
3. **The swarm.** An `Encounter` resource appears, and one delegate pod starts in each company's namespace. You can watch this in the centre panel and in Radar.
4. **Agents meet.** The delegates exchange hello, then offers and asks, then answers and follow-ups. Each company's policy checks every item before it leaves.
5. **Briefs.** Within seconds, each phone gets two briefs:
   - A **private brief** built from that person's company memory and private profile, for example: *"they're evaluating a competitor; Sam still owes them a security questionnaire."*
   - A **shared brief** with mutual interests, shared documents, follow-ups and a talk to attend together. Bo's arrives in Spanish.
6. **The attack.** With *malicious agent* switched on, Bo's agent tries a prompt injection to get Acme's pricing. Acme's policy denies it, shown in red, and the Dash0 trace shows exactly which rule fired.
7. **Memory.** Ava asks *"What did we promise Bluefin?"* and gets an answer with citations. *"Find me a talk on eBPF"* runs a hybrid search over the agenda.

## Why it's safe by design

Each person has two agents:

| | Briefer (private) | Delegate (public) |
|---|---|---|
| Sees | Company-internal memory, private profile | Only shareable memory and the shareable profile |
| Talks to | Only its own person | The other company's delegate |
| Lives | A long-running service in the company namespace | A short-lived pod for one encounter |

Three independent layers enforce the boundary:

- **Elasticsearch API key scopes:** a delegate's key cannot read internal indices.
- **Kubernetes NetworkPolicy:** nothing from another company can reach a briefer.
- **OPA policy:** every item that leaves is checked.

The delegate can't leak what it never saw. Agents only propose follow-ups; people confirm them.

## Tracks

| Track | What judges look for | What we show |
|---|---|---|
| **Elasticsearch: Find the Right Talk** | ES as the core data layer; keyword, semantic or hybrid search | All memory, profiles, agenda and follow-ups live in ES. Hybrid search (BM25 + `semantic_text`, merged with RRF) powers talk search, briefs and "what did we promise". Per-company indices plus scoped API keys form the security boundary. |
| **Dash0: Stop Flying Blind** | Deep OTel (traces, metrics, logs, RUM); Agent0 or MCP used on a real issue; dashboard or SLO | One trace runs from the click, through the gateway, the Encounter, both delegate pods and the OPA decisions, to the brief. OpenLIT records LLM cost per encounter. RUM covers the web page. An SLO says "95% of private briefs within 5 s", plus a dashboard. We show Agent0 finding a real issue we hit today. |
| **Radar: AI SRE** | Runs on Kubernetes with Radar connected; Radar UI and MCP used; AI investigation of a real issue | The swarm is visible in Radar (namespaces, Jobs, NetworkPolicies). We show a Radar AI investigation of a real failure from today. |
| **Sonar / Gitar: Never Merge Broken** | Gitar reviewed features landing through PRs; repo rules; CI diagnosis | Six subagents each ship their workstream as a PR. Gitar reviews every one against our repository rules (`.gitar/rules/`), and CI runs on each PR. |
| **Merge Forward: Conferences for Everyone** | Inclusive and accessible | Briefs come in each person's language. Conversation starters help people who find networking hard. The UI is accessible: keyboard, screen reader labels and contrast. You don't have to remember names or context. |
| **Best overall** | Strongest project | All of the above in a 3-minute live demo. |

## What it costs

About **$1.50 in OpenAI credits** for the whole hackathon day with `gpt-6-luna`. At a real conference it's about **5 cents per attendee** in LLM costs. Details are in `docs/COSTS.md`.

## Scope for today (about 6 hours)

**In scope:**

- The two emulated phones and the swarm panel.
- Personal context upload (PDF, text or Markdown).
- The agent handshake with policy.
- Private and shared briefs.
- Talk search and "ask my memory".
- Dash0 traces and an SLO.
- Radar and Gitar.

**Out of scope:**

- Live audio captions.
- Real phones and QR codes.
- Warm pools.
- Per-encounter API keys.
- The A2A protocol.
