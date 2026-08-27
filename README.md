# Newsroom

Governed AI newsroom: editorial ledger, GraphRAG, Hermes Control Plane, and
native reader surfaces.

## Current repository status

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

The Hermes Control Plane is the operational Newsroom. OpenClaw, Discord, Brave
News, GDELT, the broad media RSS pool and `news_pool.sqlite3` are dead and must
not be restarted. RSS/Atom remains a Source Definition transport. Git history
is the archive. See [ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).

Start with these records:

- [AI-native Focus Gate SDLC](docs/specs/sdlc/ai-native-focus-gated-sdlc.md)
- [Repository automation contract](.sdlc/gates.toml)
- [Focused test behaviour](docs/testing.md)
- [Increment 1C operating and rollback guide](docs/operations/increment-1c-integrated-foundation.md)
- [Neo4j B2 qualification guide](docs/operations/neo4j-b2-qualification.md)
- [Neo4j B3 rebuild and promotion guide](docs/operations/neo4j-b3-rebuild-promotion.md)
- [Architecture](ARCHITECTURE.md)
- [Agent guide](AGENTS.md)
- [Contributing](CONTRIBUTING.md)
- [Documentation map](docs/README.md)

The earlier SDLC v2 design and acceptance records remain historical provenance.
They do not override the accepted Focus Gate contract.

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment management

## Installation

```bash
git clone https://github.com/fol2/newsroom.git
cd newsroom
uv sync --dev --locked
```

## Testing and evidence

Ordinary pull requests are routed by one deterministic Focus Gate evidence job. A separate trusted PR Lifecycle check validates metadata without installing project dependencies:

```bash
python -m scripts.sdlc.focus_gate route \
  --base <base-sha> --head <head-sha> --output .focus/route.json
python -m scripts.sdlc.focus_gate verify --route .focus/route.json
```

When the manifest requires a dependency bootstrap:

```bash
uv sync --dev --locked
python -m scripts.sdlc.focus_gate execute \
  --route .focus/route.json --junit .focus/pytest.xml
```

Documentation-only changes stop at F0 and install no dependencies. Full
repository health, actual-service qualification, research and irreversible
operational controls remain independent conditional lanes. See
[`AGENTS.md`](AGENTS.md) and [`docs/testing.md`](docs/testing.md).

## Key areas

| Area | Purpose |
|---|---|
| `newsroom/authority/` | Authenticated commands, SQLite event authority, governed objects, and projection authority. |
| `newsroom/projection/` | Structural ontology, mappings, projection contracts, and Neo4j adapter. |
| `newsroom/discovery_adapters/` | Source Registry RSS/Atom, JSON and document parsers. |
| `newsroom/integrated/` | Synthetic authority-to-GraphRAG-to-Candidate foundation proof. |
| `scripts/sdlc/focus_gate.py` | Deterministic ordinary-change routing and manifest execution. |
| `.github/workflows/focus-gates.yml` | One-job ordinary pull-request evidence. |
| `.github/workflows/evidence.yml` | Scheduled, manual and merge-queue full deterministic health. |
| `.github/workflows/ci.yml` | Isolated provider-free Graphiti research. |

## License

[MIT](LICENSE)
