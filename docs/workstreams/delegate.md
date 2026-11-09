# Workstream: delegate (the agent that meets the other company's agent)

**Mission.** Implement `rapport.exchange/v1` (SPEC §5). It's one program that runs as either the **initiator** or the **responder**, inside a short-lived Job pod, with a key that can read only shareable memory.

**You own:** `src/rapport_delegate/` (`__main__.py`, `protocol.py`, `policy.py`, `llm.py`) and `tests/delegate/`.

**Read first:** `AGENTS.md`, SPEC §4.3–§4.4, §5, §6 and §8, and `rapport_common/models.py`.

## Build (P0)

1. **Config from env** (SPEC §4.4): `ROLE`, `ENCOUNTER_ID`, `SELF_*`, `PEER_*`, `PEER_URL`, `MALICIOUS`, `TRACEPARENT` and the ES delegate key. `PORT` defaults to 8080; override it only for local runs.
2. **Memory access:**
   - `MemoryClient` from the memory workstream with `indices=[shareable_index(SELF_ORG), CONFERENCE_INDEX]`. Hard-wire this and never accept an index from input.
   - Until it merges, use `InMemoryStore`.
   - Your person's card comes from the shareable profile record `profile-<persona>-shareable` plus the directory.
3. **`policy.py`:** `POST {opa_url(SELF_ORG)}/v1/data/rapport/decision`. Fail closed after 2 s, returning deny with `opa_unavailable`. Ship a `FakePolicy` for tests that implements the SPEC §6 table.
4. **Responder:**
   - A FastAPI app with `GET /healthz` and `POST /v1/exchange`.
   - Validate the inbound message with `ExchangeMessage` (return 422 if invalid) and reply with your message for the same round.
   - After the round-3 response has been **sent**, post your `shared_brief`, stop the server, call `shutdown_telemetry()` and exit 0.
5. **Initiator:**
   - Wait for `PEER_URL/healthz`, then run the three rounds.
   - Post `exchange_message`, `policy_decision` and `delegate_status` events throughout.
   - Build the `SharedBrief` and post it, then shut down telemetry and exit 0. Exit non-zero on failure, after posting `failed`.
6. **Round logic** exactly as SPEC §5:
   - Offers are checked with OPA `offer`.
   - Asks map to topics; malicious mode injects the pricing ask.
   - Answers use **tag-match first** candidates, then OPA `answer`.
   - Follow-ups must include one "attend `<talk>` together".
7. **LLM** (`llm.py`): structured outputs with pydantic and an 8 s timeout, with rule-based fallbacks. Counterparty strings appear only inside a delimited **data** block in the user message, never in system instructions. Drop any `item_id` that isn't in the candidate set.
8. **Telemetry:** a root span `exchange.run` with parent `context_from_traceparent(TRACEPARENT)`; child spans `exchange.round` and `policy.check`; metric `rapport.policy.decisions`. httpx instrumentation carries the trace into the responder.

## Done when

`pytest` runs a **full in-process exchange**: initiator ↔ responder over `httpx.ASGITransport`, an `InMemoryStore` seeded with the SPEC §11 records, `FakePolicy`, and the gateway mocked with `respx`. It must assert that:

- In malicious mode, the pricing ask is declined with `pricing_needs_approval`.
- `acme-doc-0008` and any record `text` never appear in any message sent.
- Both `SharedBrief`s validate, and Bo's has `language == "es"`.
- Events were posted in order: started → messages → shared_brief → done.

## Gotchas

- `activeDeadlineSeconds` is 120, so keep the whole run under 90 s.
- Don't exit before your round-3 HTTP response has been flushed. Use a background task to stop the server after responding.
- Spans from short-lived pods are lost without `shutdown_telemetry()`.

**Out of scope:** Kubernetes API access (the pod has no service account token), writing to Elasticsearch, A2A.
