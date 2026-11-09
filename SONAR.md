# Sonar: research notes

Research for the [Cloud Native Hackathon](https://www.wemakedevs.org/hackathons/cnh) (Salt Lake City, November 9, 2026). Gathered from the hackathon page and its [resources page](https://www.wemakedevs.org/hackathons/cnh/resources), Sonar's blog and guides, the [Gitar docs](https://docs.gitar.ai/introduction), and the [SonarQube MCP server repo](https://github.com/SonarSource/sonarqube-mcp-server).

## Sonar at this hackathon

Sonar sponsors **Track 1, "Never Merge Broken"** ($4,000 in cash). The track is about **Gitar**, an AI code-review agent Sonar bought in May 2026. It is not mainly about SonarQube, Sonar's older product.

What the judges look for:

- **Gitar used all day:** features land through PRs that Gitar reviewed, not one big PR at the end.
- **Setup that fits your project:** review instructions and repository rules that match how your team actually works.
- **CI fixes:** Gitar diagnoses a failing build and auto-apply fixes real problems.
- **The theme:** how well the project makes conferences easier.

Sonar's own project ideas:

- A schedule builder where every feature lands through a PR Gitar reviewed, with review instructions that make sure session times always handle time zones properly.
- A repository rule that runs whenever your API changes and checks your frontend still matches it.
- Breaking CI on purpose during the demo and letting auto-apply fix it live.

## What Sonar sells

Sonar now calls itself an "AI code verification" company. It claims 7M+ developers and 75% of the Fortune 100.

| Product | What it does |
|---|---|
| **SonarQube** (Cloud, Server, IDE) | Static analysis that follows fixed rules for bugs, security problems and code smells. A **quality gate** blocks a merge when the code falls below your standards. |
| **Gitar** | An AI reviewer installed as a GitHub/GitLab app. It comments on PRs, pushes fixes as new commits (never force-pushes), works out why CI failed (your code, a flaky test, or infrastructure), and can auto-approve or auto-merge. |
| **SonarQube MCP Server** | Lets AI coding agents (Claude Code, Cursor, Codex, Devin) query SonarQube: issues, quality gate status, analysing a file. |
| **Agentic Analysis, CLI, Claude Code plugin** | Let an agent check its own code against your standards while it writes, and catch secrets before they reach the LLM. |
| **Remediation Agent, AI CodeFix** | Fix issues that SonarQube found, then check the fixes. |
| **Architecture, Context Augmentation** | Give agents your architecture rules and standards before they start writing. |
| **Advanced Security** | Security scanning that also checks your dependencies (SAST and SCA). |

## How it fits agentic AI

Sonar's framing is the **[Agent Centric Development Cycle (AC/DC)](https://www.sonarsource.com/blog/the-future-is-ac-dc-the-agent-centric-development-cycle/)**. Agents now write code for hours and open huge PRs, so Sonar positions itself as the layer around whatever coding agent you use, in three steps:

1. **Guide:** give the agent context and standards up front. In Gitar this means `.gitar/review/*.md`, `AGENTS.md` and `CLAUDE.md`.
2. **Verify:** check the code inside the agent's own loop (MCP server, Agentic Analysis) and again at the PR (Gitar plus the quality gate).
3. **Solve:** let a repair agent fix what was found, then feed the lessons back into Guide.

These steps run at two levels:

- **Inner loop:** inside each step of the agent's reasoning, so it can correct itself quickly.
- **Outer loop:** once the agent says it's finished, a fuller check of the whole result.

### LLM review and rule-based analysis catch different things

From Sonar's [multilayered verification demo](https://www.sonarsource.com/resources/library/multilayered-code-verification-with-gitar-sonarqube-cloud/):

- **Gitar** caught an off-by-one pagination bug and a sort in the wrong direction. Static rules can't see those.
- **SonarQube** caught a `/tmp` directory anyone could write to and a missing HTTP-methods setting. Gitar missed both.
- **Both** found the same path traversal hole by different methods.
- After Gitar fixed its findings and approved the PR, CI went green, but the **quality gate still blocked the merge**.

Gitar and SonarQube are still separate products. They share no dashboard and don't merge duplicate findings, so the same issue can show up twice.

## Using Gitar in the project

1. Sign in at [app.gitar.ai](https://app.gitar.ai/) with GitHub and install the app on the repo. The 14-day Pro trial needs no credit card and includes auto-apply and custom rules.
2. Ship every feature as a PR. `gitar-bot` posts a summary and inline comments within a few minutes.
3. Write review instructions in `.gitar/review/instructions.md`. Gitar reads them from the PR's own branch, not only from `main`. `@` includes can pull in more docs, for example `@../documents/coding_standards.md`.
4. Add repository rules in `.gitar/rules/*.md`. Each needs YAML frontmatter with `title`, `description`, `when` and `actions`. Pro allows up to 5 rules per organization.
5. Keep a single root instruction file, `AGENTS.md` or `CLAUDE.md`. Gitar reads both and flags any contradictions between them.

### Example review instruction

```markdown
# Session time convention

For every new or changed code path that stores, compares or displays a session time:

- Store times in UTC with an explicit offset.
- Display times in the venue's time zone (America/Denver), labelled with its abbreviation.

Report a blocking review finding when a change uses a naive datetime or drops the time zone.
Do not suppress or downgrade standard reliability or security findings.
```

### Example repository rule

```markdown
---
title: "API/frontend contract check"
description: "Check the frontend still matches the API when the API changes"
when: "A pull request is opened or updated and changes any file under api/"
actions: "Post a comment listing frontend calls that no longer match the changed API"
---

Compare changed request and response shapes under `api/` with their callers under `web/`.
List any mismatch with file and line. Do not modify code.
```

### PR commands

| Command | Effect |
|---|---|
| `gitar auto-apply:on` / `gitar auto-apply:off` | Turn automatic fixes on or off for this PR |
| `gitar auto-merge:on` / `gitar auto-merge:off` | Arm or disarm auto-merge for this PR |
| `gitar display:verbose` / `gitar display:compact` | Show or hide why each rule did or didn't apply |
| `gitar unblock` | Dismiss Gitar's blocking review (an admin must enable it) |
| `gitar fix this` (or reply `fix` on a finding) | Ask in plain words for a fix |
| `gitar-skip` label | Skip Gitar on this PR |
| `gitar-managed` label | Turn on auto-apply for this PR |

## Optional: add SonarQube

For two kinds of review on every PR:

1. **SonarQube Cloud in CI.** Import the repo at [sonarcloud.io](https://sonarcloud.io/) and choose GitHub Actions. Add a `sonar-project.properties` file with `sonar.projectKey` and `sonar.organization`, store `SONAR_TOKEN` as a repo secret, and add the `SonarSource/sonarqube-scan-action` step after the tests. Use `fetch-depth: 0` on checkout. The free tier decorates PRs that target `main`.
2. **SonarQube MCP server in Claude Code,** so the agent checks its own code before it opens a PR:

   ```bash
   claude mcp add sonarqube --env SONARQUBE_TOKEN=$SONAR_TOKEN --env SONARQUBE_ORG=$SONAR_ORG -- docker run --init --pull=always -i --rm -e SONARQUBE_TOKEN -e SONARQUBE_ORG sonarsource/sonarqube-mcp
   ```

   Useful tools:
   - `search_sonar_issues_in_projects` finds issues.
   - `get_project_quality_gate_status` checks whether the gate passes.
   - `analyze_code_snippet` analyses a file.

   `SONARQUBE_TOOLSETS` limits which tools load, which saves context.

### Demo flow

1. Claude Code writes the feature and checks it through the SonarQube MCP server.
2. It opens a PR.
3. Gitar reviews it and auto-apply fixes the findings and any CI failure.
4. The SonarQube quality gate decides the merge.

That covers all three AC/DC steps: Guide, Verify and Solve.

## Links

- [Get started with Gitar](https://www.sonarsource.com/resources/library/get-started-with-gitar/)
- [Gitar quickstart](https://docs.gitar.ai/quickstart)
- [Gitar commands](https://docs.gitar.ai/commands)
- [Gitar rules](https://docs.gitar.ai/features/rules)
- [Project-aware reviews (review instructions and rules)](https://www.sonarsource.com/resources/library/gitar-context-ingestion-for-project-aware-code-reviews/)
- [Multilayered verification with Gitar and SonarQube Cloud](https://www.sonarsource.com/resources/library/multilayered-code-verification-with-gitar-sonarqube-cloud/)
- [Org instructions, Jira and Slack](https://www.sonarsource.com/resources/library/scale-gitar-context-across-an-organization/)
- [AC/DC blog post](https://www.sonarsource.com/blog/the-future-is-ac-dc-the-agent-centric-development-cycle/)
- [Sonar acquires Gitar (press release)](https://www.sonarsource.com/company/press-releases/sonar-acquires-gitar/)
- [SonarQube MCP server](https://github.com/SonarSource/sonarqube-mcp-server) and its [config generator](https://mcp.sonarqube.com/config-generator.html)
