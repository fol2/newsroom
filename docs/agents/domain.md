# Domain docs

This is a single-context repository.

## Before exploring

Read these when they exist:

- `CONTEXT.md` at the repository root
- Relevant ADRs under `docs/adr/`

Their absence is not an error. Continue silently. The domain-modelling flow creates them lazily after terminology or an architectural decision has genuinely been resolved.

## Domain language

Use canonical terms from `CONTEXT.md` in plans, issues, code, tests, and documentation. Avoid synonyms that the glossary marks as discouraged.

`CONTEXT.md` is a glossary only. It must not contain implementation details, plans, or architectural decisions.

## Architectural decisions

If proposed work conflicts with an existing ADR, identify the conflict explicitly. Do not silently override the recorded decision.
