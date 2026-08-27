# Newsroom

Automated AI newsroom: governed ledger, GraphRAG and Hermes Control Plane.

## Working contract

Follow [`AGENTS.md`](AGENTS.md). It is the concise always-loaded authority for the AI-native development loop, Focus Gates, research isolation, review discipline and stop conditions.

Use the deterministic ordinary-PR router in `scripts/sdlc/focus_gate.py`. Detailed test guidance is in [`docs/testing.md`](docs/testing.md); the accepted machine and workflow contract is in [`docs/specs/sdlc/ai-native-focus-gated-sdlc.md`](docs/specs/sdlc/ai-native-focus-gated-sdlc.md).

## Repository map

- `newsroom/` — product and authority code
- `newsroom/tests/` — deterministic and service tests
- `scripts/` — bounded operational and SDLC entry points
- `.github/workflows/focus-gates.yml` — ordinary pull-request gate
- `.github/workflows/evidence.yml` — scheduled, manual and merge full health
- `.github/workflows/ci.yml` — isolated Graphiti research
- `docs/adr/` — hard-to-reverse decisions
- `docs/README.md` — documentation map

Python 3.12+ is required. Dependencies are locked in `uv.lock`. Repository documents and code use UK English.

The OpenClaw / Discord / Brave / GDELT / `news_pool` operational stack is dead; see [ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).
