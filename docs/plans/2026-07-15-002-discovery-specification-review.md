# Discovery specification review sequence

**Status:** Active review sequence  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. This document records owner decisions and organises review; it authorises no code, external request, model call, spending, shadow run, canary or production activation.  
**Related architecture proposal:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md)  
**Topic 12 plan:** [`2026-07-16-003-discovery-implementation-and-migration.md`](2026-07-16-003-discovery-implementation-and-migration.md)

## Purpose

Review news discovery in bounded topics so research findings, product decisions, specifications, experiments and implementation plans are not collapsed into one approval.

A committed Draft, passing test, merged PR, Proposed plan or Proposed ADR is not owner approval. Runtime authority is always separate from specification acceptance.

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
| 12. Implementation and migration | Architecture consolidation, milestones, tests, rollout and rollback | Drafted; owner review pending | [`2026-07-16-003-discovery-implementation-and-migration.md`](2026-07-16-003-discovery-implementation-and-migration.md) |

## Cross-topic boundaries

The following distinctions are now accepted:

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
- shadow is not production authority;
- discovery is not evidence acquisition; and
- implementation plan cannot create requirements absent from Accepted specifications.

## Decision record

### Topic 0 — Decision-state repair

- **Agreed:** discovery decisions are reviewed sequentially.
- **Agreed:** ADR 0004 remains Proposed until explicitly accepted, amended, split or rejected.
- **Agreed:** research, Draft specifications and Proposed plans or ADRs authorise no implementation.
- **Deferred cleanup:** remove any stale false-acceptance text in the large integrated architecture plan before the documentation PR is opened.

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
- **Agreed:** watch/defer is a first-class outcome with a Watch Condition.
- **Agreed:** Evidence Handoff requires durable acknowledgement and idempotent retry.

### Topic 3 — Records

- **Agreed:** internal identity is separate from URL, provider ID and digest.
- **Agreed:** Source Definition, Item, Revision and Representation are separate and versioned.
- **Agreed:** Signals, Leads, Hypotheses, Candidates and Handoffs are immutable and append-only.
- **Agreed:** Coverage Gaps require reviewed misses.
- **Deferred:** physical schema, retention and product-wide database architecture.

### Topic 4 — Sources

- **Agreed:** coverage obligations determine source selection.
- **Agreed:** source roles and portfolio functions are explicit; silent fallback is prohibited.
- **Agreed:** official, media, RSS and search are not sufficient purposes.
- **Agreed:** the research shortlist is validation work, not coverage completeness or run authority.
- **Agreed:** devolved paths, courts/elections, UK–Hong Kong travel/aviation, Hong Kong courts and a global radar remain mandatory pre-production source work.

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

### Topic 12 — Implementation and migration

The Draft plan proposes:

- a side-by-side discovery v2 rather than in-place mutation of legacy events;
- a scheduler-neutral deterministic command surface;
- a separate append-only `DiscoveryStore` with an initial SQLite implementation for offline, replay and shadow;
- generic adapters before live named sources;
- an evaluation Evidence Intake sink before real downstream integration;
- milestone PRs from semantic kernel through live shadow, canary, activation and legacy retirement;
- no legacy quota or source-count ranking carry-forward; and
- no runtime authority from plan acceptance alone.

ADR 0004 has been amended into its final Proposed architecture form and is ready for the owner's decision together with Topic 12.

## Topic 12 completion condition

Topic 12 is complete when the owner:

1. accepts, amends or rejects the implementation plan;
2. accepts, amends, splits or rejects ADR 0004;
3. confirms that the current branch remains documentation-only;
4. confirms whether the documentation PR may be prepared and opened; and
5. leaves every runtime action behind its later milestone-specific approval gate.

## Change discipline

Before the final documentation PR:

1. update all document statuses and cross-references;
2. remove stale false-acceptance text;
3. validate links and requirement references;
4. record all Needs-experiment and deferred decisions explicitly;
5. consolidate branch commits where feasible; and
6. do not include production code or activate any runtime path.
