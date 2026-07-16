# Discovery specification review sequence

**Status:** Active review sequence  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. This document records owner decisions and organises review; it authorises no code, external request, model call, spending, shadow run, canary or production activation.  
**Related discovery proposal:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md)  
**Related authority proposals:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md)  
**Implementation-plan Draft requiring revision:** [`2026-07-16-003-discovery-implementation-and-migration.md`](2026-07-16-003-discovery-implementation-and-migration.md)

## Purpose

Review news discovery in bounded topics so research findings, product decisions, specifications, experiments and implementation plans are not collapsed into one approval.

A committed Draft, passing test, merged PR, Proposed plan or Proposed ADR is not owner approval. Runtime authority is always separate from specification acceptance.

The product owner rejected the assumption that GraphRAG may be deferred until after a separate discovery-only implementation. A governed GraphRAG architecture topic is therefore reviewed before the implementation and migration plan is finalised.

## Decision labels

- **Agreed:** accepted by the product owner and eligible for an Accepted specification or ADR.
- **Rejected:** considered and explicitly not adopted.
- **Deferred:** intentionally left for another topic or later product decision.
- **Needs experiment:** cannot be resolved responsibly without bounded evidence.
- **Unresolved:** still requires owner discussion; no default may be inferred.

## Review order and status

| Topic | Scope | State | Canonical record |
|---|---|---|---|
| 0. Decision-state repair | Correct false approval signals and establish sequential review | Completed | This sequence and Proposed ADR 0004 |
| 1. Coverage contract | Active, Best-effort, deferred and excluded coverage | Accepted | [`discovery-coverage-contract.md`](../specs/editorial-automation/discovery-coverage-contract.md) |
| 2. End-to-end workflow | Check through Candidate and Evidence Handoff | Accepted | [`discovery-workflow.md`](../specs/editorial-automation/discovery-workflow.md) |
| 3. Record semantics | Identity, versioning, decisions and lineage | Accepted | [`discovery-record-semantics.md`](../specs/editorial-automation/discovery-record-semantics.md) |
| 4. Source roles and selection | Roles, portfolio functions, gates and candidate paths | Accepted | [`discovery-source-roles-and-selection.md`](../specs/editorial-automation/discovery-source-roles-and-selection.md) |
| 5. Change and Planned Agenda | Observation, revision, state and expectation meaning | Accepted | [`discovery-change-and-planned-agenda.md`](../specs/editorial-automation/discovery-change-and-planned-agenda.md) |
| 6. Triage and grouping | Work Items, retrieval, relationships and Candidate formation | Accepted | [`discovery-triage-and-event-grouping.md`](../specs/editorial-automation/discovery-triage-and-event-grouping.md) |
| 7. Search and audit | Search roles, query control, budgets and Coverage Gaps | Accepted | [`discovery-search-and-coverage-audit.md`](../specs/editorial-automation/discovery-search-and-coverage-audit.md) |
| 8. Shadow evaluation | Plans, Epochs, review universe, metrics and release evidence | Accepted | [`discovery-shadow-evaluation.md`](../specs/editorial-automation/discovery-shadow-evaluation.md) |
| 9. Reliability and operations | Profiles, health, retries, quarantine, recovery and admission | Accepted | [`discovery-reliability-and-operations.md`](../specs/editorial-automation/discovery-reliability-and-operations.md) |
| 10. Outcomes and priority | Decision order, outcomes, reasons and ordinal lanes | Accepted | [`discovery-prioritisation-and-outcomes.md`](../specs/editorial-automation/discovery-prioritisation-and-outcomes.md) |
| 11. Locality | Initial boundary, Event-Scoped Watch and expansion | Accepted | [`discovery-locality-scope-and-expansion.md`](../specs/editorial-automation/discovery-locality-scope-and-expansion.md) |
| 12. Governed GraphRAG and knowledge projection | Authority, ontology, trust, projection, extraction, hybrid retrieval and first POC | Drafted; owner review pending | [`governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md) |
| 13. Implementation and migration | Integrated relational-plus-GraphRAG architecture, milestones, tests, rollout and rollback | Blocked; first Draft requires revision | A revised successor to [`2026-07-16-003-discovery-implementation-and-migration.md`](2026-07-16-003-discovery-implementation-and-migration.md) after Topic 12 |

## Cross-topic boundaries

The following distinctions are accepted or, for GraphRAG-specific items, proposed in Topic 12:

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
- source health is not portfolio coverage availability;
- Operational Admission is not activation;
- outcome, reason, next action, status and priority are separate;
- priority is not eligibility;
- local story is not locality coverage promise;
- GraphRAG is not an authoritative editorial ledger;
- a rebuildable graph is not permission to postpone the graph contract;
- graph outage is not no prior match;
- shadow is not production authority;
- discovery is not evidence acquisition; and
- an implementation plan cannot create requirements absent from Accepted specifications or ADRs.

## Decision record

### Topic 0 — Decision-state repair

- **Agreed:** discovery decisions are reviewed sequentially.
- **Agreed:** ADR 0004 remains Proposed until explicitly accepted, amended, split or rejected.
- **Agreed:** research, Draft specifications and Proposed plans or ADRs authorise no implementation.
- **Deferred cleanup:** remove stale false-acceptance text in the large integrated architecture plan before the documentation PR is opened.

### Topic 1 — Coverage

- **Agreed:** responsibility classes are Active, Best effort, Explicit deferred gap and Out of scope.
- **Agreed:** Hong Kong has intrinsic broad major-public-affairs value and is not utility-only.
- **Agreed:** authoritative public-safety warnings and clearly major unscheduled incidents are Active; other crime and incidents are Best effort.
- **Agreed:** exhaustive UK locality monitoring is deferred.
- **Agreed:** Active classes require a credible path or launch-blocking gap.

### Topic 2 — Workflow

- **Agreed:** deterministic controllers commit transitions and models propose.
- **Agreed:** successful unchanged, change, partial, failure and quarantine are separate before a Signal exists.
- **Agreed:** ambiguity normally survives to Lead triage.
- **Agreed:** watch or defer is a first-class outcome with a Watch Condition.
- **Agreed:** Evidence Handoff requires durable acknowledgement and idempotent retry.

### Topic 3 — Records

- **Agreed:** internal identity is separate from URL, provider ID and digest.
- **Agreed:** Source Definition, Item, Revision and Representation are separate and versioned.
- **Agreed:** Signals, Leads, Hypotheses, Candidates and Handoffs are immutable and append-only.
- **Agreed:** Coverage Gaps require reviewed misses.
- **Deferred:** physical schema and retention details; the GraphRAG topic now resolves the authority and projection boundary before implementation.

### Topic 4 — Sources

- **Agreed:** coverage obligations determine source selection.
- **Agreed:** source roles and portfolio functions are explicit; silent fallback is prohibited.
- **Agreed:** official, media, RSS and search are not sufficient purposes.
- **Agreed:** the research shortlist is validation work, not coverage completeness or run authority.
- **Agreed:** devolved paths, courts and elections, UK–Hong Kong travel and aviation, Hong Kong courts and a global radar remain mandatory pre-production source work.

### Topic 5 — Change and Agenda

- **Agreed:** source-specific observation models constrain inference.
- **Agreed:** parser or transport change cannot fabricate publisher change.
- **Agreed:** absence ends state only under complete-snapshot and confirmation rules.
- **Agreed:** Agenda and occurrence are separate; clock passage creates no story.

### Topic 6 — Triage and grouping

- **Agreed:** Work Item, Execution Batch and event grouping are separate.
- **Agreed:** retrieval and confidence are context, not authority.
- **Agreed:** same state, development, correction, related-distinct, no match and uncertain remain distinct.
- **Agreed:** Event Hypothesis consolidation and split are append-only.
- **Agreed:** no source-count minimum exists for discovery Candidate formation.

### Topic 7 — Search and audit

- **Agreed:** search is supplemental and bounded, never the sole Active Anchor or generic production clock.
- **Agreed:** prospective and retrospective queries remain separate.
- **Agreed:** zero results are neutral and provider failures remain operational.
- **Agreed:** Brave is Rights Review Required, GDELT is Held and SearXNG or unofficial wrappers remain Research candidates.
- **Deferred:** actual provider, queries, budgets and schedules.

### Topic 8 — Evaluation

- **Agreed:** shadow has no public effect or production authority.
- **Agreed:** Evaluation Plans and frozen Epochs precede qualification.
- **Agreed:** evaluation is event-level, prospective, human-reviewed, sliced and stage-specific.
- **Agreed:** zero-tolerance failures block affected qualification.
- **Needs experiment:** numerical thresholds, minimum exposure and source or component promotion.

### Topic 9 — Operations

- **Agreed:** every executable scope has a versioned Operational Profile.
- **Agreed:** healthy unchanged requires a successful qualifying check; stale is not quiet.
- **Agreed:** health is multidimensional and coverage availability is portfolio-level.
- **Agreed:** retry, quarantine, contingency, queueing, reconciliation, backup, restore, canary and rollback are explicit.
- **Needs experiment:** exact cadence, freshness, retry, queue, capacity and alert values.

### Topic 10 — Outcomes and priority

- **Agreed:** outcome, reason, next action, status and priority remain separate.
- **Agreed:** canonical outcome families and versioned reason taxonomy are accepted.
- **Agreed:** ordinal lanes are `CONTAINMENT`, `URGENT`, `TIME_SENSITIVE`, `PLANNED_WINDOW`, `ROUTINE` and `OPTIONAL_EVALUATION`.
- **Agreed:** quotas, guaranteed slots, media volume, confidence and legacy child-event status cannot promote work.
- **Agreed:** launch has no governing global composite discovery score.
- **Needs experiment:** any later bounded stage-local score or numerical threshold.

### Topic 11 — Locality

- **Agreed:** launch is locality-aware and locality-uncommitted; no fixed UK locality receives systematic all-topic monitoring by default.
- **Agreed:** material local stories remain eligible wherever discovered and create no completeness promise.
- **Agreed:** nation-level coverage is separate from local expansion.
- **Agreed:** Locality Coverage Units are exact geography-plus-source-class-plus-obligation scopes.
- **Agreed:** Event-Scoped Local Watch is bounded, budgeted, owned and expiring.
- **Agreed:** Hong Kong remains one product geography without district filters or district-completeness promises.
- **Needs experiment:** actual localities, source classes and numerical admission thresholds.

### Topic 12 — Governed GraphRAG and knowledge projection

The product owner rejected deferring GraphRAG behind a separate discovery-only implementation.

The Draft now proposes:

- one canonical identity, temporal, trust and ordered-event contract from schema v1;
- relational ledger and governed objects as authority;
- graph, vector and full-text as first-class rebuildable projections in the initial programme;
- explicit `OBSERVED`, `PROPOSED` and `ADMITTED` trust scopes;
- Graphiti as an isolated proposal producer rather than a graph authority;
- reified and admitted editorial relations;
- first-class entity resolution;
- ordered idempotent projection with visible gaps and blue-green rebuild;
- hybrid exact, full-text, vector and graph retrieval through named read-only tools;
- graph-assisted discovery grouping without graph authority over Hypotheses or Candidates;
- graph failure as degraded context rather than no match;
- Neo4j Community plus Graphiti as the first POC baseline; and
- a full live-shadow gate requiring the graph and hybrid retrieval path.

ADR 0001 and ADR 0002 remain Proposed until this topic is accepted, amended or rejected.

### Topic 13 — Implementation and migration

- **Rejected from the first Draft:** a graph-less discovery-only implementation followed by later GraphRAG integration.
- **Retained for reconsideration:** side-by-side migration from the legacy pool, scheduler-neutral commands, append-only authority, generic adapters before live sources, no legacy event identity import, no silent dual-write, Evidence Intake isolation, milestone PRs and explicit activation gates.
- **Required revision:** replace the temporary `DiscoveryStore`-first architecture with one canonical relational-plus-GraphRAG delivery programme consistent with Topic 12 and final ADR decisions.
- **Blocked:** no implementation plan may be accepted until Topic 12 resolves the graph authority, ontology, projection and engine-qualification boundaries.

## Topic 12 completion condition

Topic 12 is complete when the owner:

1. accepts, amends or rejects the governed GraphRAG specification;
2. accepts, amends or rejects the authority boundary in ADR 0001;
3. accepts, amends or rejects the integrated SQLite-ledger boundary in ADR 0002;
4. confirms the first POC lane and GraphRAG timing gate; and
5. leaves every runtime action behind later implementation, evaluation and operational approval.

Topic 13 then rewrites the implementation and migration plan. ADR 0004 receives its final decision only after that integrated plan is reviewable.

## Change discipline

Before the final documentation PR:

1. update all document statuses and cross-references;
2. supersede or rewrite the first Topic 12 implementation Draft;
3. remove stale false-acceptance text;
4. validate links and requirement references;
5. record all Needs-experiment and deferred decisions explicitly;
6. consolidate branch commits where feasible; and
7. do not include production code or activate any runtime path.
