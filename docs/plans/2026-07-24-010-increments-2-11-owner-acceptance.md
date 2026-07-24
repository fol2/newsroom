# Owner acceptance — Increments 2–11 readiness and Increment 2 implementation

**Status:** Accepted  
**Owner:** Product owner  
**Accepted by owner:** 2026-07-24  
**Canonical language:** English  
**Accepted review boundary:** PR #140  
**Immediate implementation issue:** #142  
**Reviewed base before merge:** `main@5fcd8bc862e552961b6b147572879e79c7266931`

## Decision

The product owner accepts the planning and readiness records introduced by PR #140:

- `2026-07-24-008-increment-2-complete-fixture-readiness.md`;
- `2026-07-24-009-increments-3-11-readiness-ladder.md`; and
- the dependency-ordered issue structure under programme epic #141.

This record supersedes the pre-acceptance `Proposed — owner review required` status metadata in those two readiness documents. Their technical boundaries, exclusions, dependencies, completion gates and stop conditions are accepted as the governing preparation records unless a later owner decision amends them explicitly.

## Increment 2 implementation authority

The owner authorises Increment 2 issue #142 to proceed after PR #140 is merged to `main` and the exact merge head is recorded on the issue.

Implementation authority is limited to the four dependency-ordered review units defined by the accepted Increment 2 readiness package:

1. **2A — governed relation authority and fixture schema**;
2. **2B — actual Neo4j full-text/vector projection foundation**;
3. **2C — bounded hybrid retrieval and authoritative context**; and
4. **2D — complete actual-Neo4j fixture proof**.

Each unit remains a separate review and merge boundary. Every unit must identify exact Accepted requirements, exclusions, migrations, tests, actual-service evidence, traceability and rollback. All required checks must pass for the exact reviewed head, and current-head substantive review must record zero unresolved P1/P2 findings and zero unresolved review threads before merge.

## Fixed authority and runtime limits

This acceptance does not authorise:

- live RSS, JSON, Brave, GDELT, search or other source execution;
- Graphiti runtime execution;
- external model, prompt or embedding calls;
- production protected-content vectors;
- named source credentials or schedules;
- full triage or Evidence Intake;
- spending, shadow, canary, publication, production activation or public effect.

SQLite ledger records, immutable decisions, governed objects, Retrieval Contexts and Candidate records remain authoritative. Neo4j, vector and full-text data remain rebuildable projections. Rank, similarity, relation proposals, Graphiti or models cannot allocate authoritative identity or commit Candidate authority.

## Later increments

The Increments 3–11 readiness ladder is accepted as a dependency and decision map, not as present implementation or runtime authority.

- Increments 3–8 remain blocked until their predecessor closes and a fresh current-head implementation boundary is authorised.
- Increment 9 still requires a separate owner-approved exact shadow and Evaluation Plan.
- Increment 10 still requires Accepted or explicitly authorised Evidence Intake authority and a canary plan.
- Increment 11 still requires Accepted or explicitly authorised publication-facing requirements and one explicit production activation and legacy-retirement decision.

No blocked issue is in progress merely because it exists.

## Stop rule

Increment 3 must not begin until Increment 2 review units 2A–2D are merged, issue #142 is closed as completed, exact evidence and deferred work are recorded on `main`, and a fresh owner-authorised Increment 3 implementation issue records the then-current head.

Acceptance of this record authorises no expansion beyond these exact boundaries.