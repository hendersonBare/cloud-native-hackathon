@AGENTS.md

## Quick reference

- Spec: `docs/SPEC.md` · Your brief: `docs/workstreams/<name>.md` · Setup: `docs/SETUP.md`
- Test everything: `make test` (ruff + pytest + `opa test`)
- Run a component locally: `PYTHONPATH=src uv run python -m rapport_<component>`
- Subagents live in `.claude/agents/` (one per workstream, each in its own git worktree)
