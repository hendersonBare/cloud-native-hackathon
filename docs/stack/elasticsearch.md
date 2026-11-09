# Elasticsearch

## What we use it for

Elasticsearch is Rapport's memory. The conference agenda, attendee cards, each company's documents and account notes, people's profiles, and the encounter summaries and follow-ups that agents write back all live in five indices from one index template. One search layer, hybrid BM25 plus `semantic_text` merged with RRF and optionally reranked, serves talk search, "ask my memory" answers with citations, Discover research, deep dives and the delegate's offers. Per-company indices and scoped API keys are one of Rapport's three independent security boundaries: a delegate's key can't read an internal index, whatever its code does. Speaker identification uses the same cluster for kNN over voiceprint vectors and for search by who said what.

## Where it lives

| Path | What it is |
|---|---|
| `deploy/elastic/index-template.json` | Template for `rapport-*`: keyword fields for routing and filters, `text_semantic` as `semantic_text` (a contract) |
| `deploy/elastic/role-descriptors/` | API key scopes: `briefer-<org>.json` and `delegate-<org>.json` (a contract) |
| `src/rapport_common/names.py` | `CONFERENCE_INDEX`, `shareable_index()`, `internal_index()` and `index_for()`, the only routing rule (a contract) |
| `src/rapport_common/models.py` | `MemoryRecord`, the shape of every document (a contract) |
| `src/rapport_common/interfaces.py` | `MemoryStore` protocol and the `InMemoryStore` used in tests and as the fallback |
| `src/rapport_memory/client.py` | `MemoryClient`: hybrid search, reranking, step-down fallback, validated bulk writes |
| `src/rapport_memory/__init__.py` | `store_from_env(indices)`: an index-restricted `MemoryClient`, or the seed data in memory |
| `src/rapport_memory/seed*.py` | Synthetic seed data (SPEC §11) and the loader `python -m rapport_memory.seed` |
| `src/rapport_delegate/memory.py` | The delegate's view: its own shareable index and the conference index, hard-wired |
| `src/rapport_briefer/core.py`, `src/rapport_briefer/__main__.py` | The briefer's view: its own internal and shareable indices plus the conference index |
| `src/rapport_gateway/remember.py` | Builds the `encounter_summary` and `followup` records written back after an encounter |
| `src/rapport_speakers/` | Speaker identification: index templates, key scopes, kNN decision rule, utterance search, erasure ([spec](../../speaker_identification_spec.md)) |

## How it works here

- **Five indices, one routing rule.** `rapport-conference` holds talks and attendee cards; `rapport-<org>-shareable` holds `public` and `partner` records; `rapport-<org>-internal` holds `internal` records such as account notes, private profiles, follow-ups and encounter summaries (SPEC §4.2). `names.index_for(record)` is the only routing rule (`src/rapport_common/names.py:77-84`). `MemoryClient.write` re-validates every record as a `MemoryRecord`, routes it with `index_for()`, and refuses the whole batch if any target index is outside the client's allowed set (`src/rapport_memory/client.py:217-240`).
- **Hybrid search.** `MemoryClient.build_body` (`src/rapport_memory/client.py:104-151`) sends an `rrf` retriever over two `standard` retrievers: a `multi_match` on `title^2`, `summary`, `text` and `tags`, and a `semantic` query on `text_semantic`, both with the same filters on tags, kind, `about_org_ids` and owner. The writer fills `text_semantic` with title, summary and text, and every search excludes it from `_source`.
- **Reranking.** When `ES_RERANK_INFERENCE_ID` is set, the RRF retriever is wrapped in a `text_similarity_reranker` on `text`. A 400 or 404 from the reranker turns it off for the process; any other error skips it for that call only; a 401 or 403 is raised, since it is a permission problem (`src/rapport_memory/client.py:183-206`).
- **Step-down, so search keeps working.** If Elasticsearch rejects a query shape, the client steps from `rrf` to one `bool` query with both clauses under `should`, then to keyword only, and remembers the mode.
- **Scoped API keys.** A delegate's key reads only `rapport-<org>-shareable` and `rapport-conference` (`deploy/elastic/role-descriptors/delegate-acme.json`). A briefer's key reads and writes its own internal and shareable indices and reads the conference index. In code, `store_from_env(indices)` builds a client that raises on any other index (`src/rapport_memory/__init__.py:17-38`, `client.py:70-76`), and the delegate's indices are hard-wired with no method that takes an index as input (`src/rapport_delegate/memory.py:23-42`). The delegate also filters to its own org's `public` and `partner` records before offering anything.
- **Only summaries cross.** A record's `summary` (400 characters or fewer) is the only text a delegate may send to another company; `text` never leaves.
- **The shared conference index is protected.** The briefer's `/v1/remember` drops records for another org and any record that would route to `rapport-conference`, so a caller can't forge someone's Discover card (`src/rapport_briefer/app.py:59-67`).
- **Memory that grows.** After each encounter, the gateway writes one `encounter_summary` and one `followup` record per follow-up through each person's own briefer (`src/rapport_gateway/remember.py`), so "What did we promise Bluefin?" includes what was promised today.
- **Never blocks the demo.** Without `ES_URL` and `ES_API_KEY` (the `es-briefer` or `es-delegate` Secret), `store_from_env` serves the seed records for the same indices from an `InMemoryStore`.
- **Speaker identification.** Five more indices, `rapport-speakers-sessions`, `-voiceprint-samples`, `-voiceprints`, `-utterances` and `-unknown-voices`, each from its own template at priority 600 (`src/rapport_speakers/elastic/index-templates.json`). Voiceprint centroids and unknown-voice embeddings are 192-dimension `dense_vector` fields with `dot_product` similarity on unit vectors, so the score maps to cosine. A kNN query on the voiceprints index, filtered by conference and model (`src/rapport_speakers/es_store.py:208-226`), feeds a decision rule: `identified` when the top cosine is at least `T_ACCEPT` and beats the runner-up by `MARGIN`, `ambiguous` when only the first holds, else `unknown`; too little speech is `unknown` (`src/rapport_speakers/decide.py:20-31`). Utterances carry a `semantic_text` field, and utterance search uses the same RRF, rerank and step-down pattern (`es_store.py:323-384`). Erasure deletes a person's voiceprints and samples and resets their utterances (`es_store.py:267-290`). The speaker store switches to Elasticsearch on its own only when its dedicated key, `SPEAKERS_ES_API_KEY`, is set; a generic `ES_API_KEY` is used only with an explicit `SPEAKERS_STORE=es` (`src/rapport_speakers/config.py:125-132`). Its key scopes are a pipeline role (`read`, `write`, `create_index` and `view_index_metadata` on the five speaker indices, plus `manage_index_templates`) and a reader role (read on utterances and sessions only) in `src/rapport_speakers/elastic/role-descriptors/`.

## What a reviewer should check in a PR

- Every Elasticsearch write goes through `MemoryRecord` validation and `names.index_for()`; no hard-coded index names; every record carries `org_id` and `share_level`.
- Delegate code reads only `shareable_index(self_org)` and `rapport-conference`, takes no index from input, never touches `internal_index`, the briefer or `es-briefer` credentials, and sends `summary`, never `text`.
- A client is built with an explicit `allowed_indices` list; widening it, or a role descriptor in `deploy/elastic/role-descriptors/`, is a contract change with a "Security review needed" section.
- No write path lets a caller put records into `rapport-conference` or into another company's index.
- Searches keep the same filters on both RRF retrievers and exclude `text_semantic` from `_source`.
- A 401 or 403 is never swallowed by a fallback; only query-shape errors step down.
- Spans and logs carry index names, document IDs, counts and the query mode; never query text, record text, transcript text, names or vectors.
- Speaker code uses `SPEAKERS_ES_API_KEY`, keeps vectors unit-length for `dot_product`, keeps erasure covering every biometric index, and treats voiceprints as biometric data in telemetry and logs.
- Talk times are stored in UTC and shown in America/Denver with their label.

## Evidence

- [PR #7](https://github.com/hendersonBare/cloud-native-hackathon/pull/7) (memory): the hybrid-search client, store factory and seed data. Gitar found that one transient Elasticsearch error switched the reranker off for good, and that a hard-coded "MST" label would be wrong in daylight time; both fixed in the PR (LOG 13:58 MST).
- [PR #8](https://github.com/hendersonBare/cloud-native-hackathon/pull/8) (briefer): Gitar found that `/v1/remember` could write into the shared conference index; fixed with regression tests (LOG 14:08 MST).
- [PR #14](https://github.com/hendersonBare/cloud-native-hackathon/pull/14) (speakers): speaker identification on Elasticsearch. LOG 14:41 MST: a synthetic fixture showed that the schedule-enrollment guards could enroll a co-presenter's voice under the scheduled speaker's name; the fixture now covers the guarded case and flags it for review. LOG 14:48 MST: speaker search would have picked up another pod's `ES_API_KEY`; auto mode now needs `SPEAKERS_ES_API_KEY`.
- LOG 14:12 MST, local run on the merged briefers with the seed store: `ebpf` ranks `talk-ebpf-zero-code` first; "What did we promise Bluefin?" cites `acme-note-0007`; Ava's eBPF deck is Bo (75), Priya (44), Mia (34); Bo calling Acme's briefer gets `403`.
- LOG 14:16 MST, full local stack, encounter `enc-b3293785`: after the encounter, "What did we promise Bluefin?" also cites the encounter summary and its follow-ups.
- LOG 14:41 MST, first encounter on Kubernetes, `enc-f629a19e`: the gateway wrote 6 follow-up records to each briefer.
