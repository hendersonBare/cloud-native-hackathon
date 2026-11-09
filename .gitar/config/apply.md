# Auto-apply limits

When auto-apply is on for a PR, commit only fixes that stay inside the files the PR already changes.

Never auto-apply a fix that:

- edits a contract: `src/rapport_common/**`, `deploy/crds/**`, `deploy/elastic/**` or `contracts/**`;
- edits `policy/`, `deploy/base/`, `.github/workflows/`, any RBAC, NetworkPolicy or Secret manifest, upload or redaction code in `src/rapport_briefer/`, or message handling in `src/rapport_delegate/` (a person reviews these, AGENTS.md §5);
- turns off a lint rule, skips or deletes a test, marks it xfail or loosens an assertion to get CI green;
- adds or upgrades a dependency in `pyproject.toml` or `uv.lock`.

Leave these as review comments for a person to act on.
