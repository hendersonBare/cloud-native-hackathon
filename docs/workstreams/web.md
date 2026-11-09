# Workstream: web (the two-phone demo page)

**Mission.** One page at `/` that *is* the demo. It has two phone frames side by side (left: the persona with `demo_phone: "left"`, Ava; right: Bo) and a **swarm panel** in the middle that shows the agents meeting.

**You own:** `web/` only. The page is plain HTML, CSS and JavaScript ES modules, with no build step. Use `index.html`, `app.js`, `styles.css` and `mock/`.

**Read first:** `AGENTS.md`, SPEC §2, §4.3 and §7.1, and `contracts/demo-events.json`.

## Build (P0, in this order)

1. **Mock mode first.** Copy `contracts/demo-events.json` to `web/mock/demo-events.json`. With `?mock=1`, clicking **Accept** replays the events using `at_ms`, dispatched to the same render functions the live mode uses. You can now build everything without a backend.
2. **Layout.**
   - A presenter toolbar on top with a **Malicious responder** checkbox (sets `ConnectBody.malicious`), **Reset demo** (`POST /api/demo/reset`) and a mock-mode badge.
   - Below it: the left phone, the swarm panel and the right phone. It must fit a 1440×900 projector without scrolling.
3. **Phone tabs:**
   - **Home:** the person's profile card plus a **Connect** list of the other personas.
   - **My agent:** upload a file (`.pdf`, `.md`, `.txt`) or paste text, choose **Share with people I meet** or **Private to my agent**, send `POST /api/context` (multipart), then show the shareable and private profile cards side by side, each clearly labelled.
   - **Briefs:** the private brief card ("only you see this"), the shared brief card, follow-ups and the suggested talk.
   - **Ask:** "Ask my memory" (`POST /api/ask`), showing the answer and its citations, plus talk search (`GET /api/talks`).
4. **Live mode.**
   - Open three `EventSource`s: `/api/stream?persona_id=<left>`, `/api/stream?persona_id=<right>` and `/api/stream?view=swarm`.
   - A `connect_request` shows an Accept/Decline sheet on the target phone; Accept sends `POST /api/connect/{id}/accept`.
5. **Swarm panel.**
   - A header showing initiator ↔ responder.
   - Two lanes, `org-acme` and `org-bluefin`, with pod chips (`pod_status`: Pending, Running, Succeeded).
   - A timeline of `exchange_message` events with round badges 1, 2 and 3.
   - `policy_decision` chips: allow is green with ✓; deny is red with ✕ and shows the `rule_id`.
   - `encounter_completed` closes it out.
6. **Accessibility** (Merge Forward judges this):
   - Semantic HTML with `aria-live="polite"` on briefs and the swarm timeline.
   - Everything works by keyboard, with a visible focus ring.
   - Never rely on colour alone (deny has an icon and text). Keep contrast at 4.5:1 or better and base font at 16px or larger.
   - Set the `lang` attribute on brief containers (`es` for Bo).

## Interfaces

You consume the gateway API (SPEC §7.1) and `GatewayEvent` shapes (`rapport_common.models`). You provide nothing to other components.

## Done when

- `?mock=1` plays the full demo end to end with no console errors.
- Live mode works against the deployed gateway (https://rapport.cnh.radarhq.io) and a local one (`http://localhost:8080`). Use relative URLs (`/api/...`) so both work.
- A keyboard-only run of the demo works.
- The PR includes two screenshots: mid-exchange and final briefs.

## Gotchas

- Render every server string with `textContent`, never `innerHTML`. Counterparty text is untrusted and could carry an XSS payload.
- `EventSource` reconnects on its own. Dedupe events by `type + ts + encounter_id`.
- A `private_brief` renders only on the phone whose `persona_id` matches.
- **RUM (P1):** add Dash0 website monitoring following Dash0's web SDK docs. Don't commit tokens; ask the integrator how to inject the config.

**Out of scope:** real camera or QR scanning, frameworks and build tooling, real phones.

## Discover (v1.1, added 12:00 PM): read `docs/FEATURE-DISCOVER.md`

1. **New Discover tab** on each phone:
   - Filter chips: interests from the directory, plus a **Has an agent** toggle. Role and company filters are P1.
   - A **Research** button that calls `POST /api/research`.
2. **Swipe deck:**
   - Each card shows name, title, company, headline, match score, shared interests, **why meet**, their talks, *your company's history* (private) and an **Agent available** badge.
   - Swipe with drag (pointer events), the ✕ and ✓ buttons, or the ← and → keys.
   - Screen-reader labels read "Skip Bo" and "Interested in Bo".
   - Swiping sends `POST /api/swipe`, using the presenter toolbar's **Malicious responder** and a phone-level **Let my agent act for me** toggle (`autonomy`).
3. **Deep dive panel:**
   - Show "Researching…" on `deep_dive_started`.
   - On `deep_dive_ready`, show the summary, plan (goals, offers, questions, watch-outs, opener) and the decision, with its reason and checks.
   - On `agent_decision`, show "Request sent to Bo's agent, waiting for Bo" or the human-intro suggestion.
4. **Connect sheet:** the target's sheet says **"Ava's agent wants to connect"** when `initiated_by == "agent"`.
5. **Mock mode:** the deck comes from `mock/demo-research.json` (a copy of `contracts/demo-research.json`). Replay `demo-events.json` by phase: `upload`, then `swipe` (after a right swipe on Bo), then `accept`.

**Done when:** in mock mode the full new demo plays: upload → research → swipe left on Mia → right on Bo → deep dive → Bo accepts → handshake → briefs. It must also work by keyboard only.
