# Newsroom

Governed AI newsroom: editorial ledger, GraphRAG, Hermes Control Plane, and
native reader surfaces.

## Current repository status

The accepted foundation proves deterministic authority, SQLite-authoritative
state, rebuildable Neo4j projections and governed GraphRAG boundaries. Models,
extractors, Graphiti, similarity and ranking may propose; only deterministic or
authorised controllers may commit authority.

The Hermes Control Plane is the operational Newsroom. OpenClaw, Discord, Brave
News, GDELT, the broad media RSS pool and `news_pool.sqlite3` are dead and must
not be restarted. RSS/Atom remains a Source Definition transport. Git history
is the archive. See
[ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).

This repository status is not production admission. It grants no live source,
provider, publication, deployment, activation, spend or public-effect
authority.

## AI-native development

Start with:

- [Agent guide](AGENTS.md)
- [Review policy](REVIEW.md)
- [AI-native Focus Gate SDLC](docs/specs/sdlc/ai-native-focus-gated-sdlc.md)
- [Repository automation contract](.sdlc/gates.toml)
- [Focused test behaviour](docs/testing.md)
- [Contributing](CONTRIBUTING.md)
- [Documentation map](docs/README.md)

Ordinary work is agent-owned from issue intent through implementation, focused
evidence, one feature-complete review and merge. This repository has no
organisation ruleset or merge queue. Human/owner involvement is reserved for
F4, credentials, regulated or irreversible effects, unresolved ambiguity and
explicit product decisions.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency and environment management

```bash
git clone https://github.com/fol2/newsroom.git
cd newsroom
uv sync --dev --locked
```

## Testing and evidence

```bash
python -m scripts.sdlc.focus_gate_v2 route \
  --base <base-sha> --head <head-sha> --output .focus/route.json
python -m scripts.sdlc.focus_gate_v2 verify --route .focus/route.json
```

When the manifest requires a dependency bootstrap:

```bash
uv sync --dev --locked
python -m scripts.sdlc.focus_gate_v2 execute \
  --route .focus/route.json --junit .focus/pytest.xml
```

Documentation-only changes stop at F0 and install no dependencies. Full product
health runs after pushes to `main`, on schedule and manually. Actual-service,
research and irreversible operational controls remain independent conditional
lanes.

## Key areas

| Area | Purpose |
|---|---|
| `newsroom/authority/` | Authenticated commands, SQLite event authority and governed objects |
| `newsroom/projection/` | Structural ontology, projection contracts and Neo4j adapter |
| `newsroom/discovery_adapters/` | Source Registry RSS/Atom, JSON and document parsers |
| `newsroom/integrated/` | Synthetic authority-to-GraphRAG-to-Candidate proof |
| `scripts/sdlc/focus_gate_v2.py` | Deterministic ordinary-change routing and execution |
| `.github/workflows/focus-gates.yml` | One-job ordinary pull-request evidence |
| `.github/workflows/evidence.yml` | Post-merge, scheduled and manual full product health |
| `.github/workflows/ci.yml` | Isolated provider-free Graphiti research |

## License

[MIT](LICENSE)
