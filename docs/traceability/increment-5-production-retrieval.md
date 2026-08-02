# Increment 5 production retrieval traceability

- **Status:** Exact 5A decision and delivery map
- **Machine source:** `newsroom/increment5/traceability.py`
- **Verification:** `newsroom/tests/test_increment5a_traceability.py`
- **Contract:** `newsroom/increment5/data/increment5a_retrieval_contract_v1.json`
- **Rows:** 114 unique accepted requirements

## Meaning

The map separates two facts:

- **Decision trace:** 5A binds the requirement or inherits an already accepted authority boundary.
- **Delivery trace:** implementation/evidence is present in 5A, deferred to its dependency-ordered issue, satisfied by a prior increment, or explicitly outside Increment 5 activation.

A requirement bound by 5A is not reported as an implemented retriever, tool, hydration path, production-readiness gate, Operational Profile or qualification run.

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
| 5A / #250 | 14 | Contract, reviewed-bound profile schemas, frozen plan, authority/non-effect decisions and traceability |
| 5B / #251 | 2 | Four typed retriever implementations |
| 5C / #252 | 6 | Six bounded named read-only tools |
| 5D / #253 | 29 | Authoritative hydration, freshness, reconciliation and degradation |
| 5E / #254 | 55 | Production-readiness validation, Operational Profiles/objectives, actual-service qualification, security, purge, recovery and decision evidence |
| Increment 3 / #143 | 1 | Accepted discovery-lineage actual-Neo4j foundation |
| Increment 4 / #144 | 6 | Accepted graph authority/projection foundations |
| Outside Increment 5 activation | 1 | Production activation remains unauthorised |

The counts total 114 and the groups are disjoint.

## Delivered in 5A

`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DEVAL-072`, `DOPS-070`, `DOPS-076`, `GRAG-051`, `GRAG-052`, `GRAG-053`, `GRAG-058`, `GRPROD-002`, `GRPROD-023`, `GRPROD-032`.

These rows are verified only by the 5A contract/profile/plan/traceability tests and reviewed documents.

## Exact prior delivery

`GRAG-042` is attributed to final Increment 3E, not Increment 4. Its exact anchor is the accepted `3E-07-ACTUAL-NEO4J-EVIDENCE/GRAG-042-GRAG-045` trace at `main@d03441ef2fa26b5dc83f65d1797abf2b381d8f1a`, delivery issue #143.

Increment 4 delivery contains:

- `GRAG-030` — distinct source-observation, validity, recording, proposal, admission and invalidation times;
- `GRPROD-003` — repository-owned ontology, mapping, controller, operations and tests;
- `GRPROD-005` — the shared canonical identity, trust, time and ordered-event contract;
- `GRPROD-013` — engine-neutral canonical semantics independent of Neo4j internal and Graphiti-private identity;
- `GRPROD-014` — the versioned repository ontology/mapping/controller/actual-service workflow definition; and
- `GRPROD-020` — the first ontology/mapping/graph-boundary/health/integration proof beside relational authority.

Those six rows point to exact entries in `newsroom/increment4/traceability.py` at accepted `main@c9e31879421083e82e2538d57087d04e9b454d34`, delivery issue #144.

Prior rows retain their actual increment, issue, main boundary, file and existing traceability key. Tests open the referenced repository file and prove every anchor fragment exists; a syntactically plausible but nonexistent `#REQUIREMENT-ID` target cannot pass.

## Production and operational evidence remains deferred

The map does not treat non-production profile schemas as a production build or readiness gate:

- `GRPROD-004` — a production profile must reject fake, no-op, disabled or omitted GraphRAG; and
- `GRPROD-015` — missing or incompatible mandatory graph configuration must fail production build or readiness validation.

Both remain in 5E/#254, where the production-target configuration and exact readiness checks are implemented and qualified.

The map also leaves operational evidence in 5E rather than treating partial historical time fields or global retrieval limits as complete operational delivery:

- `DOPS-001` — exact owner-approved Operational Profile for each executable scope;
- `DOPS-002` — scope-specific timing, freshness, retry, capacity and alert objectives;
- `DOPS-007` — explicit separation of source, planned, wall-clock, monotonic and authoritative record times;
- `DOPS-030`–`DOPS-034` — retry classification, bounded backoff, health-clock and circuit controls;
- `DOPS-037` — explicit bounded role-aware contingency activation and deactivation;
- `DOPS-040` — queue retention or explicit closure under capacity/dependency failure;
- `DOPS-060` — version-attributed metrics, logs, alerts and incidents;
- `DOPS-064` — owner escalation and versioned runbook evidence;
- `DOPS-072` — tested rollback evidence;
- `DOPS-074` — rights, terms, pricing, access and credential-change review evidence; and
- `DOPS-075` — complete Operational Admission evidence.

Prior increments distinguish several source, observation, validity and record timestamps, but no accepted trace proves the complete five-domain `DOPS-007` contract. It is therefore `BOUND_BY_5A`, `DEFERRED_TO_5E`, issue #254, rather than falsely reported as prior delivery.

`DEVAL-073` also remains in 5E because only a completed Run can retain its owner decision or explicit unresolved status. Real-request governance, latency/capacity evidence, rights-limited provider evaluation, failed-run retention, purge/recovery and actual-service qualification remain in 5E.

## Requirement-specific anchors

Every row has an explicit semantic anchor. The machine map rejects omitted or overlapping anchors and has no prefix-derived default. Examples include:

- `GRAG-042` → final Increment 3E actual-Neo4j evidence;
- `GRAG-054` → the machine plan’s three mandatory GraphRAG query families;
- `GRAG-056` → the machine plan’s zero-tolerance temporal and rebuild gates;
- `GRPROD-003` / `GRPROD-013` / `GRPROD-014` / `GRPROD-020` → exact accepted Increment 4 implementation and test evidence;
- `DEVAL-003` → contract non-effects;
- `DEVAL-051` → the exact threshold-freeze field;
- `DEVAL-064` → the rights matrix;
- `DEVAL-072` → the Evaluation Plan’s public-artifact-safety section;
- `DEVAL-073` → the completed-Run decision-output section;
- `GRPROD-004` → explicit deferred production-profile enforcement;
- `GRPROD-015` → explicit deferred production build/readiness validation;
- `DOPS-001` / `DOPS-002` → explicit deferred #254 profile/objective anchors;
- `DOPS-007` → explicit deferred complete five-domain time separation;
- `DOPS-037` → explicit deferred contingency controls; and
- `DOPS-060` → explicit deferred version-attributed observability evidence.

This prevents a syntactically valid pointer from claiming evidence that the referenced object does not contain.

## Decision state

There is no runtime “pending approval,” authenticated-comment, main-admission or post-merge materialisation state.

The reviewed merge is source governance. On `main`, every non-inherited row is `BOUND_BY_5A`; inherited rows remain `INHERITED_ACCEPTED_AUTHORITY`. The contract itself still authorises no production effect.

## Verification invariants

Tests reject:

- missing or duplicate requirement IDs;
- overlapping or incomplete delivery groups;
- missing, competing or generic requirement anchors;
- a prior anchor whose referenced traceability fragment does not exist;
- a prior row assigned to the wrong increment or issue;
- changed delivery counts;
- a 5A row pointing at later implementation evidence;
- a prior implementation being falsely credited to 5A;
- a partial prior time model being reported as complete `DOPS-007` delivery;
- a production profile/readiness requirement claimed before its production gate;
- an Operational Profile, retry, contingency, queue or observability requirement claimed before its operational issue;
- a deferred row without its exact issue;
- production activation appearing inside Increment 5; and
- reintroduction of runtime GitHub approval/admission targets.
