# Newsroom

Automated AI newsroom: governed ledger, GraphRAG and Hermes Control Plane.

## Working contract

Follow [`AGENTS.md`](AGENTS.md). It is the concise always-loaded authority for
the AI-native development loop, owner-above boundary, Focus Gates, research
isolation, review discipline and stop conditions.

The GitHub issue is the ordinary change-intent SSOT. Use the deterministic
router in `scripts/sdlc/focus_gate_v2.py`; the older `focus_gate.py` remains
only for retained compatibility. Detailed test guidance is in
[`docs/testing.md`](docs/testing.md), and the accepted contract is in
[`docs/specs/sdlc/ai-native-focus-gated-sdlc.md`](docs/specs/sdlc/ai-native-focus-gated-sdlc.md).

## Repository map

- `newsroom/` — product and authority code
- `newsroom/tests/` — deterministic and service tests
- `scripts/` — bounded operational and SDLC entry points
- `.github/workflows/focus-gates.yml` — ordinary pull-request gate
- `.github/workflows/evidence.yml` — post-merge, scheduled and manual health
- `.github/workflows/ci.yml` — isolated Graphiti research
- `docs/adr/` — hard-to-reverse decisions
- `docs/README.md` — documentation map

Python 3.12+ is required. Dependencies are locked in `uv.lock`. Repository
documents and code use UK English.

The OpenClaw / Discord / Brave / GDELT / `news_pool` operational stack is dead;
see [ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).
