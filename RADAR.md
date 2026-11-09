# Radar research notes

Research on Radar (Track 3, "AI SRE") for the [Cloud Native Hackathon](https://www.wemakedevs.org/hackathons/cnh), Salt Lake City, Nov 9, 2026.

**In one line:** Radar is an open-source Kubernetes UI from Skyhook with a built-in MCP server and an AI SRE that investigates broken workloads. For agentic AI, it lets a coding agent ship, debug and roll back on Kubernetes through Radar instead of through raw `kubectl`.

## The hackathon track

- **Prize:** $4,000 cash. Nadav Erell, Skyhook's CEO, is one of the judges.
- **Theme for every project:** make conferences better. Radar's suggested ideas are a talk picker, a hallway-track matchmaker and a live crowd map, all running on Kubernetes.

### What the judges look for

1. **Your project runs on Kubernetes with Radar connected**, in the cluster they give your team or on your own.
2. **You use Radar's UI and MCP all day**, to ship, troubleshoot and improve the app.
3. **You run at least one AI investigation** on a real issue and show what you learned and what you did about it.
4. **The project makes conferences easier.**

### Setup

- **Get a team cluster** at `join.cnh.radarhq.io`. The join code is given at the kickoff and at the Radar table, and setup takes 3 to 4 minutes. You get a vcluster where you're cluster-admin, with the starter app already live at `https://<team>.cnh.radarhq.io` in namespace `team-<team>`.
- **Copy the [starter repo](https://github.com/skyhook-io/cnh-starter)** with "Use this template". Make the copy **public**, because Argo CD reads it without credentials. Then run `./scripts/setup.sh <team-name>` and push. GitHub Actions builds the image to GHCR, and once `argocd/application.yaml` is applied, Argo CD deploys every push to `main`.
- **Connect Claude Code** once, then run `/mcp`, choose **Authenticate** and pick the "Cloud Native Hackathon" org:

  ```bash
  claude mcp add --scope user radar-cloud --transport http https://api.radarhq.io/mcp
  ```

- **Pass your cluster id on every call.** About 40 clusters share the Radar Cloud org, so every Radar Cloud MCP call needs your `cluster` id. The starter repo's `AGENTS.md` and `.agents/skills/` tell your agent how to find it and how to ship.
- **Keep secrets out of git.** The repo and the image are public, so API keys go in a Kubernetes Secret (`app-credentials`) that the app reads as an env var. Never put them in git, in the image or in the agent chat.
- **Know when access ends.** Hackathon clusters and access to the org end on Friday, Nov 13.

### How the starter repo suggests you spend the day

- **11:00:** get the cluster, open it in Radar Cloud and connect your agent.
- **First hour:** take a screenshot of **Checks**. That's your "before".
- **All day:** ship through Radar's MCP (push, sync, wait for each rollout). Look in Radar first when something breaks.
- **At least once:** run an investigation. An all-clear investigation after a release counts too.
- **5:30:** tell the day's story from Radar with the Timeline, the investigation, and Checks before and after.

## What Radar is

- **A single Go binary.** Run it as `kubectl radar`, as a desktop app, or in-cluster with Helm. It's Apache 2.0, needs no account for local use, and installs nothing in your cluster: it talks to the Kubernetes API with your kubeconfig.
- **Fast and private.** It watches the cluster through informers, streams live updates to the browser over SSE, and keeps your data local.
- **Views:**
  - **Issues:** a ranked queue of what's broken.
  - **Topology:** a live graph of resources and how they connect.
  - **Timeline:** events plus resource changes, with diffs.
  - **Also:** Helm, GitOps (Argo CD and Flux), Traffic, Metrics, Capacity, Cost, Audit/Checks, Network path, Upgrade impact, RBAC and an image filesystem viewer.
- **Radar Cloud** is the hosted version: multi-cluster, with alerts, and its own agent. The agent investigates automatically when an alert fires and posts the root cause to Slack or a webhook. It's free for up to 3 clusters.

### Install (local)

```bash
curl -fsSL https://get.radarhq.io | sh && kubectl radar
```

```bash
claude mcp add --transport http radar http://localhost:9280/mcp-readonly
```

### Install (in-cluster)

```bash
helm repo add skyhook https://skyhook-io.github.io/helm-charts
```

```bash
helm install radar skyhook/radar -n radar --create-namespace
```

## Why it matters for agentic AI

Radar's argument is that an agent pointed at raw `kubectl` wastes its context window on YAML and its time on round trips. Radar's MCP server returns the cluster already joined up: relationships, health, deduplicated events, changes over time and filtered logs.

### Read tools (the agent's eyes)

| Tool | What it answers |
|---|---|
| `issues` | What's broken right now? This was the agent's first call on all 50 faults in Radar's benchmark |
| `diagnose` | A bundle of evidence for one workload: spec, context, logs, crash cause |
| `get_changes` | What changed before this broke? |
| `get_resource`, `get_neighborhood`, `get_topology` | How things connect: owner chains, selectors, routing |
| `get_events`, `get_workload_logs`, `get_pod_logs` | Deduplicated events, logs filtered for errors, secrets redacted |
| `top_resources`, `query_prometheus`, `get_rightsizing`, `get_cost` | Load, metrics, sizing and cost |
| `search`, `list_resources`, `get_dashboard`, `get_cluster_audit` | Finding things, overall health, security and config posture |

### Write tools (the agent's hands)

These are only on the full `/mcp` endpoint. They're marked destructive and limited by RBAC.

| Tool | What it does |
|---|---|
| `apply_resource`, `patch_resource` | Create or change resources, with a dry-run diff |
| `manage_workload` | Restart, scale or roll back |
| `manage_rollout` | Argo Rollouts canary promote or abort |
| `manage_gitops` | Argo CD or Flux sync and rollback |
| `manage_helm`, `manage_node`, `manage_cronjob` | Helm releases, node cordon/drain, cron jobs |
| `wait_for` | Waits for a rollout to finish, so an agent can ship and confirm in one loop |

Two more tools are opt-in: `exec_pod` (enabled with `--mcp-exec-tools`) and `curl_service` (enabled with `--mcp-http-tools`).

### Safety model

- **A separate read-only endpoint:** `/mcp-readonly` has no write tools.
- **No secret values:** Secret values are never returned. Logs, env vars and Helm values are scrubbed for known secret patterns, which can't catch everything.
- **Investigations stay read-only:** those run from the UI or Radar Cloud never load write tools.
- **Approved fixes only:** a fix runs only after you approve it, in its own session. Changes to resources managed by Argo CD, Flux or Helm ask for your OK first.
- **Cluster text is data:** the server tells agents to treat anything read from the cluster, such as logs and annotations, as data and never as instructions. That protects against prompt injection through log lines.

### Benchmarks (Radar's own, on SREGym faults)

- **Radar's MCP vs raw `kubectl`, same agent and model:** 64s vs 191s to a diagnosis (about 3× faster), and 86% vs 60% diagnosed correctly within two minutes.
- **Six AI SRE tools compared:** Claude Code with Radar's MCP was the most accurate (44 of 50 correct), fastest (79s) and cheapest ($0.27 per fault). The others were kubectl-ai, HolmesGPT, OpenSRE, kagent and AWS DevOps Agent.

## Project ideas

1. **The agent ships everything through Radar.** Claude Code pushes, calls `manage_gitops` sync, uses `wait_for` until the rollout is healthy, then checks `issues`. That covers judging criterion 2 without extra work.
2. **Break it on purpose, then investigate.** Add a "chaos" toggle to the conference app, for example removing an env var from a ConfigMap or setting a tiny memory limit. Then run a Radar investigation and show `get_changes` linking the change to the crash, followed by an approved fix. This is the strongest demo for criterion 3.
3. **An agent inside the product.** Deploy Radar OSS in your namespace with Helm and have your app's own LLM agent call the in-cluster `/mcp-readonly` endpoint (you get $50 in OpenAI credits). It could power a status bot like "is the schedule service healthy?", or let a crowd-map agent scale the backend when a talk gets busy. Keep that Service ClusterIP-only, because there's no authentication on it.
4. **Enter more than one track.** Radar understands OpenTelemetry, so instrumenting for Dash0 (Track 2) also gives Radar's investigations richer evidence. An Elasticsearch-backed talk search (Track 4) could serve as the data layer in the same project.

## Sources

- [Hackathon page](https://www.wemakedevs.org/hackathons/cnh) and [resources page](https://www.wemakedevs.org/hackathons/cnh/resources)
- [Radar on GitHub](https://github.com/skyhook-io/radar)
- [Radar MCP docs](https://radarhq.io/docs/features/mcp)
- [AI investigations](https://radarhq.io/product/ai-investigations)
- [Benchmarks](https://radarhq.io/benchmark)
- [cnh-starter repo](https://github.com/skyhook-io/cnh-starter)
