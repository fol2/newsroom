# Contributing to Newsroom

## Getting Started

```bash
git clone <your-fork-url> newsroom
cd newsroom
uv sync --dev --locked
```

## Running Tests

```bash
uv lock --check
uv sync --dev --locked
uv run --no-sync python -m pytest -q newsroom/tests
```

Tests live in `newsroom/tests/` and cover the authority ledger, governed
objects, projections, retrieval, and the increment qualification evidence.

## Ground Rules

- UK English in documents and code.
- SQLite ledger records and governed objects are authoritative; Neo4j is a
  disposable, rebuildable projection.
- Only deterministic or authorised controllers commit authority; models and
  adapters may propose only.
- Changes to authority, persistence, Neo4j integration, workflows, or SDLC
  contracts are routed through the repository-owned risk classifier
  (`.sdlc/gates.toml`). Do not weaken or bypass the selected evidence.
- The legacy OpenClaw / Discord / Brave / GDELT / `news_pool` operational
  stack is dead ([ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md))
  and must not be reintroduced. Git history is its archive.

## Documentation

- `docs/README.md` explains document types and implementation authority.
- `CONTEXT.md` is the canonical domain glossary; keep terminology aligned.
- Hard-to-reverse decisions belong in `docs/adr/`.
