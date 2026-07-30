# Increment 4C general relation authority operations

**Status:** implementation review unit for issue #227
**Parent:** #144
**Authorised base:** `main@76ee0abea6010d943a6f3ec6198109e64ae2929f`
**Execution boundary:** deterministic repository-owned fixtures and retained Increment 4A/4B authority only

Increment 4C records versioned editorial predicates, immutable Relation Proposals, explicit admission decisions, admitted Relation Assertions and later lifecycle history. SQLite ledger events and checked relation rows remain authoritative. Current serving rows and later graph state are rebuildable derivatives.

A proposal, extractor confidence, graph path, shared name or predicate hint never creates an admitted relation. Admission requires one authenticated `ACCEPT` decision over the exact current proposal version, exact predicate contract, exact current endpoints, exact retained evidence and every material Entity Resolution Dependency.

No operation in this unit invokes Graphiti or a model, performs an embedding call, accesses a live source, writes governed Neo4j state, creates a Candidate, starts Evidence Intake, publishes content or activates production.

## Public boundary

Open the authority through the dedicated submodule:

```python
from newsroom.authority.editorial_relation_system import (
    open_governed_editorial_relation_authority_system,
)
```

The returned `system.relations` facade exposes only typed, authenticated operations:

```text
propose
 decide
proposal
proposal_version
decision
assertion
current
current_relations
projection_events_after
```

The facade exposes no SQLite connection, capability issuer, command grant, arbitrary SQL or Cypher, graph credential, caller-selected relationship type, predicate-registration mutation, Graphiti workspace, model provider, Candidate writer, Evidence Intake writer or publication writer.

Current projection recovery is deliberately outside the ordinary facade:

```python
from newsroom.authority.editorial_relation_projection_rebuild import (
    rebuild_governed_editorial_relation_current_projection,
)
```

That operational function acquires the same sole-writer lock, checks the complete authority, revalidates rights for every current assertion before the first insert, recreates only missing derivative assertion-head rows and refuses to overwrite divergent state.

## Commands and scopes

| Operation | Required scope | Durable meaning |
| --- | --- | --- |
| `propose` | `authority.relation.propose` | Retain one immutable proposal version, exact endpoint bindings, evidence and entity-resolution dependencies. |
| `decide` | `authority.relation.decide` | Commit accept, reject, hold, unresolved, invalidate, revoke or supersede authority. |
| Proposal reads | `authority.relation.read_proposals` | Read proposal versions and decisions without admitted or projection authority. |
| Admitted reads | `authority.relation.read_admitted` | Read admitted assertions and current admitted views. |
| Projection reads | `authority.relation.read_projection` | Read ordered admitted-only projection events. |

The three read scopes are distinct. Every read authenticates and authorises before storage access, verifies authorization provenance, enforces an allow-listed principal and applies finite result limits.

The command types are:

```text
editorial.relation.proposal.record
editorial.relation.decision.record
```

Proposal commands use `PROPOSED` trust. A decision that creates or changes admitted assertion state uses `ADMITTED` trust. No producer receives decision authority merely because it can submit a proposal.

## Closed predicate registry

The only initial registry is:

```text
Registry version:
editorial-predicate-registry-v1

Registry digest:
sha256:a53c3cc39a2f759c5898b64f982448bfc3bee15e205b40160fb2e2b62d92501b

Admission policy:
editorial-relation-admission-policy-v1
```

It contains exactly:

```text
SAME_EVENT_AS
DEVELOPMENT_OF
SAME_PROCESS_AS
CORRECTS
SUPERSEDES
SUPPORTS
DISPUTES
CONTRADICTS
ABOUT_EVENT
```

Every predicate contract binds exact endpoint-kind pairs, directionality, temporal semantics and admission policy. Caller text, source content, model output and Graphiti labels cannot extend this registry at runtime. A wrong registry digest, predicate contract digest or decision-policy version fails before commit and also fails checked reopen if mutation guards were bypassed.

Symmetric predicates require canonical endpoint order. Directional predicates preserve subject-to-object meaning. An unsupported endpoint pair fails closed.

## Checked schema v15

Migration `editorial_relation_authority_v15` advances schema v14 to schema v15.

```text
Migration checksum:
sha256:946a697524cd1ce84546208c21948ec29c59df79410c5eafef196c344f2d8587

Complete schema fingerprint:
sha256:5b113904c4ab06452f792078b32bee1752640bb821dc98fc3fdeeb747274efca
```

Schema v15 adds:

```text
editorial_predicate_registries
editorial_predicate_contracts
editorial_predicate_endpoint_pairs
editorial_relation_endpoints
editorial_relation_proposals
editorial_relation_proposal_versions
editorial_relation_proposal_heads
editorial_relation_evidence_items
editorial_relation_extraction_evidence
editorial_relation_workflow_evidence
editorial_relation_resolution_dependencies
editorial_relation_decisions
editorial_relation_decision_heads
editorial_relation_assertions
editorial_relation_assertion_heads
editorial_relation_supersessions
editorial_relation_projection_events
editorial_current_admitted_relations
```

The migration is forward-only, atomic and checked. A newer schema, wrong migration checksum, changed registry seed, missing table/view/trigger, foreign-key violation or different schema fingerprint fails closed. Historical proposal, evidence, dependency, decision, assertion, supersession and projection-event rows are immutable. Only guarded current heads may advance, and each head must agree with exact retained history.

## Proposal authority

An `EditorialRelationProposalRequest` binds:

- stable Proposal and Proposal Version identities;
- exact predicate registry and predicate contract digests;
- exact typed subject and object identities and versions;
- valid, observed and proposal time dimensions;
- one or more exact Extraction Run or workflow evidence records;
- exact material or non-material Entity Resolution Dependencies;
- producer kind, identity, version and contract digest;
- confidence and uncertainty as proposal metadata only; and
- canonical semantic, stable-semantic and complete-record digests.

Proposal versions are contiguous and immutable. A later version names the exact current predecessor. A decided proposal cannot receive a new version. Repeating the exact idempotency namespace/key and payload returns the retained result with `replayed=True`; incompatible reuse fails closed. Equivalent stable semantics cannot allocate a second proposal identity silently.

Extraction evidence revalidates the exact retained Increment 4A Proposal Envelope, Run, Run Version, Output, Passage and byte range. Workflow evidence resolves one exact retained workflow record. A bare UUID, title, timestamp, similarity score or graph-internal identifier is insufficient.

## Endpoint authority

Supported endpoint kinds are closed and typed:

```text
CANONICAL_ENTITY_VERSION
SOURCE_REVISION
EVENT_HYPOTHESIS_VERSION
STORY_CANDIDATE_VERSION
RELATION_ASSERTION
```

Canonical Entity endpoints must reference the exact current Entity Version. Stale or cross-paired Entity Versions fail closed. Source Revision endpoints must be retained under the current Source Definition Version and remain permitted. Event Hypothesis and Story Candidate endpoints require retained workflow authority rather than arbitrary UUIDs. Relation Assertion endpoints recursively resolve an admitted current assertion and cannot create an assertion cycle.

## Entity-resolution admission precondition

A material dependency blocks `ACCEPT` unless its exact current Entity Resolution Proposal state is `ACCEPTED` and its admitted identity/version remains current.

`PROPOSED`, `HELD`, `UNRESOLVED`, `REJECTED` and `REVERSED` do not supply admissible identity. A relation may therefore be held while identity is unresolved, retain that immutable hold as decision version 1, and later receive a separate version-2 `ACCEPT` after the exact dependency becomes accepted. The earlier hold is not rewritten; retained decision history is `[HOLD v1, ACCEPT v2]`.

A material Entity Resolution Dependency blocks admission even when relation confidence is high. Non-material dependencies remain attributable but do not block.

## Decisions and assertion lifecycle

Proposal decisions are contiguous and optimistic:

| Action | Proposal/current result | Assertion effect |
| --- | --- | --- |
| `ACCEPT` | `ADMITTED` | Creates one immutable active Relation Assertion. |
| `REJECT` | `REJECTED` | Creates no admitted assertion. |
| `HOLD` | `HELD` | Preserves review state for a later decision version. |
| `UNRESOLVED` | `UNRESOLVED` | Records insufficient evidence without guessing. |
| `INVALIDATE` | `INVALIDATED` | Removes a target assertion from current serving while retaining history. |
| `REVOKE` | `REVOKED` | Removes a target assertion from current serving with explicit authority. |
| `SUPERSEDE` | `SUPERSEDED` | Retains predecessor and successor plus exact directional supersession history. |

An `ACCEPT` decision creates an assertion only after validating the exact current proposal version, predicate contract, endpoint compatibility, evidence, dependencies and semantic collision authority. Duplicate current assertions for the same governed relation key are rejected.

A lifecycle decision names the exact target assertion and current decision head. `SUPERSEDE` also names the exact admitted successor and immutable supersession identity. Historical proposals, decisions and assertions are never deleted or rewritten.

## Time dimensions

The following remain distinct:

```text
source-asserted time
observation time
relation valid-from / valid-until
proposal recording time
decision recording time
assertion admission time
invalidation / revocation / supersession time
projection-event recording time
```

Unknown time remains explicit. Source time is metadata and never substitutes for Newsroom recording authority. Predicate contracts enforce their temporal shape.

## Current rights and deletion

Every proposal, assertion, current relation and projection-event read revalidates exact retained provenance:

- current Source Definition Version;
- Source Item and Source Revision state;
- governed-object Admission and Rights Decision;
- Access Decision and hydration policy;
- blob lifecycle and integrity state;
- entity identity/version and resolution-dependency state; and
- recursive assertion endpoints.

A deletion in `REQUESTED` state remains usable only while the underlying rights and governed blob remain active. `TOMBSTONED` or `PHYSICALLY_REMOVED` state blocks current use. Revoked rights, expired rights or a changed current Source Definition Version also block use while immutable audit history remains retained.

Lower-level extraction or entity rights failures are normalized to `EditorialRelationRightsDenied` at the relation boundary.

## Projection events and current rebuild

Only explicit admitted assertion state emits projection events:

```text
UPSERT ACTIVE
REMOVE INVALIDATED
REMOVE REVOKED
REMOVE SUPERSEDED
```

A proposal, rejection, hold or unresolved decision emits no admitted projection event. `projection_events_after` is ordered by exact source ledger sequence, bounded by a finite limit and returns typed admitted-only records.

`editorial_relation_assertion_heads` and `editorial_current_admitted_relations` are derivatives. `rebuild_governed_editorial_relation_current_projection` may recreate missing heads only when:

1. schema v15 and all retained authority pass integrity checks;
2. existing rows are absent rather than divergent;
3. the latest immutable projection event exactly matches the latest decision;
4. all endpoint, evidence and dependency rights pass before the first insert; and
5. recursive Relation Assertion endpoints resolve without cycles.

Rebuild is atomic, emits no ledger or projection events and never reruns extraction. A divergent row, prohibited source, stale entity, cycle or missing event causes zero inserts. Rebuild cannot resurrect prohibited material.

## Integrity and tamper response

Checked startup reconstructs and validates:

- registry, predicate contracts and endpoint pairs;
- proposal/version chains and current proposal heads;
- endpoint canonical bytes;
- extraction and workflow evidence;
- entity-resolution dependencies;
- decision chains and current decision heads;
- assertion canonical bytes, relation keys and current assertion heads;
- supersession direction and target/successor lineage;
- projection-event coverage and latest-state agreement; and
- assertion-endpoint acyclicity.

SQLite triggers reject ordinary mutation. Focused tests drop individual guards, tamper with decision policy, evidence children, dependencies, proposal/decision/assertion heads, assertion canonical digests and projection coverage, restore the trigger and prove checked reopen rejects the database.

Operators must preserve the failed database and diagnose from an unchanged copy. Authoritative history must not be repaired in place.

## Concurrency and replay

One process owns the SQLite writer lock. Concurrent identical proposal or decision commands create one ledger event and return one exact replay. Concurrent incompatible decisions serialize; one commits and the other receives a typed stale-decision or conflict result. A failure before commit leaves no partial proposal, decision, assertion, supersession or projection event.

## Recovery and rollback

### Before merge

A 4C branch can be abandoned without affecting `main`. Delete the branch and disposable test databases. Do not copy schema-v15 databases into environments still running schema-v14 code.

### After migration

Schema v15 is forward-only. Rollback means:

1. stop all writers;
2. retain the complete database and governed-object store as evidence;
3. restore a pre-v15 backup for schema-v14 code, or keep v15 code deployed while relation commands are disabled by authorization policy;
4. correct defects through a later migration/version rather than deleting committed v15 rows; and
5. rerun checked open, focused 4C evidence and all permanent repository gates.

### Current projection loss

Use `rebuild_governed_editorial_relation_current_projection` only for missing derivative heads. Do not use it to overwrite divergence. Divergence is an integrity incident.

### Rights or deletion incident

Remove relation command/read authorization for the affected principal or source, preserve immutable authority, complete the governed deletion process and verify ordinary reads plus rebuild fail closed. Do not rewrite historical decisions to simulate deletion.

## Operational checks

Before enabling a 4C writer in a controlled environment:

- confirm schema v15, migration checksum and schema fingerprint;
- confirm the exact registry version and nine predicate-contract digests;
- confirm `PRAGMA foreign_key_check` is empty and `PRAGMA quick_check` is `ok`;
- confirm both command definitions and the three distinct read scopes;
- run contract, migration, authority, proposal, lifecycle, rights, security, concurrency, integrity, rebuild and traceability tests;
- verify no Graphiti/model/network/Cypher/graph-write import entered the boundary;
- verify zero unresolved P1/P2 findings and zero unresolved review threads; and
- retain exact-head CI, Authority, Projection, authenticated Neo4j and signed SDLC evidence.

## Permanent workflow hooks

Increment 4C has dedicated files in each applicable focused lane:

```text
newsroom/tests/test_authority_a2a_editorial_relation.py
newsroom/tests/test_authority_a2b_editorial_relation.py
newsroom/tests/test_projection_b1_editorial_relation.py
```

A2a proves exact authenticated proposal and decision command/event envelopes. A2b proves governed-object revocation blocks proposal, assertion, current and projection reads while immutable rows remain. Projection B1 proves proposals emit no admitted event and one explicit `ACCEPT` emits exactly one admitted `UPSERT` event.

Actual Neo4j relation projection, purge and complete bilingual proof remain Increment 4E.

## Stop boundary

Issue #228 / Increment 4D must not begin until #227 is merged to `main` and closed with exact evidence. Completion of 4C does not authorise real Graphiti, model or embedding execution, a Graphiti proposal workspace, actual-Neo4j bilingual projection, publication or production effects.
