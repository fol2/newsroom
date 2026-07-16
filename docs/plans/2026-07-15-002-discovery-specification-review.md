# Discovery and knowledge-architecture review sequence

**Status:** Completed owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Completed:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. This document records decisions and organises review. It authorises no code, source access, graph installation, extraction, embeddings, model call, spending, shadow run, canary or production activation.  
**Accepted discovery ADR:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md)  
**Accepted architecture ADRs:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md), [`../adr/0005-native-graphrag-production-deployment.md`](../adr/0005-native-graphrag-production-deployment.md)  
**Accepted native production contract:** [`../specs/editorial-automation/graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md)  
**Accepted implementation plan:** [`2026-07-16-005-native-graphrag-production-implementation.md`](2026-07-16-005-native-graphrag-production-implementation.md)

## Purpose

Review discovery, GraphRAG and implementation in bounded topics so research, product decisions, specifications, experiments and plans are not collapsed into one approval.

A committed Draft, passing test, merged pull request, Proposed plan or Proposed ADR is not owner approval. Specification acceptance, implementation authority, Evaluation Plan approval, Operational Admission, canary and production activation remain separate decisions.

## Decision labels

- **Agreed:** accepted by the product owner and eligible for an Accepted specification or ADR.
- **Rejected:** considered and explicitly not adopted.
- **Deferred:** intentionally left for another topic or product decision.
- **Needs experiment:** cannot be resolved responsibly without bounded evidence.
- **Unresolved:** still requires owner discussion; no default may be inferred.

## Review order and final state

| Topic | Scope | State | Canonical record |
|---|---|---|---|
| 0 | Decision-state repair | Completed | This sequence and corrected ADR statuses |
| 1 | Coverage contract | Accepted | [`discovery-coverage-contract.md`](../specs/editorial-automation/discovery-coverage-contract.md) |
| 2 | End-to-end workflow | Accepted | [`discovery-workflow.md`](../specs/editorial-automation/discovery-workflow.md) |
| 3 | Record semantics | Accepted | [`discovery-record-semantics.md`](../specs/editorial-automation/discovery-record-semantics.md) |
| 4 | Source roles and selection | Accepted | [`discovery-source-roles-and-selection.md`](../specs/editorial-automation/discovery-source-roles-and-selection.md) |
| 5 | Change and Planned Agenda | Accepted | [`discovery-change-and-planned-agenda.md`](../specs/editorial-automation/discovery-change-and-planned-agenda.md) |
| 6 | Triage and event grouping | Accepted | [`discovery-triage-and-event-grouping.md`](../specs/editorial-automation/discovery-triage-and-event-grouping.md) |
| 7 | Search and coverage audit | Accepted | [`discovery-search-and-coverage-audit.md`](../specs/editorial-automation/discovery-search-and-coverage-audit.md) |
| 8 | Shadow evaluation | Accepted | [`discovery-shadow-evaluation.md`](../specs/editorial-automation/discovery-shadow-evaluation.md) |
| 9 | Reliability and operations | Accepted | [`discovery-reliability-and-operations.md`](../specs/editorial-automation/discovery-reliability-and-operations.md) |
| 10 | Outcomes and prioritisation | Accepted | [`discovery-prioritisation-and-outcomes.md`](../specs/editorial-automation/discovery-prioritisation-and-outcomes.md) |
| 11 | Locality boundary and expansion | Accepted | [`discovery-locality-scope-and-expansion.md`](../specs/editorial-automation/discovery-locality-scope-and-expansion.md) |
| 12 | Governed and native-production GraphRAG | Accepted | [`governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md), [`graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md), ADRs 0001, 0002 and 0005 |
| 13 | Native GraphRAG production implementation | Accepted | [`2026-07-16-005-native-graphrag-production-implementation.md`](2026-07-16-005-native-graphrag-production-implementation.md) |
| Architecture consolidation | Discovery architecture | Accepted | ADR 0004 |

## Accepted cross-topic boundaries

The following distinctions govern future implementation:

- product scope is not monitoring completeness;
- a source interface is not a coverage strategy;
- source role is not universal evidence authority;
- Source Revision is not editorial materiality;
- feed disappearance is not automatically deletion or resolution;
- Planned Agenda is expectation, not occurrence evidence;
- execution batching is not event grouping;
- retrieval similarity is not event identity;
- event relationship is not Candidate creation;
- search result is not publisher evidence or recall ground truth;
- prospective audit is not hindsight Gap investigation;
- healthy silence is not stale or failed source state;
- source health is not portfolio Coverage Availability;
- outcome, reason, next action, status and priority are separate;
- local story is not locality coverage promise;
- the relational ledger is authority while graph and indexes are rebuildable projections;
- projection status does not become editorial truth;
- graph outage is not no prior match;
- hybrid retrieval context is not Candidate authority;
- GraphRAG is a required native production subsystem, not a POC, backlog item or optional plugin;
- temporary graph outage is degraded operation, not a graph-free production profile;
- native production support does not make the graph authoritative;
- shadow is not production authority;
- Operational Admission is not activation;
- discovery is not evidence acquisition; and
- an implementation plan cannot create, weaken or omit Accepted requirements.

## Decision record

### Topic 0 — Decision-state repair

- **Agreed:** decisions are reviewed sequentially.
- **Agreed:** research, Draft specifications, Proposed plans and Proposed ADRs create no implementation authority.
- **Agreed:** rejected directions are marked superseded rather than silently rewritten.

### Topics 1–11 — Discovery contracts

The product owner accepted the focused specifications covering coverage, workflow, identity, sources, change semantics, triage, search, evaluation, operations, prioritisation and locality. Those focused files remain the normative records.

### Topic 12 — Governed and native-production GraphRAG

The following are **Agreed**:

- one graph-aware identity, temporal, trust and ordered-event contract from schema v1;
- relational ledger and governed-object authority;
- graph, vector and full-text structures as rebuildable projections;
- ADR 0001 and ADR 0002;
- `OBSERVED`, `PROPOSED` and `ADMITTED` trust scopes;
- governed entity resolution and reified editorial relations;
- Graphiti or another extractor as a proposal producer rather than governed-graph writer;
- idempotent projectors, checkpoints, visible gaps, generations and deterministic rebuild;
- hybrid exact, full-text, vector and bounded graph retrieval;
- named read-only tools;
- GraphRAG as advisory context with deterministic Hypothesis and Candidate authority;
- graph failure as explicit degradation rather than no match;
- ADR 0005: GraphRAG is natively implemented in the repository and mandatory in the first production deployment;
- no graph-less production, canary or complete live-shadow product stage;
- Neo4j Community plus Graphiti as the initial production-target implementation rather than a POC;
- replacement before activation if the initial implementation fails gates, with no graph-less fallback;
- repository-owned deployment, CI, readiness, rebuild and recovery mechanics under `GRPROD-001`–`GRPROD-032`;
- qualification verifies an exact mandatory implementation rather than deciding whether GraphRAG exists; and
- temporary graph outage is degraded operation inside a GraphRAG deployment.

The following are **Rejected**:

- GraphRAG as a `POC`, proof-of-concept lane, optional plugin or later adoption decision;
- graph-less activation after a graph implementation fails qualification; and
- a complete relational product slice being treated as the target before GraphRAG integration.

### Topic 13 — Native GraphRAG production implementation

The product owner accepted:

- one repository-native production deployment including SQLite authority, governed objects, graph, vector, full-text, extraction/admission and hybrid retrieval;
- no production profile that omits, disables or fakes GraphRAG;
- canonical graph-aware schema v1 and side-by-side legacy replacement;
- Neo4j Community plus Graphiti as the initial production-target implementation;
- implementation repair or replacement before activation rather than graph removal;
- graph deployment, ontology, projection and actual service integration in the first code increment;
- a graph-native first complete vertical slice;
- production-equivalent complete shadow using the production-target graph stack or an explicitly approved equivalent;
- relational authority for exact identity and Candidate collision;
- persisted extraction proposals and separate admission before projection;
- dependency-ordered pull requests as merge boundaries rather than product stages;
- separate Evaluation Plan, Operational Admission, Evidence Intake canary, activation and retirement decisions;
- no legacy identity import, silent dual write, source-count ranking, quotas or filler; and
- no runtime authority from plan acceptance.

### ADR 0004 — Consolidated discovery architecture

The product owner accepted ADR 0004 on 2026-07-16. The accepted architecture is source-portfolio-first, change-driven, natively GraphRAG and scheduler-neutral.

## Completion and pull-request authority

The owner confirmed on 2026-07-16 that:

1. the branch remains documentation-only;
2. this review sequence is complete;
3. final documentation cleanup and validation are authorised;
4. a documentation-only pull request may be prepared and opened; and
5. every runtime action remains behind later milestone-specific approval gates.

## Preserved deferred and Needs-experiment decisions

Acceptance does not resolve evidence-dependent choices including exact sources, polling and operational numbers, search provider, exact schema details, ontology predicates, admitted Neo4j and Graphiti versions, embeddings, retrieval thresholds, Evidence Intake transport, hosting, observability, locality selection or production activation date.