# Increment 5 scope and risk-tiered gate amendment

- **Status:** owner-authorised amendment; repository acceptance occurs on merge
- **Owner record:** issue #327
- **Programme:** #141
- **Increment:** #145
- **Original replanning base:** `main@7a4164f0a0b7c7c70cd68b2a5485110e7ca576f3`
- **Implementation continuation base after 5B3:** `main@896a0bd94db25927b5d63f9537d21e5170292621`
- **Machine map:** `newsroom/increment5/traceability.py`
- **Human map:** `docs/traceability/increment-5-production-retrieval.md`
- **Verification:** `newsroom/tests/test_increment5a_traceability.py`

## Decision

Increment 5 completes the bounded retrieval product. It does not complete the
newsroom's cross-request triage/Candidate effects or the full evaluation and
operational-admission programme.

The accepted authority, rights and no-false-success rules are unchanged.
This amendment changes delivery ownership and the level at which evidence is
required. It removes neither a safety requirement nor a normative requirement
from the 155-row inventory.

The amended complete distribution is:

`9 / 0 / 2 / 12 / 9 / 6 / 110 / 7`

for 5A, 5B, 5C, 5D, 5E, Increment 6, Increment 8 and accepted Increment 4
delivery respectively. There is no ownerless activation bucket.

## Retained authority boundary

- SQLite, immutable decisions and governed objects remain authoritative.
- Neo4j, full-text and vector structures remain disposable projections.
- Retrieval, graph paths, rank and similarity remain context.
- No retrieval component allocates Event Hypothesis identity, merges records,
  admits a Candidate, acquires evidence, publishes, or activates production.
- No arbitrary Cypher, graph write surface, caller-selected index or predicate,
  provider credential, live source, external call or spend is authorised.
- Rights, tombstone, current-generation, watermark, gap, provenance and
  no-false-success semantics remain fail-closed.
- A valid empty result requires a complete request. Unavailable, stale, blocked
  or incomplete work cannot become no-match.

## Corrected Increment 5 product

Increment 5 delivers:

1. four independently attributable retrievers;
2. bounded named read-only tools;
3. exact-first one-request composition, deterministic fusion and authoritative
   dependency-root deduplication;
4. authoritative hydration and truthful Retrieval Context outcomes; and
5. retrieval-specific corpus/ablation, query containment, security boundary,
   rights purge and graph/index recovery on affected actual services.

It does not claim production embedding quality, human evaluation authority,
Operational Profiles, schedules, queues, live shadow, canary or activation.

## Risk-tiered merge gates

### Tier L — leaf component atom

Use Tier L when a bounded component introduces no external call, graph write,
authoritative migration or cross-component composition.

Required evidence:

- focused component tests;
- complete deterministic CI once on the current product head;
- source-integrity and boundary tests;
- one substantive current-head review; and
- zero unresolved P1 or material P2 findings.

Unchanged service and actual-service lanes are not automatic gates.

### Tier S — service or authority integration atom

Use Tier S when a change touches Neo4j, an authority read or mutation boundary,
rights-sensitive hydration, migration or cross-component orchestration.

Required evidence:

- focused and complete deterministic CI;
- only affected Authority, Projection and actual-service lanes;
- one substantive current-head review; and
- zero unresolved P1 or material P2 findings.

### Tier M — milestone closeout

Use Tier M once at the integrated close of #251, #252, #253 and final #254.

Required evidence:

- all applicable permanent workflows on one exact integrated `main` head;
- authenticated actual-service evidence where the milestone uses Neo4j;
- a signed SDLC decision;
- integrated replay, rights, failure and no-false-success cases; and
- zero unresolved P1/P2 findings and review threads.

A leaf is not repeatedly treated as a final production release.

## Pull-request and review policy

- One canonical PR per delivery atom.
- Normal fix commits are allowed; squash merge supplies one `main` commit.
- A branch is not rebuilt solely to manufacture a one-commit review.
- Environment-error workflows may be rerun without source churn.
- Review is repeated after material product changes, not after evidence-only
  metadata, comments, labels or reruns.
- At most one disposable support/preflight PR may exist for an atom.
- Checkpoint refs may preserve work. Workflow carriers, installers, patch
  archives and source-transfer material never enter the product diff.
- P1 always blocks. Correctness, authority, rights, security, data-loss,
  false-success or evidence-integrity P2 findings also block.
- A non-material maintainability P2 may be transferred to a linked follow-up.

## Exact Increment 5 ownership

### 5A / #250 — nine requirements

`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DOPS-076`,
`GRAG-052`, `GRAG-053`, `GRAG-058`, `GRPROD-032`.

These are the accepted contract, Plan/Epoch, non-execution and traceability
decisions. Their acceptance does not deliver later runtime systems.

### 5B / #251 — no complete selected requirement

5B supplies exact, full-text, fixture-vector and admitted-graph branches.
The branches are necessary implementation atoms, but whole selected
requirements are credited at composition or a later integrated boundary.

5B closes once with a Tier M aggregate proof after all four retrievers merge.

### 5C / #252 — two requirements

`GRAG-033`, `GRAG-034`.

5C owns the bounded named read-only surface and the prohibition on unrestricted
graph mutation. It does not own fused cross-branch meaning.

### 5D / #253 — twelve request-local requirements

`GRAG-031`, `GRAG-032`, `GRAG-035`, `GRAG-040`, `GRAG-041`, `GRAG-043`,
`TRI-020`, `TRI-021`, `TRI-022`, `TRI-023`, `TRI-025`, `TRI-027`.

5D ends at one read-only Retrieval Context request: exact-first composition,
fusion, dependency-root deduplication, authority hydration, current collision
receipt, inspectable provenance and truthful complete/incomplete outcomes.

`GRAG-042` is not claimed here because its complete path reaches Hypothesis and
Candidate state outside one retrieval request.

### 5E / #254 — nine retrieval-specific requirements

`GRAG-050`, `GRAG-051`, `GRAG-054`, `GRAG-055`, `GRAG-056`,
`GRPROD-001`, `GRPROD-010`, `GRPROD-015`, `GRPROD-023`.

5E owns the exact repository-native retrieval implementation target,
mandatory-mode/configuration enforcement, bounded challenger rule,
retrieval-specific use cases and ablation, and provenance/temporal blockers.

5E1/#332 supplies the deterministic corpus and ablation. 5E2/#333 supplies
query containment, rights purge, graph/index loss and replacement recovery,
affected actual-service evidence and the final Tier M Increment 5 proof.

No complete `DEVAL-*` or operational `DOPS-*` requirement is credited to 5E.

## Ownership transferred to Increment 6 / #146

The exact six-row transfer is:

`GRAG-042`, `GRAG-044`, `GRPROD-021`, `TRI-024`, `TRI-026`, `TRI-028`.

Increment 6 owns:

- Event Hypothesis and Candidate integration after Retrieval Context;
- the complete Source/Revision/Signal/Lead → Work Item/Proposal → Hypothesis →
  Candidate path;
- Candidate-admission enforcement of a current authoritative collision result;
- empty-retrieval non-creation at the downstream decision boundary;
- Watch/Operational Hold or exact-fallback effects; and
- durable later reconciliation/Handoff after guarded urgent degradation.

Increment 5 may return a read-only collision receipt or a
reconciliation-required flag. It cannot claim that the later effect occurred.

## Ownership transferred to Increment 8 / #148

Increment 8 owns 110 requirements:

- every `DEVAL-*` requirement except the four 5A decisions;
- every `DOPS-*` requirement except `DOPS-076`; and
- `GRAG-045`, `GRAG-046`, `GRAG-057`, `GRPROD-002`, `GRPROD-004`,
  `GRPROD-011`, `GRPROD-012`, `GRPROD-022`, `GRPROD-024`, `GRPROD-030`
  and `GRPROD-031`.

This includes the prospective event universe, sampling, production labels,
human review, blinding, adjudication, disagreement and release decisions;
Operational Profiles, schedules, leases, retries, circuits, quarantine,
queues, fairness and capacity; health, coverage posture, observability, alerts,
incidents, owners and runbooks; credential/source-access/egress admission and
manual actions; complete newsroom reconciliation, backup/restore, fault
injection, rollback, intended-hardware performance, cost, licence and
Operational Admission.

`GRPROD-022` therefore has a named owner rather than an ownerless
outside-activation classification.

## Accepted prior delivery

Seven requirements retain exact accepted Increment 4 evidence:

`GRAG-030`, `GRPROD-003`, `GRPROD-005`, `GRPROD-013`, `GRPROD-014`,
`GRPROD-016`, `GRPROD-020`.

Their decision anchors remain pinned to
`main@c9e31879421083e82e2538d57087d04e9b454d34`.

## Corrected sequence

1. Finish 5B3/#303 and 5B4/#308.
2. Close #251 once with Tier M evidence.
3. Complete 5C1/#328, then 5C2/#329 and close #252 once.
4. Complete 5D1/#330, then 5D2/#331 and close #253 once.
5. Complete 5E1/#332, then final 5E2/#333 and close #254/#145 once.

5C implementation does not start until this amendment and #251 are complete.

## Amendment acceptance gate

This planning-only PR is a Tier L atom. It merges only after complete
deterministic CI once on its exact head, the focused inventory/anchor tests, one
substantive current-head review and zero unresolved P1 or material P2 findings.
Its merge accepts the corrected map; it does not itself close #251 or grant
runtime, qualification, publication or activation authority.

## Verification

The machine tests prove:

- all 155 accepted IDs remain present exactly once;
- accepted `DEVAL-*` and `DOPS-*` headings equal the machine inventory;
- delivery groups are disjoint and complete;
- the amended count distribution is exact;
- 5D contains only request-local obligations;
- 5E contains only the nine retrieval-specific obligations;
- the six cross-request obligations point to #146;
- all non-5A evaluation and operational obligations point to #148;
- prior Increment 4 anchors remain exact; and
- no issue URL replaces a normative decision anchor.

This amendment changes planning and traceability only. It creates no runtime
call, provider effect, authority mutation, public effect or activation.
