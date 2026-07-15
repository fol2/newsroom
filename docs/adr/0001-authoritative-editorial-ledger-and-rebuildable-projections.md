---
status: proposed
date: 2026-07-15
---

# Authoritative editorial ledger and rebuildable projections

The Newsroom will treat its long-lived editorial ledger as the authority for the Newsroom's system record of identities, source observations, proposals, admission decisions, story versions, publication bundles, target operations, attempts, received target responses, independently controlled target observations, reconciliation findings, remediation decisions and audit sequence. A governed content-addressed object store is authoritative for the exact retained bytes and hashes of source captures, publication artefacts, assets and retained audit artefacts, not for the factual truth of a source's claims. These object classes may use distinct security and retention domains. Knowledge graphs, vector indexes, full-text indexes and online serving replicas will be versioned, replayable projections rather than independent editorial or publication truth.

A Discovery Signal, News Lead or Story Candidate is not an authoritative Source Observation or publication evidence. The bounded discovery pool may retain operational lineage under its own approved retention rules, but evidence acquisition must independently create the governed Source Observations and exact retained objects on which proposals, claims and Evidence Packages depend.

Authority for the Newsroom's record does not make an admitted claim objectively true and does not override a target's actual external state. Target responses and observations remain untrusted evidence until validated, correlated and recorded. Model output, including Graphiti extraction, enters as immutable entity, claim or relation proposals. Entity mentions must be resolved before dependent claims or relations may be admitted. A separate admission decision is recorded before an idempotent projector may expose a deterministic Governed Claim or Governed Relation view.

The deterministic publication controller is the sole executor of committed public-effect commands but does not own editorial truth. Credential-bearing target adapters are internal to that trust boundary, accept only committed target-operation identities and use least-privilege credentials scoped by target, environment and permitted operation. Generative agents, Hermes and clients cannot reach those credentials.

This is one target architecture, not a graph-less first architecture followed by a graph-enabled second architecture. The canonical identity model, event envelope, proposal and admission records, publication records and projection contracts are defined together in canonical production schema v1. Publication, online-serving, governed-knowledge and Hermes or operations consumers use that contract from their first implementation. Their code may be delivered in dependency order, and normal governed schema evolution remains permitted, but no temporary authority model or planned semantic `v1`-to-`v2` migration is part of this decision. A later authorised consumer must replay retained events or start from a versioned Authoritative Projection Baseline.

This target boundary keeps publication reconstructable when a graph is stale, unavailable or replaced, avoids relational/graph dual-write authority, and prevents a proof of concept from locking the Newsroom to one graph engine. It is not a description of the current live runner. Projection results must expose a contiguous ledger watermark, projection version and any gap state. Graph-dependent investigations must fail closed when required projection data is stale or incomplete, but a standalone publication may proceed without graph availability when every applicable evidence, relationship, validation, bundle and audit requirement is already satisfied from authoritative records.

Graph independence is a runtime resilience and authority boundary. It must not be interpreted as permission to postpone the knowledge-graph contract or build a disposable publication-only domain model. A publication decision may proceed during graph outage only when a recorded dependency-coverage check proves the applicable relationship and source-revision requirements complete at its authoritative cutoff.

## Considered alternatives

- Making the graph authoritative was rejected because probabilistic extraction, trust mixing and graph-engine recovery would enter the publication correctness boundary.
- Writing the ledger and graph synchronously as co-authorities was rejected because partial failure would create irreconcilable truth without a distributed transaction.

## Consequences

- An authoritative transaction records each consumer-neutral ledger event once and atomically creates only the target operations required for committed public side effects; it does not create one authoritative outbox row per read-model consumer.
- Each projector owns its checkpoint, retry and failure or dead-letter state. A checkpoint cannot pass a gap.
- Stable identifiers and the versioned ledger-event contract must exist before publication, serving or graph consumers are implemented.
- Admitted and proposal data must not share a query surface that can silently omit a trust-state filter.
- A graph snapshot may reduce recovery time, but only the ledger and governed content-addressed objects are recovery authority.
- A later consumer may use only retained events or a content-addressed, ledger-attested Authoritative Projection Baseline that declares its cutoff, scope, schema, manifest and digest.
- Immutable objects must be atomically installed on a supported local filesystem, durably flushed and hash-verified before a ledger transaction commits their references; unreferenced objects remain collectable orphans. Off-machine replication is a separate backup operation.
- Projection rebuilds under the same contract must replay retained extraction outputs and admission decisions rather than rerun stochastic extraction. Deliberate re-extraction creates new proposals and never rewrites historical output.
- Rights expiry, privacy deletion and retention decisions must record their deletion scope, propagate to covered derivatives and projections, and prevent rebuild from resurrecting prohibited data while retaining permitted audit or tombstone evidence.
- The shared event envelope contains non-sensitive routing metadata. Protected event payloads and governed objects remain encrypted and authorised by consumer principal, trust scope and object class.
- Promoting any projection to authoritative status requires a later accepted ADR.
