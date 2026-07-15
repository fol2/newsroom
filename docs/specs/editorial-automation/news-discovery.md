# News discovery specification

**Status:** Draft  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Active review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Accepted record semantics:** [`discovery-record-semantics.md`](discovery-record-semantics.md)  
**Accepted source roles:** [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md)  
**Related change-semantics draft:** [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md)  
**Related architecture plan:** [`../../plans/2026-07-15-001-integrated-newsroom-architecture.md`](../../plans/2026-07-15-001-integrated-newsroom-architecture.md)  
**Related reference:** [`../../reference/editorial/product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 3–6 and 13  
**Related proposal:** [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md) (`Proposed`; owner review pending)  
**Decision state:** Coverage, workflow, record semantics, source roles and candidate-selection rules are Accepted. Change semantics, triage, search, shadow evaluation, operations and final architecture remain under sequential owner review.  
**Supersedes:** None

## Purpose

Define cross-cutting discovery controls for monitoring the accepted coverage boundary through the accepted workflow, identity model and source portfolio without treating discovery as evidence or spending model work merely to prove that nothing changed.

Coverage defines what must be sought. Workflow defines how work moves. Record semantics define identity and lineage. Source roles define why a source is included. Topic 5 now proposes what source changes and Planned expectations mean. This file must not redefine those accepted contracts to fit an endpoint, provider or implementation.

## Scope

This specification covers source-architecture controls, change-driven collection, bounded search, coverage auditing and cross-cutting safeguards.

Detailed transitions are in [`discovery-workflow.md`](discovery-workflow.md); identities are in [`discovery-record-semantics.md`](discovery-record-semantics.md); source roles and candidate paths are in [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md); source-change and Planned Agenda meaning is under Topic 5 review; triage and grouping belong to Topic 6; search to Topic 7; shadow evaluation to Topic 8; and operations to Topic 9.

It does not claim that the current Brave-, RSS-, GDELT- and Gemini-based pool conforms, and it does not authorise implementation.

## Review state

The accepted Topic 1–4 contracts are mandatory bases for later decisions. Requirements below remain Draft where they depend on the unresolved complete source-registry architecture, change semantics, search, operations or evaluation.

ADR 0004 remains Proposed until the complete architecture decision is reviewed.

## Requirements

### Source architecture

**DISC-001 — Portfolio-first discovery.** The proposed primary production boundary is an owner-approved source portfolio aligned to the accepted coverage and source-role contracts, not one recurring broad search query per beat. This remains subject to ADR 0004 review.

**DISC-002 — Source purpose.** Every enabled Source Definition Version MUST identify its accepted coverage mapping, source role, portfolio function, geography, publisher, interface and permitted use.

**DISC-003 — Source-native transport.** An adapter SHOULD prefer a permitted structured interface such as API, webhook, calendar, RSS or Atom. Selector-based change detection MAY fill an explicit high-value gap. Whole-site crawling or general browser automation MUST NOT be the default.

**DISC-004 — No silent broad fallback.** Missing, invalid or empty production source configuration MUST fail closed. A collector MUST NOT silently substitute broad media feeds, generic search or a weaker source role.

**DISC-005 — Rights before collection.** A production Source Definition Version MUST reference an owner-approved rights and permitted-use record. Public availability, official status or an allowed robots path does not authorise retrieval, retention, model submission, quotation or display.

**DISC-006 — Planned Agenda.** Known releases, proceedings, effective dates and deadlines within accepted coverage SHOULD be represented independently from breaking or routine watch. Exact Agenda and occurrence semantics belong to Topic 5.

**DISC-007 — Smallest sufficient portfolio.** A source portfolio MUST be no larger than necessary after accepted obligations, resilience and evaluation functions are met. It MUST NOT minimise endpoint count by leaving an Active obligation without a credible Anchor or explicit launch-blocking gap.

**DISC-008 — Source readiness.** Acceptance of a source role or shortlist does not authorise collection. Each executable source MUST pass the accepted editorial, rights, technical, operational and evaluation gates.

### Change-driven collection

**DISC-010 — Change before work.** Routine collection MUST establish an accepted candidate observable transition before downstream editorial work. A successful unchanged check MUST NOT invoke a model.

**DISC-011 — Per-source state.** Each enabled source MUST retain enough inspectable state to distinguish unchanged content, a new or revised item, a current-state transition, a Planned expectation and a failed check. Physical storage is not defined here.

**DISC-012 — Conditional retrieval.** Where supported, collectors SHOULD use `If-None-Match`, `If-Modified-Since` and valid `304 Not Modified` responses. Validators are retrieval optimisations, not proof of substantive change.

**DISC-013 — Failure semantics.** Parser, authentication, rights, transport, malformed-content and quarantine outcomes remain distinct from successful unchanged, disappearance and missed-expectation outcomes.

**DISC-014 — Delivery semantics.** Collection MAY be at-least-once, but downstream transitions MUST be idempotent against accepted identities and versions.

**DISC-015 — Quarantine.** A source or adapter that no longer satisfies its contract enters a visible degraded or quarantined state. Layout churn or parser failure MUST NOT be emitted as publisher change.

**DISC-016 — Observation-model constraint.** Transition inference MUST remain within the accepted observation model for the exact Source Definition Version. Feed-window disappearance, partial snapshots and clock passage cannot be silently converted into withdrawal, ending or occurrence.

### Discovery states and gates

**DISC-020 — Discovery Signal.** Every accepted candidate observable transition enters through the Discovery Signal contract with exact source, item, revision, representation and lineage references. A Signal is not evidence.

**DISC-021 — Deterministic gates.** Before model work, the system applies versioned checks for adapter integrity, stable identity, accepted duplication, observable newness, time and version validity, and unambiguous scope or exclusion rules.

**DISC-022 — Ambiguity preserves recall.** Materiality, cross-geography relevance, development status or transition meaning ambiguity MUST NOT be silently converted into deterministic editorial rejection. It proceeds to Lead triage or an operational hold as appropriate.

**DISC-023 — News Lead.** A Signal becomes a Lead only through a committed Gate Decision and retains exact lineage. A Lead is eligible for triage and is not evidence.

**DISC-024 — Story Candidate.** One or more Leads become a Candidate only through accepted retrieval, proposal validation and deterministic Candidate admission. The exact Candidate Version and basis are recorded.

**DISC-025 — Evidence boundary.** Discovery MUST NOT create a Source Observation, Governed Claim, Evidence Package or publication authority. Evidence acquisition independently retrieves and governs current permitted source material.

**DISC-026 — Inspectable outcome.** Every processed Check, Signal, Lead, Agenda expectation and Candidate handoff retains an inspectable outcome. Final reason strings remain for Topic 10.

### Model and search boundary

**DISC-030 — No model for an empty tick.** Scheduling, preflight, collection, parsing, baseline comparison and unchanged detection MUST complete without waking a model merely to confirm no work.

**DISC-031 — Bounded triage.** Model assistance operates on bounded Triage Work Items rather than unconditional calls per collected item. Prompts and outputs are versioned, structured and untrusted. Topic 6 decides batch formation and urgent exceptions.

**DISC-032 — Deferred full acquisition.** Discovery SHOULD use source-supplied metadata and minimum permitted changed fragments. Full evidence acquisition begins only after Candidate admission, except for approved replay or evaluation fixtures.

**DISC-033 — Search role unresolved.** Search remains provider-neutral and separately metered until Topic 7 defines accepted roles. It MUST NOT become an unbounded firehose or silently compensate for a missing Anchor.

**DISC-034 — Search triggers.** Automated search MAY run only under a later accepted role and rule, such as an observed gap, failed selected path, missed expected occurrence, authorised lead or bounded audit sample.

**DISC-035 — Enforced budget.** Every automated search provider MUST have an enforced request and cost budget. Exhaustion creates a visible outcome and cannot trigger unapproved switching or weaker gates.

**DISC-036 — Recall interpretation.** GDELT, media feeds and search indexes are not recall ground truth. Coverage evaluation combines bounded comparisons with reviewed missed-story decisions and Coverage Gaps.

### Safeguards and validation

**DISC-040 — No scoring decision.** This specification does not define numeric weights. Coverage, deterministic gates and editorial triage precede later prioritisation.

**DISC-041 — Origins, not volume.** Article or domain count does not establish newsworthiness or independent coverage. Common origins and dependencies remain distinguishable.

**DISC-042 — No discovery quota.** Discovery and triage support zero Leads and zero Candidates. Beat balance, cadence or unused capacity cannot promote a weaker signal.

**DISC-050 — Shadow audit.** Any authorised shadow discovery retains exact lineage sufficient to compare portfolio paths, change detection and reviewed misses. Topic 8 defines protocol and interpretation.

**DISC-051 — Source health.** Operational checks make failed, partial, stale or broken sources and bounded-search usage visible. Detailed objectives belong to Topic 9.

**DISC-052 — Shadow evaluation.** A proposed source portfolio, observation model and adapters MUST pass owner-approved shadow evaluation before production authority. A shortlist does not authorise execution.

**DISC-053 — Coverage feedback.** A relevant development found only through another permitted path may create a reviewed Coverage Gap. Closing it SHOULD improve coverage, source selection or workflow rather than create an unexamined broad-search dependency.

## Acceptance criteria

1. An unchanged selected source completes without a model call or Lead.
2. Invalid production source configuration fails closed instead of activating broad defaults.
3. A parser break remains failure or quarantine and is not reported as no news or publisher change.
4. Repeated delivery creates at most one equivalent semantic transition while retaining Occurrences.
5. An official rule revision can be considered without several outlets repeating it.
6. A rolling-feed disappearance cannot be treated as withdrawal without a source contract that supports the inference.
7. A partial current-state snapshot cannot clear an active warning by absence.
8. Media, search and index results cannot enter an Evidence Package merely because discovery found them.
9. A Planned expectation reaching its date does not itself become occurrence evidence or a Candidate.
10. Search budget exhaustion remains visible and cannot be bypassed.
11. A Candidate preserves exact contributing lineage while evidence acquisition creates its own Source Observations.
12. No shadow run or production implementation is authorised until applicable change, triage, search, evaluation and operational decisions are accepted.

## Non-goals

This specification does not select implementation mechanisms, schedules, storage, evidence store or RAG technology.

It does not define evidence extraction, claim admission, drafting or publication gates beyond their boundary from discovery.

## Open questions

- Will the owner accept, amend or reject the Topic 5 change and Planned Agenda semantics?
- How will Topic 6 form Triage Work Items and Event Hypotheses?
- What role, if any, does recurring or on-demand search play at launch?
- What shadow method is sufficient to justify production authority?
- What source-health and retry thresholds are required for production?
