# Open-source helpers and light models for importance gating

Researched 9 Nov 2026. Items marked **verify** were found in docs or articles but not yet run against our accounts.

## 1. Open-source projects worth using today

Sorted by how much time each saves *today*. Anything that adds a new service or a large model download is in the "consider, don't adopt" table.

### Adopt (cheap, no new services)

| Project | What it gives us | Where it fits | Effort |
|---|---|---|---|
| **Elastic preconfigured Jina reranker** (`text_similarity_reranker` retriever; `.jina-reranker-v3` or `.jina-reranker-v3.5` on EIS, **verify** with `GET _inference/_all`) | A hosted small cross-encoder. No download, no GPU, priced per token. | Talk search, ask-my-memory, and the importance gate (§3) | 15 min |
| **Elasticsearch `rank_feature` field and query** | Built-in static boosts by a per-document score | Stores the importance score; boosts it at query time | 10 min (contract change) |
| **elasticsearch-py native OpenTelemetry spans** (built into the client since 8.13; query capture off by default) | ES calls show up in the Dash0 trace with no extra code | Every service that searches | 0 min: already installed. Keep `OTEL_PYTHON_INSTRUMENTATION_ELASTICSEARCH_CAPTURE_SEARCH_QUERY` unset. |
| **Dash0 Web SDK** ([`dash0hq/dash0-sdk-web`](https://github.com/dash0hq/dash0-sdk-web), OTel-based, open source) | RUM: page loads, sessions, errors, fetch spans linked to backend traces | `web/index.html` | 10 min |
| **Elastic Agent Builder + MCP server** (`/api/agent_builder/mcp`) | An agent with an ES\|QL tool over our indices, usable from Claude Code | Elastic track evidence, plus a handy debugging tool | 15 min, no app code |
| **Regal** ([`StyraInc/regal`](https://github.com/StyraInc/regal)) | Rego linter | `policy/` CI step next to `opa test` | 5 min |
| **Radar cnh-starter skills** ([`skyhook-io/cnh-starter`](https://github.com/skyhook-io/cnh-starter) `.agents/skills/`) | Ready-made agent instructions for shipping and checking through Radar MCP | Copy into `.claude/` so our coding agents use Radar MCP, not raw `kubectl` | 10 min |
| **dash0-examples/openlit** ([repo](https://github.com/dash0hq/dash0-examples/tree/main/openlit)) | A known-good OpenLIT → Dash0 wiring | Reference if LLM spans don't appear | Reference only |
| **elasticsearch-labs notebooks** ([repo](https://github.com/elastic/elasticsearch-labs)) | Working RRF and rerank examples | The memory workstream | Reference only |

### Consider, don't adopt today (put them in the "future work" slide)

| Project | Why it's relevant | Why not today |
|---|---|---|
| **kubernetes-sigs/agent-sandbox** (Sandbox CRD, warm pools, SIG Apps) | Same idea as our Encounter → delegate pods, with warm pools that remove cold start | Changes the operator contract. Good answer to "why a custom CRD?": ours encodes the *two-party encounter* and per-encounter NetworkPolicy, which a generic sandbox doesn't. |
| **kagent** (CNCF Sandbox, agents on Kubernetes) | Declarative agents and tools as CRDs | Replaces too much of our stack mid-day |
| **Mem0** (Apache-2.0) | Memory layer that scores recency × importance × similarity | We do the same scoring *inside Elasticsearch* (§3), which keeps one data layer, the per-company index boundary and the Elastic track story |
| **Llama Prompt Guard 2** (22M, DeBERTa-xsmall; 86M multilingual) and **ProtectAI deberta-v3-base-prompt-injection-v2** | Small classifiers that flag prompt injection in counterparty text | Adds torch or onnxruntime plus a model download to every delegate pod, which hurts cold start. Prompt Guard is gated behind a license acceptance on Hugging Face. Our deterministic tag matching already stops the demo attack. |
| **Presidio** (now at `data-privacy-stack/presidio`) **+ GLiNER-PII** | Better PII redaction than regex | spaCy or GLiNER models add hundreds of MB. The demo CV is synthetic, so regex is enough today. |
| **LLMLingua-2** (Microsoft) | Compresses prompts by dropping low-information tokens | The model is about 560M parameters. Our gate drops whole low-value chunks, which is simpler and saves more here. |
| **A2A protocol** | Standard agent-to-agent wire format | Out of scope per the spec. `rapport.exchange/v1` could be wrapped in A2A later. |

---

## 2. Light-model importance gating: the idea

Rapport's main model is already the cheapest tier (`gpt-6-luna`). So "lighter" means **putting deterministic rules and small, hosted, task-specific models in front of the LLM**, so the LLM sees less and better context. The kit already does this in places: the Discover `match_score`, deep dive only on a right swipe, and tag matching before any LLM call. We extend the pattern into a three-gate ladder:

```
            cheap ──────────────────────────────────────────────▶ expensive
   rules (regex, tags, dedupe) → small hosted models in Elastic → gpt-6-luna
             (free, μs)              (rerank and embed, cents)    (only what survived)
```

| Gate | Question it answers | Where it runs | Light model |
|---|---|---|---|
| **G1: ingest** | Is this chunk worth remembering, and how important is it? | briefer `/v1/context`, `/v1/remember` | Jina reranker on EIS scores each chunk against the owner's goals and interests |
| **G2: context** | Which memories go into *this* prompt, within a token budget? | briefer (brief, ask, deep dive), delegate (offers) | Jina reranker via `text_similarity_reranker`, plus importance and recency |
| **G3: untrusted input** | Is the counterparty trying to steer us? | delegate, on received `Ask.text` | Rules today. Prompt Guard 2 is the stretch goal. |

Nothing here **trains** a model. If you fine-tune later, G1's scores make a ready-made data-curation filter.

---

## 3. G1: importance at ingest (the Elastic-native version)

**Contract change needed (integrator, SPEC §10).** It's additive and non-breaking:

```python
# src/rapport_common/models.py, MemoryRecord
importance: float | None = Field(default=None, gt=0, le=1)  # set by the briefer's ingest gate; None = unscored
```

```json
// deploy/elastic/index-template.json → mappings.properties
"importance": { "type": "rank_feature" }
```

`rank_feature` values must be positive, hence `gt=0`. Floor real scores at 0.01. Seed records can leave the field as `None`.

**Pipeline** (inside the existing §4.3 steps, after redaction and chunking):

1. **Rules, free:** drop chunks under 80 characters, boilerplate (for example "References available on request"), and near-duplicates of a chunk already stored for this person. For duplicates, run a `semantic` query on the chunk text against the owner's own records and treat the top hit's score as a duplicate above a threshold you tune once.
2. **Small model, one call per upload:** score every surviving chunk against what the owner cares about:

   ```http
   POST _inference/rerank/.jina-reranker-v3
   { "query": "<owner goals + interests + looking_for, joined>",
     "input": ["<chunk 1>", "<chunk 2>", "..."] }
   → { "rerank": [ { "index": 1, "relevance_score": 0.91 }, { "index": 0, "relevance_score": 0.22 }, ... ] }
   ```

   **Verify** the response shape and the Python helper in the installed `elasticsearch` client (`es.inference.rerank(...)`, or `es.perform_request` as a fallback) before relying on it.
3. **Decide:** `importance = max(0.01, relevance_score)`. Keep the top chunks until they cover 70% of the total score, with at least 3. Drop the rest; don't index them.
4. **Only the kept chunks** go to the `ProfileInfo` LLM call. That cuts input tokens on the most expensive step of the upload.
5. **Telemetry (counts only):** set `rapport.context.candidates`, `rapport.context.kept` and `rapport.context.dropped` on the `context.ingest` span. These need new constants in `rapport_common.telemetry`, which is part of the same contract change.

`/v1/remember` (encounter summaries and follow-ups) uses the same gate. Follow-ups always get `importance = 1.0`, because a promise is never low-value.

## 4. G2: context packing for every LLM call

Today: hybrid RRF → top 5 → prompt. Proposed:

1. **Retrieve wider:** RRF with `size: 20`, plus a `rank_feature` boost on `importance` inside the BM25 leg's `bool.should`:

   ```json
   {"rank_feature": {"field": "importance", "saturation": {}, "boost": 0.5}}
   ```

2. **Rerank against the actual task**, not the user's words. For a brief, the inference text is "meeting {counterparty name} from {org} about {mutual interests}":

   ```json
   {"retriever": {"text_similarity_reranker": {
       "retriever": {"rrf": { "...": "existing two retrievers" }},
       "field": "summary",
       "inference_id": ".jina-reranker-v3",
       "inference_text": "<task description>",
       "rank_window_size": 20 }}}
   ```

3. **Pack to a budget** in Python. The score is the Generative Agents and Mem0 recipe: relevance + importance + recency.

   ```python
   score = 0.6 * rerank_norm + 0.25 * (record.importance or 0.5) + 0.15 * 0.5 ** (age_hours / 24)
   ```

   Add records by score until about 1,500 tokens (estimate `len(text) / 4`). Use `summary` instead of `text` when a record doesn't fit.
4. **Telemetry:** `rapport.context.candidates`, `rapport.context.kept`, `rapport.context.tokens`. Together with OpenLIT's token counts, Dash0 can show **tokens saved per encounter**, which is a cost story for both Dash0 and Elastic.

The delegate's offers use the same pattern on its shareable index only. The gate never widens what a delegate can read; it only narrows it.

## 5. G3: untrusted counterparty input

- **Today (rules, 10 min):** in the delegate, flag `Ask.text` that matches injection patterns ("ignore (all|your) previous", "system prompt", "attach … internal", role-play markers). Add `suspected_injection` to the `exchange_message` display line, so the swarm shows a yellow chip *before* OPA's red deny. That's defence in depth on screen. The text still never enters system instructions (the house rule).
- **Stretch:** run Prompt Guard 2 22M or ProtectAI deberta-v2 as a classifier with the same flag. Load it lazily, only when `Ask.text` is non-empty, and note the image-size cost in the PR.

## 6. Who builds what

| Item | Owner | Size |
|---|---|---|
| `importance` field, template mapping, telemetry constants | integrator (contract change) | S |
| G1 ingest gate | memory (briefer) | M |
| G2 rerank + `rank_feature` boost + packer | memory (`rapport_memory` search) | S–M |
| G2 in delegate offers | delegate | S |
| G3 rules and display flag | delegate | S |
| Dashboard panel "tokens saved by gating" | integrator (Dash0) | S |

If time is short, do only **G2's reranker** (one JSON change). It's the biggest relevance gain and it's visible in the Elastic demo.

## Sources

- [Elastic semantic reranking](https://www.elastic.co/docs/solutions/search/ranking/semantic-reranking) and [`text_similarity_reranker`](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers/text-similarity-reranker-retriever)
- [ES\|QL `RERANK`](https://www.elastic.co/docs/reference/query-languages/esql/commands/rerank)
- [Mem0 paper](https://arxiv.org/html/2504.19413v1) and [RAG vs memory (scoring formula)](https://mem0.ai/library/agent-memory/rag-vs-ai-memory)
- [Prompt injection detection models compared](https://www.armosec.io/blog/prompt-injection-detection-models/), [ProtectAI deberta-v3](https://huggingface.co/protectai/deberta-v3-base-prompt-injection)
- [Presidio vs GLiNER (2026)](https://particula.tech/blog/presidio-vs-gliner-pii-redaction-llm)
- [Kubernetes Agent Sandbox](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox/), [kagent](https://kagent.dev/)
- [Dash0 Web SDK](https://www.dash0.com/hub/integrations/int_dash0_sdk_web/overview)
