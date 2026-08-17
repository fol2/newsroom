# Newsroom Agent Guide

## 0. Development workflow

When asked to create PRs (especially when using multiple sub-agents), prefer **real GitHub PRs** by default:

- Each sub-agent should work on its own branch (and worktree if helpful).
- Push the branch to the remote.
- Open a GitHub PR (e.g. via `gh pr create`) and share the PR link/number in the handoff.
- Merge via GitHub after review.

If GitHub access is unavailable (no remote, no auth, or network restrictions), fall back to local branches and clearly state that the workflow is local-only.

## 1. Operational Newsroom

The operational Newsroom is the **Hermes Control Plane**: a distinct daemon LaunchAgent with veto, ledger, broker, signed stop, Newsroom schedule and live dispatcher. `newsroom-hub` is private Control Plane UI, not the Control Plane. Canonical terms live in `CONTEXT.md`. Hard-to-reverse decisions live in `docs/adr/`.

This repository does not run OpenClaw cron planners, the OpenClaw runner, Discord publishing, Brave News, GDELT DOC 2.0, the broad media RSS pool, `news_pool.sqlite3` or per-link Gemini clustering. That stack is dead and must not be restarted. RSS/Atom remains a Source Definition transport. Git history is the archive. See [ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).

Increment 11B is a Hermes fresh start. This file grants no live source, credential, spend, publication or activation authority.

## 2. Agent documentation

- [Issue tracker](docs/agents/issue-tracker.md)
- [Triage labels](docs/agents/triage-labels.md)
- [Domain docs](docs/agents/domain.md)
- [Documentation map](docs/README.md)

## 3. Development

- Python 3.12+, deps in `pyproject.toml` (locked in `uv.lock`)
- Install (dev): `uv sync --dev`
- Tests: `uv run pytest newsroom/tests/ -v`
- Repository documents and code use UK English
