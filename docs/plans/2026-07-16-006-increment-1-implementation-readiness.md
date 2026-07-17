# Increment 1 implementation readiness package

**Status:** Completed  
**Owner:** Product owner  
**Last updated:** 2026-07-17  
**Completed by owner:** 2026-07-16  
**Implementation correction recorded:** 2026-07-17  
**Canonical language:** English  
**Target branch:** `agent/increment-1-readiness-audit`  
**Base:** `main` at `6c6b24dcf3c450fcca562be1c5f277b82ad8171d`  
**Accepted architecture decisions:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md), [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md), [`../adr/0005-native-graphrag-production-deployment.md`](../adr/0005-native-graphrag-production-deployment.md)  
**Accepted specifications:** [`../specs/editorial-automation/discovery-record-semantics.md`](../specs/editorial-automation/discovery-record-semantics.md), [`../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md), [`../specs/editorial-automation/graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md) and their referenced focused Accepted discovery specifications  
**Accepted implementation plan:** [`2026-07-16-005-native-graphrag-production-implementation.md`](2026-07-16-005-native-graphrag-production-implementation.md)  
**Implementation authority:** Documentation-only. This completed audit defines the contract, review boundaries and exit evidence for an Increment 1 implementation epic. It starts no graph service, source access, extraction, embedding, model call, spending, shadow operation, canary, public effect or production activation.  
**PR #75 disposition:** Remains open as a donor. It is not an approved implementation base.

## 1. Outcome and boundary

The owner-authorised post-merge audit found no owner-level architecture conflict. The readiness work is complete and Increment 1 may proceed through the active implementation epic.

The accepted direction is not reopened:

- discovery is **source-portfolio-first, change-driven and natively GraphRAG**;
- the single-host SQLite editorial ledger and governed object store are authoritative;
- graph, vector and full-text stores are rebuildable projections;
- Neo4j Community plus Graphiti is the initial production-target implementation;
- models and extractors propose while deterministic or authorised controllers commit;
- production, canary and complete live-shadow profiles cannot omit GraphRAG; and
- legacy event identity is neither imported nor silently dual-written.

This package closes only the contracts required to begin the native integrated foundation safely. It does not select live sources, models, embeddings, Graphiti prompts, final editorial predicates, retrieval thresholds, publication tables, Evidence Intake transport, shadow scope, canary scope or activation values.

The 2026-07-17 correction records implementation-contract details discovered while applying the completed plan. It does not reopen the accepted architecture. It separates stable semantic command identity from per-attempt authentication and authorisation, records the actual A1/A2a/A2b review boundaries inside Authority Foundation, and makes filesystem-type qualification an explicit deferred item rather than an unsupported promise.

## 2. Repository authority and consistency audit

### 2.1 Authority register

| Class | Records | Increment 1 treatment |
|---|---|---|
| Accepted ADRs | ADR 0001, 0002, 0004 and 0005 | Normative architecture authority. ADR 0003 is Accepted but outside this increment. |
| Accepted specifications | Focused discovery Topics 1–11, governed GraphRAG and native-production GraphRAG | Normative behaviour and safety requirements. |
| Accepted plan | Plan 005 | Accepted sequencing; cannot weaken an ADR or specification. |
| Completed plan | This document | Completed owner-authorised readiness audit and corrected epic boundary. |
| Active implementation | Epic #79 and linked tickets | Implements the accepted records; merge state alone creates no activation authority. |
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

### 2.3 Findings resolved by the readiness and corrective reviews

| Finding in audited base or first implementation draft | Risk | Resolution |
|---|---|---|
| Accepted governed GraphRAG text retained POC wording. | Optional experiment or later graduation could be implemented. | `GRAG-050`, scope, acceptance and completion text use the production-target repair-or-replace contract. |
| Plan 005 called ADR 0004 Proposed. | Accepted discovery direction could be treated as unresolved. | ADR 0004 is marked Accepted. |
| `news-discovery.md` duplicated focused requirements. | Drift and wrong-source implementation. | It is navigation and canonical-source mapping only. |
| Command text exposed caller principal/scope authority. | Caller-controlled privilege escalation. | Identity and effective permissions derive from verified authentication and server-side authorisation; caller claims have no authority. |
| Idempotency covered only key plus payload, then an early correction mixed in transient authz attempt state. | Results could replay across different commands, while policy or credential rollout could strand a committed result. | Use a server-derived namespace and stable semantic request digest; recheck current authn/authz on every retry and preserve original commit provenance. |
| Payload schema was only a label. | Canonicalisation could change silently under the same identity. | Versioned schema contracts have explicit immutable identity, canonicalizer implementation version and golden vectors. |
| One proposed code PR contained the whole increment. | Unreviewable implementation change. | Increment 1 remains one epic; Authority Foundation is reviewed as A1, A2a and A2b before Native Graph Foundation begins. |
| PR #75 trusts candidate rights gates and can revisit unfinished publication intents. | Prohibited use or duplicate public effects. | Those paths are rejected; independent rights admission and ambiguous-intent reconciliation remain invariants. |
| Neo4j Community has narrower privilege and online-backup capabilities than Enterprise. | Unsupported RBAC or backup promises. | Require process/network/API controls, exact-version evidence and offline dump/rebuild; failure blocks activation or requires replacement. |

The audit therefore selects outcome A: a documentation-only implementation-readiness record. No owner-level architecture decision packet is required.

## 3. Requirement-to-implementation traceability

`A`, `B` and `C` are dependency-ordered implementation boundaries inside one Increment 1 epic. `A1`, `A2a` and `A2b` are smaller review/merge units inside `A`. None is a product stage. No intermediate merge creates an activatable graph-less production, canary or complete-shadow profile.

| Requirement | Canonical source | Planned component | Invariant/evidence | Boundary | Dependency/status |
|---|---|---|---|---|---|
| ADR 0001; `GRAG-002`–`005` | ADR 0001; governed GraphRAG | Authority, objects, events | Ledger/objects remain authority; no synchronous Neo4j co-authority | A1/A2a/A2b, then B/C proof | Ready |
| ADR 0002 | ADR 0002 | SQLite writer, migrations, CAS | One writer, local supported profile, verified object before ledger reference | A2a/A2b | Numeric and filesystem-type qualification Deferred |
| ADR 0004 | ADR 0004 | Shared IDs/events and no-legacy boundary | No query-first or legacy mutable identity assumption | A1/A2a | Live source runtime later |
| ADR 0005; `GRPROD-001`–`005` | ADR 0005; native deployment spec | Graph-required configuration | GraphRAG cannot be missing, disabled, fake or no-op in qualifying profiles | B/C | Exact versions Need experiment |
| `DREC-001`–`007` | Discovery record semantics | Typed IDs and versions | Locator/digest separate from domain identity; no reuse; immutable versions | A1/A2a | Ready |
| `DREC-016`, `DREC-070`–`077` | Discovery record semantics | Rights admission, CAS, events, lineage and time | Rights-limited identity, exact upstream references, explicit time/provenance | A1/A2a/A2b | Final rights register Deferred |
| `GRAG-010`–`016` | Governed GraphRAG | Trust and ontology seams | Closed trust states; confidence is not admission; structural/editorial relations differ | A1/B | Full entity/relation behaviour Deferred |
| `GRAG-020`–`023` | Governed GraphRAG | Extraction/admission boundaries | Graphiti proposal workspace cannot mutate governed authority | B interface only | Execution Deferred |
| `GRAG-024`–`028` | Governed GraphRAG | Projector state and rebuild | Idempotent ordered consumption; no gap skipping or stochastic historical rewrite | B/C; deletion evidence begins A2b | Actual Neo4j CI |
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

The caller submits a semantic command, an idempotency key and transport credentials or an equivalent authentication proof. It does **not** authoritatively submit `principal_id`, roles, scopes, event semantics, trust, security, retention or payload authority.

A trusted authenticator converts the transport proof into a verified authentication context containing at least:

```text
authentication_context_id, principal_id, authority_domain,
authentication_method, assurance_class, credential_binding_digest,
authenticated_at, expires_at
```

The context is valid only while `authenticated_at <= now < expires_at`. Raw credentials are never included in canonical audit values and public proof types redact them from representations.

A versioned server-side command definition and payload-schema contract derive the aggregate, event, payload, trust, security, retention and required-scope semantics. A server-side authoriser evaluates the exact derived request and produces:

```text
authorization_decision_id, authorization_request_digest,
authorization_policy_version, effective_scopes, effective_scope_digest,
decision, reason_code, decided_at
```

Only an allowing decision may reach the writer. The request-bound capability includes canonical digests of the complete authentication context, exact authorization request, authorization decision and resolved payload. Persistence independently recomputes operation, required scope, namespace, stable semantic digest and closed payload invariants before accepting the capability.

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

The stable semantic request digest covers the command itself rather than a particular authentication attempt:

```text
command type;
exact command-definition version and digest;
exact payload-schema contract version, digest and canonicalizer implementation version;
server-derived aggregate type and typed aggregate ID;
expected aggregate version;
closed resolved payload mode, canonical bytes or admission identity, and payload digest.
```

It deliberately excludes ephemeral authentication-context IDs, credential rotation, authorization-policy rollout, unrelated effective-scope changes, and non-semantic correlation/causation metadata. Those values remain in the request and original commit provenance where applicable, but do not make an already committed business command a different command.

Every request and retry performs current authentication and authorisation. A caller who is still authorised may receive the exact original committed result. A caller who is no longer authorised is denied. The original commit provenance remains immutable. Reusing the durable idempotency identity for a genuinely different command is an explicit conflict.

Historical command definitions and payload-schema contracts remain resolvable for the idempotency/result-retention horizon. Composition fails closed if a retained definition loses its exact schema contract.

Create commands require expected aggregate version `0`; updates require the exact current positive version.

### 4.5 Consumer-neutral ordered events

Each authoritative domain change appends one event in the same SQLite transaction as its mutation and audit record. No authoritative per-consumer outbox is created.

The envelope contains non-sensitive routing metadata sufficient for an independent projector:

```text
ledger_seq, event_id, event_type, event_schema_version,
aggregate_type, aggregate_id, aggregate_version, recorded_at,
command_id, principal_id, authentication_context_id,
authorization_request_digest, authorization_decision_id,
producer_version, command_definition_version, command_definition_digest,
correlation_id, causation_kind, causation_identifier,
payload_id, payload_mode, payload_schema_version,
payload_schema_contract_digest, payload_digest,
object_admission_id nullable, security_scope, retention_scope, trust_scope
```

Sensitive payload bytes are separately authorised. Unknown required event versions create a visible projector gap. Replay never fabricates sequence numbers or recording times. Neo4j is never part of the authoritative transaction.

### 4.6 SQLite, migrations and governed objects

The supported authority profile is one SQLite file on one host, one accepted writer and a local filesystem profile with the required locking and durability behaviour. The implementation immediately enforces checks it can prove reliably: no symlink roots, writer ownership and restrictive modes, a lifetime single-writer lock, foreign keys, WAL, `synchronous=FULL`, bounded busy timeout, bounded write duration and explicit checkpoint policy.

Multi-host direct SQLite access is unsupported. Reliable filesystem-type qualification for NFS, SMB and cloud-synchronised folders is **Deferred** pending platform-specific evidence; the implementation must not claim universal detection that it cannot prove. Production qualification must still fail closed when the actual hosting profile or required locking/durability evidence is unresolved.

Migrations are forward-only, exclusive, atomic and checksummed. Startup fails on a changed checksum, newer database version, non-empty unversioned database, schema fingerprint drift, missing expected constraints or integrity-check failure. Rollback after an incompatible migration uses a verified pre-migration recovery point rather than unreviewed reverse SQL.

Governed blob identity is separate from governed use admission. Installation writes bounded bytes to a same-filesystem staging file, applies global and object-class limits, verifies size and digest, durably flushes, atomically installs read-only bytes, re-verifies through the pinned file descriptor and only then permits an authoritative admission or ledger reference.

A governed admission identifies the blob, object class, allowed use, rights decision and policy, security scope, retention scope and validity. Candidate, model or extractor output cannot grant permitted use. `PROHIBITED`, expired, conflicting or unsupported use is a hard admission failure. Admission, revocation and deletion/tombstone changes have ordered event semantics. Deletion propagates to projections and prevents rebuild resurrection while retaining only permitted audit identity.

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

The epic is **Increment 1 — Native Integrated Foundation**. Its boundaries are review and merge units, not independently activatable product stages.

### A. Authority foundation

Authority Foundation completes only after all three dependency-ordered units merge:

#### A1 — Command, authentication and authorisation contract

- typed IDs, trust and time values;
- caller-minimal semantic command;
- versioned server-side command definitions;
- immutable payload-schema contract identity and golden canonicalisation vectors;
- verified authentication, exact authorisation request/decision binding and opaque commit capabilities;
- stable semantic idempotency plus current authn/authz recheck;
- expected-version contract and no-legacy boundary.

#### A2a — SQLite event authority

- atomic checked schema and migrations;
- immutable command-definition, schema-contract, authn/authz, payload, command, audit, aggregate-version and event records;
- inline and explicit no-payload authority;
- ordered consumer-neutral event envelope and exact provenance;
- causation, result replay, writer locking, schema fingerprint and authenticated bounded metadata reads.

A2a does not claim filesystem CAS, rights admission, deletion or `GRAG-028` completion.

#### A2b — Governed rights, object admission and CAS lifecycle

- immutable blob identity separated from use admission;
- server-side rights decisions and exact allowed-use admission;
- bounded streaming CAS, read-only installed bytes and pinned-FD verification;
- authenticated purpose-bounded hydration;
- transaction-time validity checks;
- admission, revocation and deletion/tombstone events;
- authoritative GC, recovery pins, reconciliation and fault-injection evidence.

**Authority Foundation exit evidence:** authentication spoofing, caller authority rejection, capability derivation attacks, schema-contract drift, idempotent replay, current denial, stale versions, atomic migrations, schema tamper, event causality, object corruption/prohibited-rights/deletion cases and complete repository gates all pass. All A1/A2a/A2b reviews are clean before issue #80 closes.

**Rollback:** No production migration or activation. Revert the affected review unit and remove disposable test authority/object data; a test migration restores its verified pre-migration fixture.

### B. Native graph foundation

**Dependency:** Authority Foundation merged and issue #80 closed.

**Deliverables**

- ontology v1 and ledger-to-projection mappings;
- checkpoint, retry, gap, dead-letter and generation records through the single writer;
- graph/vector/full-text projector interfaces;
- narrow Neo4j repository and credential boundary;
- versioned development/integration deployment configuration;
- production/evaluation validation requiring GraphRAG;
- actual Neo4j Community CI; and
- deterministic structural wipe/rebuild proof.

**Tests and exit evidence:** duplicate delivery, required gaps, retry/dead-letter behaviour, validated generation activation, structural mapping allow-list, actual-service projection, credential isolation, graph wipe/rebuild and rejection of missing/fake/disabled graph profiles all pass.

**Rollback:** Revert code, remove the disposable graph and rebuild no authority. SQLite/object authority remains intact.

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

**Tests and exit evidence:** the fixture traverses authority to governed structural projection, trust-labelled context and deterministic Candidate admission. There is no graph-free passing variant. Wipe/rebuild restores the projection without changing authority, and deletion prevents resurrection.

**Rollback:** Revert the fixture/proof code and remove disposable graph/index data. No source, model, publication or production state exists.

### Epic-wide exclusions

No live source access, RSS/search/GDELT/Brave execution, Graphiti execution, model or embedding calls, vector generation from protected content, final full-text/hybrid ranking, full entity resolution, editorial relation admission, complete triage workflow, Evidence Intake, publication tables, target credentials, legacy import/dual write, background activation, shadow, canary, production, spending or public effect.

## 7. Deferred and Needs-experiment register

| Item | Status | Required later evidence |
|---|---|---|
| Production command transport and principal provisioning | Needs experiment | Security design and integration evidence; no unauthenticated fallback. |
| Production authentication method and credential lifecycle | Needs experiment | Rotation, revocation, expiry and incident evidence. |
| Filesystem-type qualification for NFS/SMB/cloud-sync | Deferred | Platform-specific locking/durability tests; unresolved evidence blocks admission. |
| Exact Neo4j Community version/image and read/write capability | Needs experiment | Pin, image provenance, licence/security and compensating-control tests. |
| Neo4j backup procedure | Needs experiment | Offline dump/load plus authoritative rebuild drill. |
| Numeric SQLite/CAS limits and operational thresholds | Deferred | Intended-hardware measurements and Operational Profile. |
| Read-access audit retention policy | Deferred | Security/privacy decision and bounded audit implementation. |
| Final discovery, entity, relation, Evidence Intake and publication tables | Deferred | Later accepted designs and increments. |
| Graphiti/model/prompt/embedding versions | Deferred | Rights, cost and Evaluation Plan approval. |
| Full vector/full-text implementation, chunking and hybrid thresholds | Deferred | Later implementation and pre-registered ablation. |
| Live sources and search providers | Deferred | Source-specific editorial, rights, technical and operational approvals. |
| Shadow/canary/production values | Deferred | Evaluation Plan, Operational Admission and activation decision. |
| Backup encryption, keys, cadence, RPO/RTO | Deferred | Hosting/risk decisions and restore drill. |

## 8. Completion and correction record

The product owner completed this readiness audit on 2026-07-16 after reviewing PR #78. The 2026-07-17 corrective implementation review clarified, without reopening the accepted architecture, that:

1. principal identity and permissions are server-derived from verified authentication and authorisation, never caller-controlled;
2. audit and events retain resolvable authentication and authorisation provenance;
3. idempotency uses a server-derived namespace plus stable semantic command identity, while every retry performs current authentication and authorisation and preserves original commit provenance;
4. payload-schema contracts have explicit immutable identity and retained historical versions for the replay horizon;
5. UUIDv4 supplies identity only, while `ledger_seq` and explicit time fields supply order;
6. Authority Foundation uses A1, A2a and A2b review boundaries; these are not product stages and create no graph-less qualifying profile;
7. filesystem checks enforce what the implementation can prove now, while filesystem-type qualification remains Deferred;
8. canonical discovery wording is source-portfolio-first, change-driven and natively GraphRAG; and
9. PR #75 remains an open donor and is neither merged nor cherry-picked wholesale.

A separate Active GitHub epic owns implementation progress. Issue #81 remains blocked until A1, A2a and A2b have merged and issue #80 is closed. PR #75 remains open unless a later owner decision closes or repurposes it.
