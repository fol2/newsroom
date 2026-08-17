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

All tests must pass before submitting changes:

```bash
uv run python -m pytest newsroom/tests/ -v
```

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
- Ensure all tests still pass.
