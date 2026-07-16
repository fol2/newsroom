# Discovery and knowledge-architecture review sequence

**Status:** Active owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. This document records decisions and organises review. It authorises no code, source access, graph installation, extraction, embeddings, model call, spending, shadow run, canary or production activation.  
**Related discovery ADR:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md) (`Proposed`)  
**Accepted authority ADRs:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md)  
**Native production amendment:** [`../specs/editorial-automation/graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md)  
**Current implementation Draft:** [`2026-07-16-005-native-graphrag-production-implementation.md`](2026-07-16-005-native-graphrag-production-implementation.md)

## Purpose

Review discovery, GraphRAG and implementation in bounded topics so research, product decisions, specifications, experiments and plans are not collapsed into one approval.

A committed Draft, passing test, merged pull request, Proposed plan or Proposed ADR is not owner approval. Specification acceptance, implementation authority, Evaluation Plan approval, Operational Admission, canary and production activation remain separate decisions.

## Decision labels

- **Agreed:** accepted by the product owner and eligible for an Accepted specification or ADR.
- **Rejected:** considered and explicitly not adopted.
- **Deferred:** intentionally left for another topic or product decision.
- **Needs experiment:** cannot be resolved responsibly without bounded evidence.
- **Unresolved:** still requires owner discussion; no default may be inferred.

## Review order and state

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
| 12 | Governed GraphRAG core architecture | Accepted, with native-production amendment under review | Accepted core: [`governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md); amendment Draft: [`graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md) |
| 13 | Native GraphRAG production implementation | Drafted; owner review pending | [`2026-07-16-005-native-graphrag-production-implementation.md`](2026-07-16-005-native-graphrag-production-implementation.md) |

## Accepted cross-topic boundaries

The following distinctions govern the plan:

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
- GraphRAG is not a backlog item or optional later product stage;
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

### Topic 12 — Governed GraphRAG

The following remain **Agreed**:

- one graph-aware identity, temporal, trust and ordered-event contract from schema v1;
- relational ledger and governed-object authority;
- graph, vector and full-text structures as rebuildable projections;
- ADR 0001 and ADR 0002;
- `OBSERVED`, `PROPOSED` and `ADMITTED` trust scopes;
- governed entity resolution and reified editorial relations;
- Graphiti as a proposal producer, not a governed-graph writer;
- idempotent projectors, checkpoints, visible gaps, generations and deterministic rebuild;
- hybrid exact, full-text, vector and bounded graph retrieval;
- named read-only tools;
- GraphRAG as advisory context, with deterministic Hypothesis and Candidate authority; and
- graph failure as explicit degradation rather than no match.

The product owner subsequently made these decisions:

- **Rejected:** describing GraphRAG as a `POC`, proof-of-concept lane or optional adoption decision.
- **Agreed:** GraphRAG must be natively implemented in this repository and included in the first production deployment.
- **Agreed:** there is no graph-less production, canary or complete live-shadow product stage.
- **Agreed:** qualification verifies an exact mandatory implementation; it does not decide whether GraphRAG exists.
- **Agreed:** temporary graph outage is degraded operation inside a GraphRAG deployment, not a supported graph-free profile.

The following detailed amendment decisions remain **Unresolved** until the owner reviews the Draft:

- Neo4j Community plus Graphiti as the initial production-target implementation rather than a POC;
- replacement-before-activation if that implementation fails gates;
- the exact native repository and deployment contract; and
- the release and CI gates in `GRPROD-001`–`GRPROD-032`.

### Topic 13 — Native production implementation

The earlier integrated plan is superseded because its POC language preserved a two-stage interpretation.

The current Draft proposes:

- one repository-native production deployment including SQLite authority, governed objects, graph, vector, full-text, Graphiti admission and hybrid retrieval;
- no production profile that omits or fakes GraphRAG;
- graph deployment and integration plumbing in the first code increment;
- a graph-native first complete vertical slice;
- production-equivalent complete shadow using the production-target graph stack;
- component replacement before activation rather than graph removal;
- focused dependency-ordered pull requests that are merge boundaries, not product stages; and
- separate Evaluation Plan, Operational Admission, canary, activation and retirement decisions.

## Completion condition

The review is complete when the owner:

1. accepts or amends the native-production amendment;
2. accepts, amends or rejects ADR 0005;
3. accepts or amends the native GraphRAG production implementation plan;
4. accepts, amends, splits or rejects ADR 0004 against those decisions;
5. confirms the branch remains documentation-only;
6. authorises preparation of the documentation pull request; and
7. leaves runtime actions behind later explicit gates.

## Change discipline before the documentation pull request

1. Update all statuses and cross-references.
2. Keep superseded POC-framed plans as clear tombstones.
3. Correct stale ADR references in the large integrated architecture plan.
4. Validate Markdown links and requirement references.
5. Record Needs-experiment and deferred choices.
6. Keep the branch documentation-only.
7. Consolidate commits where repository tooling permits.