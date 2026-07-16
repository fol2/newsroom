---
status: proposed
date: 2026-07-16
owner_review: ready
---

# Native GraphRAG in the first production deployment

## Decision status

This ADR is ready for product-owner review. It amends the remaining proof-of-concept interpretation in the accepted GraphRAG architecture and the current Topic 13 Draft.

It authorises no code, engine installation, extraction, embeddings, source access, model call, spending, shadow run, canary or production activation.

## Context

The product owner accepted GraphRAG as part of canonical schema v1, with a relational ledger and governed objects as authority and graph, vector and full-text stores as rebuildable projections.

The current documents nevertheless describe Neo4j Community plus Graphiti as an initial `POC` or proof-of-concept lane. That wording leaves an incorrect two-stage interpretation:

```text
build and qualify a relational product
→ run a GraphRAG POC
→ later decide whether GraphRAG graduates into production
```

That is not the intended architecture.

News discovery depends materially on graph-aware event identity, multilingual entity resolution, long-running policy and case timelines, shared-source dependencies and source-revision impact. Building production without those capabilities would create a second semantic architecture and later migration.

## Proposed decision

GraphRAG is a required native subsystem of the first production deployment.

The production system includes:

- the canonical SQLite editorial ledger;
- governed content-addressed objects;
- an admitted graph projection;
- vector and full-text indexes;
- governed entity and relation proposal or admission records;
- an extraction path such as Graphiti operating outside the governed graph;
- bounded hybrid retrieval; and
- named read-only retrieval tools integrated with discovery and later knowledge consumers.

There is no supported graph-less production, canary or complete live-shadow target.

## Initial production implementation

Neo4j Community plus Graphiti is the initial production-target implementation.

This is not a proof-of-concept stage and does not make GraphRAG optional. The exact versions must still pass licence, security, backup, recovery, resource, performance, rights and quality gates before activation.

If Neo4j or Graphiti fails those gates, the Newsroom replaces the failing implementation before the first production activation. It does not activate a graph-less system and add GraphRAG later.

The engine remains replaceable because canonical identities, trust states, time semantics, ordered events, proposals, admission decisions and named-tool contracts belong to the Newsroom rather than to Neo4j internal IDs or Graphiti private state.

## Native project requirement

The repository owns the GraphRAG implementation and operating contract, including:

- ontology and schema versions;
- ledger-to-projection mapping;
- graph, vector and full-text projectors;
- Graphiti proposal integration;
- entity and relation admission;
- hybrid retrieval and named tools;
- deployment configuration;
- health, lag, gap and dead-letter state;
- backup, purge, destructive rebuild and recovery;
- security and credential separation; and
- integration, replay, ablation and fault-injection tests.

An external notebook, manually configured graph or separate experimental repository does not satisfy this decision.

## Delivery and release consequence

Code may be merged in dependency order, but the first complete vertical product slice includes:

```text
canonical ledger write
→ governed graph and index projection
→ hybrid Retrieval Context
→ deterministic triage and Candidate admission
```

The first implementation milestone contains the graph-aware canonical contract, ontology, projection mapping, deployment boundary and integration-test path beside the relational foundation.

Complete live-shadow qualification and production activation require the admitted GraphRAG stack. Qualification verifies a mandatory production component; it is not a separate optional product stage.

## Degraded operation

Temporary graph outage remains an accepted resilience case:

- safe deterministic collection may continue;
- graph-dependent work is marked unavailable, stale or gapped;
- evaluated exact fallbacks may serve only their approved routes;
- other work enters Watch or Operational Hold; and
- graph recovery reconciles the same mandatory deployment.

This does not create a graph-free product profile.

## Rejected alternatives

### GraphRAG as a POC before an adoption decision

Rejected because it preserves two product stages and permits a complete relational system to become the de facto architecture.

### GraphRAG as an optional production plugin

Rejected because production correctness, event continuity and long-horizon retrieval would vary by deployment profile and invite semantic drift.

### Activate without GraphRAG if the first engine fails qualification

Rejected because engine failure is an implementation blocker or replacement trigger, not permission to remove a required capability.

### Make the graph authoritative because it is mandatory

Rejected. Mandatory deployment does not change the accepted authority boundary. Probabilistic extraction and derived projection remain subordinate to the relational ledger and governed objects.

## Consequences

- GraphRAG code and deployment support are part of the project from the first implementation milestones.
- Production and complete shadow cannot omit graph, vector, full-text or hybrid retrieval.
- Neo4j and Graphiti are implemented toward production and evaluated before activation.
- An alternative engine, if needed, replaces the initial implementation inside the same architecture before activation.
- Graph outages have explicit degraded behaviour but do not make GraphRAG optional.
- The implementation plan must remove `POC`, `proof-of-concept lane` and optional-graduation language.
- Production activation must bind exact GraphRAG versions and operating evidence.

## Owner decision required

Accepting this ADR approves native mandatory GraphRAG in the first production deployment and instructs Topic 13 to implement it as part of the repository-owned product. It still authorises no runtime action.