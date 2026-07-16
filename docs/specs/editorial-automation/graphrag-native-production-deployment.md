# Native GraphRAG production-deployment amendment

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Amends:** [`governed-graphrag-and-knowledge-projection.md`](governed-graphrag-and-knowledge-projection.md)  
**Related accepted decisions:** [`../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md)  
**Related proposed decision:** [`../../adr/0005-native-graphrag-production-deployment.md`](../../adr/0005-native-graphrag-production-deployment.md)  
**Implementation authority:** None. This amendment defines a mandatory production capability. It does not install Neo4j, run Graphiti, create embeddings, access a source, call a model, spend money, start shadow operation, canary or production.  
**Supersedes:** The `proof of concept`, `POC lane`, optional-adoption and graph-less-production interpretations of `GRAG-050` and related Topic 13 wording.

## Purpose

Correct the remaining two-stage interpretation of GraphRAG.

The Newsroom does not build a complete relational discovery product and then decide whether GraphRAG should graduate from a proof of concept. GraphRAG is a native, required subsystem of the first production deployment.

Qualification still decides whether an exact engine, extractor, ontology, projector and retrieval version is safe and effective enough to deploy. Qualification does **not** decide whether production contains GraphRAG.

The accepted target is:

```text
one repository-owned production system
  ├── canonical SQLite editorial ledger
  ├── governed content-addressed object store
  ├── governed graph projection
  ├── vector and full-text indexes
  ├── Graphiti proposal and admission path
  ├── bounded hybrid retrieval tools
  └── discovery, triage and later evidence consumers
```

A production release without the governed graph and hybrid retrieval capability is not a reduced version of the target. It is a different, non-conforming architecture.

## Decisions not reopened

This amendment does not change the accepted authority boundary:

- the relational ledger remains authoritative for identities, versions, proposals, admission decisions, outcomes and ordered history;
- governed objects remain authoritative for exact retained permitted bytes and hashes;
- graph, vector and full-text structures remain rebuildable projections;
- Graphiti and models remain proposal producers;
- deterministic or authorised admission remains required;
- graph similarity and paths remain context rather than editorial authority; and
- temporary graph failure must remain distinguishable from no prior event or no relation.

Native production support and projection authority are separate questions. GraphRAG is mandatory in the deployment without becoming the system of record.

## Native project support

GraphRAG is `native` only when the repository owns and tests the complete contract needed to operate it. The project must contain, or generate from versioned repository configuration:

- canonical graph-aware identities, time fields, trust states and ordered event mappings;
- the graph ontology and versioning rules;
- graph, vector and full-text projector code;
- projector checkpoints, gap, dead-letter, generation and rebuild logic;
- the Graphiti extraction adapter and isolated proposal-workspace boundary;
- entity and relation proposal, admission, rejection, merge, split and reversal records;
- hybrid retrieval and authoritative hydration;
- bounded named read-only retrieval tools;
- production configuration and deployment definitions for the admitted graph stack;
- readiness, liveness, lag, gap, storage and licence diagnostics;
- backup, destructive rebuild, rights purge and recovery procedures;
- security controls and credential separation;
- integration, replay, fault-injection and end-to-end tests; and
- migration and rollback behaviour.

A separate experimental repository, notebook, manual Neo4j setup or operator-only script does not satisfy native support.

## Production deployment contract

The first production activation must bind exact versions of:

- canonical ledger schema and event envelope;
- governed object contract;
- ontology;
- graph projector;
- vector and full-text indexers;
- graph engine;
- extraction framework and model where used;
- entity and relation admission policy;
- embedding, chunking and normalisation;
- named retrieval tools;
- projection freshness and degraded-operation policy;
- backup, rebuild and purge procedures; and
- operational, security and licence decisions.

The production deployment definition must include the admitted graph service and retrieval components. A production build, deployment profile or activation decision must not silently omit them.

Test, fixture and local unit-test profiles may use in-memory or fake graph interfaces. A fake, disabled or no-op graph implementation is prohibited in the production profile.

## Initial production implementation

Neo4j Community plus Graphiti is the initial production-target implementation, not a proof-of-concept stage:

- Neo4j supplies the governed property-graph projection and, where admitted, vector and full-text indexes;
- Graphiti operates only in the isolated proposal path;
- relation and entity proposals are persisted in the ledger before admission;
- only governed projectors write admitted graph state; and
- Newsroom-owned named tools expose retrieval rather than raw graph credentials.

Neo4j, Graphiti and their exact versions still require licence, security, backup, resource, performance, recovery and product-use qualification.

Failure of that qualification does not authorise graph-less production. It requires replacing the engine, framework or deployment mechanism before production activation while retaining the same canonical authority and projection contracts.

Another engine is therefore an implementation substitution inside the same production architecture, not a later GraphRAG stage.

## Delivery model

Implementation pull requests may be dependency ordered, but there is no intermediate product release or qualifying complete shadow architecture without GraphRAG.

The first implementation milestone must establish both:

1. the canonical relational authority contract; and
2. the native graph production contract, including ontology, event mapping, graph client boundary, deployment configuration, health semantics and integration-test path.

The first complete vertical slice must exercise:

```text
source or fixture input
→ canonical ledger record
→ governed graph projection
→ exact/full-text/vector/graph retrieval
→ trust-labelled Retrieval Context
→ deterministic triage and Candidate decision
```

A ledger-only or adapter-only slice may be useful as an internal test, but it is not the first complete product slice and cannot qualify the target architecture.

## Qualification is not a product stage

The project may use pre-production environments, controlled datasets and shadow traffic to qualify the mandatory production implementation. These are release-verification activities, not a separate optional product phase.

The exact production-target GraphRAG stack must be exercised in a production-equivalent evaluation environment before activation. Where the physical environment differs, the Evaluation Plan must identify and justify every difference.

The following evidence is still required:

- relation and entity quality;
- bilingual and mixed-language identity resolution;
- temporal and provenance correctness;
- hybrid retrieval ablation;
- projection lag and gap behaviour;
- destructive rebuild without stochastic historical rewrite;
- rights and privacy purge followed by rebuild;
- backup and recovery;
- resource and cost envelope;
- security and named-tool containment;
- licence approval; and
- degraded operation during temporary graph outage.

Passing these gates admits the exact implementation to production. Failing them blocks activation or requires implementation replacement; it does not remove the GraphRAG requirement.

## Temporary outage is not optional deployment

A deployed graph may become temporarily unavailable. The accepted degraded behaviour remains:

- deterministic collection and durable Lead creation may continue where safe;
- graph-dependent work reports an explicit unavailable, stale or gap outcome;
- an approved exact relational fallback may serve only the routes for which it has been evaluated;
- other graph-dependent Leads enter Watch or Operational Hold;
- no graph failure becomes `no prior match`; and
- recovery reconciles the same mandatory graph deployment.

This resilience behaviour does not create a supported graph-free production mode.

## Requirements

### Native production requirement

**GRPROD-001 — Mandatory production subsystem.** The first production deployment MUST include an admitted governed graph projection, vector and full-text retrieval indexes and bounded hybrid GraphRAG retrieval.

**GRPROD-002 — No graph-less product stage.** The implementation programme MUST NOT define a production, canary or complete live-shadow target that omits GraphRAG and later migrates to it.

**GRPROD-003 — Native repository ownership.** The repository MUST own the ontology, projection, extraction-boundary, admission, retrieval, deployment, health, rebuild, security and test contracts required to operate GraphRAG.

**GRPROD-004 — Production profile requires GraphRAG.** A production configuration or build profile MUST NOT select a fake, no-op, disabled or omitted graph implementation.

**GRPROD-005 — Same canonical contract.** Relational, graph, vector, full-text, discovery and later evidence consumers MUST use the same canonical identities, trust states, time semantics and ordered event contract.

### Initial implementation and substitution

**GRPROD-010 — Initial production implementation.** Neo4j Community plus Graphiti is the initial production-target GraphRAG implementation, subject to exact release qualification rather than optional POC graduation.

**GRPROD-011 — Qualification decides version, not existence.** Evaluation and Operational Admission determine whether an exact GraphRAG implementation is production-ready; they MUST NOT be used to make GraphRAG optional.

**GRPROD-012 — Replacement before activation.** If the initial engine or framework fails a release gate, an alternative implementation MUST satisfy the same contract before activation. The system MUST NOT activate without GraphRAG as a fallback response.

**GRPROD-013 — No engine lock-in of domain semantics.** Canonical IDs, ontology meanings, proposal and admission history and retrieval-tool contracts MUST NOT depend on Neo4j internal IDs or Graphiti-private state.

### Integrated delivery

**GRPROD-020 — Graph contract in first milestone.** The first implementation milestone MUST include the production graph contract, ontology version, projection-event mapping, deployment boundary, health model and integration-test path beside the relational authority foundation.

**GRPROD-021 — Graph-native complete slice.** The first complete end-to-end vertical slice MUST include governed projection and hybrid retrieval before triage and Candidate admission.

**GRPROD-022 — Production-equivalent shadow.** Complete live-shadow qualification MUST run the production-target graph, projector, indexes and retrieval path, or a documented production-equivalent environment approved in the Evaluation Plan.

**GRPROD-023 — No optional-plugin semantics.** GraphRAG MAY have replaceable adapters, but the capability MUST NOT be modelled as an optional product plugin whose absence is a supported production state.

**GRPROD-024 — Outage is degraded operation.** Temporary graph outage MAY invoke accepted degraded behaviour but MUST NOT redefine the deployed architecture as graph-free.

### Release and authority

**GRPROD-030 — Activation binds graph versions.** Production activation MUST identify the exact graph engine, ontology, projector, extraction, admission, indexes, retrieval tools, Operational Profiles, licence decision and rollback or replacement path.

**GRPROD-031 — Graph health is release health.** Missing, stale, gapped or unadmitted mandatory graph capability MUST block or scope production readiness according to the accepted release policy.

**GRPROD-032 — Acceptance is not execution.** Acceptance of this amendment MUST NOT install an engine, run extraction or embeddings, access sources, spend money, start shadow operation or activate production.

## Acceptance criteria

1. The production deployment manifest cannot be rendered successfully without an admitted GraphRAG configuration.
2. A production build cannot substitute the fake graph used by unit tests.
3. The first complete vertical test traverses ledger, governed graph, hybrid retrieval, triage and Candidate admission.
4. Neo4j qualification failure blocks activation or causes an implementation replacement; it never creates a graph-less release.
5. Replacing Neo4j preserves canonical IDs, proposal and admission history and named-tool contracts.
6. Complete shadow evidence includes the production-target graph and retrieval path.
7. A temporary graph outage creates explicit degraded outcomes while the deployment remains a GraphRAG system.
8. GraphRAG remains a projection and does not become authoritative merely because it is mandatory in production.
9. The repository includes operational and rebuild procedures rather than relying on an undocumented manually managed graph.
10. Acceptance creates no runtime authority.

## Owner decisions required

The Draft recommends that the owner accept:

1. GraphRAG as a mandatory native subsystem of the first production deployment, not a POC, backlog item or optional later stage.
2. No production, canary or complete live-shadow architecture without governed graph, vector, full-text and hybrid retrieval.
3. Repository ownership of GraphRAG code, ontology, projection, admission, retrieval, deployment, operations and tests.
4. Neo4j Community plus Graphiti as the initial production-target implementation rather than a proof-of-concept lane.
5. Exact qualification of that implementation before activation, with replacement before activation if it fails and no graph-less fallback.
6. One canonical relational-plus-graph contract, while preserving relational and object authority and graph rebuildability.
7. Graph production contracts and integration plumbing in the first implementation milestone.
8. A graph-native first complete vertical slice.
9. Production-equivalent integrated shadow evidence.
10. A prohibition on fake, disabled or omitted GraphRAG in production profiles.
11. Temporary graph outage as degraded operation rather than a supported graph-free deployment mode.
12. Production activation binding exact graph, projector, ontology, extraction, index, retrieval, licence and rollback versions.
13. Engine substitution as an implementation change within one architecture, not a second product stage.
14. Acceptance of this amendment authorising no runtime action.