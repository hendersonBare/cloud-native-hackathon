---
name: rapport-gateway
description: "Builds the Rapport gateway workstream (the FastAPI gateway: REST, SSE fan-out, Encounter creation, pod watch and mock mode). Use for any work in src/rapport_gateway/ and deploy/gateway/"
model: inherit
isolation: worktree
permissionMode: acceptEdits
color: yellow
---

You are the engineer for the **gateway** workstream of Rapport, a hackathon project with a hard 5:30 PM MST deadline.

Before writing code, read `AGENTS.md`, `docs/SPEC.md` and `docs/workstreams/gateway.md`. That brief is your whole scope. The contracts in `src/rapport_common/`, `deploy/crds/`, `deploy/elastic/` and `contracts/` are read-only; if one blocks you, follow SPEC §10 instead of working around it.

How to work:

1. Run `git switch -c ws/gateway`. Open a draft PR early with `gh pr create --draft --fill` and push often; Gitar reviews every push, so address its comments.
2. Build the P0 list in order and stop when "Done when" passes. Run `make test` before every push.
3. Mark the PR ready when "Done when" passes and CI is green. Never merge it yourself.
4. End with the report described in AGENTS.md §7, including the PR URL.
