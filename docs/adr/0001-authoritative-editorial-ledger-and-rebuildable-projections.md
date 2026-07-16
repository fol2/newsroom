---
status: accepted
date: 2026-07-15
last_updated: 2026-07-16
accepted_by_owner: 2026-07-16
---

# Authoritative editorial ledger and rebuildable projections

## Decision

The Newsroom will treat its long-lived relational editorial ledger as the authority for the Newsroom's system record of identities, source observations, proposals, admission decisions, story versions, publication bundles, target operations, attempts, received target responses, independently controlled target observations, reconciliation findings, remediation decisions and audit sequence.

A governed content-addressed object store is authoritative for the exact retained permitted bytes and hashes of source captures, publication artefacts, assets and retained audit artefacts. It is not authority for the factual truth of a source's claims.

Knowledge graphs, vector indexes, full-text indexes, online-serving replicas and operational views are versioned, replayable projections. They are not independent editorial, evidence or publication authorities.

## Discovery and evidence boundary

A Discovery Signal, News Lead, Event Hypothesis or Story Candidate is not an authoritative Source Observation or publication evidence. Discovery may retain operational lineage under approved rights and retention rules, but Evidence Intake must independently create the governed Source Observations, source objects, claims and Evidence Packages on which later drafting and publication depend.

## Proposal and admission boundary

Authority for the Newsroom's record does not make an admitted claim objectively true and does not override a target's actual external state.

Model output, including Graphiti extraction, enters as immutable entity, claim or relation proposals. Entity mentions must be resolved before dependent claims or relations may be admitted where identity uncertainty could change their meaning. A separate admission decision is recorded before an idempotent projector may expose a Governed Claim, Governed Relation or equivalent admitted view.

Proposed and admitted records must not share a query surface whose safety depends on every caller remembering an optional trust-state filter.

## Public-effect boundary

The deterministic publication controller is the sole executor of committed public-effect commands, but it does not own editorial truth. Credential-bearing target adapters are internal to that trust boundary, accept only committed target-operation identities and use least-privilege credentials scoped by target, environment and permitted operation. Generative agents, Hermes and clients cannot reach those credentials.

## One target architecture from schema v1

This is one target architecture, not a graph-less first architecture followed by a graph-enabled second architecture.

The canonical identity model, temporal fields, trust states, ordered event envelope, proposal and admission records, publication records and projection contracts are defined together in canonical production schema v1. Discovery, evidence, publication, online-serving, governed-knowledge and Hermes or operations consumers use that contract from their first implementation.

Code may be delivered in dependency order and the schema may evolve through governed migrations, but no temporary authority model or planned semantic `v1`-to-`v2` migration is part of this decision. A later authorised consumer must replay retained events or start from a versioned Authoritative Projection Baseline.

Graph independence is a runtime resilience and authority boundary. It is not permission to postpone the knowledge-graph contract or build a disposable graph-less domain model.

## Projection and recovery contract

- An authoritative transaction records each consumer-neutral ledger event once and atomically creates only target operations required for committed public effects.
- The ledger does not create one authoritative outbox row per read-model consumer.
- Each projector owns its checkpoint, retry state, failure or dead-letter state, projector version and projection generation.
- A checkpoint cannot pass an unresolved required event and still claim a contiguous projection.
- Projection responses expose a contiguous ledger watermark, projection and ontology versions, generation, trust scope and gap state.
- Graph-dependent work fails closed or uses an explicitly approved exact fallback when required projection data is stale, incomplete or unavailable.
- A graph snapshot may reduce recovery time, but the ledger and governed objects remain recovery authority.
- Projection rebuild under the same contract replays retained extraction outputs and admission decisions rather than rerunning stochastic extraction as historical truth.
- Deliberate re-extraction creates new proposals and never rewrites historical output.
- Rights expiry, privacy deletion and retention decisions record their scope, propagate to covered derivatives and prevent rebuild from resurrecting prohibited data while retaining permitted audit or tombstone evidence.
- Protected payloads and governed objects remain encrypted and authorised by consumer principal, trust scope and object class; the shared event envelope contains only non-sensitive routing metadata.

## Considered alternatives

### Make the graph authoritative

Rejected because probabilistic extraction, trust mixing and graph-engine recovery would enter the publication-correctness boundary.

### Write the ledger and graph synchronously as co-authorities

Rejected because partial failure would create irreconcilable truth without a distributed transaction and would make graph-engine replacement a migration of authority.

### Build a graph-less production model and add GraphRAG later

Rejected because it would force a planned semantic migration in identities, ontology, event history, retrieval and source-revision impact.

## Consequences

- Stable identifiers and the ordered ledger-event contract must exist before dependent discovery, publication, serving or graph consumers are implemented.
- Graph, vector and full-text projection work belongs to the initial delivery programme.
- Publication and direct deterministic reconciliation can remain reconstructable during graph outage when an accepted dependency-coverage check proves the required relationship and source-revision work complete at the authoritative cutoff.
- Promoting any projection to authoritative status requires a later accepted ADR.

## Completion record

The product owner accepted this ADR on 2026-07-16 together with the governed GraphRAG boundary and ADR 0002. Acceptance establishes the authority-versus-projection architecture. It authorises no implementation, source access, model call, graph-engine installation, spending, shadow run, canary or production activation.