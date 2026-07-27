# Increment 3A substantive review

**Date:** 2026-07-27
**Implementation issue:** #205
**Parent:** #143
**Programme:** #141
**Authorised base:** `main@eb900c8b16e42506fdf0ff7c12de62773d0dad42`
**Review unit:** Increment 3A — Source registry and immutable source contracts
**Runtime authority:** Fixture and approved replay only

## Review conclusion

The Increment 3A implementation now provides a production-shaped, repository-native source registry while preserving SQLite and governed records as authority. It creates no live-source, transport, parser, Check, Signal, Lead, projection, model, search, publication or production authority.

Current substantive-review disposition:

- P1 findings: **0**;
- P2 findings found and corrected: **13**;
- unresolved P1/P2 findings: **0**;
- focused retained/new tests: **78 passed**;
- focused failures, errors and skips: **0**;
- timed authenticated service tests: **32 passed**;
- timed authenticated service failures, errors and skips: **0**;
- temporary materialisation, review or timing transport retained in the PR: **0 files**.

This document is the owner-authored final-evidence trigger. The exact reviewed head and final workflow run identities are recorded in PR #210 after the required workflows complete for this commit.

## Reviewed surface

The review covered:

- typed source and lineage identities;
- Source Definition and immutable Source Definition Version contracts;
- source roles, portfolio functions, coverage mappings, dependencies and explicit gaps;
- rights, adapter, extraction-scope, observation-model, baseline, item-identity, revision and canonicalisation policy references;
- stable Source Item identity and explicit locator continuity;
- Source Revision, Discovery Representation and Discovery Occurrence separation;
- authenticated command definitions and exact payload schemas;
- redacted metadata and sensitive-detail read boundaries;
- checked SQLite migration version 10;
- private transaction, replay, collision and exact-head logic;
- canonical-byte and normalized-column startup validation;
- migration compatibility with retained Increment 2 authority;
- traceability, operations, rollback, exclusions and deferred work; and
- import/runtime guards excluding legacy source identity and live execution paths.

## Corrected findings

### P2-01 — Retained migration tests assumed schema version 9 was still current

Increment 3A correctly advances the shared authority schema to version 10. Historical Increment 2 tests were updated to retain and verify the version-9 Candidate migration identity while accepting version 10 as the current complete schema. No historical migration record or checksum was weakened.

### P2-02 — Source command boundaries converted typed UUIDs to strings before constructing `AggregateId`

All seven source command paths now preserve the typed UUID value when constructing authority aggregate identities. The prior conversion caused every new source write path to fail before persistence.

### P2-03 — Startup integrity did not rebind every normalized parent-table column to canonical bytes

Source Item, locator-continuity decision, Source Revision, Discovery Representation and Discovery Occurrence reopen paths now compare each normalized SQL column against the value reconstructed from retained canonical bytes.

### P2-04 — Startup integrity did not fully rebind normalized child tables

Explicit gaps, coverage mappings and dependency rows now validate both canonical child blobs and each normalized column, including geography, language, limitation and upstream-source fields.

### P2-05 — Source Item equality included policy metadata and uncertainty wording

Stable Source Item equality now uses only the source-scoped identity basis. Identity-policy versions and uncertainty notes remain retained provenance but cannot create a second logical item merely because code or wording changed.

### P2-06 — Source Revision equality included revision-policy and canonicalizer versions

Revision equality now represents source state only: an approved source-native revision token and/or permitted source-state digest. Parser, policy and canonicalizer changes remain Representation provenance and cannot fabricate publisher history.

### P2-07 — Global semantic uniqueness blocked explicit configuration reversion

A later Source Definition Version may explicitly return to earlier semantics as a new immutable version, preserving all intervening history. A semantic no-op against the current exact head remains rejected.

### P2-08 — Mixed Anchor and Comparator semantics were over-restricted

A Source Definition Version may carry both Anchor and Comparator portfolio functions. However, an Active coverage mapping cannot use the `COMPARATOR` contribution and a Comparator-only source cannot claim an Active path.

### P2-09 — Source-time values accepted noncanonical or arbitrary text

Date-only values must be canonical ISO dates. Exact and approximate values must be canonical UTC timestamps. Unknown and conflicting states remain explicitly typed. Invalid authority timestamp exceptions are converted to the source-contract error boundary.

### P2-10 — Source Item and Source Revision detail reads used the metadata scope

Full item and revision records may contain source-native identifiers, tokens or sensitive provenance. They now require `authority.sources.read_sensitive`; ordinary metadata readers receive only the redacted Source Definition Version summary. Authorization remains before lookup.

### P2-11 — Source-native item and revision-token uniqueness needed explicit guards

Source-native item identifiers are unique within one Source Definition. Source-native revision tokens are unique within one Source Item. The source-native guard runs before the generic semantic-collision guard so the retained failure reason remains inspectable.

### P2-12 — The initial review artifact and temporary transport were not suitable for merge evidence

The corrupted review record was replaced completely. All installer, repair-runner and retained failure-diagnostic files were removed after materialisation and focused verification. PR #210 now contains only intended implementation, migration, test and durable documentation files.

### P2-13 — Repeated administrative Neo4j driver creation exhausted service-lane margin

The first final-evidence attempt passed all ordinary and authenticated Neo4j workflows but the signed SDLC service process reached the unchanged 55-second hard deadline. The complete-projection actual-service test module created many short-lived administrative drivers for setup, inspection and cleanup. Those calls now reuse one process-scoped authenticated driver, closed through `atexit`; every production adapter, system boundary, destructive test, credential-failure test and all 32 service scenarios remain unchanged. Source-integrity documentation whitespace found by the same signed run was also removed rather than bypassed.

## Adversarial evidence added

`newsroom/tests/test_source_3a_review_regressions.py` proves:

1. item and revision equality remain stable across policy/code metadata changes;
2. source time rejects noncanonical date and timestamp values;
3. mixed Anchor/Comparator configuration preserves valid Active mappings and rejects Comparator-as-Active;
4. explicit version reversion is retained while current-head semantic no-op fails;
5. repeated item identity and conflicting native revision tokens fail closed;
6. source-native item identifiers cannot allocate a second item identity;
7. metadata-only readers cannot read item or revision details; and
8. trigger-bypassing raw-SQL tampering of item, locator-decision, revision, representation, occurrence and coverage-mapping normalized columns fails reopen.

## Focused test evidence

Workflow run `30258893577` produced the final focused JUnit artifact after committing focused review corrections as `14018fd985dbb9efeb1e0d2b5050b543be272bab`.

Artifact:

```text
name: increment-3a-focused-test-evidence
artifact id: 8650047829
artifact digest: sha256:18b184ce0b853b7d2facec05f707181d6b508abc198e85d8340cb7072b4b4cc2
```

Retained JUnit result:

```text
tests: 78
failures: 0
errors: 0
skipped: 0
```

The focused set includes retained Projection B1, complete-projection 2B, retrieval 2C, Candidate 2D and relation 2A migration/authority compatibility plus all Increment 3A contract, authority, lifecycle-integrity, adversarial-review and traceability tests.

## Timed service-margin evidence

Workflow run `30260027624` applied the bounded connection-reuse correction, executed the exact permanent service manifest under the unchanged 55-second timeout and removed its proof workflow after success.

Artifact:

```text
name: increment-3a-service-margin-evidence
artifact id: 8650516596
artifact digest: sha256:486d281950ffcc7273f1c447bd3bb34260cc8d48f91ac035853b2ecca4e2b7ee
```

Retained result:

```text
tests: 32
failures: 0
errors: 0
skipped: 0
JUnit duration: 52.316 seconds
measured command wall time: 53.315 seconds
hard deadline: 55 seconds
```

This is margin evidence only. The permanent signed SDLC workflow must still pass for the final owner-authored reviewed head.

## Authority and safety assessment

The implementation preserves these boundaries:

- SQLite ledger records and immutable source records remain authoritative.
- Source configuration creates no coverage, rights, operational or production authority.
- URLs, GUIDs, filenames, cursors, titles, timestamps and content digests are not global Newsroom identity.
- Source content cannot alter command policy, egress, credentials, budgets or authority.
- Parser/version reprocessing creates a Discovery Representation, not a Source Revision.
- Re-observation creates a Discovery Occurrence, not duplicate Revision, Signal or Lead authority.
- No legacy `links`, mutable `events`, clusters or legacy IDs are imported or dual-written.
- No live network, source credential, schedule, TLS bypass, browser collection, Graphiti, model, embedding, search, Neo4j source projection, shadow, canary, publication, production activation, spending or public effect is present.

## Migration and rollback assessment

Schema version 10 is checked, forward-only and included in the exact migration history and schema fingerprint. Fresh creation and upgrade from version 9 use one exclusive migration transaction. Immutable-record triggers, foreign keys, exact heads, canonical digests and startup relational checks remain active.

Before a version-10 database is opened, rollback is a normal source revert. After version 10 has opened a database, restore a verified pre-v10 backup or apply a reviewed forward fix. Do not delete migration rows, rewrite source authority or use a derivative projection as rollback truth.

## Remaining exact-head merge gates

Before merge, PR #210 must retain successful evidence for the final reviewed head from:

- CI;
- Authority A2a;
- Authority A2b;
- Projection B1;
- authenticated Projection B2/B3/C1 Neo4j regression; and
- SDLC Evidence Shadow route, core, service and final decision.

The final head must also have zero unresolved review threads, zero actionable review comments and zero unresolved P1/P2 findings. CI is regression evidence, not owner or production approval.

## Stop boundary

Increment 3B remains blocked. Do not begin generic transport or parser implementation until PR #210 is merged, issue #205 is closed with exact completion evidence and the Source Definition, Version, Item, Revision, Representation, Occurrence, observation-model and baseline-policy contracts are stable on `main`.
