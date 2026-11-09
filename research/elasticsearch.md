# Elasticsearch: research notes for the Cloud Native Hackathon

Researched 2026-11-09. Sources are linked inline.

## 1. Elastic's part in this hackathon

From the [hackathon page](https://www.wemakedevs.org/hackathons/cnh) and its [resources page](https://www.wemakedevs.org/hackathons/cnh/resources):

- **Track 4: "Find the Right Talk" (search and vector database). $4,000 cash.**
- The theme for every track is "make conferences better". A project can enter more than one track. Every project is also in the running for best overall (an NVIDIA DGX Spark).
- **What the judges look for:**
  1. Elasticsearch is the core data layer of the app, not a side feature.
  2. Smart use of search: keyword, semantic, vector or hybrid.
  3. How well the project makes conferences easier.
- **Ideas Elastic suggested:**
  - Talk search where "something on eBPF and security" finds the right session even when those words aren't in the title.
  - A hallway matchmaker that stores what everyone is working on as vectors and finds the closest matches.
  - A conference assistant that answers schedule questions with RAG over every talk abstract.
- **Setup:** use the [free Serverless trial](https://ela.st/hack-kubecon) and pick the **Elasticsearch** project type. The FAQ also says to have Docker and a Kubernetes cluster ready for this track (kind, k3d or minikube is fine).
- **Features Elastic wants you to use:** store your data in Elasticsearch; make embeddings with **Jina** (built into the Cloud service); query keyword, vector, time-series or geo data; build aggregations and dashboards; use **Elastic Workflows** or **Agent Builder**, including MCP.
- They also point to [Elastic Agent Skills](https://github.com/elastic/agent-skills), which help coding agents use Elastic well.

## 2. What Elastic is and what it sells

**Elastic N.V.** (NYSE: ESTC) calls itself "the Search AI Company". Its homepage now reads "Elasticsearch: The search database for AI." ([elastic.co](https://www.elastic.co/))

### The platform ("Elastic Stack")

| Component | What it is |
|---|---|
| **Elasticsearch** | A distributed search, analytics and vector database built on Apache Lucene. It stores text, numbers, geo data, timestamps and vectors, and makes new data searchable almost immediately. |
| **Kibana** | The web UI for exploring data, building dashboards and managing the platform. Agent Builder and Workflows live here. |
| **Logstash, Beats, Elastic Agent** | Tools that ship data into Elasticsearch. |
| **Jina AI** | Embedding and reranking models. Elastic acquired Jina, and the models are now served by the Elastic Inference Service (EIS). |
| **Elastic Inference Service (EIS)** | Managed, GPU-backed inference for embeddings, reranking and LLMs. It is on by default in Cloud. |
| **Agent Builder** | A framework for building agents and tools on top of your Elasticsearch data. Covered in section 4. |
| **Elastic Workflows** | An automation engine inside Kibana. Workflows and agents can call each other. |

### Three solutions built on the platform

1. **Elasticsearch (Search and AI):** vector, hybrid and semantic search, RAG, search apps and e-commerce search.
2. **Elastic Observability:** logs, metrics, traces, APM, OpenTelemetry and LLM observability.
3. **Elastic Security:** SIEM, endpoint protection (XDR) and cloud security.

### Ways to deploy it

- **Elastic Cloud Serverless:** fully managed and autoscaling. This is what the hackathon trial gives you.
- **Elastic Cloud Hosted:** managed clusters on AWS, Google Cloud or Azure.
- **Self-managed:** run it yourself, including on Kubernetes with the ECK operator.

### License

The core of Elasticsearch and Kibana is dual-licensed under **AGPL v3** (an OSI-approved open source license) and the **Elastic License 2.0**. Elastic added the AGPL option in 2024, after moving away from Apache 2.0 in 2021, the move that led AWS to fork the code as OpenSearch. ([elastic.co FAQ](https://www.elastic.co/), [10-K](https://www.sec.gov/Archives/edgar/data/1707753/000170775325000021/estc-20250430.htm))

Elastic says Elasticsearch is "the most downloaded open source vector database."

## 3. Core search features you'll use

### Lexical (keyword) search
Classic BM25 full-text search with analyzers, fuzzy matching, filters and aggregations. Exact terms still matter: speaker names, "eBPF", room numbers.

### Semantic search with `semantic_text`
This is the easiest route to vector search. Declare a field as `semantic_text`, and Elasticsearch chunks the text and creates embeddings automatically when documents are indexed. There's no pipeline to build. ([docs](https://www.elastic.co/docs/solutions/search/semantic-search/semantic-search-semantic-text))

```json
PUT talks
{
  "mappings": {
    "properties": {
      "title":    { "type": "text" },
      "abstract": { "type": "semantic_text" },
      "speaker":  { "type": "keyword" },
      "room":     { "type": "keyword" },
      "starts_at":{ "type": "date" },
      "tags":     { "type": "keyword" }
    }
  }
}
```

Query it with an ordinary `match` query (Query DSL), or with ES|QL:

```
FROM talks METADATA _score
| WHERE abstract: "something on eBPF and security"
| SORT _score DESC
| LIMIT 10
```

- If you leave out `inference_id`, the field uses the default EIS endpoint. Elastic recommends naming the endpoint explicitly for anything long-lived, because the default can change.
- **ELSER** is Elastic's own *sparse* model. It expands text into weighted, related terms, so you can see why something matched. **Jina** models are *dense* embeddings and are multilingual.

### Hybrid search (keyword + vector together)
**Retrievers** let you combine several searches in one request. **RRF** (reciprocal rank fusion) merges the ranked lists from BM25 and vector search, so you get exact-term precision and meaning-based recall together. You can also add a **reranker** step (for example a Jina reranker) to reorder the top results. ([hybrid search explainer](https://www.elastic.co/what-is/hybrid-search))

```json
GET talks/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": { "query": "eBPF security", "fields": ["title^2", "tags"] } } } },
        { "standard": { "query": { "match": { "abstract": "eBPF security" } } } }
      ]
    }
  }
}
```

### Other useful features
- **ES|QL:** a piped query language. Easy for LLMs to write, and Agent Builder uses it heavily.
- **Aggregations and Kibana dashboards:** for example "most popular topics" or "rooms by fill rate".
- **Geo queries:** for example "coffee near me" or venue maps.
- **Document- and field-level security:** an agent only sees what its API key is allowed to see.
- **BBQ quantization:** compresses dense vectors to cut memory use at scale. You won't need it at hackathon scale.

## 4. Elasticsearch in an agentic AI context

Elastic's pitch is that agents mostly fail because they get **bad context**, not because the model is weak. Search is the context layer: it finds the right few passages, records, logs or memories and gives them to the LLM. Elastic calls this **context engineering**.

### 4.1 The patterns

1. **RAG / knowledge retrieval.** The agent calls a search tool, and hybrid search returns the most relevant chunks for the LLM to answer from. Example: a conference Q&A bot grounded in talk abstracts.
2. **Agent memory.** Store conversation turns, user preferences and facts in an index. Use semantic search to recall them later, and filters to scope them by user and time. ([dev.to write-up](https://dev.to/omkar598/why-elasticsearch-is-the-best-memory-for-ai-agents-a-deep-dive-into-agentic-architecture-137l))
3. **Tool use over structured data.** The agent writes ES|QL to answer analytical questions, such as "which Kubernetes talks are in the afternoon and under-attended?"
4. **Semantic matching and recommendations.** Represent people and talks as vectors, run a kNN search for nearest neighbours, and let the agent explain why two things matched.
5. **Agent observability and audit.** Log every tool call, decision and token count to Elasticsearch, then search and chart them. This is also what Elastic's LLM observability does.
6. **Human-in-the-loop orchestration.** Elastic Workflows can pause an agent for human approval, resume later, and keep every decision searchable. ([blog](https://www.elastic.co/search-labs/blog/ai-agent-orchestration-human-approval-workflow))

### 4.2 Elastic Agent Builder (GA on Serverless and 9.3+)

([docs](https://www.elastic.co/docs/explore-analyze/ai-features/elastic-agent-builder)) Agent Builder is an agent framework built into Kibana. It has four parts:

- **Agent Chat:** a chat UI and API for talking to agents.
- **Agents:** custom instructions plus an assigned set of tools. Built-in agents work immediately on any index.
- **Skills:** bundles of domain knowledge and tools that load only when a query needs them.
- **Tools:** typed functions that agents call. The **built-in tools** handle index discovery, search, ES|QL generation and execution, and more. **Custom tools** come in these types ([docs](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/tools/custom-tools)):
  - **ES|QL tool:** a parameterized ES|QL query, so the agent fills in values and can't write arbitrary queries.
  - **Index search tool:** natural-language search scoped to one index or pattern.
  - **Workflow tool:** runs an Elastic Workflow, which can take actions.
  - **MCP tool:** imports tools from an external MCP server.
  - Tools can require user confirmation before they run.

Agent Builder comes with preconfigured LLMs on Cloud. You can also plug in other providers (OpenAI, Anthropic, Bedrock, local models) through inference endpoints. The hackathon gives everyone $50 in OpenAI credits.

### 4.3 How external agents connect

([MCP blog](https://www.elastic.co/search-labs/blog/elastic-mcp-server-agent-builder-tools))

| Interface | Use it when |
|---|---|
| **MCP server** at `https://<kibana-url>/api/agent_builder/mcp` | You want Claude Code, Cursor, VS Code or your own MCP client to use your Elastic tools. Only tools are exposed, not agents. Authenticate with `Authorization: ApiKey <key>`. |
| **A2A server** | Your Elastic agent should collaborate as a peer with other agents (agent-to-agent delegation). |
| **Kibana REST APIs** (`/api/agent_builder/...`) | Your own app should drive agents, tools and conversations programmatically. For example, your frontend calls an Elastic agent. |
| **Plain Elasticsearch clients** (Python, JS, Go, Java…) plus LangChain or LlamaIndex | You run your own agent loop and just use Elasticsearch as the vector store and retriever. |

Example MCP config for Claude Code:

```bash
claude mcp add elastic --transport http https://<your-kibana>/api/agent_builder/mcp \
  --header "Authorization: ApiKey $ELASTIC_API_KEY"
```

### 4.4 Developer tooling for coding agents

- **Elastic Agent Skills** ([repo](https://github.com/elastic/agent-skills)): skills that teach coding agents to use Elastic correctly, covering index design, ES|QL, ingest, Agent Builder, dashboards and more. They are in technical preview. *They are already installed in this Claude Code session as the `elastic:*` skills, for example `elastic:elasticsearch-onboarding`, `elastic:kibana-agent-builder` and `elastic:elasticsearch-esql`.*
- **Elastic CLI** ([blog](https://www.elastic.co/search-labs/blog/elastic-cli-ai-agents)): one CLI for the Elasticsearch, Kibana and Cloud APIs. It takes JSON in and returns JSON, validates input against schemas, keeps keys in the OS keychain, and has allow and block lists that an agent can't bypass. Elastic built it so that agents don't need curl.
- **Context engine** ([blog](https://www.elastic.co/search-labs/blog/context-engineering-for-agents)): Elastic precomputes "knowledge indicators" so agents don't have to rediscover the same things on every query. Elastic reports 71% fewer input tokens and 33 → 9 tool calls. It's a good argument to cite in a pitch.

## 5. How this maps to a Track 4 project

A design that scores on all three judging criteria:

1. **Ingest** the conference schedule: talks, abstracts, speakers, rooms and times. Add attendee profiles if you're doing matchmaking. Use `semantic_text` on abstracts and bios and `keyword` on filters. *(Elasticsearch is the core data layer.)*
2. **Search UI** that uses hybrid search (RRF over BM25 and semantic), with facets for time, room and track, and maybe a reranker. *(Smart search.)*
3. **Agent layer** built in Agent Builder:
   - An index search tool over talks.
   - An ES|QL tool for "what's on at 3pm in room X?"
   - A matchmaking tool that runs kNN over attendee interests.
   - A workflow tool that adds a talk to "My agenda" (writes to an index).
   - Expose all of it over MCP so the demo also works from Claude Code or Cursor.
4. **Memory and personalization:** store each attendee's chat and preferences in an index and recall them semantically.
5. **Kibana dashboard** of popular queries and topics, as a bonus. *(Conference value: organizers can see demand.)*
6. Optionally run the app on the Kubernetes cluster to also enter Track 3 (Radar), and instrument it with OpenTelemetry for Track 2 (Dash0).

## Key links

- Free trial (hackathon link): https://ela.st/hack-kubecon
- Get started with search: https://www.elastic.co/docs/solutions/search/get-started
- `semantic_text` tutorial: https://www.elastic.co/docs/solutions/search/semantic-search/semantic-search-semantic-text
- Agent Builder docs: https://www.elastic.co/docs/explore-analyze/ai-features/elastic-agent-builder
- Agent Builder MCP server: https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/mcp-server
- Clients: https://www.elastic.co/docs/reference/elasticsearch/clients
- Agent Skills: https://github.com/elastic/agent-skills
- Example notebooks: https://github.com/elastic/elasticsearch-labs
