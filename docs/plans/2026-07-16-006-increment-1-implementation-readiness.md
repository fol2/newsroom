# Increment 1 implementation readiness package

**Status:** Active  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Target branch:** `agent/increment-1-readiness-audit`  
**Base:** `main` at `6c6b24dcf3c450fcca562be1c5f277b82ad8171d`  
**Accepted architecture decisions:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md), [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md), [`../adr/0005-native-graphrag-production-deployment.md`](../adr/0005-native-graphrag-production-deployment.md)  
**Accepted specifications:** [`../specs/editorial-automation/discovery-record-semantics.md`](../specs/editorial-automation/discovery-record-semantics.md), [`../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md), [`../specs/editorial-automation/graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md) and their referenced focused Accepted discovery specifications  
**Accepted implementation plan:** [`2026-07-16-005-native-graphrag-production-implementation.md`](2026-07-16-005-native-graphrag-production-implementation.md)  
**Implementation authority:** Documentation-only. This package defines the bounded contract and exit evidence for the first Increment 1 code pull request. It starts no graph service, source access, extraction, embedding, model call, spending, shadow operation, canary, public effect or production activation.  
**PR #75 disposition:** Remains open as a donor. It is not an approved implementation base.

## 1. Outcome and boundary

The post-merge audit found no owner-level conflict. Increment 1 can proceed after this readiness pull request is reviewed and merged.

This package does not reopen the accepted product direction: discovery remains source-portfolio-first and change-driven; SQLite and governed objects remain authoritative; GraphRAG is repository-native and mandatory; Neo4j Community plus Graphiti remains the initial production target; extractors propose; controllers commit; and no production, canary or complete live-shadow target may be graph-less.

It closes only the contracts needed to begin the native integrated foundation safely: IDs and versions, trust and time, authenticated commands, ordered events, SQLite and object durability, projector state, ontology v1 boundaries, Neo4j integration and isolation, production configuration validation, actual-Neo4j CI, recovery expectations, PR #75 donor use and the first code-PR boundary.

It does not select live sources, models, embeddings, Graphiti prompts, final editorial predicates, retrieval thresholds, publication tables, Evidence Intake transport, shadow scope, canary scope or activation values.

## 2. Repository authority and consistency audit

### 2.1 Authority register

| Class | Records | Increment 1 treatment |
|---|---|---|
| Accepted ADRs | ADR 0001, 0002, 0004 and 0005 | Normative architecture authority. ADR 0003 is Accepted but outside this increment. |
| Accepted specifications | Focused discovery Topics 1–11, governed GraphRAG and native-production GraphRAG | Normative behaviour and safety requirements. |
| Accepted plan | Plan 005 | Accepted sequencing; cannot weaken an ADR or specification. |
| Active plan | This document | Exact Increment 1 readiness and first code-PR boundary under explicit owner instruction. |
| Proposed | Plan 001 and any individually Proposed record | Non-authoritative where not independently adopted. Its earlier GraphRAG deferral is superseded. |
| Draft | Publication, rights, autonomy, lifecycle and other individually Draft specifications | Non-normative evidence. Do not freeze their later physical schemas in Increment 1. |
| Superseded | Plans 003 and 004 | Historical only. Their graph-less or POC staging cannot control implementation. |
| Consolidated navigation | `news-discovery.md` | Non-normative index only; no duplicate requirement IDs. |
| Research/reference | `docs/research/`, `docs/reference/` | Evidence and context only unless adopted by an Accepted record. |
| Current system | Legacy runner, `ARCHITECTURE.md`, `AGENTS.md`, `PROMPTS.md` | Describes existing Brave/RSS/GDELT/Gemini/Discord behaviour, not target authority. |
| Pull requests | Merged PR #77; open PR #75 | Merge state does not itself create requirement authority. PR #75 is donor material only. |

### 2.2 Canonical source by decision

| Decision | Canonical source | Supporting source | Do not implement from |
|---|---|---|---|
| Ledger/object authority and rebuildable projections | ADR 0001 | `GRAG-002` to `GRAG-005` | Draft publication restatements or PR #75 tables |
| Single-host SQLite authority boundary | ADR 0002 | Plan 005 Increment 1 | Draft `DBOPS-*` as if Accepted |
| Source-first, change-driven discovery | ADR 0004 | Focused Accepted discovery specs | Proposed plan 001 or consolidated `DISC-*` text |
| Mandatory native GraphRAG | ADR 0005 | `GRPROD-001` to `GRPROD-005` | Superseded POC language or plan 004 |
| Neo4j Community plus Graphiti target | ADR 0005; `GRPROD-010` | Plan 005 | Research comparisons or POC graduation semantics |
| Proposal/admission separation | ADR 0001; `GRAG-020` to `GRAG-023` | Focused discovery controller requirements | Candidate/model gate output |
| Canonical IDs, versions and lineage | `DREC-001` to `DREC-007`, `DREC-070` to `DREC-077` | `GRAG-001`, `GRPROD-005` | Legacy IDs, URLs, digests or mutable rows |
| Ordered projection and rebuild | ADR 0001; `GRAG-024` to `GRAG-028` | `GRPROD-020` | Consumer-specific authority outboxes or skipped gaps |
| Increment 1 boundary | Plan 005 plus this document | `GRPROD-020` | PR #75's shadow feature boundary |

### 2.3 Conflicts and missing executable contracts

| Finding | Risk | Resolution |
|---|---|---|
| Accepted governed GraphRAG spec still uses POC wording in scope, `GRAG-050`, acceptance and completion text. | Optional experiment or later graduation could be implemented. | Replace only superseded POC wording with the Accepted production-target qualification contract. |
| Plan 005 calls ADR 0004 Proposed. | Source-first discovery could be treated as unresolved. | Correct the reference to Accepted. |
| `news-discovery.md` duplicates normative `DISC-*` requirements while declaring itself non-normative. | Drift and wrong-source implementation. | Reduce it to pure navigation and canonical-source mapping. |
| Plan 001 and Draft publication documents retain stale status or design text. | Search may surface obsolete direction. | Keep status and authority explicit; do not broaden this PR into a rewrite of non-controlling Drafts. |
| Plan status guidance defines `Active`/`Completed`, while owner-accepted plan 005 says `Accepted`. | Naive validation would reject an owner decision. | Grandfather plan 005; any repository-wide status migration needs separate owner review. |
| PR #75 trusts candidate rights gates and can revisit unfinished publication intents. | Prohibited use or duplicate public effects. | Reject those paths; carry forward independent rights admission and ambiguous-intent reconciliation invariants. |
| Neo4j Community has narrower native privilege and online-backup capability than Enterprise. | Unsupported RBAC/backup promises could weaken isolation. | Require compensating process/network/API controls, exact-version evidence and offline dump/rebuild; failure blocks activation or requires replacement. |
| IDs, command envelope, event envelope, object durability order, projector state and ontology scope were not exact enough for independent implementations. | Incompatible first code changes. | Freeze the bounded contracts in sections 4 and 5. |

The audit therefore selects outcome A: a documentation-only implementation-readiness pull request. No decision packet is required.

## 3. Requirement-to-implementation traceability matrix

`Foundation PR` means the first code pull request in section 6. `Reserved` means Increment 1 preserves the type/interface without implementing later product behaviour.

| Requirement ID | Canonical source | Component | Invariant/behaviour | Evidence | Increment | Dependency/status |
|---|---|---|---|---|---|---|
| ADR-0001/Decision | ADR 0001 | `newsroom.authority`, `newsroom.knowledge` | Ledger and governed objects are authority; graph/indexes are disposable projections. | Delete/rebuild Neo4j without authority loss. | Foundation PR | Ready |
| ADR-0002/Decision | ADR 0002 | SQLite writer and object store | One local supported SQLite writer; objects committed only after durable verification. | Fresh create, PRAGMA and crash-boundary tests. | Foundation PR | Numeric production limits deferred |
| ADR-0004/Decision | ADR 0004 | Shared ID/event registry | Foundation cannot assume query-first or legacy mutable identity. | No legacy dual write/import. | Foundation PR | Source runtime later |
| ADR-0005/Decision | ADR 0005 | Neo4j target and config validator | GraphRAG mandatory; Neo4j plus Graphiti is initial production target. | Actual service plus negative production profiles. | Foundation PR | Exact versions need qualification |
| DREC-001/002/003 | Record semantics | `authority.ids`, objects | Typed stable IDs; locators and digests remain separate. | Validation and equality tests. | Foundation PR | Ready |
| DREC-004/005/006/007 | Record semantics | Commands, versions, current views | No ID reuse; uncertainty explicit; versions immutable; current state rebuildable. | Conflict and rebuild tests. | Foundation PR | Uncertainty relations Reserved |
| DREC-016 | Record semantics | Rights scope and object admission | Identity/audit cannot require prohibited full bytes. | Prohibited-object rejection fixture. | Foundation PR | Final rights register later |
| DREC-070/073/074/076/077 | Record semantics | Events, time, extension registry | Exact lineage; explicit supersession; separate times; producer versions; rebuildable views. | Schema and replay tests. | Foundation PR | Full relation domain Reserved |
| GRAG-001 | Governed GraphRAG | Canonical registry | Graph-aware semantics exist in schema v1. | Ontology/event mapping present. | Foundation PR | Ready |
| GRAG-002/003/004/005 | Governed GraphRAG | SQLite, objects, projectors | Relational/object authority, rebuildable projections, no dual-write co-authority. | Failure injection and destructive rebuild. | Foundation PR | Ready |
| GRAG-006 | Governed GraphRAG | Repository/config layout | Graph capability remains in the initial programme. | Module/config contract tests. | Foundation PR | Ready |
| GRAG-010/011/012 | Governed GraphRAG | Trust and ontology | Closed trust states; confidence is not admission; structural and editorial relations differ. | Enum/transition/ontology tests. | Foundation PR | Editorial predicates Reserved |
| GRAG-013/014/015/016 | Governed GraphRAG | Relation/entity/retrieval extension types | Reified relation, entity resolution, dependent-admission and trust-labelled context seams stay compatible. | Type/schema contract tests. | Foundation PR | Full behaviour Increment 4/5 |
| GRAG-020/021 | Governed GraphRAG | Extraction boundary/config | Graphiti cannot mutate ledger/governed graph; proposal workspace isolated. | Dependency and endpoint-separation tests. | Foundation PR | Graphiti execution later |
| GRAG-022/023 | Governed GraphRAG | Extraction/admission extension schemas | Persisted proposal provenance and explicit admission remain required. | Reserved schemas only. | Reserved | Increment 4 approvals |
| GRAG-024/025 | Governed GraphRAG | Projector/checkpoint | Idempotent ordered consumption; contiguous watermark cannot skip a required gap. | Duplicate/gap tests. | Foundation PR | Actual Neo4j CI |
| GRAG-026/027/028 | Governed GraphRAG | Rebuild/generation/deletion | No stochastic rewrite; isolated generations; no prohibited resurrection. | Wipe/rebuild and tombstone fixtures. | Foundation PR | Full policies later |
| GRAG-030 | Governed GraphRAG | Time types/properties | Time meanings never collapse into one timestamp. | Round-trip mapping tests. | Foundation PR | Ready |
| GRAG-031/032/033 | Governed GraphRAG | Retrieval interfaces | Hybrid retrieval, authoritative hydration and bounded named tools remain mandatory. | Interfaces/manifest only. | Reserved | Increment 5 |
| GRAG-034/035 | Governed GraphRAG | Neo4j repository/metadata | No agent write path; results expose checkpoint/version/generation/gap/trust metadata. | Credential and envelope tests. | Foundation PR | Full retrieval later |
| GRAG-042/043/044/046 | Governed GraphRAG | Ontology, health, decision seam, profile validator | Discovery lineage projectable; outage is not no-match; graph-dependent decisions hold/fallback; no graph-less full shadow. | Mapping/status/config tests. | Foundation PR | Decision flow later |
| GRAG-050/051 | Governed GraphRAG | Target manifest | Neo4j plus Graphiti is production target, not POC; one challenger only after measured blocker/owner decision. | Manifest validation. | Foundation PR | Exact version Needs experiment |
| GRAG-057/058 | Governed GraphRAG | Qualification schema/test guard | Security/resource/licence/backup evidence gates versions; acceptance starts no runtime. | Unresolved evidence blocks; network-call guards. | Foundation PR | Measurements later |
| GRPROD-001/002/003/004/005 | Native deployment | Production manifest and repository | Mandatory native GraphRAG; no graph-less stage; no fake/no-op production; shared contract. | Negative profile and path tests. | Foundation PR | Implementations continue later |
| GRPROD-010/011/012/013 | Native deployment | Target/replacement/domain mapping | Qualification selects exact version; failure repairs/replaces; domain never depends on engine internals. | Manifest and mapping tests. | Foundation PR | Exact release evidence later |
| GRPROD-014/015/016 | Native deployment | Deploy/config/CI | Versioned deployment; missing graph fails; CI uses actual service. | Pinned Neo4j job. | Foundation PR | Image pin required |
| GRPROD-020 | Native deployment | Entire Foundation PR | Ontology, event mapping, graph boundary, health, deployment and integration enter Increment 1. | Section 6 exit evidence. | Foundation PR | This readiness package |
| GRPROD-021/022/023 | Native deployment | Later full slice/shadow | First complete slice and shadow remain graph-native; GraphRAG is not an optional plugin. | No graph-free passing variant. | Reserved | Increments 2, 5, 6 and 9 |
| GRPROD-024/030/031/032 | Native deployment | Health and release manifest | Outage is degradation; activation binds exact versions; missing/stale/gapped graph blocks readiness; acceptance starts no runtime. | Status/config/manifest tests. | Foundation PR | Activation later |

## 4. Increment 1 technical design

### 4.1 Repository and dependency direction

Representative ownership:

```text
newsroom/
  authority/{ids,trust,time,commands,events,sqlite,objects,projections,config}.py
  authority/migrations/
  knowledge/{ontology_v1,projection,neo4j,config}.py
config/{authority,knowledge}/
deploy/neo4j/
```

Names may change, but the dependency direction cannot:

```text
authenticated command -> SQLite authority + governed objects -> ordered events -> projectors -> Neo4j
```

The authority package cannot import Neo4j or Graphiti. The target implementation lives beside the legacy pipeline and performs no silent legacy dual write.

### 4.2 Canonical IDs, versions, trust and time

Controllers create opaque typed IDs, externally serialised as lowercase canonical UUID strings. URLs, provider IDs, titles, timestamps, digests and Neo4j internal IDs are never global Newsroom IDs. Each implemented aggregate has a stable `aggregate_id`, positive `aggregate_version` starting at 1, immutable version records where needed and explicit predecessor/supersession references. SHA-256 digests remain byte/payload identities, not domain identities.

The closed trust enum is `OBSERVED`, `PROPOSED`, `ADMITTED`. Unknown values fail. Confidence creates no authority. Proposed and admitted query surfaces remain distinct rather than depending on an optional status filter.

Canonical temporal values distinguish source publication/revision, Newsroom observation, source-asserted valid interval, authoritative `recorded_at`, proposal/admission/invalidation and later publication/acknowledgement time. Source times may be missing, approximate, date-only or conflicting. No generic ambiguous `timestamp` field substitutes for these meanings.

### 4.3 Authenticated command boundary

Only the repository-owned command writer mutates SQLite or governed-object references. The command envelope includes:

```text
command_id, command_type, principal_id, principal_scopes, issued_at,
idempotency_key, aggregate_type, aggregate_id, expected_aggregate_version,
payload_schema_version, payload_digest/object_ref, correlation_id,
causation_id, producer_version, authentication_context_reference
```

The boundary authenticates and authorises the principal, allow-lists command types, validates payload version/size, fences on expected aggregate version and records audit/result atomically. Reusing the same idempotency key with different payload is a conflict; the same key/payload returns the committed result without another mutation.

Increment 1 provides an authenticator interface and deterministic test authenticator. Production transport/principal provisioning is `Needs experiment`; no production profile may start with an unauthenticated local writer.

### 4.4 Consumer-neutral ordered events

Each authoritative domain change appends one consumer-neutral event in the same SQLite transaction as its mutation and audit record. No per-consumer authoritative outbox is created.

Required fields:

```text
ledger_seq, event_id, event_type, event_schema_version,
aggregate_type, aggregate_id, aggregate_version, recorded_at,
command_id, principal_id, correlation_id, causation_id,
producer_version, payload_digest, payload_object_ref,
security_scope, retention_scope
```

The envelope contains non-sensitive routing metadata; sensitive payload access is separately authorised. Event versions are immutable. Unknown required versions create a visible projector gap. Replay never fabricates sequence numbers or recording times. Neo4j is never part of the authoritative transaction.

### 4.5 SQLite and migrations

The supported profile is one SQLite file on one host and a local filesystem with supported locking/durability. NFS, SMB, cloud-synchronised folders and multi-host direct access fail validation. Connections enable foreign keys; the writer verifies WAL, `synchronous=FULL`, bounded busy timeout, bounded transaction duration and checkpoint policy. Parsing, hashing, source access, model calls, Neo4j calls and object copying happen outside the SQLite write lock.

Migrations are forward-only, exclusive and checksummed. Startup fails on changed checksum, newer database version, non-empty unversioned database or missing expected constraints. Rollback after an incompatible committed migration uses a verified pre-migration recovery point, not an unreviewed reverse SQL script.

The first schema contains only command, generic authority/version, ordered event, object-reference and projector/generation records required by this foundation. It does not invent final publication, Evidence Package or entity-relation tables from Draft specifications.

### 4.6 Governed content-addressed objects and rights

Objects are immutable `sha256:<hex>` values under a deterministic path such as `sha256/<first-two>/<remaining>`. Installation is:

1. write bounded bytes to a same-filesystem temporary file;
2. enforce object-class rights/security/retention scope;
3. hash and verify size/digest;
4. flush the file;
5. atomically install without overwriting different bytes;
6. flush the directory where required;
7. verify the installed object; then
8. commit the ledger reference.

A committed reference cannot point to missing, partial or corrupt bytes. Pre-commit crash orphans are collectable only after a safe grace period and recovery-point reachability check.

`PROHIBITED`, expired, conflicting or unsupported use is a hard admission failure for the covered object class. Candidate/model gate output cannot override it. When bytes cannot be retained, only permitted minimised audit material may be stored. Deletion/tombstone decisions propagate to every covered projection and are replayed before restored data is released.

### 4.7 Projector state, gaps and generations

A projector identity is:

```text
projector_name + projector_version + ontology_version + generation_id
```

It records `last_contiguous_ledger_seq`, `next_expected_ledger_seq`, retry state, health, unresolved gaps and dead letters. Delivery is idempotent by projector identity and event ID. A later event cannot advance the contiguous watermark past an unresolved required earlier event.

Retry exhaustion creates a dead letter and unresolved gap, not permission to skip. Repair, non-applicability, replacement or generation failure requires an authorised recorded disposition.

Generation states are `BUILDING`, `VALIDATING`, `ACTIVE`, `RETIRED`, `FAILED`; only one generation per family is active. Material ontology/projector/index changes build in isolation and switch only after declared validation. Results expose versions, generation, contiguous sequence, gap/dead-letter state, query-valid time, serving time, trust and provenance.

### 4.8 Ontology v1 scope

Ontology v1 is a versioned repository artifact. It reserves stable types for Source Definition/Version, Item/Revision/Representation, Signal, Lead, Hypothesis/Version, Candidate/Version, Agenda, Entity Mention/Alias/Entity, Extraction Run, Relation Proposal/Assertion/Decision, Finding, Coverage Gap, Handoff references and projection metadata.

Increment 1 implements only deterministic structural mapping contracts for:

```text
HAS_VERSION, HAS_REVISION, HAS_REPRESENTATION, PRODUCED_SIGNAL,
PROMOTED_TO_LEAD, DERIVED_FROM, CONTAINS_PAYLOAD, PROJECTED_FROM_EVENT
```

Every mapping names the authoritative event and fields that establish it. Generic `RELATED_TO`, caller-supplied labels and model predicates are rejected. Same-event, development, correction, support, dispute, contradiction, supersession and entity equivalence remain reified later proposal/admission domains.

### 4.9 Neo4j and least privilege

Neo4j Community is the governed projection target. Future Graphiti execution uses a logically isolated proposal workspace or separate controlled instance and never receives the governed projector credential.

Domain code sees a narrow repository, not raw driver sessions, unrestricted Cypher or Neo4j internal IDs. Only the projector process receives write capability. Agents, source/model code, clients and logs receive no graph secret.

Because exact Community capabilities vary from the desired Enterprise-style boundary, the implementation uses and tests compensating controls:

- private/loopback network exposure and authentication;
- separate governed-projection and future proposal-workspace secrets;
- repository APIs with no general Cypher endpoint;
- disabled/allow-listed import paths, procedures and extensions;
- pinned immutable image/configuration;
- process/container and network-policy isolation; and
- exact-version evidence for users, read/write separation, dump, restore and recovery.

Where database-level read separation is unavailable, retrieval uses a separate Newsroom-owned read-only application API with no mutation method and no credential exposed to callers. A measured blocker causes repair or replacement under ADR 0005, never graph-less deployment.

### 4.10 Graph-required configuration and actual-Neo4j CI

Profiles are `unit`, `integration`, `evaluation`, `production`. Unit may use fakes. Integration uses actual Neo4j. Evaluation/production require admitted production-target components.

A production or complete-live-shadow manifest fails when the graph is missing, disabled, fake, no-op or incompatible, or when required engine/version, endpoint/secret, ontology/projector versions, active generation, freshness/gap policy, graph/vector/full-text declarations, readiness, backup/rebuild/purge, licence/security evidence or rollback/replacement path is unresolved. Later components may be `NOT_YET_QUALIFIED`, which blocks readiness rather than disabling them.

A separate GitHub Actions job starts a pinned authenticated Neo4j Community image and proves: fresh SQLite/object setup; migrations; deterministic fixture commands/events; structural projection through production interfaces; canonical IDs; checkpoint metadata; duplicate delivery; gap/retry handling; graph wipe/rebuild; unchanged authority; credential boundary; and rejection of fake/disabled/missing production graph configuration. It makes no source, Graphiti, model, embedding, search or public-target call.

### 4.11 Failure, backup, restore and rollback

A valid authority recovery point is one SQLite cutoff plus every reachable governed object, a content-addressed manifest, schema/migration versions, scopes and digests. Incomplete sets are never called restorable. Restore is quarantined until database/object integrity passes and later deletion/tombstone decisions have been replayed.

Neo4j Community recovery is bounded to a verified offline dump/restore where supported and deterministic rebuild from SQLite/objects. The design does not promise Enterprise online backup semantics. Neo4j loss can reduce availability but cannot lose authority.

Exact off-machine encryption, keys, cadence, RPO/RTO and drill frequency remain Operational Admission decisions. Foundation rollback is code revert plus disposable graph removal; after a test migration, restore the verified pre-migration SQLite/object fixture and rebuild projections. This increment has no production activation or public effect.

## 5. PR #75 donor map

PR #75 remains open and unmerged.

| PR #75 area | Classification | Treatment |
|---|---|---|
| Canonical JSON parsing, duplicate-key rejection, restricted numeric domain, SHA-256 verification in `packages.py` | Reuse with adaptation | Move to neutral authority utilities; remove publication-package coupling; retain bounded-input tests. |
| Package integrity tests | Reuse with adaptation | Preserve UTF-8, duplicate key, float, unsafe integer, non-canonical and digest mismatch cases under new contracts. |
| WAL/FULL/foreign-key/busy-timeout/STRICT/transaction patterns in `governance_store.py` | Reference/selective reuse | Rewrite around commands, events, CAS references and projector state. |
| Direct `GovernanceStore` mutation surface | Rewrite | Replace with authenticated command writer and explicit read-only interfaces. |
| In-database package BLOB store | Reject as governed-object implementation | Governed objects use filesystem CAS; only bounded event payloads may be inline. |
| Audit hash-chain ideas | Reference-only | Useful defence-in-depth, but not a substitute for canonical events and records. |
| Stable-story/occurrence/decision/authority/publication tables | Reject as canonical schema | Shadow/Draft vocabulary is not Accepted Increment 1 authority. |
| Fence, lease and stale-writer test patterns | Reuse with adaptation | Apply to command/projector concurrency; never treat a fence as proof no external effect occurred. |
| Pause/resource-limit primitives | Reference-only | Exact scopes and thresholds are later operational decisions. |
| `decisions.py` gate evaluation | Reject for rights authority | Candidate `PASS` cannot override an authoritative prohibited-source decision. |
| `publication_control.py` controller/adapter separation | Reference-only | Useful later, but publication is excluded and unfinished-intent recovery is unsafe. |
| Recording-only publisher and `RECORDED_NOT_PUBLISHED` lane | Reject as product stage | May become a test double only; it is not an approved architecture. |
| PR #75 evidence/candidate/publication schemas | Reference-only | Reuse validation techniques, not final domain names or tables. |
| CLI inspection/exact-version fixtures | Reference-only | Rewrite against canonical IDs, events and projection metadata. |
| Whole branch | Reject for merge | Incompatible shadow authority, no native GraphRAG foundation and two unresolved P1 findings. |

### 5.1 Prohibited-source rights P1

The new architecture independently resolves effective authoritative rights at object admission and, later, Evidence Package admission. A `PROHIBITED` covered source/use hard-fails regardless of candidate, model or extractor output. Projectors receive only permitted references and replay deletion/tombstone decisions. Increment 1 implements the rights-scope seam and fail-closed object/deletion fixtures, not the final owner-approved rights register.

### 5.2 Ambiguous unfinished publication-intent P1

Publication is excluded, but later controller correctness is reserved: an intent without a terminal authenticated receipt or reconciled observation is an ambiguous prior attempt. Before adapter entry the controller must fence work, use target idempotency/correlation/observation where available, reconcile or record `UNKNOWN`, and require governed retry/remediation where absence of effect cannot be proven. Matching owner, lease or fence never proves that a previous process made no external effect.

## 6. First Increment 1 code pull-request boundary

### 6.1 Exact deliverables

1. New isolated `newsroom.authority` and `newsroom.knowledge` package skeletons.
2. Typed IDs, aggregate versions, trust and temporal value objects.
3. Authenticated-principal/command interfaces, test authenticator, idempotency and expected-version fencing.
4. Fresh SQLite schema and forward-only migration runner for commands, generic authority/version records, ordered events, object references and projector state.
5. Governed filesystem CAS with atomic install, flush, verification, rights rejection and safe orphan handling.
6. Consumer-neutral event append/read APIs.
7. Checkpoint, retry, gap, dead-letter and generation state machines.
8. Ontology v1 registry, bounded structural mappings and graph/vector/full-text projector interfaces.
9. Neo4j repository implementation for deterministic structural fixtures only.
10. Versioned development/integration Neo4j deployment definition and credential boundary.
11. Production/evaluation config schema requiring GraphRAG and rejecting fake/no-op/disabled/missing components.
12. Dedicated actual-Neo4j CI job.
13. Recovery interfaces/fixtures proving authority survives graph wipe/rebuild and deletion is not resurrected.
14. Requirement references from delivered code/tests to the matrix above.

### 6.2 Exact exclusions

No live sources, RSS/search/GDELT/Brave, Graphiti execution, model/embedding calls, vector generation, final full-text/hybrid ranking, entity resolution, relation admission, triage/Candidate flow, Evidence Intake, publication tables, target adapters/credentials, legacy import/dual write, background activation, shadow, canary, production, spending or owner decision on later Draft specifications.

### 6.3 Tests and CI

Required evidence covers ID/trust/time validation; unauthenticated/unauthorised/idempotency/stale-version commands; migration checksum/newer/unversioned failures; SQLite PRAGMAs and rollback; object crash/corruption/prohibited-rights/orphan cases; event compatibility; projector duplicate/retry/gap/dead-letter/generation cases; ontology allow-list; actual Neo4j projection/metadata/wipe/rebuild; credential isolation; negative production configs; restore quarantine/deletion non-resurrection; and the existing unit and clustering-evaluation gates unchanged.

### 6.4 Rollback

The PR carries no production data migration or activation. Rollback is code revert, removal of disposable integration graph/object data, restore of the pre-migration non-production SQLite/object fixture where used, and rerun of the existing suite. No automatic reverse migration is promised for authoritative production data.

### 6.5 Exit evidence

The code PR is complete only when it proves:

1. deterministic fresh authority setup;
2. command authentication, authorisation, idempotency and fencing;
3. complete event causality and integrity;
4. no ledger reference to missing, corrupt or prohibited bytes;
5. no checkpoint advancement past a gap;
6. idempotent duplicate delivery;
7. validated generation activation only;
8. actual Neo4j structural projection through the repository;
9. graph deletion loses no authority and rebuild restores the fixture;
10. no agent/source/model graph-write path or raw mutation API;
11. graph-less/fake production and complete-shadow profiles fail;
12. deletion/tombstone prevents projection resurrection;
13. no source, model, Graphiti, embedding, spending or public action occurred; and
14. every delivered matrix row has reviewable code/test/manifest evidence.

### 6.6 Later dependencies

Later work still requires approved source definitions and rights before source access; an Evaluation Plan before Graphiti/model/embedding execution; exact Neo4j security/licence/resource/backup qualification; accepted entity/relation details; accepted Evidence Intake/publication specifications; Operational Admission before shadow/canary; and explicit production activation.

## 7. Deferred and Needs-experiment register

| Item | Status | Required later evidence |
|---|---|---|
| Production command transport/principal provisioning | Needs experiment | Security design and integration evidence; no unauthenticated fallback. |
| Exact Neo4j Community version/image and read/write capability | Needs experiment | Pin, image provenance, licence/security and compensating-control tests. |
| Neo4j backup procedure | Needs experiment | Offline dump/restore plus authoritative rebuild drill. |
| Numeric SQLite limits and operational thresholds | Deferred | Intended-hardware measurements and Operational Profile. |
| Final discovery, entity, relation, Evidence Intake and publication tables | Deferred | Their later accepted designs and increments. |
| Graphiti/model/prompt/embedding versions | Deferred | Rights, cost and Evaluation Plan approval. |
| Vector/full-text implementation, chunking and hybrid thresholds | Deferred | Increment 5 implementation and pre-registered ablation. |
| Live sources and search providers | Deferred | Source-specific editorial, rights, technical and operational approvals. |
| Shadow/canary/production values | Deferred | Evaluation Plan, Operational Admission and activation decision. |
| Backup encryption, keys, cadence, RPO/RTO | Deferred | Hosting/risk decisions and restore drill. |

## 8. Readiness conclusion

Increment 1 is ready to start after this documentation pull request merges. The accepted architecture now has one authority map, stale POC and ADR-status text is corrected, the consolidated discovery file is navigation-only, the foundation contract and exit evidence are exact, PR #75's useful primitives are separated from its incompatible architecture and P1 findings, and genuinely later decisions remain explicit.

PR #75 should remain open as a donor unless a separate owner decision closes or repurposes it. It must not be merged wholesale or used as the canonical schema base.
