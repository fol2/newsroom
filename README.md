# Newsroom

Newsroom is the accepted authority/GraphRAG foundation for an integrated,
governed news system. The legacy OpenClaw / Discord / Brave / GDELT /
`news_pool` operational stack is dead and has been deleted from the working
tree ([ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md)); git
history is its archive. RSS/Atom survives only as a Source Definition
transport inside the Source Registry.

## Current Repository Status

Increment 1 is complete. The merged foundation proves one synthetic,
deterministic path through authenticated command authority, the SQLite ledger,
governed-object hydration, an authority-selected Neo4j structural projection,
and SQLite-authoritative Candidate admission.

The foundation establishes these rules:

- SQLite ledger records, retained contracts, governed objects, Retrieval Context
  records, and Candidate tables are authoritative.
- Neo4j is a disposable, rebuildable projection. It never creates or repairs
  ledger, governed-object, or Candidate authority.
- GraphRAG is mandatory for qualifying production, evaluation, and complete
  live-shadow profiles; a missing, fake, disabled, stale, or graph-free variant
  fails closed.
- Models, extractors, Graphiti, similarity, and ranking may propose. Only
  deterministic or authorised controllers may commit authority.
- Graph loss is recovered from SQLite and governed-object authority, and
  deletion or tombstone state cannot be resurrected by rebuild.

This is a foundation proof, not production admission. It authorises no live
source access, Graphiti/model/embedding execution, publication, product shadow,
canary, production activation, spending, or public effect.

Start with these records:

- [Increment 1C operating and rollback guide](docs/operations/increment-1c-integrated-foundation.md)
- [Neo4j B2 qualification guide](docs/operations/neo4j-b2-qualification.md)
- [Neo4j B3 rebuild and promotion guide](docs/operations/neo4j-b3-rebuild-promotion.md)
- [SDLC v2 specification](docs/specs/sdlc/high-performance-evidence-sdlc.md)
- [SDLC v2 owner acceptance record](docs/specs/sdlc/2026-07-22-sdlc-v2-owner-acceptance.md)
- [Machine gate contract](.sdlc/gates.toml)

## Legacy Operational Stack (Dead)

The OpenClaw cron planners, deterministic runner, Discord publishing path,
Brave News and GDELT ingestion, the broad-media RSS pool, and the
`news_pool.sqlite3` clustering pipeline are dead and must not restart
([ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md)). Their code
has been removed from the tree; git history is the inspirational archive.
None of that stack is live or eligible to return.

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment management

## Installation

```bash
git clone https://github.com/fol2/newsroom.git
cd newsroom
uv sync --dev --locked
```

## Testing and Evidence

Run the locked deterministic suite:

```bash
uv lock --check
uv sync --dev --locked
uv run --no-sync python -m pytest -q newsroom/tests
```

Changes to authority, persistence, Neo4j integration, workflows, or SDLC
contracts are routed through the repository-owned risk classifier and may
require the authenticated actual-service lane. See `.sdlc/gates.toml` rather
than weakening or bypassing the selected evidence.

## Key Areas

| Area | Purpose |
|---|---|
| `newsroom/authority/` | Authenticated commands, SQLite event authority, governed objects, and projection authority. |
| `newsroom/projection/` | Structural ontology, mappings, projection contracts, and Neo4j adapter. |
| `newsroom/integrated/` | Synthetic authority-to-GraphRAG-to-Candidate foundation proof. |
| `newsroom/sources/` | Source Registry (including RSS/Atom as a Source Definition transport). |
| `newsroom/increment2/` – `increment10/` | Governed increment proofs and qualification evidence. |
| `scripts/sdlc/` | Exact-tree routing, watchdog, evidence, transport, telemetry, and decision tooling. |
| `.github/workflows/evidence.yml` | Permanent always-reporting SDLC evidence shadow. |

## Documentation

- [docs/README.md](docs/README.md) -- Documentation map and authority rules
- [CONTEXT.md](CONTEXT.md) -- Canonical domain glossary
- [docs/adr/](docs/adr/) -- Accepted architecture decisions
- [CONTRIBUTING.md](CONTRIBUTING.md) -- Development guidance

## License

[MIT](LICENSE)
