---
status: accepted
date: 2026-07-16
accepted_by_owner: 2026-07-16
---

# Native GraphRAG in the first production deployment

## Decision

GraphRAG is a required, repository-native subsystem of the Newsroom's first production deployment.

The production architecture includes:

- the canonical relational editorial ledger;
- governed content-addressed objects;
- an admitted graph projection;
- vector and full-text indexes;
- governed entity and relation proposal or admission records;
- an isolated extraction path;
- bounded hybrid retrieval; and
- named read-only retrieval tools integrated with discovery and later knowledge consumers.

There is no supported graph-less production, canary or complete live-shadow target.

This decision supersedes any `POC`, proof-of-concept-lane, optional-plugin or later-adoption interpretation in earlier GraphRAG and implementation documents.

## Requirement supersession

The following parts of [`../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md) are retained for history but no longer govern:

- `GRAG-050` as worded with an `Initial POC baseline`; and
- acceptance criterion 17 stating that POC success does not select the production engine.

They are superseded by this ADR's mandatory native-production decision and by the detailed `GRPROD-*` contract once accepted. The exact engine still requires release qualification, but GraphRAG itself does not require a later adoption or graduation decision.

## Authority boundary

Native production support does not make the graph authoritative.

- The relational ledger remains authoritative for identities, versions, proposals, admission decisions, outcomes and ordered history.
- Governed objects remain authoritative for exact retained permitted bytes and hashes.
- Graph, vector and full-text structures remain rebuildable projections.
- Models and extractors remain proposal producers.
- Deterministic or authorised admission remains required.
- Graph paths, similarity and ranking remain context rather than editorial or publication authority.

## Native project requirement

The repository owns the GraphRAG product and operating contract, including:

- graph-aware identity, trust, temporal and event contracts;
- ontology and projection mappings;
- graph, vector and full-text projectors;
- extraction and proposal integration;
- entity and relation admission;
- hybrid retrieval and named tools;
- production deployment configuration;
- health, lag, gap and dead-letter state;
- backup, purge, destructive rebuild and recovery;
- security and credential separation; and
- integration, replay, ablation and fault-injection tests.

An external notebook, manually configured graph, separate experimental repository, optional build plugin or operator-only script does not satisfy native support.

## Delivery consequence

Code may be merged in dependency order, but dependency order is not product staging.

The first implementation milestones define the graph-aware canonical contract, ontology, projection mapping, deployment boundary and integration-test path beside the relational foundation.

The first complete vertical product slice includes:

```text
canonical ledger write
→ governed graph and index projection
→ hybrid Retrieval Context
→ deterministic triage and Candidate admission
```

A ledger-only or adapter-only test may occur earlier internally, but it is not a complete product slice and cannot qualify the target architecture.

## Qualification consequence

Qualification verifies whether an exact mandatory GraphRAG implementation is safe, lawful, reliable and useful enough to activate. It does not decide whether GraphRAG exists.

If an engine, extractor or deployment mechanism fails release gates, the implementation must be repaired or replaced before production activation. The Newsroom must not respond by activating a graph-less system and adding GraphRAG later.

The exact initial graph engine, extraction framework and versions remain implementation decisions until separately accepted. Any replacement remains inside the same production architecture and must preserve the canonical contracts.

## Degraded operation

Temporary graph outage is an accepted resilience case inside the mandatory GraphRAG deployment:

- safe deterministic collection may continue where its own dependencies are healthy;
- graph-dependent work is explicitly unavailable, stale or gapped;
- evaluated exact fallbacks may serve only their approved routes;
- other work enters Watch or Operational Hold; and
- recovery reconciles the same mandatory graph deployment.

This does not create a supported graph-free product profile.

## Rejected alternatives

### GraphRAG as a proof of concept before adoption

Rejected because it preserves two product stages and permits a complete relational system to become the de facto architecture.

### GraphRAG as an optional production plugin

Rejected because event continuity, source dependencies and long-horizon retrieval would vary by deployment profile and create semantic drift.

### Graph-less activation after an engine fails qualification

Rejected because implementation failure is a blocker or replacement trigger, not permission to remove a required capability.

### Make the graph authoritative because it is mandatory

Rejected because probabilistic extraction, trust mixing and projection recovery must not enter the authority boundary.

## Consequences

- GraphRAG code, configuration, deployment support and tests are part of the principal project.
- Production and complete shadow cannot omit graph, vector, full-text or hybrid retrieval.
- The production manifest must bind an admitted GraphRAG implementation.
- The implementation plan must not use `POC` or optional-graduation language.
- Temporary graph outage has explicit degraded behaviour but does not make GraphRAG optional.
- Engine qualification and engine selection remain separate from the non-negotiable capability requirement.
- This ADR authorises no code, engine installation, source access, extraction, embedding, model call, spending, shadow run, canary or production activation.

## Completion record

The product owner accepted this decision on 2026-07-16 after rejecting the POC framing and requiring GraphRAG to be natively merged into the project and present in the production deployment.