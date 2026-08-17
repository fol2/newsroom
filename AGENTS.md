# Newsroom Agent Notes

## Development Workflow Note

When asked to create PRs (especially when using multiple sub-agents), prefer **real GitHub PRs** by default:

- Each sub-agent should work on its own branch (and worktree if helpful).
- Push the branch to the remote.
- Open a GitHub PR (e.g. via `gh pr create`) and share the PR link/number in the handoff.
- Merge via GitHub after review.

If GitHub access is unavailable (no remote, no auth, or network restrictions), fall back to local branches and clearly state that the workflow is local-only.

## Legacy Operational Stack (Dead)

The OpenClaw cron planner / deterministic runner / Discord publishing system
that this file previously documented is dead and deleted from the working tree
([ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md)). That includes
the Brave News and GDELT ingestion clocks, the broad-media RSS pool, the
`news_pool.sqlite3` clustering pipeline, the prompt registry and validators,
and the story-job runner. Git history is the inspirational archive.

Do not restart, reinstall, or recreate any part of that stack. It is not live
and not eligible to return. RSS/Atom remains only as a Source Definition
transport inside the Source Registry (`newsroom/sources/`,
`newsroom/discovery_adapters/`).

The operational successor is the Hermes Control Plane and the governed
increment path (Increments 9–11). See `CONTEXT.md` for canonical terms and
`docs/adr/` for the accepted decisions.
