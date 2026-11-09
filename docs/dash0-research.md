# Dash0 research

Research notes for the [Cloud Native Hackathon](https://www.wemakedevs.org/hackathons/cnh) (WeMakeDevs, Nov 9 2026, The Shop Workspace, Salt Lake City). Theme: build something that makes conferences better.

## Hackathon context

Dash0 sponsors **Track 2 · Observability, "Stop Flying Blind"** with a **$4,000 cash** prize. Julia Furst Morgado (Principal DevRel Engineer at Dash0) is one of the judges.

### Judging criteria (Dash0 track)

- How deeply the app is instrumented: traces, logs, metrics, and real-user monitoring (RUM) if there is a frontend.
- **Using Agent0 or the MCP server to find and fix something real during the day, and showing it in the demo.**
- Observability built into the product experience, not added at the end.
- Bonus: a dashboard or SLO showing how healthy the app is.
- How much easier the project makes conferences.

### Sponsor-suggested ideas

- A self-diagnosing microservice app (storefront, booking system, chat app) instrumented end to end, with a "chaos" button that injects latency or errors; Agent0 finds the cause in the demo.
- A live crowd map where check-ins become metrics and a Dash0 dashboard shows which rooms are filling up.
- A schedule app where Agent0 explains why "My agenda" slowed down after the keynote.
- An AI assistant for attendees traced with OpenLIT, showing every LLM call, token and cost in Dash0.

### Features the sponsor wants to see

- Agent0
- Dash0 MCP server
- Bonus: Dash0 CLI, dashboards, alerts, synthetic monitoring

## What Dash0 is

- **An observability platform built on OpenTelemetry from the start.** Logs, metrics, traces, profiles, events and RUM are stored together, with no proprietary data-collection agent. Data arrives as standard OTLP and is queried with PromQL, SQL, the CLI or the API.
- **"Observability for the AI Era" (June 2026 repositioning).** Coding agents ship code faster than people can review it, so observability has to move from dashboards to agents that act. Six pillars:
  1. An agent platform with production skills (performance, errors, reliability, security, cost, testing), triggered by deployments, anomalies, alerts or schedules
  2. An open agent interface: APIs, MCP server and CLI
  3. Observability for AI agents (LLMs, prompts, sessions, end-to-end flows)
  4. An OpenTelemetry-native telemetry warehouse
  5. Transparent usage-based pricing and data controls (spam filters, tail sampling, log deduplication)
  6. AI built into every screen
- **Ways to get data in:** OpenTelemetry auto-instrumentation, the Dash0 Kubernetes Operator, the OpenTelemetry Collector, and an Integrations Hub with a setup guide per language.
- More than 700 customers, including Zalando, Taco Bell and The Telegraph. Recently acquired Polar Signals (profiling).

## The agentic AI side

"Agentic observability" means two things, and Dash0 covers both.

### 1. Agents doing the observing

#### Agent0

Dash0's built-in AI for production, generally available in 2026.

- **Agent0 Chat:** ask a question ("why is checkout slow?"). It correlates traces, logs and metrics, follows the problem into code through GitHub, and drafts a fix as a pull request. Every tool call is inspectable.
- **Agent0 Automations:** run without anyone asking. Triggers include failed checks, cron schedules and GitHub events; results can be delivered to Slack.
- **Integrations:** GitHub (reads code, PRs, commits, CI; opens PRs), Linear, and any external MCP server, so Agent0 can use your own tools.
- **Pricing and control:** task-based credits, no per-seat AI charge. It drafts changes but does not merge them; autonomy is meant to grow step by step as trust builds.

#### Dash0 MCP server

Gives Claude Code, Cursor, Codex, Windsurf and other assistants access to live telemetry.

- Hosted by Dash0, streamable HTTP transport, OAuth sign-in (or an auth token for CI/CD).
- **All tools are read-only:** service catalog, PromQL and SQL queries, log and span search, traces, failed checks, synthetic checks, SLOs, dashboards, websites. Most tools take a `dataset` argument; `listDatasets` lists the ones you can access.
- **`runTask`** delegates an open-ended question to Agent0 (roughly 1–2 credits per investigation). **`waitForTask`** fetches the result if it takes longer than the wait time. Over MCP, Agent0 runs read-only and cannot open PRs.
- Read-only telemetry queries over MCP are free.

Endpoints (`https://api.<region>.<cloud>.dash0.com/mcp`):

| Region | Endpoint |
| --- | --- |
| AWS Europe (Ireland) | `https://api.eu-west-1.aws.dash0.com/mcp` |
| AWS Europe (Frankfurt) | `https://api.eu-central-1.aws.dash0.com/mcp` |
| Google Cloud Europe (Netherlands) | `https://api.europe-west4.gcp.dash0.com/mcp` |
| AWS US East (N. Virginia) | `https://api.us-east-1.aws.dash0.com/mcp` |
| AWS US West (Oregon) | `https://api.us-west-2.aws.dash0.com/mcp` |

Setup in Claude Code (the docs render the exact command client-side; this follows the documented pattern of HTTP transport and a server named `dash0`):

```bash
claude mcp add --transport http dash0 https://api.us-west-2.aws.dash0.com/mcp --scope user
```

Swap in your region's endpoint, then run `/mcp` in Claude Code and select **dash0** to sign in.

Example prompts from the docs:

- "Which services in my production dataset have the highest error rate right now?"
- "Show me the error logs from the last hour and group them by service and message."
- "What's the p95 latency of the frontend service over the last 6 hours? Give me the PromQL you used."
- "Ask Agent0 to investigate why the checkout service got slower this morning."

### 2. Observing the agents

- Dash0 natively reads the **OpenTelemetry GenAI semantic conventions** (`gen_ai.*`). An agent run is a normal trace tree: `invoke_agent` → `chat` (model call: model, input/output tokens, finish reason) → `execute_tool`. MCP tool calls produce the same `execute_tool` shape.
- **OpenLIT** auto-instruments 50+ LLM providers, vector databases and agent frameworks with one `openlit.init()` call. It captures prompts, completions, token usage, cost, latency and optional GPU metrics. Working example: [`dash0hq/dash0-examples/openlit`](https://github.com/dash0hq/dash0-examples/tree/main/openlit). OpenLLMetry and LangChain integrations also exist.
- **Observability for Claude Code** tracks adoption, cost, waste and DORA metrics for AI-assisted development. The `dash0-agent-plugin` for Claude Code sends session telemetry to Dash0 (configure with `/dash0-agent-plugin:dash0-configure`).

## Suggested project shape for Track 2

An **AI conference assistant** (schedule Q&A or talk picker) built as a few small services:

1. OpenTelemetry auto-instrumentation across every service, browser RUM on the frontend, and OpenLIT tracing the LLM calls.
2. A "chaos" toggle that injects latency or errors, so the demo shows **Agent0 finding the root cause and opening a PR**.
3. The Dash0 MCP server connected to Claude Code during the build, so the coding agent fixes problems from real traces instead of guessing.
4. A dashboard and SLO for app health, plus a token and cost panel for the LLM.

This covers every Dash0 judging criterion. Tracks can be combined, so the same project could also enter Radar (run it on Kubernetes) or Elasticsearch (retrieval-augmented search over talk abstracts).

## Sources

- [Hackathon page](https://www.wemakedevs.org/hackathons/cnh)
- [Hackathon resources](https://www.wemakedevs.org/hackathons/cnh/resources)
- [Dash0 MCP server docs](https://www.dash0.com/docs/dash0/ai/mcp)
- [Dash0 MCP server integration](https://www.dash0.com/hub/integrations/int_dash0_mcp/overview)
- [Agent0](https://www.dash0.com/agent0)
- [Agent0 is GA](https://www.dash0.com/blog/observability-for-the-ai-era-starts-here-agent0-is-ga)
- [From OpenTelemetry-Native to Observability for the AI Era](https://www.dash0.com/blog/from-opentelemetry-native-to-observability-for-the-ai-era)
- [What is agentic observability](https://www.dash0.com/knowledge/what-is-agentic-observability)
- [OpenTelemetry GenAI semantic conventions explained](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained)
- [OpenLIT integration](https://www.dash0.com/hub/integrations/int_openlit/overview)
- [Dash0 docs](https://www.dash0.com/docs/dash0)
- [Dash0 CLI quickstart](https://dash0.com/docs/dash0/miscellaneous/tooling/dash0-cli/quickstart)
- [Dash0 Operator for Kubernetes](https://www.dash0.com/docs/dash0/monitoring/kubernetes/dash0-operator/overview)
