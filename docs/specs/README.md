# Specifications

Specifications define the intended behaviour of the newsroom application and its automated or agentic systems. They are the development source of truth when their status is `Accepted`.

## What belongs here

Examples include:

- product and user-visible behaviour;
- news discovery, clustering, selection, writing and publishing workflows;
- agent roles, tool permissions and human-control boundaries;
- pipeline states, interfaces, schemas and failure handling;
- source, evidence and quality gates that can be implemented or tested;
- storage, retention, privacy, security and observability requirements;
- acceptance criteria for a feature or system change.

A spec should contain only the policy or reference material that has been converted into a concrete, implementable requirement. Longer legal, editorial, market or business background belongs under `docs/reference/` and may be linked from the spec.

## Status values

- `Draft` — under discussion; not an implementation instruction by default.
- `Accepted` — approved target behaviour and normative for implementation.
- `Superseded` — replaced by another spec; retain it for history and link to the replacement.
- `Retired` — no longer applies and has no replacement.

## Minimum document shape

```markdown
# <Specification title>

**Status:** Draft | Accepted | Superseded | Retired  
**Owner:** <name or role>  
**Last updated:** YYYY-MM-DD  
**Related plan:** <link or none>  
**Related reference:** <link or none>  
**Supersedes:** <link or none>

## Purpose

## Scope

## Requirements

Use MUST, SHOULD and MAY deliberately. Requirements should be testable or reviewable.

## Acceptance criteria

## Non-goals

## Open questions
```

## Writing rules

- Distinguish current behaviour from target behaviour.
- Prefer precise requirements over broad aspirations.
- State inputs, outputs, invariants, failure behaviour and human approval points where relevant.
- Do not hide unresolved decisions inside apparently final requirements.
- Keep task lists and delivery sequencing in a plan rather than in the spec.
- If a reference document is adopted, state exactly which constraint is adopted; do not make the entire reference normative by implication.