# Integrated publication, serving and temporal knowledge architecture

**Status:** Proposed
**Owner:** Product owner
**Last updated:** 2026-07-15
**Canonical language:** English
**Target specs and requirements:** [`publication-engineering-and-projection-control.md`](../specs/editorial-automation/publication-engineering-and-projection-control.md) (`ARCH-001`–`ARCH-010`, `RETR-001`–`RETR-003`, `SERV-001`–`SERV-004`, `PUBENG-001`–`PUBENG-007`, `OPS-001`–`OPS-006`); [`autonomy-and-publication-control.md`](../specs/editorial-automation/autonomy-and-publication-control.md) (`AUTO-020`–`AUTO-025`, `AUTO-040`–`AUTO-041`, `AUTO-060`–`AUTO-064`); [`publication-lifecycle-and-audit.md`](../specs/editorial-automation/publication-lifecycle-and-audit.md) (`LIFE-001`–`LIFE-005`, `LIFE-023`–`LIFE-024`, `LIFE-030`–`LIFE-035`, `LIFE-050`–`LIFE-066`, `AUDIT-001`–`AUDIT-013`)
**Related decisions:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md) (`Proposed`), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md) (`Proposed`)
**Related research:** [`../research/2026-07-15-database-architecture.md`](../research/2026-07-15-database-architecture.md), [`../research/2026-07-15-local-agentic-graph-rag-database-options.md`](../research/2026-07-15-local-agentic-graph-rag-database-options.md)
**Explicitly out of scope:** A temporary graph-less production architecture; a planned publication-v1-to-graph-v2 migration; permanent graph-engine lock-in; generic document chat; a Web reader client; Discord or OpenClaw as target dependencies
**Target branch or release:** One new target-architecture programme based on current `origin/main`; PR [#75](https://github.com/fol2/newsroom/pull/75) is not a merge prerequisite and no implementation is authorised while this plan and its ADRs remain Proposed

## Delivery model — one target architecture

The SQLite ledger and governed object store, publication controller, online serving projection, Neo4j/Graphiti temporal knowledge projection and Hermes retrieval tools will share one canonical identity, temporal, trust and ordered ledger-event contract from the first durable schema.

Work is dependency-ordered because consumers cannot safely precede their contract. It is not divided into a publication-only Stage 1 and a graph-enabled Stage 2. No workstream may introduce an interim canonical model that a later workstream must migrate. Runtime graph independence is a failure-containment property, not a later delivery phase.

```text
                         Hermes commands and ingestion
                                      |
                                      v
                 SQLite ledger + governed object store
             one identity system + one ordered event contract
                                      |
              +-----------------------+-----------------------+
              |                       |                       |
     publication outbox       knowledge projection      operations events
              |                 outbox/checkpoint              |
              v                       v                       v
  target adapters + online     Neo4j + lexical/vector    admin, audit and
  serving + reconciliation     projection + Hermes       Semantic UI views
```

The graph, full-text/vector indexes, online serving store and operational views are separate rebuildable consumers. Their independent failure and replacement do not create a second authority model.

## Current state and corrected interpretation

### Current `main`

Current `main` is the legacy OpenClaw/Discord-oriented runner. It can create a public external effect before final mutable job state is persisted, and posted-event recording is best-effort. It has no long-lived editorial ledger, governed object authority, transactional publication outbox, online app-serving projection, governed graph projector or target reconciliation.

The existing `news_pool.sqlite3` is a bounded discovery pool, not the target editorial ledger. Current `main` is therefore not Stage 1 of this architecture.

### PR 75 is a donor, not Stage 1

PR [#75](https://github.com/fol2/newsroom/pull/75) is an unmerged, credential-free shadow implementation. It contains potentially reusable work:

- canonical JSON and SHA-256 package identity;
- deterministic editorial outcomes and policy checks;
- SQLite transaction, durability and schema-admission patterns;
- append-only audit, authority revision, pause, lease and fencing concepts;
- recording-intent idempotency; and
- zero-public-capability tests.

It does not contain the final publication state model, decision-free multi-surface bundle, claim-to-surface manifest, transactional command set, live acknowledgements, correction reconciliation, online serving projection, governed graph projection, Graphiti admission boundary or Hermes tools. Its schemas also bind shadow-specific concepts that should not become a production compatibility obligation.

PR 75 MUST NOT be merged unchanged merely to establish an intermediate base. Reusable algorithms and tests may be ported or rewritten against the final contract after their residual review findings are resolved. This is a source-code donor mapping, not a runtime `v1`-to-`v2` data migration. The owner may close PR 75 as superseded after deciding which primitives to carry forward.

## Canonical contract fixed before consumers

The first durable schema must define stable, typed identifiers for at least:

- source document, source snapshot, source passage and source observation;
- entity, event or formal process, claim, relation proposal, admission decision and admitted relation;
- story, story version, evidence package, surface payload, publication bundle and publication decision;
- target publication, target operation, attempt and acknowledgement; and
- governed object, ledger event, projection consumer and projector checkpoint.

A content digest identifies immutable bytes; it does not replace a domain identity.

Every authoritative change emits a versioned event envelope containing at least `ledger_seq`, `event_id`, `event_type`, `schema_version`, `aggregate_type`, `aggregate_id`, `recorded_at`, `correlation_id`, `causation_id` and `payload_digest`. Publication, serving, graph and operations consumers use the same envelope and canonical identifiers. Each consumer has its own idempotent queue state and contiguous checkpoint, but history is never synthesised later for a new consumer.

Graphiti may suggest entities and relationships, but it may not allocate authoritative identity or write the governed graph directly. The exact extraction result first becomes an immutable proposal in the ledger. A separate admission decision controls whether the governed projector exposes it.

## Dependency-ordered workstreams

These are concurrent workstreams after the shared contract is approved. They are not release stages.

### WS-A — Canonical contract and authority plane

- Decide ADR 0001 and ADR 0002 together as parts of this target architecture while preserving their different reversibility.
- Define the final identity catalogue, event envelope, temporal fields, trust states, proposal/admission model and orthogonal publication states.
- Implement the local SQLite ledger, governed content-addressed object installation, ordered event/outbox records, integrity checks, off-machine backup and restore proof.
- Define one authoritative transaction boundary for domain mutation, audit event, ordered ledger event and every required consumer/outbox entry.
- Replace PR 75 compatibility migration language with a donor map showing which algorithms and tests are reused, reshaped or rejected.

**Exit evidence:** A fresh database is created directly at the target contract. Model and transaction tests prove stable identities, valid transitions and atomic event fan-out without applying a shadow-v1 migration.

### WS-B — Publication and online serving action plane

- Render and content-address every target-specific `SurfacePayload` before approval, including app/API article representation, feed card and notification payload where applicable.
- Commit the decision-free bundle, separate decision, audit and one command per required target operation in one authoritative transaction.
- Implement idempotent app-serving adapters, target-native acknowledgement, ambiguous-outcome handling, desired-versus-observed reconciliation, and correction, withdrawal and removal propagation.
- Include stable story/version identity, visibility and correction state, asset digests and a versioned `AccessPolicyRef` in the serving contract so free and paid rules can evolve without changing story identity or payload schema.
- Project machine-readable Semantic UI state for reader and admin surfaces from the same canonical identifiers; do not infer it from screenshots.

**Exit evidence:** The same approved bundle converges to the intended online serving state after crash, timeout, lost response and retry. Direct claim impact and target reconciliation remain correct with the graph unavailable.

### WS-C — Governed temporal knowledge projection

- Implement the proposal/admission records and graph projection outbox against the WS-A contract from ledger sequence zero.
- Use Neo4j Community with Graphiti as the initial projection implementation and qualification lane inside this programme, not as a later add-on.
- Isolate any Graphiti extraction workspace from the admitted graph. Only the governed projector credential may expose admitted records.
- Pin ontology, projector, embedding, chunking, normalisation and index versions; expose contiguous checkpoint, gap and dead-letter state.
- Validate `same_event` or `development_of`, source-revision impact and long-running case or policy timeline retrieval on one versioned corpus.
- Replace only the projection adapter before first activation if Neo4j produces a measured licence, backup, footprint or deployment blocker. LadybugDB is a contingency, not a planned second stage.

**Exit evidence:** Delete Neo4j, lexical and vector projections, then rebuild them from retained ledger records and governed objects without rerunning stochastic extraction. Canonical IDs, admitted relations and provenance remain structurally identical.

### WS-D — Hermes retrieval and operational control plane

- Expose versioned, bounded, read-only operations such as `find_related_story_candidates`, `get_event_timeline`, `find_source_revision_impact`, `find_versions_using_claim` and `get_story_provenance`.
- Return canonical IDs, trust scope, exact provenance references, temporal context, projection watermark, projector/ontology version and explicit gap or incompleteness state.
- Keep Hermes unaware of Neo4j internal IDs and deny generic write-capable Cypher. Any Hermes-generated relationship follows the same ledger proposal command as every other extractor.
- Provide Web Admin health, subscription/loading state, manual-approval queues, projection lag, dead letters, target drift and reconciliation views through bounded admin APIs.

**Exit evidence:** Hermes answers the three priority use cases through named tools, and Admin can identify stale or incomplete projection and target state without inspecting raw databases or visual screenshots.

### WS-E — Integrated vertical proof and one activation gate

Prove three end-to-end slices against one fresh target database:

1. source ingest -> immutable observation -> extraction proposal -> admission -> governed graph projection -> Hermes retrieval;
2. approved story version -> evidence and surface manifest -> immutable bundle and publication decision -> outbox -> online serving -> acknowledgement and Semantic UI projection; and
3. source revision -> claim and story impact -> correction decision -> updated graph and serving projections -> target reconciliation.

Publication, serving, graph, Hermes and reconciliation must pass one production-activation gate. Internal pull requests may follow dependency order or deliver thin vertical slices, but there is no intermediate production release whose canonical data later needs conversion.

**Exit evidence:** Every item in the release acceptance section passes on a clean installation and after destructive projection rebuilds.

## PR 75 disposition and reuse gates

PR 75 remains independently reviewable until the owner decides its disposition. Passing CI or being mergeable does not make it production-ready.

| PR 75 area | Treatment in this programme |
|---|---|
| Canonical JSON, content digests and package-integrity tests | Port after resolving identity and digest-cycle findings; bind them to final `EvidencePackage`, `SurfacePayload` and decision-free `PublicationBundle` contracts. |
| SQLite transaction and durability patterns | Reuse selectively behind smaller repositories; do not carry the multi-responsibility `GovernanceStore` forward unchanged. |
| Audit, pause, authority revision, leases and fencing | Preserve the semantics after crash/replay and ownership findings are resolved against the final event/outbox model. |
| Recording intent and recording-only publisher | Use as test inspiration only; replace with the final multi-target command, acknowledgement and reconciliation model. |
| Shadow policy and fixtures | Retain useful deterministic policy cases and zero-public-capability tests; remove shadow target names from production contracts. |
| Legacy adapter | Do not make it the authority intake for the new system. Any approved historical import is a separate, idempotent one-time adapter. |

Before reuse, PR 75 findings #61, #62 and #65 block package and decision primitives; #63, #66 and #67 block outbox/event primitives; #68 blocks reuse of the monolithic store design; #64, #69 and #71 block live authority, storage admission or crash-safe dispatch; #70 blocks a delivery response contract; #72 and #74 block intake or CLI error-contract reuse; and #73 blocks audit-control reuse. All fourteen issues remain open as of 2026-07-15.

## Release acceptance

1. A fresh installation creates the final canonical schema directly; neither a PR 75 database nor a shadow-v1 migration is required.
2. One source fixture completes observation, proposal, admission, Neo4j projection, Hermes retrieval, publication bundle, online serving and acknowledgement using the same canonical IDs.
3. The same story and version IDs are visible in the ledger, graph, serving payload, Semantic UI projection and target acknowledgement.
4. Crash injection proves each domain mutation, audit record, ledger event and required outbox entry is atomic and replayable.
5. Deleting graph and serving stores and rebuilding from the ledger/object store preserves canonical IDs, payload digests and external contracts.
6. Graph unavailability does not corrupt a valid publication or direct reconciliation; restoration resumes from a contiguous checkpoint without synthetic history.
7. Serving unavailability retains commands and eventually converges without a lost or duplicate publication.
8. Graphiti output remains an immutable proposal and cannot enter the governed graph before a separate admission decision.
9. A source revision finds directly affected claims and controlled surfaces, produces the required correction workflow, and updates graph and serving projections.
10. Free/paid policy references can change without rewriting story, story-version or publication-bundle identity.
11. Hermes and Admin receive explicit projection lag, gap and trust metadata and cannot use a write-capable graph credential.
12. Discord and OpenClaw credentials, message models and identifiers are absent from the new target contracts and activation path.

## Cutover and rollback

The legacy runner may remain frozen as a separate current service only until the integrated target passes its single activation gate. It is not incorporated into the new architecture, and no new component depends on Discord or OpenClaw. Cutover is one controlled switch to the app-serving controller followed by retirement of the legacy path; it is not a migration between two versions of the new data model.

Any historical content import requires an explicit owner decision and a one-time idempotent adapter into the final contract. The new system does not inherit PR 75 records merely because its code is useful.

Rollback of a projector, adapter or serving release preserves ledger sequence, immutable object and bundle identities, target acknowledgements and audit history. Replacing Neo4j or another derived engine means dropping and rebuilding that projection. It must not rewrite canonical records, revive superseded commands or rerun stochastic extraction as historical fact.

## Risks and decisions still required

- ADR 0001 and ADR 0002 remain Proposed and require explicit owner decisions.
- The specifications remain Draft; this plan does not itself authorise production implementation.
- PR 75 has unresolved review findings despite clean mergeability and CI.
- The first app-serving platform and target API capability matrix remain unselected.
- Free-layer rules are undecided; the architecture only fixes a versioned access-policy seam.
- Entitlement verification, privacy scope and any unavoidable subscriber-data handling require a separate accepted decision before implementation.
- Governed-object retention may conflict with rights, privacy or deletion duties and needs an explicit deletion-scope policy.
- SQLite recovery point, recovery time, restore window and capacity triggers require measurable thresholds.
- Neo4j Community licence, backup, security and single-instance limits must pass the commercial-product qualification gate before activation.

## Decisions needed

1. Accept, amend or reject ADR 0001 and ADR 0002 as simultaneous parts of this single target architecture.
2. Decide whether PR 75 should be closed as superseded after its approved donor primitives are listed, or kept open solely as a non-production evidence branch.
3. Select the first online app-serving target and its required create, update, remove, observe and idempotency capabilities.
4. Define the first controlled-public-effect and feed-order clock policy.
5. Set projection freshness, gap and degraded-operation thresholds for every Hermes and Admin operation.
6. Set ledger/object-store recovery targets and the pre-production Neo4j qualification thresholds.

## Completion record

Not started. This Proposed plan defines one target architecture and one activation gate; it does not claim implementation or approval.
