# Discovery and knowledge-architecture review sequence

**Status:** Active owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. This document records owner decisions and organises review. It authorises no code, external request, graph installation, extraction, embedding, model call, spending, shadow run, canary or production activation.  
**Related discovery ADR:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md) (`Proposed`)  
**Accepted authority ADRs:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md)  
**Superseded first implementation Draft:** [`2026-07-16-003-discovery-implementation-and-migration.md`](2026-07-16-003-discovery-implementation-and-migration.md)

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
| 12 | Governed GraphRAG and knowledge projection | Accepted | [`governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md), ADR 0001 and ADR 0002 |
| 13 | Integrated implementation and migration | Drafting | New successor plan required; GraphRAG cannot be deferred |

## Accepted cross-topic boundaries

The following distinctions now govern the implementation plan:

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
- comparator union is not complete real-world ground truth;
- calendar duration is not sufficient evaluation exposure;
- healthy silence is not stale or failed source state;
- source health is not portfolio Coverage Availability;
- outcome, reason, next action, status and priority are separate;
- priority is not eligibility;
- local story is not locality coverage promise;
- relational authority is not permission to postpone GraphRAG;
- graph projection is not authoritative editorial truth;
- graph outage is not no prior match;
- hybrid retrieval context is not Event Hypothesis or Candidate authority;
- shadow is not production authority;
- Operational Admission is not activation;
- discovery is not evidence acquisition; and
- an implementation plan cannot create, weaken or omit Accepted requirements.

## Decision record

### Topic 0 — Decision-state repair

- **Agreed:** decisions are reviewed sequentially.
- **Agreed:** research, Draft specifications, Proposed plans and Proposed ADRs create no implementation authority.
- **Agreed:** stale false-acceptance metadata must be corrected before the documentation pull request.

### Topics 1–11 — Discovery contracts

The product owner accepted the focused specifications covering:

- Active, Best-effort, deferred and excluded coverage;
- deterministic Check-to-Candidate workflow and Evidence Handoff;
- stable identities, immutable versions and append-only lineage;
- source roles, portfolio functions, readiness and no silent fallback;
- observation models, Source Revisions, current-state transitions and Planned Agenda;
- bounded triage, relationship classes and append-only Event Hypotheses;
- bounded supplemental search and prospective coverage audit;
- event-level, human-reviewed, sliced shadow evaluation;
- Operational Profiles, health, quarantine, recovery and admission;
- canonical outcomes, reasons, ordinal priority and removal of quotas; and
- locality-aware, locality-uncommitted launch and evidence-based expansion.

The focused specifications remain the normative records. This sequence does not restate or narrow them.

### Topic 12 — Governed GraphRAG and authority architecture

- **Agreed:** GraphRAG, vector and full-text projections are first-class parts of canonical schema v1 and the initial programme, not a later backlog item.
- **Agreed:** the relational editorial ledger and governed object store are authority; graph and indexes are rebuildable projections.
- **Agreed:** ADR 0001 is Accepted.
- **Agreed:** ADR 0002 is Accepted; the canonical single-host ledger uses SQLite and is implemented together with the graph workstream rather than as a temporary graph-less phase.
- **Agreed:** discovery, later evidence and publication, and graph consumers share one identity, temporal, trust and ordered-event contract.
- **Agreed:** trust scopes distinguish `OBSERVED`, `PROPOSED` and `ADMITTED`.
- **Agreed:** deterministic structural relationships remain separate from reified editorial relation proposals and assertions.
- **Agreed:** entity resolution, merge, split and reversal are governed first-class decisions.
- **Agreed:** Graphiti is an isolated proposal producer and cannot write governed graph state directly.
- **Agreed:** projectors are idempotent, checkpointed, gap-aware, generation-versioned and rebuildable without stochastic re-extraction.
- **Agreed:** retrieval is hybrid exact, full-text, vector and bounded graph traversal, with authority hydrated from the ledger or object store.
- **Agreed:** Hermes or another agent receives named read-only tools and no graph write credential.
- **Agreed:** GraphRAG supplies advisory event, timeline, dependency and source-revision context; deterministic controllers retain Hypothesis, Candidate and evidence authority.
- **Agreed:** graph failure is not no-match. Safe collection may continue; graph-dependent decisions use an approved exact fallback or enter Watch or Operational Hold.
- **Agreed:** Neo4j Community plus Graphiti is the first proof-of-concept baseline, not automatic production admission. Another engine is a conditional challenger only after measured need.
- **Agreed:** complete live-shadow qualification requires the governed graph and hybrid retrieval path.
- **Needs experiment:** exact ontology details, model and embedding versions, retrieval thresholds, projection freshness, graph depth, resource envelope, licence admission and production engine.
- **Agreed:** Topic 12 acceptance authorises no execution.

### Topic 13 — Integrated implementation and migration

The first Topic 13 Draft is rejected as the final plan because it proposed a discovery-only SQLite store followed by later GraphRAG work. It remains in history as a superseded Draft.

The successor plan must:

- create canonical schema v1 directly;
- implement the SQLite authority plane and governed object store;
- define graph ontology and projection mappings from the first milestone;
- deliver Neo4j projection, Graphiti proposal and admission, hybrid retrieval and named tools in the initial programme;
- use the same canonical schema in offline, replay, shadow and later production environments;
- avoid relational-and-graph co-authority dual write;
- avoid legacy identity import and silent dual write;
- keep real sources, providers, models and spending disabled until their exact gates pass;
- require the graph path before complete end-to-end live-shadow qualification; and
- retain separate owner decisions for Evaluation Plan, Operational Admission, canary, production activation and legacy retirement.

## Topic 13 completion condition

Topic 13 is complete when the owner:

1. accepts or amends the integrated implementation plan;
2. accepts, amends, splits or rejects ADR 0004 against that plan;
3. confirms that the current branch remains documentation-only;
4. authorises preparation of the documentation pull request; and
5. leaves every runtime action behind a later milestone-specific approval gate.

## Change discipline before the documentation pull request

1. Update all statuses and cross-references.
2. Mark the first implementation Draft superseded rather than silently rewriting it.
3. Correct stale ADR references in the large integrated architecture plan.
4. Validate Markdown links and requirement references.
5. Record all Needs-experiment and deferred choices.
6. Keep the branch documentation-only.
7. Consolidate commits where repository tooling permits.