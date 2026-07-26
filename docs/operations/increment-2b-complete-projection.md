# Increment 2B complete Neo4j projection foundation

**Role:** Implementation and operations record
**Status:** Draft PR evidence — no activation authority
**Owner:** Product owner
**Implementation issue:** #156
**Parent epic:** #142
**Draft PR:** #164
**Authorised base:** `main@819883fb77eeabfb76d91aca531003d07932d5a7`
**Canonical language:** English

## Purpose and exact boundary

Increment 2B adds the actual-Neo4j full-text and vector projection foundation for the repository-owned `integrated_fixture_v2` family. It does not implement Increment 2C retrieval, Retrieval Context version 2 or any public serving tool.

SQLite ledger records, immutable decisions and governed objects remain authoritative. Neo4j structural, admitted-relation, full-text and vector state remains disposable and rebuildable. Neo4j owns no authoritative identity, checkpoint, gap, validation, promotion, rights, deletion or publication decision.

One complete fixture generation contains all mandatory derivatives together:

1. deterministic structural nodes and relationships;
2. governed admitted `DEVELOPMENT_OF` relation projection;
3. bilingual full-text documents and a generation-specific full-text index; and
4. deterministic 16-dimensional vector documents and a generation-specific vector index.

A structural-only, relation-only, missing-index, wrong-contract or partial-state generation cannot validate or promote.

## Retained contracts

The complete generation binds immutable identities and digests for:

- projection family definition and version;
- ontology and structural projector;
- admitted-relation projector;
- complete-projection contract;
- full-text normalization and index contract;
- vector index contract;
- deterministic fixture-vector manifest;
- projection mapping; and
- exact source fixture manifest.

Store open re-derives canonical bytes and compares every normalized SQLite contract, manifest, fixture-document, generation-binding and validation-binding column with the typed registry. A re-digested or trigger-bypassing raw-SQL change fails startup integrity.

`fixture_fulltext_v1` uses repository-normalized permitted fixture passages. Normalization is NFKC, case folding and whitespace collapse under the retained contract. Qualification executes both the original bilingual query text and its retained normalized form as separately identified query evidence.

`fixture_vector_v1` uses repository-committed finite vectors:

- dimension: `16`;
- similarity: cosine;
- quantization: none;
- exact component and vector digests retained in repository authority;
- no external embedding provider or model call; and
- explicit rejection outside the fixture-qualification profile.

The Neo4j server selects the concrete index providers. Qualification inventories the actual indexes and requires exact compatibility with the retained `fulltext-2.0` and `vector-2026.06` provider contracts, plus exact analyzer, consistency, dimension, similarity and quantization configuration. Provider identity is compatibility evidence, not caller-controlled DDL.

## Private Neo4j boundary

The complete adapter is private and exposes typed operations only. It contains fixed, parameterized Cypher for:

- generation-specific index bootstrap;
- ordered derivative application;
- complete reconciliation;
- bounded full-text and vector qualification reads;
- generation cleanup; and
- index inventory.

Label, relationship type and index names are derived from typed generation and contract identities. No caller supplies Cypher, labels, relationship types, index names, index configuration or administration commands. The bootstrap administrator is separate from the non-bootstrap projector identity and is rejected by the governed projector boundary.

Neo4j null semantics remove properties assigned `null`. Optional retained fields such as a missing `revision_id` or open-ended `valid_until` are therefore omitted from Neo4j properties. Required and unknown properties remain fail-closed; absence is accepted only for fields that the typed canonical contract declares nullable.

## Ordered delivery and checkpoint authority

Projectors consume canonical ledger events in exact sequence. Every generation retains:

- next required ledger sequence;
- last applied contiguous checkpoint;
- delivery identity and digest;
- required gaps;
- retries and dead letters; and
- complete contract identity.

An exact duplicate delivery is idempotent. A collision at the same generation and sequence fails. A required gap or dead letter prevents complete validation and promotion. The graph cannot advance the authoritative checkpoint.

Complete rebuild uses the latest non-projection authoritative source ledger sequence. Projection-management events remain immutable ordered history but cannot extend the source cutoff merely because rebuild, delivery, validation or promotion generated them.

## Source-watermark race protection

The rebuild entrypoint binds the exact current non-projection source watermark. Validation, qualification and promotion then protect that watermark at three levels:

1. pre-operation comparison with the current SQLite source watermark;
2. post-Neo4j-reconciliation or post-query comparison; and
3. an atomic `BEGIN IMMEDIATE` SQLite comparison immediately before the validation or promotion authority commit.

A source event arriving during Neo4j reconciliation or qualification invalidates the attempted operation. The stale generation remains unvalidated and unpromoted. The final transactional check occurs before an idempotent replay is returned, so an old idempotency key cannot bypass current-source authority.

## Complete reconciliation

Expected state is derived only from retained SQLite and governed-object authority. Reconciliation compares exact expected and actual:

- structural nodes and relationships;
- admitted editorial relations;
- active full-text/vector documents;
- delivery records and digests;
- full-text and vector index state;
- labels, properties and generation identities;
- index providers and complete index configuration; and
- current rights and lifecycle exclusions.

Unexpected, missing, altered or mixed-generation state fails. Graph loss, index deletion or tampering loses no authority; it blocks validation until a replacement generation is rebuilt from retained authority.

## Validation, qualification and promotion

Validation requires:

- exact family and generation contracts;
- exact current source watermark;
- contiguous checkpoint through that watermark;
- zero required gaps and zero dead letters;
- complete expected-versus-actual reconciliation; and
- exact authenticated projector and compatibility evidence.

Qualification re-runs reconciliation and executes actual Neo4j reads. Every retained full-text query executes twice: original input and normalized input. Every vector query executes with the exact deterministic 16-dimensional vector. Evidence retains query identity, kind, rank, passage identity and score. The authority boundary independently requires the exact raw/normalized full-text query set, exact vector query set, contiguous ranks, expected leading passages and exact tombstone exclusions before accepting adapter evidence.

Promotion is an atomic SQLite-owned decision. It requires the exact validation digest and repeats the current-source watermark check inside the promotion transaction. Neo4j cannot self-promote. A retired or failed generation is not directly reactivated; recovery creates a replacement generation.

Increment 2B creates no Increment 2C named read tool and no production serving authority. `ACTIVE` in these tests is generation-authority evidence for the fixture boundary only.

## Rights, deletion and tombstone behavior

Source derivation rehydrates permitted bytes and lifecycle state from governed authority. A revoked, deletion-requested, tombstoned, physically removed or otherwise ineligible object is excluded from current derivative state.

Lifecycle changes produce rights-safe removals for every derivative. A rebuild from authority does not rerun stochastic extraction or embedding and cannot resurrect tombstoned material. Neo4j properties, full-text index contents or vector values never restore authority.

## Actual-service evidence

`.github/workflows/projection-b2-neo4j.yml` runs against an authenticated disposable Neo4j service with:

- runtime-generated masked credentials;
- runner-loopback Bolt exposure;
- distinct bootstrap and projector identities;
- the retained Increment 1 B1/B2/B3/C1 service regressions; and
- eight permanent complete Increment 2B cases.

The complete cases prove bilingual raw and normalized full-text queries, deterministic vector nearest-neighbor reads, exact complete generation promotion, wrong configuration and dimension failure, graph or index loss failure, replacement-generation recovery, rights revocation, tombstone non-resurrection and authority-only rebuild.

JUnit evidence must prove every required case executed without skip, failure or error. The workflow retains both the extended complete evidence artifact and the legacy B2/B3/C1 artifact alias expected by the accepted SDLC service lane.

## SDLC evidence margin

The accepted deterministic core lane remains a complete repository suite under the existing 55-second deadline. Increment 2B preserves that evidence margin without selecting tests or raising the budget:

- dependency analysis is cached only by the exact path and bytes of every repository-owned Python source; any add, delete, rename or byte change creates a new graph identity;
- callers receive isolated dependency mappings and cannot mutate the cached authority used by another classification;
- watchdog tests shorten their waits only after an explicit child or command readiness marker has been observed, while still proving shared-deadline enforcement, descendant termination and background-process rejection; and
- repeated deterministic complete-fixture tests clone a closed SQLite and governed-object template into each isolated test directory, then independently reopen and validate it before mutation.
- the deterministic core JUnit manifest marks the exact authenticated Neo4j cases optional only in that no-service lane; the service route still selects the complete 2B service file and proves all eight cases execute without skip, failure or error.

These are test and classifier execution optimizations only. They create no shared authority writer, skip no production test, change no SDLC contract, and expose no runtime product surface.

## Operator verification

Before merge, run from the repository root:

```bash
uv lock --check
python -m compileall -q newsroom scripts
python -m pytest -q
python scripts/eval_clustering_metrics.py \
  --dataset newsroom/evals/clustering_eval_dataset_v1.jsonl \
  --baseline newsroom/evals/clustering_eval_metrics_baseline_v1.json \
  --fail-on-regression
git diff --check
```

The exact final PR head must pass CI, Authority A2a, Authority A2b, Projection B1, authenticated actual-Neo4j evidence and the SDLC route/core/service/decision gate. A prior head's result is not evidence for a later head.

## Rollback

Before schema version 7 has been opened, rollback is a normal source revert.

After schema version 7 has been opened, do not delete migration rows, edit immutable authority records or reconstruct SQLite from Neo4j. Use one of:

1. restore a verified pre-v7 SQLite and governed-object backup; or
2. apply a reviewed forward fix and create a replacement projection generation.

Disposable generation-specific Neo4j nodes, relationships and indexes may be deleted and rebuilt from retained authority. Never perform graph-to-ledger recovery, restore prohibited material from an index, directly reactivate a retired generation or treat a graph/index outage as no prior match.

## Explicit exclusions

Increment 2B includes no:

- Increment 2C or later implementation;
- public driver, arbitrary Cypher or caller-selected graph mutation;
- Graphiti execution;
- external model, prompt or embedding call;
- live RSS, JSON, Brave, GDELT, search or source execution;
- production protected-content vector generation;
- hybrid retrieval, fusion or Retrieval Context version 2;
- full triage, Candidate admission or Evidence Intake;
- scheduler, shadow, canary or production activation;
- publication, spending or public effect.

## Stop boundary

Issue #157 remains blocked. Do not begin Increment 2C until Increment 2B is merged, issue #156 is closed with exact-head evidence, and the complete structural/relation/full-text/vector generation contracts are stable on `main`.
