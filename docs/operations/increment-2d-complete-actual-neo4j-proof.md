# Increment 2D complete actual-Neo4j fixture proof

**Role:** Implementation and operations record
**Status:** Draft review-unit evidence — no activation authority
**Owner:** Product owner
**Implementation issue:** #158
**Parent epic:** #142
**Authorised base:** `main@41e8bcdc1664514932c0994d58512faa4fe7658c`
**Canonical language:** English

## Purpose and exact boundary

Increment 2D proves the complete deterministic Increment 2 fixture path against authenticated Neo4j Community while keeping every durable decision in SQLite and governed-object authority:

```text
synthetic Source Revisions
→ governed objects and ordered authority events
→ governed DEVELOPMENT_OF admission
→ complete structural/relation/full-text/vector generation
→ exact validation and SQLite-owned ACTIVE promotion
→ bounded exact/full-text/vector/graph retrieval
→ deterministic fusion and dependency-aware deduplication
→ governed bilingual passage hydration
→ immutable Retrieval Context v2
→ authenticated SQLite-authoritative development Candidate admission
```

The public `Increment2CompleteProofController` owns no database, Neo4j driver, object store, relation authority, projection authority, Retrieval Context authority or Candidate authority. It composes two typed capabilities supplied by the application boundary: one preparation operation and one Candidate-authority opener. The controller verifies the prepared generation, contiguous checkpoint and admitted relation identity, then calls the retained public retrieval and Candidate facades.

SQLite ledger records, immutable relation and Candidate decisions, governed objects and retained Retrieval Contexts remain authoritative. Neo4j nodes, relationships, index rows, paths, ranks and similarity scores remain disposable derivative context.

## Candidate authority and minimum handoff

Checked SQLite schema version `9` adds immutable development Candidate, Candidate Version and Candidate Admission Decision records. Admission requires the exact retained `COMPLETE` Retrieval Context v2 and the exact repository-owned `integrated_fixture_v2` Candidate manifest.

The manifest binds:

- Signal, Lead, current and prior Hypothesis Version identities;
- current and prior Source Revision identities;
- the canonical process and admitted governed relation key;
- the prior Candidate Version and Retrieval Context contract;
- development route and proposed-hypothesis trust scope;
- coverage basis and an explicitly unverified hypothesis summary;
- geography, category and qualitative urgency;
- likely substantive new information and reader-utility basis;
- sorted known uncertainties and bounded evidence objectives; and
- coverage, triage, retrieval and admission policy versions.

A Candidate does not assert that the hypothesis is true. The fixture hypothesis remains `PROPOSED`; admission records a bounded development handoff supported by exact evidence and current authority.

## Authentication, replay and collision semantics

The public request exposes only typed proposal and Retrieval Context identities, the expected context digest and an idempotency key. It exposes no SQL, Neo4j driver, Cypher, label, predicate, generation, index, result limit or policy object.

The public controller passes one typed authentication proof through complete-generation preparation, retrieval, Candidate admission, replay and restart reads. Authentication and authorisation occur before context lookup. The command grant is bound to the exact proposal and expected aggregate version. The Candidate store rechecks authentication, current projection authority, deterministic branch evidence, governed hydration, current rights/lifecycle state and current admitted relation state inside the single SQLite writer transaction.

Exact replay creates no duplicate event, Candidate, Candidate Version or decision. A new authorised proposal over an equivalent recovered context creates a new immutable `DEDUPLICATED` decision pointing to the existing Candidate and Candidate Version. Semantic collision is resolved by relational authority; graph ranking cannot allocate identity.

Candidate authority events use `authority.candidate` and are excluded from the complete projection source watermark. Candidate admission therefore cannot make its own source context stale.

## Complete actual-service proof

The permanent authenticated Neo4j workflow requires exactly these Increment 2D cases without skip, failure or error:

1. complete initial generation, all four retrieval branches, deterministic fusion, governed bilingual hydration, Candidate admission, exact replay and process restart;
2. replacement-generation rebuild and promotion from retained authority only, followed by deterministic Candidate deduplication;
3. relation revocation changing a later context without rewriting the earlier Candidate, Candidate Version, decision or Retrieval Context;
4. governed object revocation, deletion and tombstone causing derivative purge and preventing qualification or resurrection;
5. full-text-index loss causing explicit unavailability and zero Candidate authority;
6. vector-index loss causing explicit unavailability and zero Candidate authority;
7. admitted-relation projection loss causing explicit contract incompleteness and zero Candidate authority;
8. an unresolved required gap blocking complete retrieval and Candidate reuse; and
9. a retained dead letter blocking complete retrieval and Candidate reuse.

The nominal proof additionally retains one authorised `SAME_EVENT_AS` distractor proposal, requires it to remain absent from admitted assertions and requires zero projected `SAME_EVENT_AS` relationships. The workflow also retains and rechecks all earlier B2/B3/C1, complete 2B and retrieval 2C actual-service cases. A fake, disabled, no-op, graph-free, exact-only or missing-index configuration cannot satisfy the JUnit identity set.

## Relation revocation and immutable history

Revoking the admitted `DEVELOPMENT_OF` relation does not mutate or delete the Candidate, its first Candidate Version, the original Candidate Admission Decision or the original Retrieval Context. It does block replay as a new admission input because current relation authority no longer permits it.

A replacement complete generation rebuilt from retained authority omits the revoked relation. A later retrieval is explicitly non-complete; it does not become a false `no prior match`. Earlier history remains readable through the separately authorised Candidate decision surface. That read requires `authority.candidate.read` and carries `authority.candidate` security provenance; it does not reuse the admission scope or the broader integrated domain.

## Governed deletion, purge and tombstone non-resurrection

Revocation, deletion request and tombstone are distinct retained governed-object states. After the prior English fixture passage is tombstoned:

- the original Candidate decision remains immutable and readable;
- the old Retrieval Context cannot authorise a later Candidate decision;
- delivery removes the passage derivative from the active generation;
- a replacement-generation rebuild does not recreate that passage derivative;
- complete validation fails because the required active-document set is no longer satisfiable; and
- no graph or index rebuild can reconstruct prohibited governed bytes.

Neo4j is never used to restore SQLite, object admissions, rights, lifecycle state, Retrieval Contexts or Candidate authority.

## Gap, dead-letter, generation and restart boundaries

Complete proof requires one SQLite-selected ACTIVE generation at the current non-projection/non-Candidate source watermark, a matching complete validation, zero open required gaps and zero dead letters. Wrong generation, stale checkpoint, missing contract, unresolved gap or dead letter fails closed before Candidate authority is created.

Process restart reopens schema version 9 and structurally revalidates canonical and normalized Candidate, Candidate Version and decision rows plus their retained Retrieval Context, projection, relation, access-decision, command payload and authority-event links. It independently derives first-admission versus later-deduplication order and requires Candidate creation, first-version and first-decision chronology to agree. Restart performs no history rewrite. Every decision is also rebound to the exact proposal command, inline payload and ledger event under `authority.candidate`; trigger-restored, re-digested outcome, chronology, payload or normalized-linkage tampering fails reopen.

## Operator verification

The permanent service gate is repository-owned. It supplies disposable credentials, creates a non-bootstrap projector identity, starts Neo4j Community through the checked workflow and runs:

```text
newsroom/tests/test_increment_2d_neo4j_service.py
```

The service-required environment is fixed by the workflow:

```text
NEWSROOM_NEO4J_INCREMENT_2D_SERVICE_REQUIRED=1
NEWSROOM_NEO4J_COMPLETE_SERVICE_REQUIRED=1
NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED=1
NEWSROOM_NEO4J_SERVICE_REQUIRED=1
```

The evidence step requires the exact nine test identities listed above and rejects any skip, failure or error. The signed SDLC service lane uses the same dedicated environment. The no-service deterministic core permits only those exact tests to skip and requires zero other skips.

## Rollback

Before schema version 9 opens, rollback is a normal source revert. After schema version 9 has opened a database, do not delete migration rows, rewrite immutable Candidate records or attempt an ad hoc down-migration.

Use one of these reviewed paths:

1. restore a verified pre-v9 SQLite and governed-object backup; or
2. apply a reviewed forward fix that preserves immutable event and decision history.

Neo4j can be wiped and rebuilt from SQLite and governed objects. It must never be treated as the rollback source of truth. A tombstoned object remains prohibited after every rebuild.

## Fixed exclusions and stop boundary

This unit performs no live-source execution, Graphiti, external model or embedding call, production protected-content vector generation, generalized retrieval, full triage, scheduler, shadow, canary, activation, spending, publication or public effect.

Issue #158 remains open until this review unit is merged with exact-head CI, authenticated actual-Neo4j and signed SDLC evidence plus zero unresolved P1/P2 findings and review threads. Parent #142 remains open until #158 closes and the final Increment 2 completion record is added. **Do not start Increment 3 issue #143 before parent #142 is closed as completed on the resulting `main` head.**
