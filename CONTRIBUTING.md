# Contributing to Newsroom

## Getting started

1. Fork and clone the repository:

```bash
git clone <your-fork-url> newsroom
cd newsroom
```

2. Install dependencies with uv:

```bash
uv sync --dev
```

Do not add OpenClaw, Discord, Brave, GDELT or `news_pool` credentials. That
stack is dead ([ADR 0009](docs/adr/0009-legacy-operational-newsroom-dead.md)).
RSS/Atom remains a Source Definition transport via `newsroom/discovery_adapters/`.

## Running tests

Run the smallest relevant files or node IDs during local iteration:

```bash
uv run --no-sync python -m pytest -q \
  newsroom/tests/test_RELEVANT.py
```

Environment setup is described above and should not be repeated before every
test command. Agent behaviour, complete-suite authority and stop-and-report
guidance live in [`AGENTS.md`](AGENTS.md) and [`docs/testing.md`](docs/testing.md).

## Code guidelines

- Follow existing code patterns and module structure.
- Keep modules focused on a single responsibility.
- The project intentionally avoids heavy dependencies like pandas and numpy. Do not introduce them.
- Use `from __future__ import annotations` in new modules.
- Type hints are used throughout; maintain them in new code.
- Test new functionality with unit tests in `newsroom/tests/`.
- Use UK English in code and documentation.

## Pull requests

- Keep PRs small and focused on a single change.
- Describe what changed and why in the PR description.
- Include test coverage for new functionality.
- When touching tests or fixtures, remove obvious duplicated setup and avoid
  sleeps or repeated I/O where a smaller semantics-preserving path already
  exists. Keep assertions and isolation intact.
- Prefer the smallest working change; do not add speculative abstractions,
  scaffolding or dependencies.
- Record the focused validation performed and anything deliberately not run.
- Do not add or expand a machine gate whose predicate is compliance with the
  behavioural guidance in `AGENTS.md`.
