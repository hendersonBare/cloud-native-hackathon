# Workstream: memory (Elasticsearch, seed data and the briefer service)

**Mission.** Make Elasticsearch the brain. You build:

- The hybrid-search client.
- The demo's seed data.
- The **briefer**: each company's private memory API, covering private briefs, ask, talk search, CV and context upload, and remember.

**You own:**

- `src/rapport_memory/`: `client.py`, `seed.py`, `redact.py`, `profiles.py`.
- `src/rapport_briefer/`: the FastAPI app and `__main__.py`.
- `seed/`: data files plus `ava-cv-synthetic.md`.
- `deploy/briefer/`: one Deployment and one Service named `briefer` in **each** of `org-acme` and `org-bluefin`, listed in `deploy/briefer/kustomization.yaml`. Image `app`, label `rapport.dev/role: briefer` (the NetworkPolicy lets only the gateway in), resources `names.RESOURCES_SERVICE` (requests **and** limits), `names.SECURITY_CONTEXT`, `automountServiceAccountToken: false`, and `envFrom` the `openai`, `dash0-otlp` and `es-briefer` Secrets.
- `tests/memory/` and `tests/briefer/`.

**Read first:** `AGENTS.md`, SPEC §4.2, §4.3, §7.2 and §11, and `rapport_common/interfaces.py`.

## Build (P0, in this order; tell the integrator when step 2 lands)

1. **`MemoryClient(es_url, api_key)`** implementing `MemoryStore` (`search`, `get`, `write`):
   - Use the hybrid RRF recipe in SPEC §4.2, with the fallback.
   - `write` upserts by `memory_id` into `names.index_for(record)` and sets `text_semantic`.
   - Strip `text_semantic` before validating `_source`.
2. **Seed** (`python -m rapport_memory.seed`, run by `make seed` with the admin key): every record in SPEC §11, upserted idempotently, printing counts per index. **Target: merged by 1:15 PM.**
3. **Briefer service** (`python -m rapport_briefer`, env `RAPPORT_ORG_ID`, ES key from the `es-briefer` secret):
   - `GET /v1/talks`: hybrid search on `rapport-conference`, boosted by the person's interests, returning `TalkSearchResult`.
   - `POST /v1/ask`: RAG over own internal, own shareable and conference indices. The answer must cite `memory_id`s; return `AskAnswer`. *"What did we promise Bluefin?"* must cite `acme-note-0007` and, after an encounter, the `followup` records.
   - `POST /v1/brief`: builds a `PrivateBrief` in the person's language from:
     - the counterparty's **directory** entry (`names.persona`);
     - own-company notes about them (`about_org_ids` / `about_persona_ids`);
     - own shareable docs relevant to their interests;
     - the person's private goals (`goal_matches`);
     - suggested talks from the intersection of interests.

     The briefer **never reads another company's indices**. Anything the other side chose to share arrives through the exchange.
   - `POST /v1/context` and `GET /v1/profile`: the pipeline in SPEC §4.3. Redact contact details **before** the LLM call and before indexing. Return `PersonaProfile`.
   - `POST /v1/remember`: reject records whose `org_id` isn't yours; write the rest.
   - Return 403 for personas of other companies.
4. **LLM:** use OpenAI structured outputs (`RAPPORT_LLM_MODEL`) with an 8 s timeout. Fall back to templates built from the search hits so a brief always comes back, within 5 s for the SLO.

## Interfaces

- **You provide:** `MemoryClient` (the delegate workstream imports it) and the briefer API (the gateway calls it).
- **You consume:** Elasticsearch and OpenAI.

## Done when

- `make seed` prints non-zero counts for all 5 indices.
- Unit tests use `InMemoryStore`, including redaction tests: emails and phone numbers are gone from what is indexed and what is sent to the LLM.
- Locally (`BRIEFER_URL_*` overrides) and, after merge, in the team vcluster:
  - `/v1/talks?q=ebpf` returns `talk-ebpf-zero-code` first.
  - The ask above cites `acme-note-0007`.
  - Uploading `seed/ava-cv-synthetic.md` returns a profile.
  - A delegate-scoped key gets a 403 on `rapport-acme-internal`. Note this in the PR; it's a nice demo proof.

## Gotchas

- Use elasticsearch-py 9.x and check its docs for `retriever=` support in `search()`. On Serverless, don't set shard or replica settings.
- `semantic_text` runs inference at index time, so the first seed can take a minute.
- PDFs: `pypdf` only. Scanned PDFs have no text, so say so in the response rather than failing.

**Out of scope:** reading other companies' data, deleting indices, audio.

## Discover (v1.1, added 12:00 PM): read `docs/FEATURE-DISCOVER.md`

1. **Seed:** add `kind=attendee` cards for all 12 personas (`names.attendee_card_id`) and the four speaker-linked talks. Headlines must match `contracts/demo-research.json`.
2. **`POST /v1/research`:** the research algorithm, with **one** batched LLM call for `why_meet` and a cache per (viewer, target).
3. **`POST /v1/deep-dive`:** one LLM call, then the deterministic guardrails. Record every guardrail outcome in `decision.checks`.

**Done when:** Ava's research with `interests=["ebpf"]` returns Bo first with `company_history` citing `acme-note-0007`, then Priya and Mia. A deep dive on Bo returns `agent_handshake`; on Priya it returns `human_intro` (no agent).
