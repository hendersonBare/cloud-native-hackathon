# What Rapport costs to run

**Short answer:**

- **Today:** about **$1.50 of OpenAI credits** for the whole hackathon day with `gpt-6-luna`, or about $5 with the deprecated `gpt-5-mini`. Each participant has $50 in credits.
- **Everything else** runs on the trial or hackathon accounts for Elastic, Dash0, Radar and Gitar, plus kind on your laptop.
- **At conference scale:** roughly **5 cents per attendee** in LLM costs.

## Prices used (checked 9 Nov 2026)

| Item | Price | Source |
|---|---|---|
| `gpt-6-luna` (the kit's default) | $0.10 per 1M input tokens, $0.50 per 1M output, $0.01 cached input | OpenAI model page and pricing page |
| `gpt-5-mini` (marked deprecated) | $0.25 per 1M input, $2.00 per 1M output | OpenAI model page |
| Elastic Inference Service (embeddings) | from $0.08 per 1M tokens | Elastic Serverless pricing page |
| Elasticsearch Serverless | from $0.09 per search VCU-hour and $0.14 per ingest VCU-hour; storage $0.047 per GB-month | Elastic Serverless pricing page |

## Cost per operation

Token assumptions: reasoning effort is `low`, and reasoning tokens are counted as output.

| Operation | Tokens per call (in / out) | gpt-6-luna | gpt-5-mini |
|---|---|---|---|
| Research: 5 swipe cards (one batched call) | 3,000 / 900 | $0.0008 | $0.0026 |
| Deep dive after a right swipe | 6,000 / 1,500 | $0.0014 | $0.0045 |
| Agent-to-agent encounter (2 private briefs + 8 delegate calls) | 4,000 / 1,000 per brief; 1,500 / 600 per delegate call | $0.0054 | $0.0186 |
| CV or notes upload | 5,000 / 800 | $0.0009 | $0.0029 |
| Ask my memory | 4,000 / 700 | $0.0008 | $0.0024 |

## Totals

| Scenario | gpt-6-luna | gpt-5-mini |
|---|---|---|
| One demo run (10 cards, 3 deep dives, 1 encounter, 1 upload, 2 asks) | $0.013 | $0.045 |
| Hackathon day (300 research batches, 150 deep dives, 150 encounters, 50 uploads, 200 asks) | **$1.43** | $4.85 |
| Per attendee at a real conference (1 upload, 40 cards, 8 deep dives, 4 handshakes started, 10 asks) | **$0.047** | $0.158 |
| 2,000-attendee conference | **~$94** | ~$315 |

**Embeddings:** about 5,000 tokens per attendee (CV chunks and cards) comes to about 10M tokens for 2,000 people, about $0.80 at $0.08 per 1M.

**Not modelled:**

- Elasticsearch VCU-hours, Dash0 ingest and the Kubernetes nodes. These are usage-based, so check the vendors' pricing pages for a real event.
- Claude usage for your subagents, which is billed to your Claude plan, not OpenAI.

## What keeps it cheap (already in the design)

- **Research is batched:** one LLM call writes `why_meet` for a whole deck, and results are cached per (viewer, target).
- **The expensive work only runs on intent:** a deep dive happens only on a right swipe, and a handshake only when guardrails pass and the other person accepts.
- **Deterministic first:** search, filters, match scores, policy and the brief structure involve no LLM. The LLM writes only short text.
- **Hard caps:** 5 agent handshakes per person per hour, 8 s LLM timeouts with template fallbacks, and short `max_length` limits on every model field.
- **One environment variable switches models:** `RAPPORT_LLM_MODEL`.
