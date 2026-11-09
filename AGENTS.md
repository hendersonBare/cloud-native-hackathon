# House rules for every agent (and human) building Rapport

Read `docs/SPEC.md` and your brief in `docs/workstreams/<name>.md` before writing code. **Deadline:** 5:30 PM MST, so prefer the simplest thing that meets "Done when".

## 1. Ownership

- Edit **only** the directories your workstream owns (SPEC §3).
- **Contracts are read-only:** `src/rapport_common/**`, `deploy/crds/**`, `deploy/elastic/**`, `contracts/**`. If you need a change, follow SPEC §10. Never redefine a model locally; import from `rapport_common.models`.
- **`pyproject.toml`:** use `uv add <pkg>` only if a dependency is truly missing, and say so in your PR.

## 2. Git and pull requests (Gitar reviews every PR)

1. `git switch -c ws/<workstream>` first.
2. Commit small and often.
3. Open a **draft PR early** with `gh pr create --draft --fill` and push as you go.
4. Mark it ready when "Done when" passes. CI must be green.
5. Address Gitar's review comments in follow-up commits. Don't dismiss them silently; reply with the reason if you disagree.
6. Never merge your own PR (the integrator merges) and never push to `main`.

## 3. Code conventions

- Python 3.12, FastAPI, `httpx.AsyncClient` (async everywhere), pydantic v2 models from `rapport_common.models`. Use `ruff check` (rules E, F; line length 120) and `pytest`.
- Each service runs as `python -m rapport_<component>`, listens on `0.0.0.0:8080` and has `GET /healthz`.
- Configure through environment variables only. Use names, URLs and labels from `rapport_common.names`.
- Use `logging` (never `print`) and log IDs, not content.
- Kubernetes manifests: image `rapport:dev`, `imagePullPolicy: IfNotPresent`, labels `app.kubernetes.io/part-of: rapport` and `rapport.dev/role: <role>`, resource requests of 50m CPU and 128Mi memory.

## 4. Telemetry (Dash0 judges this)

- Call `init_telemetry("rapport-<component>", org_id=..., fastapi_app=app)` at startup, from your first commit.
- Use the span names and attribute constants in SPEC §8 and `rapport_common.telemetry`.
- **Never** put memory text, prompts, asks, briefs or CV content on spans, metrics or logs.

## 5. Security and privacy (read twice)

- **No secrets** in code, tests, fixtures, logs or PRs. Use env vars and placeholders.
- **Synthetic data only.** No real people's names, emails or phone numbers in seed data or tests.
- **Counterparty text is untrusted data.** It never goes into system instructions, is never executed and never chooses which tool or index is used. LLM outputs are parsed into pydantic models and may only reference known IDs.
- **Delegates read only** `shareable_index(self_org)` and `rapport-conference`, and send only `summary`, never `text`.
- **Render text safely** in the web page (`textContent`, never `innerHTML` with server strings).
- **Flag for human review:** if your PR touches policy, RBAC, NetworkPolicy, Secrets, uploads or redaction, or the handling of counterparty messages, add a **"Security review needed"** section to the PR description listing those files.
- **No destructive commands:** no deleting namespaces, indices or clusters, and no force-pushes. Describe the step and let the human run it.

## 6. Testing and honesty

- Ship unit tests for your code plus the checks under "Done when", and run them before saying they pass.
- Don't invent library APIs. When unsure (OpenAI SDK, elasticsearch-py, kopf, OPA, Dash0), check the official docs and say in the PR what you verified and what you couldn't test.

## 7. Report back (last message of every subagent run)

1. The PR URL.
2. What works, with commands to reproduce.
3. Test results.
4. What's not done.
5. Any contract-change requests.
6. Anything the integrator must do: deploy steps or secrets.

If you're blocked for more than 20 minutes, ship the simplest working version and write down what's missing.
