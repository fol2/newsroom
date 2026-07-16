# Native GraphRAG production-deployment amendment

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Amends:** [`governed-graphrag-and-knowledge-projection.md`](governed-graphrag-and-knowledge-projection.md)  
**Accepted invariant:** [`../../adr/0005-native-graphrag-production-deployment.md`](../../adr/0005-native-graphrag-production-deployment.md)  
**Related accepted decisions:** [`../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md)  
**Implementation authority:** None. This Draft proposes detailed engine, repository, deployment, CI and release mechanics. It does not install an engine, run extraction or embeddings, access sources, call a model, spend money, start shadow operation, canary or production.  
**Supersedes:** The `proof of concept`, `POC lane`, optional-adoption and graph-less-production interpretations of `GRAG-050` and earlier Topic 13 plans.

## Purpose

Translate Accepted ADR 0005 into testable production mechanics.

The following is already decided and is not reopened here:

> GraphRAG is a repository-native mandatory subsystem of the first production deployment. There is no graph-less production, canary or complete live-shadow product stage.

This Draft decides how the first implementation satisfies that invariant without making the graph authoritative.

## Authority boundary retained

- The relational ledger remains authoritative for identities, versions, proposals, admission decisions, outcomes and ordered history.
- Governed objects remain authoritative for exact retained permitted bytes and hashes.
- Graph, vector and full-text structures remain rebuildable projections.
- Extractors and models remain proposal producers.
- Deterministic or authorised admission remains required.
- Graph paths, similarity and rank remain context rather than Candidate, evidence or publication authority.

Mandatory production deployment and editorial authority are separate concepts.

## Proposed native implementation contract

GraphRAG is native only when the principal repository owns and tests:

- graph-aware canonical identities, time, trust and event mappings;
- ontology and versioning;
- graph, vector and full-text projectors;
- checkpoints, gaps, dead letters, generations and rebuild;
- extraction and proposal integration;
- entity and relation admission, merge, split and reversal;
- hybrid retrieval and authoritative hydration;
- bounded named read-only tools;
- production configuration and deployment definitions;
- readiness, lag, storage and licence diagnostics;
- backup, purge and recovery;
- security and credential separation; and
- integration, replay, ablation and fault-injection tests.

A notebook, separately managed experimental repository, undocumented manual graph or optional plugin does not satisfy native support.

## Proposed initial production implementation

The Draft proposes **Neo4j Community plus Graphiti** as the initial production-target implementation:

- Neo4j provides the governed property-graph projection and admitted vector or full-text capabilities where suitable;
- Graphiti operates only in an isolated proposal workspace;
- every extraction output and proposal is persisted in the ledger before admission;
- only governed projectors write admitted graph state; and
- Newsroom-owned named tools expose retrieval rather than raw graph credentials.

This is not a POC and does not require a later adoption decision. It is the implementation built toward production.

Exact Neo4j and Graphiti versions still require licence, security, backup, recovery, resource, performance, rights and quality gates.

If that implementation fails a gate, it is repaired or replaced before production activation. GraphRAG is not removed. An alternative engine must satisfy the same canonical contracts and complete the same release evidence.

## Production deployment contract

The production deployment definition binds exact versions of:

- canonical ledger schema and event envelope;
- governed-object contract;
- ontology;
- graph, vector and full-text projectors;
- graph engine;
- extraction framework and model where used;
- entity and relation admission policy;
- embedding, chunking and normalisation;
- named retrieval tools;
- projection freshness and degraded-operation policy;
- backup, rebuild and purge procedures;
- security roles and secrets;
- resource and licence decisions; and
- rollback or engine-replacement path.

A production build or deployment manifest must fail validation when a mandatory GraphRAG component is missing, incompatible, disabled or replaced by a fake.

Unit tests may use fake graph or extraction implementations. Production profiles may not.

## Delivery model

Dependency-ordered pull requests are permitted, but they are not product stages.

The first code increment includes both the relational and graph production contract:

- graph-aware canonical schema;
- ontology v1;
- event-to-projection mapping;
- graph client and credential boundary;
- production deployment configuration;
- graph readiness and gap semantics; and
- an actual Neo4j integration-test path.

The first complete vertical product slice includes:

```text
source or fixture input
→ canonical ledger record
→ governed graph and index projection
→ exact/full-text/vector/graph retrieval
→ trust-labelled Retrieval Context
→ deterministic triage and Candidate admission
```

Ledger-only or adapter-only tests may occur earlier but cannot be called the first complete product slice or qualify the full target architecture.

## Production-equivalent evaluation

Complete live-shadow qualification runs the production-target graph engine, projector, indexes, extraction/admission path and hybrid retrieval, or an explicitly approved production-equivalent environment.

The Evaluation Plan identifies every topology, resource, version or configuration difference from production.

Required evidence includes:

- relation and entity quality;
- English, Traditional Chinese and mixed-language resolution;
- temporal and provenance correctness;
- exact/full-text/vector/graph hybrid ablation;
- projection lag, gap and dead-letter behaviour;
- destructive rebuild without stochastic historical rewrite;
- rights and privacy purge followed by rebuild;
- backup and recovery;
- resource and cost envelope;
- security and named-tool containment;
- product-use licence approval; and
- temporary graph-outage behaviour.

Passing admits the exact implementation. Failing blocks activation or triggers implementation replacement; it never creates a graph-less production path.

## Temporary outage

A deployed graph may become temporarily unavailable. That is degraded operation inside the mandatory architecture:

- safe deterministic collection may continue where independent requirements pass;
- graph-dependent work reports unavailable, stale or gap outcomes;
- evaluated exact fallbacks serve only approved routes;
- other graph-dependent Leads enter Watch or Operational Hold;
- no outage becomes `no prior match`; and
- recovery restores and reconciles the mandatory graph deployment.

## Requirements

### Accepted invariant restatement

The following requirements restate ADR 0005 for traceability; ADR 0005 is the Accepted authority.

**GRPROD-001 — Mandatory production subsystem.** The first production deployment includes an admitted governed graph projection, vector and full-text indexes and bounded hybrid GraphRAG retrieval.

**GRPROD-002 — No graph-less product stage.** Production, canary and complete live shadow cannot omit GraphRAG and add it later.

**GRPROD-003 — Native repository ownership.** The principal repository owns GraphRAG code, ontology, projection, admission, retrieval, deployment, operations and tests.

**GRPROD-004 — Production profile requires GraphRAG.** A production profile cannot use a fake, no-op, disabled or omitted graph implementation.

**GRPROD-005 — Same canonical contract.** Relational, graph, vector, full-text, discovery and later knowledge consumers use the same canonical identities, trust, time and ordered events.

### Proposed implementation details

**GRPROD-010 — Initial production target.** Neo4j Community plus Graphiti is the initial production-target implementation, subject to exact release qualification rather than POC graduation.

**GRPROD-011 — Qualification decides version, not existence.** Evaluation and Operational Admission determine whether the exact implementation is ready; GraphRAG remains mandatory.

**GRPROD-012 — Replacement before activation.** Failure of the initial implementation requires repair or replacement before activation and cannot authorise graph-less production.

**GRPROD-013 — Engine-neutral domain semantics.** Canonical IDs, ontology meanings, proposals, admissions and named tools cannot depend on Neo4j internal IDs or Graphiti private state.

**GRPROD-014 — Repository deployment definition.** The project contains versioned development, evaluation and production GraphRAG deployment configuration or an equivalent generated contract.

**GRPROD-015 — Production configuration validation.** Missing or incompatible mandatory graph configuration fails production build or readiness validation.

**GRPROD-016 — Real integration path.** Repository CI includes an approved integration path against an actual graph service; pure fakes alone are insufficient.

### Integrated delivery

**GRPROD-020 — Graph contract in first increment.** The first code increment includes ontology, projection-event mapping, graph boundary, deployment configuration, health semantics and integration tests beside relational authority.

**GRPROD-021 — Graph-native complete slice.** The first complete end-to-end product slice includes governed projection and hybrid retrieval before triage and Candidate admission.

**GRPROD-022 — Production-equivalent shadow.** Complete live-shadow qualification uses the production-target graph stack or an approved production-equivalent environment.

**GRPROD-023 — No optional-plugin semantics.** Replaceable adapters are permitted, but GraphRAG cannot be an optional product capability.

**GRPROD-024 — Outage is degradation.** Temporary graph outage invokes accepted degraded behaviour and does not define a graph-free production profile.

### Release and authority

**GRPROD-030 — Activation binds exact versions.** Production activation identifies the exact graph engine, ontology, projectors, extraction, admission, indexes, retrieval, licence decision and rollback or replacement path.

**GRPROD-031 — Graph readiness is release readiness.** Missing, stale, gapped or unadmitted mandatory graph capability blocks or scopes production readiness under the release policy.

**GRPROD-032 — Acceptance is not execution.** Acceptance of this amendment starts no engine, source, extraction, embedding, model call, spending, shadow operation or production activation.

## Acceptance criteria

1. A production deployment manifest cannot validate without an admitted GraphRAG configuration.
2. A production build cannot substitute the fake graph used by unit tests.
3. The first complete vertical integration test traverses ledger, graph, hybrid retrieval, triage and Candidate admission.
4. Neo4j or Graphiti qualification failure blocks activation or causes implementation replacement; it never creates a graph-less release.
5. Replacing the engine preserves canonical IDs, proposal and admission history and named-tool contracts.
6. Complete shadow evidence includes the production-target graph and retrieval path.
7. A temporary outage creates explicit degraded outcomes while the system remains a GraphRAG deployment.
8. Mandatory deployment does not make GraphRAG authoritative.
9. The repository includes operational and rebuild procedures rather than an undocumented manual graph.
10. Acceptance creates no runtime authority.

## Owner decisions required

The Draft asks the owner to accept:

1. Neo4j Community plus Graphiti as the initial production-target implementation rather than a POC.
2. Repair or replacement before activation if that implementation fails gates, with no graph-less fallback.
3. The detailed native repository ownership boundary.
4. Production configuration and deployment validation that cannot omit or fake GraphRAG.
5. Actual graph-service integration in repository CI.
6. Graph production contracts and integration plumbing in the first code increment.
7. A graph-native first complete vertical slice.
8. Production-equivalent complete shadow evidence.
9. Engine-neutral canonical semantics and named-tool contracts.
10. Temporary graph outage as degraded operation rather than optional deployment.
11. Production activation binding exact graph and retrieval versions, licence and replacement path.
12. Acceptance authorising no runtime action.