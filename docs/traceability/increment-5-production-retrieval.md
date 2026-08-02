# Increment 5 production retrieval traceability

- **Status:** Exact 5A decision and delivery map
- **Machine source:** `newsroom/increment5/traceability.py`
- **Verification:** `newsroom/tests/test_increment5a_traceability.py`
- **Contract:** `newsroom/increment5/data/increment5a_retrieval_contract_v1.json`
- **Rows:** 114 unique accepted requirements

## Meaning

The map separates two facts:

- **Decision trace:** 5A binds the requirement or inherits an already accepted authority boundary.
- **Delivery trace:** implementation/evidence is present in 5A, deferred to its dependency-ordered issue, satisfied by Increment 4, or explicitly outside Increment 5 activation.

A requirement bound by 5A is not reported as an implemented retriever, tool, hydration path, Operational Profile or qualification run.

## Coverage families

The 114 rows cover:

- 22 `GRAG` requirements;
- 20 `GRPROD` requirements;
- 9 `TRI` requirements;
- 25 `DEVAL` requirements; and
- 38 `DOPS` requirements.

## Delivery distribution

| Boundary | Count | Meaning |
|---|---:|---|
| 5A / #250 | 21 | Contract, schemas, frozen plan, authority/non-effect decisions and traceability |
| 5B / #251 | 2 | Four typed retriever implementations |
| 5C / #252 | 7 | Six bounded named read-only tools |
| 5D / #253 | 35 | Authoritative hydration, freshness, reconciliation and degradation |
| 5E / #254 | 44 | Operational Profiles/objectives, actual-service qualification, security, purge, recovery and decision evidence |
| Increment 4 / #144 | 4 | Already accepted authority/projection foundations |
| Outside Increment 5 activation | 1 | Production activation remains unauthorised |

The counts total 114 and the groups are disjoint.

## Delivered in 5A

`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DEVAL-072`, `DOPS-037`, `DOPS-070`, `DOPS-076`, `GRAG-051`, `GRAG-052`, `GRAG-053`, `GRAG-058`, `GRPROD-002`, `GRPROD-003`, `GRPROD-004`, `GRPROD-013`, `GRPROD-014`, `GRPROD-015`, `GRPROD-020`, `GRPROD-023`, `GRPROD-032`.

These rows are verified only by the 5A contract/profile/plan/traceability tests and reviewed documents.

## Operational evidence remains deferred

The map intentionally leaves operational evidence in 5E rather than treating global retrieval limits as an executable Operational Profile:

- `DOPS-001` — exact owner-approved Operational Profile for each executable scope;
- `DOPS-002` — scope-specific timing, freshness, retry, capacity and alert objectives;
- `DOPS-064` — owner escalation and versioned runbook evidence;
- `DOPS-072` — tested rollback evidence;
- `DOPS-074` — rights, terms, pricing, access and credential-change review evidence; and
- `DOPS-075` — complete Operational Admission evidence.

`DEVAL-073` also remains in 5E because only a completed Run can retain its owner decision or explicit unresolved status. Real-request governance, latency/capacity evidence, rights-limited provider evaluation, failed-run retention, purge/recovery and actual-service qualification remain in 5E.

## Requirement-specific anchors

Every row has an explicit semantic anchor. The machine map rejects omitted or overlapping anchors and has no prefix-derived default. Examples include:

- `DEVAL-003` → contract non-effects;
- `DEVAL-051` → the exact threshold-freeze field;
- `DEVAL-064` → the rights matrix;
- `DEVAL-072` → the Evaluation Plan’s public-artifact-safety section;
- `DEVAL-073` → the completed-Run decision-output section; and
- `DOPS-001` / `DOPS-002` → explicit deferred #254 evidence anchors.

This prevents a syntactically valid pointer from claiming evidence that the referenced object does not contain.

## Decision state

There is no runtime “pending approval,” authenticated-comment, main-admission or post-merge materialisation state.

The reviewed merge is source governance. On `main`, every non-inherited row is `BOUND_BY_5A`; inherited rows remain `INHERITED_ACCEPTED_AUTHORITY`. The contract itself still authorises no production effect.

## Verification invariants

Tests reject:

- missing or duplicate requirement IDs;
- overlapping or incomplete delivery groups;
- missing, competing or generic requirement anchors;
- changed delivery counts;
- a 5A row pointing at later implementation evidence;
- an Operational Profile or scope-objective requirement claimed in 5A;
- a deferred row without its exact issue;
- production activation appearing inside Increment 5; and
- reintroduction of runtime GitHub approval/admission targets.
