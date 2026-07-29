# Increment 3E substantive review

**Issue:** #209
**Parent:** #143
**Authorised base:** `main@65ba31c403c84b9fbe82243912fd57612c097735`
**Reviewed local product commit:** `191bda19759cccb015c2cf3304d50b295127c18d`
**Reviewed local product tree:** `d2a96f1672d3479cf6751c5b303114aea267ecbc`
**Status:** current-tree review checkpoint; remote exact-head qualification pending

## Review method

The review traced the fixture-only path from retained Source, Check and Discovery authority through the fixed `graph.discovery_lineage` ontology and mapping, ordered delivery, checkpoint/gap/dead-letter authority, replacement-generation rebuild, server-computed reconciliation, ACTIVE-generation selection, bounded reads and dimension-specific health. It also inspected startup/replay behavior, rights-removal eligibility, graph loss/tamper, actual-service routing and every explicit exclusion.

The review treated SQLite ledger records, immutable decisions and governed lifecycle IDs as authoritative. Neo4j was reviewed only as a disposable projection. No graph result, health state or empty read was accepted as source, editorial, Candidate, evidence or publication authority.

Machine evidence on the current local tree before this review record:

```text
Focused Increment 3E / SDLC tests:        111 passed
Complete repository topology:           1,527 passed
Intentional service-only skips:             34
Failures/errors:                             0
Clustering regression:                    pass
Python compilation:                       pass
Whitespace validation:                   pass
```

The complete topology was executed as twelve deterministic file shards because the restored local environment exceeded the single-command wall-clock limit. Every repository test file executed exactly once; the separately isolated 75-case news-pool database suite also passed.

## Corrected findings

### P2-01 — new explicit discovery relations could break the retained B2 vocabulary freeze

The first structural kernel added valid allow-listed discovery relations while a retained B2 test froze the previous global relation enum. That made explicit, governed relation growth appear equivalent to introducing a generic predicate.

**Correction:** the retained contract now freezes the complete explicit relation vocabulary and continues to reject generic relations such as `RELATED_TO`. Legacy ontology and mapping digests remain unchanged.

### P2-02 — health imports could form a Source/Check/Projection package cycle

Early health imports reached Check types through package initialisers, allowing partial module initialisation during authority tests.

**Correction:** health contracts import stable lifecycle identities from the Source type boundary, defer Check enum imports until validation, and avoid package-initialiser cycles. Full import-order and repository collection now pass.

### P2-03 — ACTIVE lineage reads could trust retained validation without current graph reconciliation

A generation could have valid retained validation while its disposable graph was subsequently deleted or tampered.

**Correction:** every ACTIVE lineage read and projection-health assessment performs server-computed reconciliation against the current graph before serving. Graph loss, relation mutation, endpoint mutation and count mismatch fail closed.

### P2-04 — Increment 3E actual-service cases were not durably bound to the permanent service topology

The initial actual-Neo4j cases lived on a separate test path that the accepted B3 service topology did not prove exactly.

**Correction:** the two 3E cases are retained within `test_projection_b3_neo4j_service`, included in the signed service-test inventory and classified as intentional core skips only when the authenticated service is absent.

### P2-05 — a `HEALTHY` result could lack positive typed evidence

A boolean combination could previously produce healthy state without an inspectable retained authority reference.

**Correction:** every healthy assessment requires bounded, canonical evidence. Source health requires the exact current Source Definition Version and, when present, the exact latest Check Outcome. Projection health requires both exact status and validation evidence.

### P2-06 — absent governed subjects could leak an internal persistence error

A missing or retired source identity could expose an `AuthorityPersistenceError` through a public lineage or health read.

**Correction:** bounded public reads translate ineligible authority into stable `DiscoveryLineageReadError` or `DiscoveryHealthReadError` responses before graph serving.

### P2-07 — accepted observation models lacked direct 3E transition-projection proof

Increment 3C proved each observation model, but the first 3E evidence did not directly demonstrate that every model's meaningful transition uses the fixed structural mapping.

**Correction:** a dedicated fixture proof covers all six accepted models and the `REVISED`, `FIRST_OBSERVED`, `AMBIGUOUS_ABSENCE`, `ACTIVATED`, `ESCALATED` and `AGENDA_CREATED` transitions. Each projects one governed transition node with exact Item and Check Outcome relations.

### P2-08 — a coverage path could self-declare substitute authority

The pure health contract accepted `qualifies_as_substitute=True` without requiring the retained operational-resilience and explicit-contingency classification used by the authority facade.

**Correction:** substitute coverage now requires `OPERATIONAL_RESILIENCE` responsibility plus `EXPLICIT_CONTINGENCY`, and coverage evidence must be sorted and unique. Comparator count still cannot repair an unavailable sole Anchor.

### P2-09 — the permanent Neo4j workflow proved only a subset of B3 cases

The workflow accepted at least six B3 cases and named only three, so a missing 3E proof could evade the permanent gate while total test count remained high enough.

**Correction:** the workflow requires exactly eight B3 actual-service cases and names every one, including both 3E cases. Skips, failures, errors, duplicates and omissions fail the job.

### P2-10 — actual-service graph-loss proof attempted to rewrite ACTIVE history

The first authenticated graph-loss proof replayed a destructive rebuild command after the generation had already been promoted. The projection authority correctly rejected that operation because an `ACTIVE` generation is immutable projection history.

**Correction:** exact rebuild replay remains available only while a generation is `BUILDING`. Once promoted, graph loss is recovered by creating, rebuilding, reconciling and atomically promoting a replacement generation while retiring the prior ACTIVE generation. A direct unit regression and the authenticated Neo4j case now prove that boundary.

## Authority and resilience review

- Structural mappings are fixed, versioned and allow-listed; no arbitrary Cypher, labels, relation types or properties are accepted.
- Governed lifecycle IDs are graph keys. Titles, locators, digests and mutable status do not become identity.
- Required unsupported or out-of-order events create retained gaps/dead letters and block contiguous qualification.
- Exact replay is idempotent while a generation remains BUILDING. Graph loss after activation is recovered through a replacement generation without mutating the prior ACTIVE history.
- Replacement generations rebuild from retained SQLite authority, reconcile against actual graph state and replace the prior ACTIVE generation through authority.
- Retired or rejected source authority becomes projection-ineligible; serving fails closed and replacement rebuild does not resurrect covered lineage.
- Last complete observation, last successful observation and last source change remain distinct.
- Transport, parser, Check, freshness, semantic, projection and coverage states remain independently attributable.

## Boundary review

The current implementation has no callable or import surface for:

```text
named live source access
source credential or schedule
external network or browser collection
model, Graphiti, embedding or search execution
Triage Work Item or Retrieval Context
Event Hypothesis, Candidate or Evidence Handoff
editorial materiality or rejection authority
publication, spending, production activation or public effect
legacy link/event/cluster authority import
arbitrary Cypher, driver or mutation access
```

## Review disposition

```text
P1 findings:             0
P2 findings corrected:  10
Unresolved P1/P2:        0 on the reviewed local product tree
```

This is not merge evidence. Before PR #222 may merge, this exact clean tree must be durably present on the PR branch, the permanent workflow correction must be published through an authorised GitHub write path, a normal exact-head qualification commit must pass all six permanent workflows, every mandatory 3E actual-service case must execute without skip/failure/error, and the PR must have zero actionable comments, submitted-review blockers or unresolved review threads.
