# Increment 4E bilingual governance and actual-Neo4j proof operations

**Status:** final local completion candidate for issue #229; exact-head remote qualification pending
**Parent:** #144
**Authorised base:** `main@bf7b955d57f5e583fcfc9bade109eec79564a200`
**Runtime boundary:** repository-owned deterministic fake and approved replay; authenticated actual Neo4j Community projection only

Increment 4E proves the complete governed path from retained source material through proposal production, entity resolution, relation admission and admitted-only Neo4j generation. SQLite and governed objects remain authority. Neo4j remains a disposable, rebuildable projection. The private Graphiti proposal workspace remains disposable and non-authoritative.

Real Graphiti, model and embedding execution remains disabled and unqualified. This unit starts no live source, search, schedule, provider credential, spending, publication, shadow, canary or production activation.

## Public proof boundary

The admitted graph proof is exposed through a bounded controller:

```python
from newsroom.increment4 import (
    Increment4Neo4jActiveReadRequest,
    Increment4Neo4jBuildRequest,
    Increment4Neo4jController,
)
```

`Increment4Neo4jController` owns no SQLite connection, Neo4j driver, session, credential, raw Cypher or graph authority. It delegates only three fixed operations:

```text
build_and_promote
generation_status
read_active
```

The official Neo4j driver remains imported only inside `newsroom/projection/neo4j/_adapter.py`. Package-root Increment 4 exports use lazy loading so importing the canonical proof contracts does not import the driver.

## Complete deterministic fixture path

The qualified path is:

```text
rights-permitted Source Revision and Discovery Representation
→ exact governed Passage hydration
→ immutable Extraction Run through deterministic fake adapter
→ retained structured output and Proposal Envelopes
→ complete proposal-workspace cleanup
→ explicit approved replay over retained output and proposals
→ Entity Mentions
→ accepted, held or unresolved Entity Resolution Decisions
→ Canonical Entities, Entity Versions and bilingual Aliases
→ append-only merge, split and reversal decisions
→ material entity-resolution dependency checks
→ Relation Proposal
→ hold or explicit Relation Admission Decision
→ immutable Relation Assertion
→ correction, supersession, invalidation or revocation history
→ admitted-only projection snapshot
→ isolated Neo4j generation build
→ exact reconciliation and validation
→ SQLite-owned ACTIVE promotion
→ bounded ACTIVE read with generation and watermark metadata
```

The proof deliberately binds downstream entity and relation authority to the approved replay output rather than treating the original fake attempt or private workspace as recovery authority.

## Admitted projection contracts

The dedicated projection family is:

```text
family:     graph.increment4.admitted
family:     increment4-admitted-family-v1
ontology:   increment4-admitted-ontology-v1
mapping:    increment4-admitted-mapping-v1
projector:  increment4-admitted-snapshot-projector-v1
```

`Increment4AdmittedProjectionSnapshot` accepts only typed current authority:

- current Canonical Entities and exact Entity Versions;
- admitted bilingual aliases and their exact resolution provenance;
- current active Editorial Relation Assertions;
- exact immutable ledger events required by every projected record; and
- one authoritative cutoff covering the retained events.

The mapper emits deterministic structural batches containing canonical Newsroom identifiers. It never emits Graphiti private node IDs, Graphiti private relation IDs, Neo4j element IDs, proposal identifiers, credentials or source text.

Editorial relations are reified assertion nodes. Subject and object roles remain distinct structural edges. A current correction may point to a retained superseded predecessor assertion, but the predecessor's underlying source and entity rights are revalidated. Supersession never silently retargets an earlier assertion.

## Bilingual identity governance

The repository-owned fixtures prove:

1. an English mention and Hong Kong Traditional Chinese alias resolve to one Canonical Entity only after exact accepted evidence;
2. identical English and Chinese names in two different contexts remain separate Canonical Entities;
3. lexical equality, transliteration and extractor confidence never canonicalise automatically;
4. unresolved identity is retained as an explicit decision;
5. a materially dependent relation cannot be accepted while that identity remains unresolved;
6. the relation may receive `HOLD` at decision version 1;
7. later accepted identity resolution permits `ACCEPT` at decision version 2; and
8. the earlier hold remains immutable, preserving the exact decision sequence `[HOLD v1, ACCEPT v2]`.

## Entity lineage

Merge, split and reversal are append-only authority.

A merge retains exact predecessor Entity Versions and creates a successor version. A split retains the exact source version, successor entities and complete mention allocation. A reversal identifies the exact merge or split decision and restores explicit identities. Replacement Neo4j generations are built from the resulting current authority while immutable predecessor aliases, versions and decisions remain reconstructable.

Earlier relation assertions are not rewritten merely because entity preferred identity changes. A later editorial decision is required to create a new assertion or correction.

## Relation lifecycle

The fixture covers:

```text
HOLD
ACCEPT
INVALIDATE
REVOKE
SUPERSEDE
CORRECTS
```

A correction is represented by a new admitted assertion whose endpoints may be prior retained relation assertions. The predecessor's lifecycle changes through an explicit supersession decision. The correction retains subject, object, predicate, exact proposal version, decision, provenance and temporal scope.

Revoked, invalidated, superseded, rejected, held and unresolved relations are absent from current admitted projection. Their immutable authority remains queryable under the appropriate historical scope.

## Generation build and promotion

`Increment4Neo4jBuildRequest` binds:

- exact generation identity;
- exact admitted snapshot digest;
- exact family, ontology, mapping and projector versions;
- exact required source watermark;
- bounded idempotency key and operational reason; and
- whether a retired predecessor generation may be physically purged.

The controller performs:

1. family registration or exact replay;
2. creation of one isolated BUILDING generation;
3. cleanup of pre-existing derivative state in that generation;
4. deterministic batch application;
5. exact delivery coverage and optional-event accounting;
6. transition to VALIDATING;
7. actual Neo4j expected/actual reconciliation;
8. atomic source-watermark validation;
9. SQLite-authoritative validation recording;
10. ACTIVE promotion;
11. retirement of the prior ACTIVE generation; and
12. optional physical purge of the retired generation.

A mismatch in node count, relation count, canonical identities, relation keys, contract digests, watermark or source authority prevents promotion.

A structural admitted generation may have a checkpoint later than the source watermark because projection-management events are optional. The atomic rule therefore requires:

```text
generation checkpoint >= required source watermark
latest non-projection source watermark == required source watermark
```

This prevents a new source event from appearing between reconciliation and activation without incorrectly rejecting permitted projection-control events.

## Bounded ACTIVE reads

`Increment4Neo4jActiveReadRequest` is a named read contract. It requires the authority-selected ACTIVE generation and bounded limits. A response carries:

- family and generation identity;
- ontology, mapping and projector identity;
- checkpoint and source watermark;
- gap and validation state;
- canonical Newsroom node and relation identities;
- admitted trust and exact source-event provenance; and
- no Neo4j internal identifier.

A missing, stale, unvalidated, gapped or mismatched generation fails closed. Graph loss is not represented as no match.

## Workspace loss and replay

The deterministic fake writes only to a private disposable workspace with no credentials and deny-all egress. Every attempt records cleanup and proves the namespace is absent.

After complete workspace deletion:

- retained Extraction Run output and Proposal Envelopes remain intact;
- approved replay verifies the exact retained output and proposal digests;
- replay does not invoke the fake, Graphiti, a model or network;
- entity and relation authority remains intact; and
- the Neo4j generation rebuild requires no stochastic historical extraction.

The proposal workspace is never a hidden backup or recovery source.

## Graph loss and replacement recovery

To recover complete Neo4j loss:

1. retain the SQLite and governed-object authority unchanged;
2. allocate a fresh generation identity;
3. derive the admitted snapshot from current entity and relation authority;
4. build deterministic batches;
5. reconcile the new actual Neo4j generation;
6. validate and promote it; and
7. retire or purge any damaged predecessor generation.

Exact replay is idempotent and creates no duplicate Runs, attempts, mentions, entities, aliases, proposals, decisions, assertions, batches or graph state.

## Rights revocation, deletion and purge

Current entity, relation, adapter-attempt and replay reads revalidate the exact governed Passage, Source Definition Version, object admission, access and deletion state.

When the covered source is tombstoned:

- current entity and relation reads are denied;
- a replacement admitted snapshot contains no prohibited current entity or relation state;
- an empty replacement generation is valid and becomes the only ACTIVE generation;
- the prior generation is physically purged when requested;
- exact replay cannot resurrect the prohibited data; and
- immutable lawful history remains retained in SQLite subject to its retention policy.

The controller therefore supports a zero-node, zero-relation admitted generation. Empty current authority is not a failed build and must not force stale prohibited derivatives to remain active.

## Permanent workflow evidence

The permanent focused lanes include:

```text
Authority A2a: test_authority_a2a_increment4e.py
Authority A2b: test_authority_a2b_increment4e.py
Projection B1: test_projection_b1_increment4e.py
```

The permanent authenticated Neo4j workflow explicitly invokes `test_increment4e_neo4j_service.py` and requires exactly these four unskipped cases:

```text
test_actual_service_increment4_admitted_state_projects_exactly_and_replays
test_actual_service_increment4_graph_loss_replays_retained_authority_exactly
test_actual_service_increment4_replacement_generation_is_only_serving_state
test_actual_service_increment4_tombstone_purges_and_never_resurrects
```

Every case begins from the governed deterministic fake and approved-replay authority path before projecting to the authenticated service.

The SDLC classifier's exact service inventory includes the Increment 4E actual-service file. A workflow edit without the corresponding classifier contract update fails the repository suite.

## Operator runbook

### Build a replacement generation

- obtain an authenticated management proof;
- construct one exact current admitted snapshot;
- choose a new UUIDv4 generation identity;
- bind the current source watermark and all contract versions;
- call `build_and_promote` once;
- verify the returned generation is ACTIVE and the prior generation is RETIRED; and
- use only `read_active` for serving reads.

### Reconcile a suspected mismatch

Do not patch graph rows manually. Build a replacement generation from retained authority. A reconciliation mismatch keeps the generation non-active. Preserve the failed generation metadata for diagnosis, then purge derivative state only after evidence is retained.

### Recover graph loss

Do not rerun extraction. Rebuild from retained output, entity decisions, relation decisions and ledger events. Use a new generation identity and require exact reconciliation before promotion.

### Process rights deletion

Commit the governed deletion or tombstone first. Reopen current authority to confirm covered reads fail. Build and promote the empty or reduced replacement generation. Purge the retired generation. Re-run exact replay to prove non-resurrection.

## Rollback

The Increment 4E source can be rolled back by reverting its merge commit while retaining SQLite authority and any safely isolated Neo4j generation. Do not roll back by mutating entity decisions, relation decisions or ledger events.

If a newly promoted generation is defective and the predecessor is still rights-current and physically present, authority may select a separately validated replacement under the established generation controls. If the predecessor contains prohibited or tombstoned data, it must not be reactivated; rebuild a clean generation instead.

Removing the dedicated 4E projection family loses only derivative state. It does not remove Extraction Runs, proposals, entity decisions, relation decisions or governed source authority.

## Explicit exclusions and deferred work

This unit does not authorise or qualify:

- real Graphiti, model or embedding execution;
- live source access, search, schedules, provider credentials or spending;
- Candidate, Evidence Intake, publication, shadow, canary or production activation;
- unrestricted Cypher or caller-selected graph labels and predicates;
- hybrid retrieval ablation or product-answer quality; or
- production Operational Admission.

Those require fresh owner decisions and later increment boundaries. Completion of issue #229 closes Increment 4 only after exact-head repository, authority, projection, authenticated-service and signed SDLC evidence passes.

## Stop boundary

Increment 5 must not start until issue #229 and parent #144 close on `main` with exact 4A–4E merge commits, workflow runs, signed evidence, review state, exclusions and deferred runtime decisions.
