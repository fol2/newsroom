# openclaw-newsroom

Automated AI newsroom: LLM clustering, multi-source news pool, Discord publishing.

## Key Documentation

- [README.md](README.md) -- Project overview, installation, configuration
- [ARCHITECTURE.md](ARCHITECTURE.md) -- Technical architecture and data flow
- [AGENTS.md](AGENTS.md) -- Cron agent system, planner/runner architecture
- [PROMPTS.md](PROMPTS.md) -- Prompt template system and validator reference

## Project Structure

- `newsroom/` -- Core Python package (18 modules)
- `newsroom/prompts/` -- LLM prompt templates (Mustache-style `{{VAR}}`)
- `newsroom/schemas/` -- JSON schemas for job files
- `newsroom/validators/` -- Output validators for LLM responses
- `newsroom/tests/` -- Test suite
- `scripts/` -- CLI entry points (9 scripts)

## Development

- Python 3.12+, deps in `pyproject.toml` (locked in `uv.lock`)
- Install (dev): `uv sync --dev`
- Tests: `uv run pytest newsroom/tests/ -v`
- All prompt template paths use `{{OPENCLAW_HOME}}` (resolved at runtime)
- `_render_template()` in runner.py auto-injects `OPENCLAW_HOME`

## Code Style

- No auto-formatting enforced; follow existing patterns
- Validators must inherit structure from `newsroom/validators/`
- New prompts need entries in `prompt_registry.json` + a matching validator

## Agent skills

### Issue tracker

Engineering work is tracked in GitHub Issues. External pull requests are not a triage request surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository, using a root `CONTEXT.md` and system-wide ADRs under `docs/adr/`. See `docs/agents/domain.md`.
