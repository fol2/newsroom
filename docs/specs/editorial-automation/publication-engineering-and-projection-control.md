# Publication engineering and projection control specification

**Status:** Draft
**Owner:** Product owner
**Last updated:** 2026-07-15
**Canonical language:** English
**Related plan:** [`../../plans/2026-07-15-001-integrated-newsroom-architecture.md`](../../plans/2026-07-15-001-integrated-newsroom-architecture.md)
**Related reference:** [`../../research/2026-07-15-database-architecture.md`](../../research/2026-07-15-database-architecture.md), [`../../research/2026-07-15-local-agentic-graph-rag-database-options.md`](../../research/2026-07-15-local-agentic-graph-rag-database-options.md)
**Related decision:** [`../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md) (`Proposed`)
**Supersedes:** None

## Purpose

Define the engineering invariants that keep editorial truth, publication effects and derived retrieval data reconstructable across crashes, retries, partial target failure, correction and projection outage.

## Scope

This specification covers authoritative records, governed-object identity, proposal admission, temporal semantics, projection replay, bounded retrieval, orthogonal publication state, immutable surface payloads, transactional dispatch, target acknowledgements, claim-to-surface traceability, reconciliation and degraded operation.

The proposed terms `Evidence Package`, `Story Version`, `Surface Payload`, `Publication Bundle`, `Publication Decision`, `Relation Proposal`, `Relation Admission Decision`, `Admitted Relation`, `Target Publication`, `Access Policy Reference` and `Semantic UI Projection` have the meanings recorded in [`../../../CONTEXT.md`](../../../CONTEXT.md). PR 75 names are donor aliases only. The target system adopts this canonical vocabulary in its first durable schema; no long-lived compatibility model is required unless the owner separately approves a legacy-data import.

## Requirements

### Authority and derived projections

**ARCH-001 — Scoped authority.** The system MUST distinguish:

- governed content-addressed objects as authority for their exact retained bytes and content hashes, not for the truth of source claims;
- the editorial ledger as authority for identities, observations, proposals, admissions, decisions, versions, publication bundles, target intent and audit sequence;
- the publication controller as the only authority permitted to create public effects; and
- graph, vector, full-text and online serving stores as derived projections or replicas unless a later accepted ADR explicitly changes that boundary.

The durable editorial ledger MUST be distinct from a short-lived discovery or candidate pool.

**ARCH-002 — Persisted proposal admission.** A model-extracted claim, entity resolution or semantic relationship MUST be persisted as an immutable proposal with its exact provenance before a separate immutable admission decision. A rejected proposal MUST remain auditable subject to retention policy. An extractor MUST NOT write directly to the governed admitted-relation projection.

**ARCH-003 — Trust separation.** Proposal exploration and admitted retrieval MUST use distinct, explicit trust scopes. Model confidence MUST NOT be interpreted as admission. An observed source statement or an admitted relationship MUST NOT enter a publication bundle unless the applicable evidence, rights, risk and policy gates independently permit that use.

**ARCH-004 — Temporal semantics.** The system MUST distinguish at least:

- source publication and revision time;
- source retrieval and revision-observation time;
- asserted real-world validity start and end time;
- ledger recording time; and
- relation admission and admission-revocation time.

A query or payload MUST NOT collapse these meanings into one ambiguous `timestamp` or `as_of` value.

**ARCH-005 — Replayable projection.** Every governed projection mutation MUST be reproducible from an ordered authoritative record by a versioned, idempotent projector. Rebuild MUST replay retained extraction output and admission decisions; it MUST NOT rerun a stochastic extractor and treat the new output as historical truth.

**ARCH-006 — Contiguous projection watermark.** Every governed retrieval result MUST identify the contiguous ledger sequence and recording time through which all required events have been applied, together with projector and ontology versions, query-valid time and serving time. A later applied event MUST NOT conceal an earlier gap, dead letter or failed dependency.

**ARCH-007 — Projection retention.** A rights-expiry, privacy-deletion, legal-removal or retention decision MUST define its deletion scope and propagate to every covered graph, vector, full-text, cache and serving derivative. Rebuild logic MUST prevent prohibited data from being resurrected while preserving any audit or tombstone evidence that the decision permits.

**ARCH-008 — Durable object reference.** A committed ledger reference MUST never point to an incomplete or missing governed object, including a source capture, surface payload, asset or retained audit artefact. The system MUST install, synchronise and hash-verify each immutable object before committing its ledger reference. Unreferenced objects MUST remain safely collectable. Integrity checking, backup and restore MUST have documented crash-safe procedures and verification evidence.

**ARCH-009 — One canonical contract from inception.** The first production schema MUST define stable identities, the ordered ledger-event envelope and the records required by publication, online serving and knowledge-graph projection. Those consumers MUST share the same canonical identifiers and event sequence from their first implementation. The programme MUST NOT introduce a temporary publication-only authority model, require a planned `v1`-to-`v2` migration to add graph semantics, or treat an unmerged shadow schema as a production compatibility contract.

**ARCH-010 — Integrated delivery, independent operation.** Publication, serving and governed graph capabilities MUST be implemented and accepted within one target-architecture programme. Dependency order and feature gates MAY control delivery and activation, but MUST NOT create two authority models. Runtime publication correctness MUST remain reconstructable when the graph is unavailable; this degraded-operation property MUST NOT be used to defer the graph identity, event or projector contracts.

### Bounded retrieval

**RETR-001 — Named read-only operations.** An agent MUST retrieve governed graph data through allow-listed, read-only operations with limits on relationship type, depth, fan-out, time range, result count, execution time and trust scope. A general write-capable or unbounded generated-query tool MUST NOT be exposed to Hermes.

**RETR-002 — Provenance-rich result.** A retrieval result MUST return stable candidate identifiers, paths, trust state, temporal context, projection metadata and provenance references. Exact source passages, decisions and immutable payloads MUST be hydrated from authoritative records before publication use.

**RETR-003 — No live relationship publication.** A reader-facing related-story, supersession or correction relationship MUST come from an admitted ledger record bound into the applicable publication bundle. A live graph query MAY suggest a candidate but MUST NOT directly alter a public surface.

### Online serving and semantic projections

**SERV-001 — Canonical serving identity.** Every online article, feed, card or notification record MUST carry stable story and story-version identifiers, its exact surface-payload and publication-bundle digests, visibility and correction state, governed asset references and the applicable `AccessPolicyRef`. The serving platform MUST NOT allocate a competing editorial identity.

**SERV-002 — Versioned access-policy seam.** Free and paid presentation MUST be controlled by a separately versioned access-policy reference. Changing a free-window, free-item or paid-access rule MUST NOT require rewriting story, story-version, evidence-package, surface-payload or publication-bundle identity. This seam does not decide the entitlement authority, subscriber-data model or commercial rule.

**SERV-003 — Native Semantic UI projection.** Reader and Web Admin surfaces MUST expose a versioned, machine-readable Semantic UI Projection keyed by canonical identifiers. It MUST describe relevant content, loading, empty, restricted, correction, error, approval and operational states without requiring an agent to infer them from screenshots. The client and server projections MUST declare their schema and producer versions.

**SERV-004 — Rebuildable serving state.** The online serving store and Semantic UI views MUST be replayable projections of authoritative bundle, decision, target-operation and access-policy records. Rebuilding either projection MUST preserve canonical IDs and payload digests and MUST NOT create a new editorial decision.

### Publication state and immutable payloads

**PUBENG-001 — Orthogonal state.** Editorial decision, story-version disposition, public visibility, correction class and per-target delivery MUST be represented as separate state dimensions. The system MUST NOT overload one status field such that a corrected, superseded, withdrawn or partially delivered story loses its other applicable semantics.

**PUBENG-002 — Atomic authorisation and enqueue.** For an authorising outcome, the immutable story version, evidence-package reference, validation results, decision-free publication bundle, separate publication decision, required audit record and one dispatch command per required target operation and surface payload MUST commit in one authoritative transaction, or none may become dispatchable. A refusing decision MUST commit its audit record but MUST create no dispatch command.

**PUBENG-003 — Immutable surface payload.** Every editorially meaningful target-specific payload MUST be rendered, validated, content-addressed and included in the publication bundle before dispatch. A target adapter MUST NOT generate, summarise, truncate or otherwise rewrite editorial content.

**PUBENG-004 — Claim-to-surface manifest.** Each publication bundle MUST record which approved claim-evidence record from its Evidence Package occurs in each controlled surface payload, including the applicable field or span and materiality. Direct correction impact MUST be determinable from authoritative records without semantic or graph inference.

**PUBENG-005 — Idempotent public action.** Every target operation MUST have a stable semantic identity. Where a target cannot enforce native idempotency, the adapter MUST support correlation lookup or an equivalent reconciliation mechanism. An accepted request followed by a lost response MUST enter an explicit ambiguous-outcome state rather than be blindly retried.

**PUBENG-006 — Dispatch linearisation and cancellation.** A worker MUST recheck current bundle authority, pause state, target policy and supersession when conditionally moving an operation from `PENDING` to `IN_FLIGHT`. A pause, withdrawal, removal or superseding correction committed first MUST prevent stale dispatch. Once an external action is in flight, the system MUST NOT claim that cancellation can prevent every public effect; acknowledgement or ambiguous outcome MUST trigger observation, compensation where possible and reconciliation.

**PUBENG-007 — Truthful publication clocks.** The system MUST record the earliest confirmed or subsequently observed controlled public-effect time separately from target acknowledgement and any feed-order timestamp. Feed ordering policy MUST NOT make the recorded first-publication time later than an earlier controlled public action later established through reconciliation.

### Target state, correction and reconciliation

**OPS-001 — Target capability contract.** Every target adapter MUST declare whether it can create, edit, delete, tombstone, query by idempotency key, list items, observe payloads and issue follow-up corrections. Lifecycle behaviour MUST account for these capabilities rather than assume uniform targets.

**OPS-002 — Durable acknowledgement.** Each target attempt MUST record its immutable command identity, attempt identity, target-native identifier where available, acknowledgement or failure, and relevant target timestamps. It MUST record the observed payload digest when the target supports observation, otherwise an explicit `NOT_OBSERVABLE` capability limitation. Delivery success MUST NOT be inferred from worker completion alone.

**OPS-003 — Desired-state reconciliation.** The system MUST periodically compare intended target state with observed state to the extent declared target capabilities permit and classify at least missing, duplicated, stale-version, wrong-payload, unapplied-correction, orphaned, unexpectedly removed and unauthorised-mutation drift. An unobservable class MUST be recorded as `NOT_OBSERVABLE`, never as absence of drift.

**OPS-004 — Correction completion.** A correction, withdrawal or removal workflow is `COMPLETED` only when every required target has reached its valid corrected desired state. An authorised exception or terminal target limitation MUST produce a distinct `PARTIAL` or `TERMINAL_LIMITATION` outcome and MUST NOT satisfy full completion under `LIFE-055`.

**OPS-005 — Graph-independent containment.** Known affected surfaces MUST be correctable, withdrawable or removable from authoritative target mappings while graph services are unavailable. A graph-dependent search for indirect impact MUST hold or report incomplete when its required projection is stale; it MUST NOT claim that the full impact radius is complete.

**OPS-006 — Degraded action matrix.** The system MUST define which discovery, drafting, publication, correction, withdrawal, reassessment and retrieval actions may proceed for each unavailable or stale dependency. A standalone publication MAY proceed without graph availability only when every applicable relationship and evidence requirement is already satisfied by authoritative records.

## Acceptance criteria

1. A crash at each governed-object installation boundary never leaves an accepted ledger reference to missing or unverified bytes; orphaned objects remain safely collectable.
2. Deleting graph, vector and full-text projections and replaying authoritative records restores structurally identical admitted identities, relations and provenance without rerunning extraction, while golden retrieval metrics remain within predeclared tolerances.
3. A failed projection event followed by a later available event exposes a gap and cannot advance the contiguous watermark past the failure.
4. A high-confidence malicious proposal and a rights-unknown observed source cannot enter a publishable evidence package.
5. An authorised standalone bundle remains publishable during graph outage, while a story requiring unresolved development or supersession checks holds.
6. For an authorising outcome, the decision-free bundle, separate decision, audit record and all required target-operation commands are either committed together or absent together; a refusing decision creates no command.
7. A target that accepts an action and loses the response produces one public item after recovery, not a blind duplicate.
8. A pause or superseding correction committed before `PENDING` becomes `IN_FLIGHT` prevents stale dispatch; if committed after that boundary, any resulting effect is detected and reconciled or compensated according to target capability.
9. Invalidating one claim identifies every directly affected controlled surface from the publication manifest while graph services are offline.
10. Reconciliation detects each observable required drift class and records remediation; unsupported observation is explicitly classified and cannot be presented as clean state.
11. Expiring or deleting a protected object purges every derivative covered by the recorded deletion scope, retains only permitted audit or tombstone evidence, and a clean rebuild does not restore prohibited material.
12. A restored ledger and object store pass integrity and audit verification before projection or publication resumes.
13. A fresh installation creates one canonical schema and can run an end-to-end source-observation, relation-proposal, admission, graph-projection, publication-bundle, target-dispatch and serving-projection flow without applying a temporary-stage migration.
14. Publication and graph projectors consume the same stable identifiers and ordered ledger events; deleting and rebuilding either projection does not rewrite authoritative identities or require adapter-specific remapping.
15. Changing the active free/paid access rule preserves story, story-version, surface-payload and publication-bundle identities while producing the intended restricted or free serving state.
16. Reader and Admin Semantic UI projections expose the same canonical IDs and explicit loading, restriction, correction and error states before and after a clean rebuild.

## Non-goals

This specification does not select SQLite, PostgreSQL, Neo4j, Graphiti, LadybugDB, a cloud provider, a queue implementation or a target SDK. It does not authorise a temporary graph-less authority model, Discord or OpenClaw as target dependencies, or the use of graph retrieval as publication evidence without the existing editorial gates. A plan may sequence implementation dependencies, but it may not reinterpret that sequence as separate target architectures.

## Open questions

- Which public surface defines feed ordering, and which target acknowledgements count as controlled public actions?
- Which targets are required for initial release, and what is the authorised outcome when a target lacks edit or observation capability?
- What projection freshness and gap rules apply to each named retrieval operation?
- What recovery point, recovery time, off-machine backup and restore-drill requirements apply to the ledger and governed-object domains?
- Which retention and deletion classes require cryptographic erasure, physical deletion or projection tombstones?
