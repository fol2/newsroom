# Increment 1 implementation readiness package

**Status:** Completed  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Completed by owner:** 2026-07-16  
**Canonical language:** English  
**Target branch:** `agent/increment-1-readiness-audit`  
**Base:** `main` at `6c6b24dcf3c450fcca562be1c5f277b82ad8171d`  
**Accepted architecture decisions:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md), [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md), [`../adr/0005-native-graphrag-production-deployment.md`](../adr/0005-native-graphrag-production-deployment.md)  
**Accepted specifications:** [`../specs/editorial-automation/discovery-record-semantics.md`](../specs/editorial-automation/discovery-record-semantics.md), [`../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md), [`../specs/editorial-automation/graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md) and their referenced focused Accepted discovery specifications  
**Accepted implementation plan:** [`2026-07-16-005-native-graphrag-production-implementation.md`](2026-07-16-005-native-graphrag-production-implementation.md)  
**Implementation authority:** Documentation-only. This completed audit defines the contract, review boundaries and exit evidence for an Increment 1 implementation epic. It starts no graph service, source access, extraction, embedding, model call, spending, shadow operation, canary, public effect or production activation.  
**PR #75 disposition:** Remains open as a donor. It is not an approved implementation base.

## 1. Outcome and boundary

The owner-authorised post-merge audit found no owner-level architecture conflict. The readiness work is complete and Increment 1 may begin after this documentation pull request merges.

The accepted direction is not reopened:

- discovery is **source-portfolio-first, change-driven and natively GraphRAG**;
- the single-host SQLite editorial ledger and governed object store are authoritative;
- graph, vector and full-text stores are rebuildable projections;
- Neo4j Community plus Graphiti is the initial production-target implementation;
- models and extractors propose while deterministic or authorised controllers commit;
- production, canary and complete live-shadow profiles cannot omit GraphRAG; and
- legacy event identity is neither imported nor silently dual-written.

This package closes only the contracts required to begin the native integrated foundation safely. It does not select live sources, models, embeddings, Graphiti prompts, final editorial predicates, retrieval thresholds, publication tables, Evidence Intake transport, shadow scope, canary scope or activation values.

## 2. Repository authority and consistency audit

### 2.1 Authority register

| Class | Records | Increment 1 treatment |
|---|---|---|
| Accepted ADRs | ADR 0001, 0002, 0004 and 0005 | Normative architecture authority. ADR 0003 is Accepted but outside this increment. |
| Accepted specifications | Focused discovery Topics 1–11, governed GraphRAG and native-production GraphRAG | Normative behaviour and safety requirements. |
| Accepted plan | Plan 005 | Accepted sequencing; cannot weaken an ADR or specification. |
| Completed plan | This document | Completed owner-authorised readiness audit and epic boundary. |
| Proposed | Plan 001 and any individually Proposed record | Non-authoritative where not independently adopted. Earlier GraphRAG deferral is superseded. |
| Draft | Publication, rights, autonomy, lifecycle and other individually Draft specifications | Non-normative evidence. Increment 1 must not freeze their later physical schemas. |
| Superseded | Plans 003 and 004 | Historical only. Graph-less or POC staging cannot control implementation. |
| Consolidated navigation | `news-discovery.md` | Non-normative index only; no duplicate requirement namespace. |
| Research/reference | `docs/research/`, `docs/reference/` | Evidence and context only unless an Accepted record adopts a constraint. |
| Current system | Legacy runner, `ARCHITECTURE.md`, `AGENTS.md`, `PROMPTS.md` | Current Brave/RSS/GDELT/Gemini/Discord behaviour, not target authority. |
| Pull requests | Merged PR #77; open PR #75 | Merge state alone creates no product authority. PR #75 is donor material only. |

### 2.2 Canonical source by decision

| Decision | Canonical source | Supporting source | Do not implement from |
|---|---|---|---|
| Ledger/object authority and rebuildable projections | ADR 0001 | `GRAG-002` to `GRAG-005` | Draft publication restatements or PR #75 tables |
| Single-host SQLite authority boundary | ADR 0002 | Plan 005 Increment 1 | Draft `DBOPS-*` as if Accepted |
| Source-portfolio-first, change-driven and natively GraphRAG discovery | ADR 0004 | Focused Accepted discovery specifications | Proposed plan 001 or a consolidated summary |
| Mandatory native GraphRAG | ADR 0005 | `GRPROD-001` to `GRPROD-005` | Superseded POC language or plan 004 |
| Neo4j Community plus Graphiti target | ADR 0005; `GRPROD-010` | Plan 005 | Research comparisons or POC-graduation semantics |
| Proposal/admission separation | ADR 0001; `GRAG-020` to `GRAG-023` | Focused controller requirements | Candidate/model gate output |
| Canonical IDs, versions and lineage | `DREC-001` to `DREC-007`, `DREC-070` to `DREC-077` | `GRAG-001`, `GRPROD-005` | Legacy IDs, URLs, digests or mutable rows |
| Ordered projection and rebuild | ADR 0001; `GRAG-024` to `GRAG-028` | `GRPROD-020` | Consumer-specific authority outboxes or skipped gaps |
| Increment 1 epic boundary | Plan 005 plus this document | `GRPROD-020` and `GRPROD-021` | PR #75's shadow feature boundary |

### 2.3 Findings resolved by this pull request

| Finding in audited base | Risk | Resolution |
|---|---|---|
| Accepted governed GraphRAG text retained POC wording. | Optional experiment or later graduation could be implemented. | `GRAG-050`, scope, acceptance and completion text now use the production-target repair-or-replace contract. |
| Plan 005 called ADR 0004 Proposed. | Accepted discovery direction could be treated as unresolved. | ADR 0004 is marked Accepted. |
| `news-discovery.md` duplicated focused requirements. | Drift and wrong-source implementation. | It is navigation and canonical-source mapping only. |
| Command text exposed `principal_scopes` in the command envelope. | Caller-controlled privilege escalation. | Identity and effective permissions are now derived from verified authentication and server-side authorisation; caller claims have no authority. |
| Idempotency covered only key plus payload. | A result could be replayed across a different command, aggregate or version. | A server-derived namespace and canonical semantic request digest are required. |
| One proposed code PR contained the whole increment. | Unreviewable implementation change. | Increment 1 is one epic with three stacked dependency-ordered code PRs. |
| PR #75 trusts candidate rights gates and can revisit unfinished publication intents. | Prohibited use or duplicate public effects. | Those paths are rejected; independent rights admission and ambiguous-intent reconciliation remain invariants. |
| Neo4j Community has narrower privilege and online-backup capabilities than Enterprise. | Unsupported RBAC or backup promises. | Require process/network/API controls, exact-version evidence and offline dump/rebuild; failure blocks activation or requires replacement. |

The audit therefore selects outcome A: a documentation-only implementation-readiness pull request. No owner-level decision packet is required.

## 3. Requirement-to-implementation traceability

`A`, `B` and `C` are stacked review/merge boundaries inside one Increment 1 epic. They are not product stages. No intermediate merge creates an activatable graph-less production, canary or complete-shadow profile.

| Requirement | Canonical source | Planned component | Invariant/evidence | Boundary | Dependency/status |
|---|---|---|---|---|---|
| ADR 0001; `GRAG-002`–`005` | ADR 0001; governed GraphRAG | Authority, objects, events | Ledger/objects remain authority; no synchronous Neo4j co-authority | A, then B/C proof | Ready |
| ADR 0002 | ADR 0002 | SQLite writer, migrations, CAS | One writer, local filesystem, verified object before ledger reference | A | Numeric operating limits Deferred |
| ADR 0004 | ADR 0004 | Shared IDs/events and no-legacy boundary | No query-first or legacy mutable identity assumption | A | Live source runtime later |
| ADR 0005; `GRPROD-001`–`005` | ADR 0005; native deployment spec | Graph-required configuration | GraphRAG cannot be missing, disabled, fake or no-op in qualifying profiles | B/C | Exact versions Need experiment |
| `DREC-001`–`007` | Discovery record semantics | Typed IDs and versions | Locator/digest separate from domain identity; no reuse; immutable versions | A | Ready |
| `DREC-016`, `DREC-070`–`077` | Discovery record semantics | CAS, events, lineage and time | Rights-limited identity, exact upstream references, explicit time/provenance | A | Final rights register Deferred |
| `GRAG-010`–`016` | Governed GraphRAG | Trust and ontology seams | Closed trust states; confidence is not admission; structural/editorial relations differ | A/B | Full entity/relation behaviour Deferred |
| `GRAG-020`–`023` | Governed GraphRAG | Extraction/admission boundaries | Graphiti proposal workspace cannot mutate governed authority | B interface only | Execution Deferred |
| `GRAG-024`–`028` | Governed GraphRAG | Projector state and rebuild | Idempotent ordered consumption; no gap skipping or stochastic historical rewrite | B/C | Actual Neo4j CI |
| `GRAG-030`, `GRAG-034`, `GRAG-035` | Governed GraphRAG | Time, graph repository and metadata | Separate time meanings; no agent writes; watermark/version/gap/trust metadata | A/B/C | Ready |
| `GRAG-031`–`033` | Governed GraphRAG | Retrieval interfaces | Hybrid retrieval and authoritative hydration remain mandatory | C seam only | Full implementation later |
| `GRAG-042`–`046` | Governed GraphRAG | Structural projection and degraded states | Lineage projectable; outage is not no-match; no graph-less complete shadow | B/C | Decision flow later |
| `GRAG-050`–`058` | Governed GraphRAG | Target manifest and qualification | Neo4j plus Graphiti is production target, not POC; qualification gates exact version | B | Exact version Needs experiment |
| `GRPROD-010`–`016` | Native deployment spec | Neo4j/config/CI | Engine-neutral domain; versioned deployment; real service in CI | B | Image pin required |
| `GRPROD-020` | Native deployment spec | Entire epic | Authority and native graph contracts enter the first increment together | A/B | This completed audit |
| `GRPROD-021`–`024` | Native deployment spec | Integrated proof | Graph-native fixture proof; no optional-plugin semantics; outage is degradation | C | Depends on A and B |
| `GRPROD-030`–`032` | Native deployment spec | Release metadata seam | Later activation binds exact versions; acceptance starts no runtime | B/C | Activation Deferred |

## 4. Increment 1 technical contracts

### 4.1 Dependency direction

```text
verified authentication
→ server-side authorisation
→ authenticated command service
→ SQLite authority + governed objects
→ consumer-neutral ordered events
→ projectors
→ Neo4j and indexes
```

The authority package cannot import Neo4j or Graphiti. The implementation lives beside the legacy pipeline and performs no silent legacy dual write or legacy identity import.

### 4.2 Canonical IDs, versions, trust and time

Controllers create opaque typed UUID version 4 values conforming to RFC 9562, serialised as lowercase canonical hyphenated strings. UUIDv4 is random and supplies no ordering or causality; order comes from `ledger_seq` and explicit temporal fields. URLs, provider IDs, titles, timestamps, digests and Neo4j internal IDs are never global Newsroom IDs.

Each implemented aggregate has a stable ID, a positive version beginning at 1, immutable version records where required and explicit predecessor or supersession references. SHA-256 digests identify exact bytes or semantic requests, not domain lifecycles.

The closed trust enum is `OBSERVED`, `PROPOSED`, `ADMITTED`. Unknown values fail. Confidence creates no authority. Proposed and admitted query surfaces remain separate.

Temporal values distinguish source publication/revision, Newsroom observation, source-asserted validity, authoritative recording, proposal/admission/invalidation and later publication/acknowledgement. Missing, approximate, date-only and conflicting values remain explicit.

### 4.3 Authentication and authority provenance

The caller submits a semantic command, an idempotency key and transport credentials or an equivalent authentication proof. It does **not** authoritatively submit `principal_id`, roles or scopes.

A trusted authenticator converts the transport proof into a verified authentication context containing at least:

```text
authentication_context_id, principal_id, authority_domain,
authentication_method, assurance_class, credential_binding_digest,
authenticated_at, expires_at
```

A server-side authoriser evaluates that verified context against the allow-listed command type, aggregate target and policy version. It produces:

```text
authorization_decision_id, authorization_policy_version,
effective_scope_digest, decision, reason_code
```

Only an allowing decision may reach the command writer. Caller-provided principal, role or scope claims are ignored or rejected and never copied into effective authority. The committed command result and audit record identify the verified `authentication_context_id`, server-derived `principal_id`, `authorization_decision_id`, `authorization_policy_version` and `effective_scope_digest` used.

Increment 1 provides authenticator and authoriser interfaces plus deterministic test implementations. Production transport and principal provisioning remain `Needs experiment`, but production configuration has no unauthenticated local-writer fallback.

### 4.4 Scoped idempotency and semantic request identity

The service derives an idempotency namespace; the caller cannot choose it. The namespace is at least:

```text
authority_domain + authenticated principal_id + command_type
```

The durable idempotency identity is:

```text
idempotency_namespace + idempotency_key
```

Before execution, the service creates a canonical semantic request digest over at least:

```text
command_type, aggregate_type, aggregate_id, expected_aggregate_version,
payload_schema_version, payload_digest,
authenticated principal_id, authority_domain,
authorization_policy_version, effective_scope_digest
```

Reusing the same durable idempotency identity with the same semantic request digest returns the committed result without another mutation. Reusing it with a different digest is an explicit conflict. A matching payload body cannot replay a result for a different command type, aggregate, expected version or authenticated authority context.

Create commands require expected aggregate version `0`; updates require the exact current positive version. The semantic digest and expected-version check are both evaluated before returning or committing a result.

### 4.5 Consumer-neutral ordered events

Each authoritative domain change appends one event in the same SQLite transaction as its mutation and audit record. No authoritative per-consumer outbox is created.

The envelope contains non-sensitive routing metadata:

```text
ledger_seq, event_id, event_type, event_schema_version,
aggregate_type, aggregate_id, aggregate_version, recorded_at,
command_id, principal_id, authentication_context_id,
authorization_decision_id, correlation_id, causation_id,
producer_version, payload_digest, payload_object_ref,
security_scope, retention_scope
```

Sensitive payload access is separately authorised. Unknown required event versions create a visible projector gap. Replay never fabricates sequence numbers or recording times. Neo4j is never part of the authoritative transaction.

### 4.6 SQLite, migrations and governed objects

The supported authority profile is one SQLite file on one host and a local filesystem with supported locking and durability. NFS, SMB, cloud-synchronised folders and multi-host direct access fail validation. Connections enforce foreign keys, WAL, `synchronous=FULL`, bounded busy timeout, bounded write duration and an explicit checkpoint policy.

Migrations are forward-only, exclusive and checksummed. Startup fails on a changed checksum, newer database version, non-empty unversioned database or missing expected constraints. Rollback after an incompatible migration uses a verified pre-migration recovery point rather than unreviewed reverse SQL.

Governed objects are immutable `sha256:<hex>` values. Installation writes bounded bytes to a same-filesystem temporary file, enforces rights/security/retention scope, verifies size and digest, durably flushes, atomically installs, verifies the installed object and only then commits a ledger reference. A committed reference cannot point to missing, partial, corrupt or prohibited bytes.

`PROHIBITED`, expired, conflicting or unsupported use is a hard admission failure for the covered object class. Candidate, model or extractor output cannot override it. Deletion and tombstone decisions propagate to projections and prevent rebuild resurrection.

### 4.7 Projector state and ontology v1

A projector identity is:

```text
projector_name + projector_version + ontology_version + generation_id
```

It records the last contiguous sequence, next expected sequence, retry state, health, unresolved gaps and dead letters. Retry exhaustion creates a dead letter and unresolved gap, never permission to skip. Generation states are `BUILDING`, `VALIDATING`, `ACTIVE`, `RETIRED`, `FAILED`; only a validated generation may become active.

Ontology v1 is a versioned repository artifact. Increment 1 implements deterministic structural mappings only, including `HAS_VERSION`, `HAS_REVISION`, `HAS_REPRESENTATION`, `PRODUCED_SIGNAL`, `PROMOTED_TO_LEAD`, `DERIVED_FROM`, `CONTAINS_PAYLOAD` and `PROJECTED_FROM_EVENT`. Generic `RELATED_TO`, caller-supplied labels and model predicates are rejected. Editorial relations and entity equivalence remain later reified proposal/admission domains.

### 4.8 Neo4j, configuration and recovery

Neo4j Community is the governed projection target. Future Graphiti execution uses a logically isolated proposal workspace or separate controlled instance and never receives the governed projector credential.

Domain code uses a narrow repository rather than raw driver sessions, unrestricted Cypher or Neo4j internal IDs. Only the projector process receives write capability. Compensating controls include private network exposure, authentication, separate secrets, no general Cypher endpoint, allow-listed procedures/imports, pinned configuration and process/network isolation. Where database-level read separation is unavailable, callers use a Newsroom-owned read-only application API with no mutation method.

Unit tests may use deterministic fakes. Integration uses an actual authenticated Neo4j Community service. Evaluation, production and complete-shadow configuration fails when GraphRAG is missing, disabled, fake, no-op, incompatible or unresolved.

A valid authority recovery point is one SQLite cutoff plus every reachable governed object and a verified manifest. Neo4j recovery uses a verified offline dump/load where supported and deterministic rebuild from authority. Neo4j loss can reduce availability but cannot lose authority. Exact encryption, keys, cadence, RPO/RTO and drill frequency remain later Operational Admission decisions.

## 5. PR #75 donor map

PR #75 remains open and unmerged.

| PR #75 area | Classification | Treatment |
|---|---|---|
| Canonical JSON, duplicate-key rejection, restricted numeric domain and SHA-256 verification | Reuse with adaptation | Move to neutral authority utilities; retain bounded-input tests. |
| Package integrity tests | Reuse with adaptation | Preserve UTF-8, duplicate-key, float, unsafe-integer, non-canonical and digest-mismatch cases. |
| WAL/FULL/foreign-key/busy-timeout/STRICT transaction patterns | Reference/selective reuse | Rewrite around authenticated commands, events and CAS references. |
| Direct `GovernanceStore` mutation surface | Rewrite | Replace with the single authenticated command writer and read-only interfaces. |
| In-database package BLOB store | Reject as governed-object implementation | Use filesystem CAS; only tightly bounded routing payloads may be inline. |
| Audit hash-chain ideas | Reference-only | Defence in depth, not a substitute for canonical events and records. |
| Shadow story/decision/authority/publication tables | Reject as canonical schema | Draft/shadow vocabulary is not Accepted Increment 1 authority. |
| Fence, lease and stale-writer tests | Reuse with adaptation | Apply to command/projector concurrency; never infer absence of an external effect. |
| Candidate-controlled rights gate | Reject | Authoritative prohibited rights cannot be overridden. |
| Unfinished publication-intent replay | Reject | Ambiguous prior intent requires reconciliation or `UNKNOWN` before later adapter entry. |
| Recording-only publication lane | Reject as product stage | At most a later test double; not an approved architecture. |
| Whole branch | Reject for merge/cherry-pick | No wholesale merge or branch cherry-pick. |

## 6. Increment 1 epic and stacked code boundaries

The epic is **Increment 1 — Native Integrated Foundation**. It has three stacked code PRs. Each branch starts from its declared dependency, but the epic begins from the latest `main`. These are review boundaries only.

### A. Authority foundation

**Deliverables**

- typed canonical UUIDv4 IDs, aggregate versions, trust and temporal value types;
- verified authentication and server-side authorisation interfaces;
- committed authentication/authorisation provenance;
- server-derived idempotency namespace and canonical semantic request digest;
- expected-version fencing and deterministic command results;
- fresh SQLite authority schema and checked forward migrations;
- consumer-neutral ordered events;
- governed filesystem CAS and rights-scope seam; and
- explicit no-legacy-dual-write/import boundary.

**Tests and exit evidence**

Authentication spoofing, caller-supplied scope rejection, unauthorised commands, idempotent replay, semantic-digest conflicts, cross-aggregate/key conflicts, stale versions, migration checksums, SQLite profile, object crash/corruption/prohibited-rights cases, event causality and existing repository gates all pass.

**Rollback**

No production migration or activation. Revert code and remove disposable test authority/object data; a test migration restores its verified pre-migration fixture.

### B. Native graph foundation

**Dependency:** A merged.

**Deliverables**

- ontology v1 and ledger-to-projection mappings;
- checkpoint, retry, gap, dead-letter and generation records through the single writer;
- graph/vector/full-text projector interfaces;
- narrow Neo4j repository and credential boundary;
- versioned development/integration deployment configuration;
- production/evaluation validation requiring GraphRAG;
- actual Neo4j Community CI; and
- deterministic structural wipe/rebuild proof.

**Tests and exit evidence**

Duplicate delivery, required gaps, retry/dead-letter behaviour, validated generation activation, structural mapping allow-list, actual-service projection, credential isolation, graph wipe/rebuild and rejection of missing/fake/disabled graph profiles all pass.

**Rollback**

Revert code, remove the disposable graph and rebuild no authority. SQLite/object authority remains intact.

### C. Integrated foundation proof

**Dependency:** A and B merged.

**Deliverables**

- fixture authority command and event;
- graph and index projection;
- trust-labelled retrieval metadata and authoritative-hydration seam;
- minimal deterministic Candidate-admission fixture sufficient to prove the boundary, without implementing full triage;
- graph-loss recovery;
- deletion/tombstone non-resurrection; and
- negative production and complete-shadow profile tests.

**Tests and exit evidence**

The fixture traverses authority to governed structural projection, trust-labelled context and deterministic Candidate admission. There is no graph-free passing variant. Wipe/rebuild restores the projection without changing authority, and deletion prevents resurrection.

**Rollback**

Revert the fixture/proof code and remove disposable graph/index data. No source, model, publication or production state exists.

### Epic-wide exclusions

No live source access, RSS/search/GDELT/Brave execution, Graphiti execution, model or embedding calls, vector generation from protected content, final full-text/hybrid ranking, full entity resolution, editorial relation admission, complete triage workflow, Evidence Intake, publication tables, target credentials, legacy import/dual write, background activation, shadow, canary, production, spending or public effect.

## 7. Deferred and Needs-experiment register

| Item | Status | Required later evidence |
|---|---|---|
| Production command transport and principal provisioning | Needs experiment | Security design and integration evidence; no unauthenticated fallback. |
| Exact Neo4j Community version/image and read/write capability | Needs experiment | Pin, image provenance, licence/security and compensating-control tests. |
| Neo4j backup procedure | Needs experiment | Offline dump/load plus authoritative rebuild drill. |
| Numeric SQLite limits and operational thresholds | Deferred | Intended-hardware measurements and Operational Profile. |
| Final discovery, entity, relation, Evidence Intake and publication tables | Deferred | Later accepted designs and increments. |
| Graphiti/model/prompt/embedding versions | Deferred | Rights, cost and Evaluation Plan approval. |
| Full vector/full-text implementation, chunking and hybrid thresholds | Deferred | Later implementation and pre-registered ablation. |
| Live sources and search providers | Deferred | Source-specific editorial, rights, technical and operational approvals. |
| Shadow/canary/production values | Deferred | Evaluation Plan, Operational Admission and activation decision. |
| Backup encryption, keys, cadence, RPO/RTO | Deferred | Hosting/risk decisions and restore drill. |

## 8. Completion record

The product owner completed this readiness audit on 2026-07-16 after reviewing PR #78 and requiring these final corrections:

1. principal identity and permissions are server-derived from verified authentication and authorisation, never caller-controlled;
2. audit and events retain authentication and authorisation provenance;
3. idempotency uses a server-derived namespace plus a canonical semantic request digest covering command, aggregate, expected version, payload and authenticated authority context;
4. UUIDv4 supplies identity only, while `ledger_seq` and explicit time fields supply order;
5. Increment 1 is one epic with three stacked review boundaries rather than one unreviewable code PR;
6. those boundaries are not product stages and create no graph-less qualifying profile;
7. canonical discovery wording is source-portfolio-first, change-driven and natively GraphRAG; and
8. PR #75 remains an open donor and is neither merged nor cherry-picked wholesale.

Increment 1 may start after this documentation pull request is merged. A separate Active GitHub epic owns implementation progress. PR #75 remains open unless a later owner decision closes or repurposes it.