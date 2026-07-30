# Increment 4C substantive review — general relation authority

**Issue:** #227
**Parent:** #144
**Authorised base:** `main@76ee0abea6010d943a6f3ec6198109e64ae2929f`
**Review status:** current-tree substantive review; exact remote-head qualification still required

## Review question

Does Increment 4C create a production-shaped, append-only, rights-safe general editorial-relation authority without allowing extractor confidence, arbitrary predicates, unresolved identity, source text, graph paths or Graphiti private state to admit a relation automatically?

## Review conclusion

At the current reviewed tree, the implementation meets the 4C authority boundary:

- The nine-predicate registry is closed, versioned and seeded by checked schema v15.
- Proposals retain exact typed endpoints, producer, temporal scope, evidence and identity dependencies.
- Proposal confidence remains metadata and never grants admission.
- Accept, reject, hold and unresolved remain explicit proposal decisions.
- Assertions exist only after an explicit authenticated `ACCEPT` decision.
- Invalidation, revocation and supersession are append-only and preserve predecessors.
- Material unresolved entity identity blocks admission; later resolution allows a later decision without rewriting the earlier hold.
- Proposal, admitted and projection surfaces use distinct authorization scopes.
- Current rights are recursively revalidated through endpoints, Extraction Run evidence and entity dependencies.
- Current assertion heads are rebuildable from immutable decisions/events without rerunning extraction.
- No arbitrary predicate, SQL, Cypher, graph credential, Graphiti workspace, model provider or publication path enters the public facade.

The review found no P1 issue. Sixteen P2 findings identified during implementation were corrected and covered by focused tests. This document is not final merge evidence: the exact clean source must still receive all permanent workflows and a current-head review audit.

## Corrected findings

### P2-01 — editorial decoders collided with inherited extraction/entity decoder names

The first store mixin used generic helper names such as `_proposal_from_row`. Python method resolution could therefore replace Increment 4A extraction decoders when the combined 4C store opened.

**Correction:** every 4C decoder, head lookup and current-use helper has an `editorial_`-specific name. Opening the complete extraction/entity/relation authority now preserves predecessor startup validation.

### P2-02 — retained extraction evidence ordinal used a different indexing convention

Increment 4A persists evidence ordinals as one-based values, while in-memory tuples are zero-based. Direct tuple indexing could bind the wrong range or fail valid evidence.

**Correction:** 4C converts the retained ordinal explicitly and verifies Proposal Envelope, Run, Output, Passage, byte range and digest before commit.

### P2-03 — decision policy was initially an arbitrary token

A syntactically valid changed decision-policy version could have been represented even though the predicate registry and schema seed require one exact admission policy.

**Correction:** `EditorialRelationDecisionRequest` requires `editorial-relation-admission-policy-v1`; the migration, registry, golden command vector, tests and startup integrity use the same constant. Wrong policy fails construction and trigger-bypassed mutation fails reopen.

### P2-04 — Event Hypothesis endpoints initially accepted an arbitrary UUID

A typed UUID alone does not prove workflow authority and could turn an invented hypothesis into relation provenance.

**Correction:** proposal persistence resolves the exact retained Event Hypothesis Version and current workflow state. Unretained endpoint identities fail closed.

### P2-05 — lower-layer rights and stale errors leaked through the relation API

Entity and extraction exceptions escaped directly, weakening the typed relation boundary and making caller behavior depend on internal implementation layers.

**Correction:** current endpoint/evidence checks normalize rights, stale-decision and state failures into the corresponding editorial-relation error types.

### P2-06 — identical concurrent commands could lose exact replay semantics

Two authorized callers could race before either persisted. Without in-transaction idempotency lookup, the second identical decision might appear stale instead of replaying the first result.

**Correction:** proposal and decision commits check and retain idempotency inside the serialized transaction. Identical concurrency returns one durable row plus exact replay; incompatible concurrency fails closed without partial state.

### P2-07 — current projection rebuild could become a silent repair or resurrection path

A generic upsert could overwrite divergent state, insert some assertions before a later rights failure or recreate prohibited material.

**Correction:** the operator-only rebuild derives the complete expected projection, rejects divergence, validates every current assertion before the first insert and writes missing heads atomically. It emits no authority events and cannot rerun extraction.

### P2-08 — relation assertions used as endpoints required recursive rights and cycle checks

A relation-on-relation endpoint could bypass source rights by validating only its immediate assertion row, or create a recursive assertion graph.

**Correction:** current-use and rebuild recursively validate assertion endpoints back to exact admitted evidence and reject cycles. Focused rebuild evidence covers nested assertions.

### P2-09 — an early hold needed an explicit later-resolution admission path

Blocking premature admission was insufficient unless the authority also proved that a retained hold can advance after identity becomes accepted without rewriting history.

**Correction:** the fixture records a material unresolved dependency, rejects premature accept, commits `HOLD` as decision version 1, accepts the exact entity-resolution proposal and commits `ACCEPT` as version 2. Both decisions remain immutable.

### P2-10 — stale or cross-paired Entity Versions needed a relation-layer failure

A caller could pair a current Entity ID with another entity’s version. Lower layers identified the mismatch, but 4C needed a stable public contract.

**Correction:** endpoint validation requires the exact current entity/version pair and raises `EditorialRelationStaleDecision` before proposal persistence.

### P2-11 — safe representations could expose retained source expression

Statements and evidence text in ordinary dataclass representations could leak source expression through logs or assertion output.

**Correction:** sensitive statement/expression fields are excluded from safe representations while canonical persistence and intentional scoped reads remain unchanged.

### P2-12 — lifecycle state could diverge from projection-event coverage

An assertion head could be changed independently of the latest immutable event if database triggers were bypassed.

**Correction:** startup rederives proposal, decision and assertion heads and requires exact UPSERT/REMOVE coverage for every current lifecycle. Divergent heads or missing events fail reopen.

### P2-13 — evidence and dependency child deletion needed direct tamper proof

Immutable parent rows alone did not demonstrate that deleting exact evidence or entity-resolution dependency children would be detected.

**Correction:** raw-SQL tests bypass individual delete guards and prove checked reopen rejects missing extraction evidence and missing dependency lineage.

### P2-14 — permanent focused workflows did not automatically exercise 4C

Repository CI would see the tests, but Authority A2a, Authority A2b and Projection B1 use filename-selected inventories.

**Correction:** dedicated bridge files prove command/event envelopes, rights revalidation and admitted-only projection behavior under the existing permanent globs.

### P2-15 — traceability could omit non-authority, collision and retrieval deferrals

A narrow relation-only matrix could claim the direct assertion requirements while omitting Retrieval Context non-authority, equivalent admission collision control and the fact that hybrid retrieval remains deferred.

**Correction:** the exact matrix includes `DREC-042`, `DREC-054` and `GRAG-031`, binds each to an implementation/test or explicit deferral, rejects unknown requirement IDs and verifies every referenced symbol and test path.

### P2-16 — public traceability names were routed through the wrong lazy module

The package’s first lazy-name set accidentally included traceability exports, so a public traceability import would query `editorial_models` before reaching `editorial_traceability`.

**Correction:** traceability names are routed only through the dedicated module, included in `__all__`, and covered by import, symbol, requirement-ID, ADR, operations and review tests.

## Authority and runtime boundary review

The reviewed implementation exposes no callable surface for:

```text
Graphiti or a model-provider SDK
network access, live source credentials or schedules
runtime predicate extension
arbitrary SQL or Cypher
Neo4j or graph write credentials
caller-selected relationship labels or graph-internal IDs
Candidate or Evidence Intake writes
publication, spending, shadow, canary or production activation
legacy mutable link/event/cluster dual writes
```

The predicate registry is repository-owned and closed. An extractor may submit a typed proposal only. It cannot call `decide`, allocate an admitted assertion or write a governed projection directly.

## Current local evidence

```text
Increment 4C contract/migration/proposal/authority/lifecycle/rights/
security/integrity/rebuild/traceability tests:                            58 passed
Increment 2 governed-relation regression:                                46 passed
Increment 4A extraction contract/output/migration and 4B migration:      32 passed
Permanent A2a/A2b/Projection B1 relation bridges:                         3 passed
Combined focused qualification:                                         139 passed
Focused required skips:                                                   0
Focused failures/errors:                                                  0
ResourceWarning policy:                                                   fatal
Compile and diff checks:                                                  pass
Fresh schema v15 and checked v14-to-v15 migration:                       pass
Hold then later resolution/admission history:                            pass
Wrong registry, predicate contract and decision policy:                  pass
Stale entity-version admission guard:                                    pass
Rights revocation, tombstone and source-version blocking:                pass
Invalidation, revocation and supersession history:                       pass
Projection events and rights-safe atomic rebuild:                        pass
Concurrent exact replay and incompatible decision conflict:              pass
Raw-SQL tamper and checked reopen:                                        pass
```

The directly executed combined command reported `139 passed` with no skip, failure or error. Permanent full-repository and authenticated-service evidence must come from the exact clean PR head.

## Review disposition

```text
P1 findings:             0
P2 findings corrected:  16
Unresolved local P1/P2:  0 on the current reviewed tree
Review threads:          pending current remote-head audit
Exact-head workflows:    pending final clean publication
```

Before PR #239 may merge, this same clean source tree must be durably present on the PR branch, all permanent workflows must pass on that exact head, the signed SDLC decision must be `PASS`, and current-head review must retain zero actionable comments, submitted review blockers and unresolved threads.

Issue #228 remains blocked. Completion of relation authority does not authorise real Graphiti/model execution, the disposable proposal workspace, actual-Neo4j bilingual entity/relation proof, publication or production effects.
