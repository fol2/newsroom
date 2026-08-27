# Contributing to Newsroom

## Set up

```bash
git clone <your-fork-url> newsroom
cd newsroom
uv sync --dev --locked
```

Do not add OpenClaw, Discord, Brave, GDELT or `news_pool` credentials. That
stack is dead; see
[ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).

## Delivery shape

Keep one coherent change in one issue, branch and PR. Split only at an
independent merge, rollback, owner, dependency or release boundary. Prefer
deletion and reuse over new scaffolding.

The GitHub issue is the ordinary change-intent SSOT. Do not manufacture a
second intent, plan or specification unless a concrete ambiguity or independent
durable decision requires one.

## Local validation

```bash
python -m scripts.sdlc.focus_gate_v2 route \
  --base <base-sha> --head <head-sha> --output .focus/route.json
python -m scripts.sdlc.focus_gate_v2 verify --route .focus/route.json
```

When the manifest says `bootstrap_required: true`:

```bash
uv sync --dev --locked
python -m scripts.sdlc.focus_gate_v2 execute \
  --route .focus/route.json --junit .focus/pytest.xml
```

Do not substitute the complete repository for a missing direct regression. Do
not add Neo4j, provider, research or full-health work unless the route selects
it. Detailed guidance is in [`docs/testing.md`](docs/testing.md).

## Code

- Follow existing module boundaries and patterns.
- Use `from __future__ import annotations` in new modules.
- Maintain type hints.
- Avoid heavy dependencies such as pandas and numpy.
- Preserve deterministic, isolated tests.
- Use UK English.

## Pull requests and merge

Describe the intent, exact state, Focus Gate manifest, focused evidence, review
findings and non-effects. One feature-complete review is the default. Repeat
only after a material change or unresolved relevant finding.

This repository has no organisation ruleset or merge queue. For ordinary
non-F4 work, the agent may merge after one observed exact-head Focus Gate
success and one clean feature-complete review. F4, credentials, regulated or
irreversible effects and explicit owner decisions remain human/owner gated.

Do not wait or poll merely to fill the PR template. Report an independently
running workflow once if its state is already available.
