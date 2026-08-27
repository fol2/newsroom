# Contributing to Newsroom

## Set up

```bash
git clone <your-fork-url> newsroom
cd newsroom
uv sync --dev --locked
```

Do not add OpenClaw, Discord, Brave, GDELT or `news_pool` credentials. That stack is dead; see [ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md).

## Delivery shape

Keep one coherent change in one issue, branch and PR. Split only at an independent merge, rollback, owner, dependency or release boundary. Prefer deletion and reuse over new scaffolding.

The repository's ordinary PR workflow generates a deterministic Focus Gate manifest. It selects the smallest relevant evidence set and escalates on unresolved or cross-cutting risk.

## Local validation

```bash
python -m scripts.sdlc.focus_gate route \
  --base <base-sha> --head <head-sha> --output .focus/route.json
python -m scripts.sdlc.focus_gate verify --route .focus/route.json
```

When the manifest says `bootstrap_required: true`:

```bash
uv sync --dev --locked
python -m scripts.sdlc.focus_gate execute \
  --route .focus/route.json --junit .focus/pytest.xml
```

Do not substitute the complete repository for a missing direct regression. Do not add Neo4j, provider, research or full-health work unless the route selects it. Detailed guidance is in [`docs/testing.md`](docs/testing.md).

## Code

- Follow existing module boundaries and patterns.
- Use `from __future__ import annotations` in new modules.
- Maintain type hints.
- Avoid heavy dependencies such as pandas and numpy.
- Preserve deterministic, isolated tests.
- Use UK English.

## Pull requests

Describe the intent, exact state, Focus Gate manifest, focused evidence, review findings and non-effects. One feature-complete review is the default. Repeat only after a material change or unresolved relevant finding.

Do not wait or poll merely to fill the PR template. Report an independently running workflow once if its state is already available.
