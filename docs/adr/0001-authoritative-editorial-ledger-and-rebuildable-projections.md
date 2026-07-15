---
status: proposed
date: 2026-07-15
---

# Authoritative editorial ledger and rebuildable projections

The Newsroom will treat its long-lived editorial ledger as the authority for identities, source observations, governed claim-evidence records, relation proposals and admission decisions, story versions, publication bundles, target intent and audit sequence. A governed content-addressed object store is authoritative for the exact retained bytes and hashes of source captures, publication artefacts, assets and retained audit artefacts, not for the factual truth of a source's claims. These object classes may use distinct security and retention domains. Knowledge graphs, vector indexes, full-text indexes and online serving replicas will be versioned, replayable projections rather than independent editorial or publication truth. Model output, including Graphiti extraction, enters as an immutable persisted proposal; a separate admission decision is recorded in the ledger before an idempotent projector may expose the admitted record in a governed retrieval projection. The publication controller retains action authority for public effects but does not own editorial truth.

This is one target architecture, not a graph-less first architecture followed by a graph-enabled second architecture. The canonical identity model, event envelope, proposal/admission records, publication records and projection contracts are defined together before the first production schema. Publication, serving and knowledge-graph projectors consume that same contract from their first implementation. Their code may be delivered in dependency order, but no temporary authority model or planned `v1`-to-`v2` data migration is part of this decision.

This target boundary keeps publication reconstructable when a graph is stale, unavailable or replaced, avoids relational/graph dual-write authority, and prevents a proof of concept from locking the Newsroom to one graph engine. It is not a description of the current live runner. Projection results must expose a contiguous ledger watermark, projection version and any gap state. Graph-dependent investigations must fail closed when required projection data is stale or incomplete, but a standalone publication may proceed without graph availability when every applicable evidence, relationship, validation, bundle and audit requirement is already satisfied from authoritative records.

Graph independence is a runtime resilience and authority boundary. It must not be interpreted as permission to postpone the knowledge-graph contract or build a disposable publication-only domain model.

## Considered alternatives

- Making the graph authoritative was rejected because probabilistic extraction, trust mixing and graph-engine recovery would enter the publication correctness boundary.
- Writing the ledger and graph synchronously as co-authorities was rejected because partial failure would create irreconcilable truth without a distributed transaction.

## Consequences

- Authoritative transactions must enqueue ordered, idempotent projection work.
- Stable identifiers and the versioned ledger-event contract must exist before publication, serving or graph consumers are implemented.
- Admitted and proposal data must not share a query surface that can silently omit a trust-state filter.
- A graph snapshot may reduce recovery time, but only the ledger and governed content-addressed objects are recovery authority.
- Immutable objects must be installed, synchronised and hash-verified before a ledger transaction commits their references; unreferenced objects remain collectable orphans.
- Projection rebuilds must replay retained extraction outputs and admission decisions rather than rerun stochastic extraction.
- Rights expiry, privacy deletion and retention decisions must record their deletion scope, propagate to covered derivatives and projections, and prevent rebuild from resurrecting prohibited data while retaining permitted audit or tombstone evidence.
- Promoting any projection to authoritative status requires a later accepted ADR.
