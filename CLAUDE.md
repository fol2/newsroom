# newsroom

Governed authority/GraphRAG newsroom foundation. The legacy OpenClaw / Discord
/ Brave / GDELT / `news_pool` operational stack is dead (ADR 0009); git history
is its archive.

## Key Documentation

- [README.md](README.md) -- Project overview, installation, repository status
- [docs/README.md](docs/README.md) -- Documentation map and authority rules
- [AGENTS.md](AGENTS.md) -- Agent workflow notes and dead-stack boundary

## Project Structure

- `newsroom/` -- Core Python package (authority, projection, retrieval, sources, increments)
- `newsroom/tests/` -- Test suite
- `scripts/` -- Increment qualification CLIs and SDLC tooling
- `docs/` -- Specs, plans, ADRs, operations and research records

## Development

- Python 3.12+, deps in `pyproject.toml` (locked in `uv.lock`)
- Install (dev): `uv sync --dev --locked`
- Tests: `uv run --no-sync python -m pytest -q newsroom/tests`

## Code Style

- UK English; no auto-formatting enforced; follow existing patterns
- SQLite authority is canonical; Neo4j projections are rebuildable
- Fail closed: refusals are the default for unresolved or drifted identity

## Agent skills

### Issue tracker

Engineering work is tracked in GitHub Issues. External pull requests are not a triage request surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository, using a root `CONTEXT.md` and system-wide ADRs under `docs/adr/`. See `docs/agents/domain.md`.
