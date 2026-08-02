# Increment 5 production retrieval traceability

- **Status:** Exact 5A decision and delivery map
- **Machine source:** `newsroom/increment5/traceability.py`
- **Verification:** `newsroom/tests/test_increment5a_traceability.py`
- **Contract:** `newsroom/increment5/data/increment5a_retrieval_contract_v1.json`
- **Rows:** 114 unique accepted requirements

## Meaning

The map separates two facts:

- **Decision trace:** 5A binds the requirement or inherits an already accepted authority boundary.
- **Delivery trace:** the implementation/evidence is present in 5A, deferred to its dependency-ordered issue, satisfied by Increment 4, or explicitly outside Increment 5 activation.

A requirement bound by 5A is not reported as an implemented retriever, tool, hydration path or qualification run.

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
| 5A / #250 | 23 | Contract, schemas, frozen plan, authority/non-effect decisions and traceability |
| 5B / #251 | 2 | Four typed retriever implementations |
| 5C / #252 | 7 | Six bounded named read-only tools |
| 5D / #253 | 35 | Authoritative hydration, freshness, reconciliation and degradation |
| 5E / #254 | 42 | Actual-service qualification, security, purge, recovery and decision evidence |
| Increment 4 / #144 | 4 | Already accepted authority/projection foundations |
| Outside Increment 5 activation | 1 | Production activation remains unauthorised |

The counts total 114 and the groups are disjoint.

## Delivered in 5A

`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DEVAL-072`, `DOPS-001`, `DOPS-002`, `DOPS-037`, `DOPS-070`, `DOPS-076`, `GRAG-051`, `GRAG-052`, `GRAG-053`, `GRAG-058`, `GRPROD-002`, `GRPROD-003`, `GRPROD-004`, `GRPROD-013`, `GRPROD-014`, `GRPROD-015`, `GRPROD-020`, `GRPROD-023`, `GRPROD-032`.

These rows are verified only by the 5A contract/profile/traceability tests and reviewed documents.

## Sensitive evidence remains deferred

The map intentionally leaves the following in 5E rather than claiming that a contract file is operational evidence:

- `DEVAL-073` — explicit completed-run decision;
- `DOPS-064` — owner escalation runbook evidence;
- `DOPS-072` — tested rollback evidence; and
- `DOPS-074` — rights, terms, pricing, access and credential-change review evidence.

Similarly, real-request governance, latency/capacity evidence, rights-limited provider evaluation, failed-run retention, purge/recovery and actual-service qualification remain in 5E.

## Decision state

There is no runtime “pending approval,” authenticated-comment, main-admission or post-merge materialisation state.

The reviewed merge is source governance. On `main`, every non-inherited row is `BOUND_BY_5A`; inherited rows remain `INHERITED_ACCEPTED_AUTHORITY`. The contract itself still authorises no production effect.

## Verification invariants

Tests reject:

- missing or duplicate requirement IDs;
- overlapping or incomplete delivery groups;
- changed delivery counts;
- a 5A row pointing at a later implementation;
- a deferred row without its exact issue;
- production activation appearing inside Increment 5; and
- reintroduction of runtime GitHub approval/admission targets.
