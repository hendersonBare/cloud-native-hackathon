# Gitar and SonarQube Cloud

## What we use it for

Rapport was built by six workstreams in parallel, each a Claude Code subagent in its own git worktree on a `ws/<name>` branch, against contracts that were already written and tested. Nothing reaches `main` except through a pull request, and merging to `main` is the deploy (the build-and-deploy Action builds the image and Argo CD syncs `deploy/`). Gitar reviews every PR against review instructions and repository rules that encode our threat model: what may cross between companies, what may reach telemetry, and how untrusted counterparty text is handled. SonarQube Cloud runs on the same PRs as a rule-based second layer with a quality gate, and GitHub Actions runs `make test`'s checks.

## Where it lives

| Path | What it is |
|---|---|
| `.gitar/review/instructions.md` | Review instructions: the blocking findings for this project, plus the house rules included from `AGENTS.md` |
| `.gitar/review/team-workflow.md` | Workstream ownership (SPEC §3), read-only contracts (SPEC §10), test and CI expectations |
| `.gitar/rules/delegate-reads-shareable-only.md` | Delegate code may read only `shareable_index(self_org)` and `rapport-conference`, and send only summaries |
| `.gitar/rules/memory-records-carry-org-and-share-level.md` | Every Elasticsearch write goes through `MemoryRecord` and `names.index_for()` |
| `.gitar/rules/no-content-in-telemetry.md` | Spans, metrics and logs carry IDs, counts, decisions and rule IDs only |
| `.gitar/rules/untrusted-counterparty-input.md` | Counterparty text is data, never instructions |
| `.gitar/rules/security-review-flag.md` | Policy, RBAC, NetworkPolicy, Secrets, uploads, redaction and delegate message handling need a human reviewer |
| `.gitar/config/apply.md` | Auto-apply limits: what Gitar may and may not commit on its own |
| `AGENTS.md` | House rules for every agent and human; included into the review instructions with `@../../AGENTS.md` |
| `.github/workflows/ci.yml` | CI on every PR and on `main`: `uv sync --frozen --no-build`, ruff, pytest, `opa fmt`/`opa check`, `opa test`, `kubectl kustomize deploy`, `node --test web/tests/` |
| `Makefile` (`make test`) | The same checks locally |
| `docs/stack/` | These pages, included into the review instructions as stack context |

## How it works here

- **Review instructions.** `.gitar/review/instructions.md` lists what blocks a merge: sending `MemoryRecord.text` instead of `summary` to another company; a delegate reading anything other than `shareable_index(self_org)` and `rapport-conference`; content (memory text, prompts, asks, briefs, CV text, query text) on spans, metrics or logs; counterparty strings (`Ask.text`, `Card.headline`) in system instructions or choosing a tool, index or URL; accepting an LLM output that cites an `item_id` outside the candidate list; redefining a contract model locally or editing a contract path without a "CONTRACT CHANGE REQUEST"; the gateway accepting an `/internal/events` event for a persona or org that doesn't match the reporting delegate; a talk time without a time zone; `innerHTML` with server strings; an LLM call without a timeout and a deterministic fallback. It also checks manifests (image `app`, explicit namespace, labels, requests and limits from `names.RESOURCES_*`, `names.SECURITY_CONTEXT`) and that `/internal/*` is served only on port 8081.
- **Repository rules.** Each file in `.gitar/rules/` has front matter with `title`, `description`, `when` (the paths or kinds of change that trigger it) and `actions` (what to request). For example, `security-review-flag.md` triggers on `policy/`, `deploy/base/`, RBAC or NetworkPolicy manifests, secret handling, briefer upload and redaction code, and delegate message handling, and asks for a "Security review needed" section in the PR description.
- **Ownership.** `.gitar/review/team-workflow.md` maps each `ws/<name>` branch to the paths it owns. A file changed outside that list is flagged with the workstream that owns it. Branches that don't start with `ws/` are the integrator's.
- **Auto-apply limits.** `.gitar/config/apply.md` lets Gitar commit fixes only inside files the PR already changes. It never auto-applies a change to a contract path, `policy/`, `deploy/base/`, `.github/workflows/`, RBAC, NetworkPolicy or Secret manifests, upload or redaction code, or delegate message handling, never skips, deletes or loosens a test, never turns off a lint rule, and never adds or upgrades a dependency.
- **SonarQube Cloud.** The SonarQube Cloud GitHub integration analyses each PR and reports the "SonarCloud Code Analysis" check with a quality gate (project `hendersonBare_CloudNativeHackathon`). Its rules caught CI and code issues that Gitar's instructions don't target, such as `uv sync` without `--frozen --no-build` (githubactions S8541, S8544) and a plain-HTTP URL (S5332).
- **Workflow.** House rules (AGENTS.md §2) say: branch first, open a draft PR early, address Gitar's comments in follow-up commits, reply with a reason when we disagree, and never merge your own PR. The integrator merges.

## What a reviewer should check in a PR

- Changed files stay inside the owning workstream's paths (`.gitar/review/team-workflow.md`); any other file is named with its owner.
- Contract paths (`src/rapport_common/**`, `deploy/crds/**`, `deploy/elastic/**`, `contracts/**`) change only under a "CONTRACT CHANGE REQUEST". Models, index names, labels, Service names and URLs are imported from `rapport_common.models` and `rapport_common.names`, never redefined.
- Delegate code reads only `shareable_index(self_org)` and `rapport-conference`, and sends `summary`, never `text`.
- Spans, metrics and logs carry IDs, counts, decisions and rule IDs; never memory text, prompts, LLM responses, asks, briefs, CV text, emails or keys.
- Counterparty strings never reach system instructions and never choose a tool, index or URL. LLM output is parsed into a pydantic model and may only reference known IDs.
- Every LLM call has a timeout and a deterministic fallback.
- A PR that touches policy, RBAC, NetworkPolicy, Secrets, uploads, redaction or delegate message handling has a "Security review needed" section listing those files.
- New behaviour ships with a test in the workstream's `tests/<name>/` folder. No lint rule is turned off and no test is skipped, deleted, marked xfail or loosened to get CI green.
- `pyproject.toml` and `uv.lock` change only to add a missing dependency, and the PR says which and why.
- The PR description has a "Track evidence" section.

## Evidence

As of 4:00 PM MST, 28 PRs had merged since [#2](https://github.com/hendersonBare/cloud-native-hackathon/pull/2) set Gitar up, and Gitar reviewed every one: it left a review comment on each PR from #2 to [#29](https://github.com/hendersonBare/cloud-native-hackathon/pull/29) except [#22](https://github.com/hendersonBare/cloud-native-hackathon/pull/22), where its check passed without a comment. SonarQube Cloud commented on PRs #1 to #29.

What the reviews caught, from `docs/evidence/LOG.md` (times MST):

| LOG time | PR | Found by | What it caught | Fix |
|---|---|---|---|---|
| 14:00 | [#9 delegate](https://github.com/hendersonBare/cloud-native-hackathon/pull/9) | Gitar (security) | The responder replayed a cached round reply before checking the sender and encounter, so any caller that reached it could read the peer-only round-2 offers | `1756e10` with a regression test; `check_sender` now runs before the replay lookup (`src/rapport_delegate/responder.py:57`) |
| 14:08 | [#8 briefer](https://github.com/hendersonBare/cloud-native-hackathon/pull/8) | Gitar (security) | `POST /v1/remember` could write talk and attendee records into the shared conference index, letting a caller forge someone's Discover card; the do-not-contact guardrail missed company-level notes; redaction missed Unicode spaces | Fixed in PR #8 with regression tests; `/v1/remember` now drops other orgs' records and conference-index records (`src/rapport_briefer/app.py:59-67`) |
| 13:55 | [#5 policy-ci](https://github.com/hendersonBare/cloud-native-hackathon/pull/5) | Gitar | OPA would never get ready: kubelet's hidden `..data` entries in a ConfigMap mount made it load `rapport.rego` three times | `a3957b7` (`--ignore=.*` in `deploy/policy/*/opa.yaml`) |
| 13:55 | [#5 policy-ci](https://github.com/hendersonBare/cloud-native-hackathon/pull/5) | SonarQube Cloud | CI ran `uv sync` and `uv run` without `--frozen --no-build` (S8541, S8544), failing the quality gate | `a3957b7` |
| 14:02 | [#6 operator](https://github.com/hendersonBare/cloud-native-hackathon/pull/6) | Gitar, SonarQube Cloud | Encounters the operator rejected were never TTL-deleted; the kopf liveness URL tripped S5332 | `d760079`, `e20e981` |
| 13:58 | [#7 memory](https://github.com/hendersonBare/cloud-native-hackathon/pull/7) | Gitar | A hard-coded "MST" label would be wrong in daylight time; one transient Elasticsearch error switched the reranker off for good | Fixed in PR #7; the memory client now turns the reranker off only when Elasticsearch answers 400 or 404, and skips it for one call on any other error (`src/rapport_memory/client.py:186-195`) |

Gitar asked for human security review on PR #8 (upload and redaction code, LLM prompt handling, secret wiring) and PR #10 (RBAC, upload limits, the admin-token guard and the `/internal/events` party check). On PR #8, Gitar also cited the house rules for a missing test folder and a missing "Track evidence" section. On PR #10, Gitar's summary still listed two of six findings open, both about files outside `ws/gateway`'s paths (`Dockerfile`, `docs/API.md`). The integrator replied on the PR that both were assigned to the workstream; Gitar then answered on both threads that the finding does not apply, and the PR merged.

Process note from the log (14:10 MST): parallel coding agents shared one scratch file for PR bodies, so one PR's description (PR #9) was briefly replaced by another's. Each workstream now uses its own scratch file names.
