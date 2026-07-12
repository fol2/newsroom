# Specifications

Specifications define the intended behaviour of the newsroom application and its automated or agentic systems. They are the development source of truth when their status is `Accepted`.

English is the default canonical language for specifications because they are consumed by development agents, code-generation workflows, tests and technical contributors. A translation may be provided for review, but it must identify the English canonical file and must not silently alter requirements.

## What belongs here

Examples include:

- product and user-visible behaviour;
- news discovery, clustering, selection, writing and publishing workflows;
- agent roles, tool permissions and human-control boundaries;
- pipeline states, interfaces, schemas and failure handling;
- source, evidence and quality gates that can be implemented or tested;
- storage, retention, privacy, security and observability requirements;
- acceptance criteria for a feature or system change.

A spec should contain only policy or reference material that has been converted into a concrete, implementable requirement. Longer legal, editorial, market or business background belongs under `docs/reference/` and may be linked from the spec.

## Specification suites

A broad product boundary may be represented as a specification suite containing an index and several stable modules. Split by enduring behavioural concern rather than by expected implementation ticket.

A suite should:

- define cross-cutting invariants once;
- give every normative requirement a stable identifier;
- identify which reference sections it adopts;
- keep module boundaries understandable without duplicating requirements; and
- state how conformance is evaluated across modules.

The first suite is [`editorial-automation/`](editorial-automation/).

## Relationship to plans

A specification and a plan do not need a one-to-one relationship.

- One stable spec may require several delivery plans or phases.
- One implementation plan may target several specs to deliver a safe vertical slice.
- Every plan must list the exact spec files and requirement identifiers in scope.
- A plan cannot change a requirement by restating it differently; the spec must be reviewed or superseded.

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
**Canonical language:** English  
**Related plan:** <link or none>  
**Related reference:** <link or none>  
**Supersedes:** <link or none>

## Purpose

## Scope

## Requirements

Use MUST, SHOULD and MAY deliberately. Give normative requirements stable identifiers and make them testable or reviewable.

## Acceptance criteria

## Non-goals

## Open questions
```

## Writing rules

- Distinguish current behaviour from target behaviour.
- Prefer precise requirements over broad aspirations.
- State inputs, outputs, invariants, failure behaviour and human-control points where relevant.
- Treat model and agent outputs as untrusted until the applicable gates pass.
- Do not hide unresolved decisions inside apparently final requirements.
- Keep task lists and delivery sequencing in a plan rather than in the spec.
- If a reference document is adopted, state exactly which constraint is adopted; do not make the entire reference normative by implication.
- Use requirement identifiers in plans, issues, tests and implementation notes so future agents can trace intent.
