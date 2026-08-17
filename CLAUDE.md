# Newsroom

Automated AI newsroom: governed ledger, GraphRAG, Hermes Control Plane.

## Key documentation

- [README.md](README.md) -- Project overview, installation, configuration
- [ARCHITECTURE.md](ARCHITECTURE.md) -- Architecture and the dead legacy stack
- [AGENTS.md](AGENTS.md) -- Agent workflow and operational Newsroom
- [docs/README.md](docs/README.md) -- Documentation map

## Project structure

- `newsroom/` -- Core Python package (authority, projection, discovery adapters, increments)
- `newsroom/tests/` -- Test suite
- `scripts/` -- Increment and SDLC entry points
- `docs/adr/` -- Accepted architecture decisions

## Development

- Python 3.12+, deps in `pyproject.toml` (locked in `uv.lock`)
- Install (dev): `uv sync --dev`
- Tests: `uv run pytest newsroom/tests/ -v`

## Code style

- No auto-formatting enforced; follow existing patterns
- Repository documents and code use UK English

## Agent skills

### Issue tracker

Engineering work is tracked in GitHub Issues. External pull requests are not a triage request surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository, using a root `CONTEXT.md` and system-wide ADRs under `docs/adr/`. See `docs/agents/domain.md`.

The OpenClaw / Discord / Brave / GDELT / `news_pool` operational stack is dead.
See [ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).
