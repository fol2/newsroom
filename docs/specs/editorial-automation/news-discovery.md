# News discovery specification

**Status:** Draft  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Active review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Accepted record semantics:** [`discovery-record-semantics.md`](discovery-record-semantics.md)  
**Related source-role draft:** [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md)  
**Related architecture plan:** [`../../plans/2026-07-15-001-integrated-newsroom-architecture.md`](../../plans/2026-07-15-001-integrated-newsroom-architecture.md)  
**Related reference:** [`../../reference/editorial/product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 3–6 and 13  
**Related proposal:** [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md) (`Proposed`; owner review pending)  
**Decision state:** Coverage, workflow and record semantics are Accepted. Source roles, source portfolio, search, orchestration, change semantics and shadow requirements remain under sequential owner review.  
**Supersedes:** None

## Purpose

Define candidate source-architecture and cross-cutting controls for monitoring the accepted coverage boundary through the accepted workflow and record model without treating discovery as evidence or spending model work merely to prove that nothing changed.

Coverage defines what must be sought. Workflow defines how work moves. Record semantics define identity and lineage. The Topic 4 Draft now proposes why sources are selected and how they form a portfolio. This file must not redefine those accepted contracts to fit an available endpoint or provider.

## Scope

This specification covers candidate source-architecture controls, source-native change detection, bounded search, coverage auditing and cross-cutting safeguards.

Detailed transitions are in [`discovery-workflow.md`](discovery-workflow.md); identities are in [`discovery-record-semantics.md`](discovery-record-semantics.md); source roles and candidates are under Topic 4 review; change semantics belong to Topic 5; triage and grouping to Topic 6; search to Topic 7; and shadow evaluation to Topic 8.

It defines proposed target behaviour for unresolved architecture topics. It does not claim that the current Brave-, RSS-, GDELT- and Gemini-based pool conforms, and it does not authorise implementation.

## Review state

The accepted coverage, workflow and record contracts are mandatory bases for later decisions. The requirements below remain Draft proposals where they depend on source architecture, search, change semantics, operations or evaluation.

Topic 4 is currently under owner review through `discovery-source-roles-and-selection.md`. Topic 7 will review search. Topic 8 will review shadow evaluation. ADR 0004 remains Proposed until the complete architecture decision is reviewed.

## Requirements

### Candidate source architecture

**DISC-001 — Direct-watch-first discovery.** The proposed primary production boundary is an owner-approved source portfolio aligned to the accepted coverage contract, not one recurring broad search query per beat. This remains subject to ADR 0004 review.

**DISC-002 — Source purpose.** Every enabled source MUST identify its accepted coverage mapping, discovery role, portfolio function, geography, publisher, interface and permitted use. Further metadata is defined when the source is activated.

**DISC-003 — Source-native transport.** An adapter SHOULD prefer a permitted structured interface such as API, webhook, calendar, RSS or Atom. Selector-based change detection MAY fill an explicit high-value gap. Whole-site crawling or general browser automation MUST NOT be the default.

**DISC-004 — No silent broad fallback.** A missing, invalid or empty production source configuration MUST fail closed. A collector MUST NOT silently substitute built-in broad media feeds, generic search or a weaker source role.

**DISC-005 — Rights before collection.** A production Source Definition Version MUST reference an owner-approved rights and permitted-use record. Public availability, official status or an allowed robots path does not authorise retrieval, retention, model submission, quotation or display.

**DISC-006 — Planned Agenda.** Known releases, proceedings, effective dates and deadlines within accepted coverage SHOULD be represented independently from breaking or routine watch. A Planned Agenda Item must identify an expected path and window; a missed release remains distinct from a successful unchanged check. Exact semantics belong to Topic 5.

**DISC-007 — Smallest sufficient portfolio.** A proposed source portfolio MUST be no larger than necessary after accepted obligations, resilience and evaluation functions are met. It MUST NOT minimise endpoint count by leaving an Active obligation without a credible candidate Anchor or explicit launch-blocking gap.

### Change-driven collection

**DISC-010 — Change before work.** Routine collection MUST determine whether a selected source emitted a new item or observable revision before creating downstream triage work. An unchanged check MUST NOT invoke a model.

**DISC-011 — Per-source state.** Each enabled source MUST retain enough inspectable state to distinguish unchanged content, a new or revised item and a failed check. Physical storage is not defined here.

**DISC-012 — Conditional retrieval.** Where supported, collectors SHOULD use `If-None-Match` or `If-Modified-Since` and valid `304 Not Modified` responses. Validators are an optimisation, not proof of correctness; source-specific identity and sanity checks still apply.

**DISC-013 — Failure semantics.** Parser, authentication, rights, transport, malformed-content and quarantine outcomes remain distinct from a successful unchanged check.

**DISC-014 — Delivery semantics.** Collection MAY be at-least-once, but downstream transitions MUST be idempotent against accepted identities and versions.

**DISC-015 — Quarantine.** A source or adapter that no longer satisfies its contract MUST enter a visible degraded or quarantined state. Layout churn or parser failure MUST NOT be emitted as substantive change.

### Discovery states and gates

**DISC-020 — Discovery Signal.** Every candidate observable transition enters through the accepted Discovery Signal contract with exact source, item, revision, representation and lineage references. A Signal is not evidence.

**DISC-021 — Deterministic gates.** Before model work, the system MUST apply versioned checks for adapter integrity, stable identity, accepted duplication, observable newness, time and version validity, and unambiguous scope or exclusion rules.

**DISC-022 — Ambiguity preserves recall.** Materiality, cross-geography relevance, development status or another editorial ambiguity MUST NOT be silently converted into deterministic rejection. The accepted workflow routes it to Lead triage or an operational hold.

**DISC-023 — News Lead.** A Signal becomes a Lead only through a committed Gate Decision and retains exact lineage. A Lead is eligible for triage and is not evidence.

**DISC-024 — Story Candidate.** One or more Leads become a Candidate only through accepted retrieval, proposal validation and deterministic Candidate admission. The exact Candidate Version and basis are recorded.

**DISC-025 — Evidence boundary.** Discovery MUST NOT create a Source Observation, Governed Claim, Evidence Package or publication authority. Evidence acquisition independently retrieves and governs current permitted source material.

**DISC-026 — Inspectable outcome.** Every processed Signal and Lead retains an inspectable outcome. Final reason strings remain for Topic 10.

### Model and search boundary

**DISC-030 — No model for an empty tick.** Scheduling, preflight, collection, parsing and unchanged detection MUST complete without waking a model merely to confirm no work.

**DISC-031 — Bounded triage.** Model assistance operates on bounded Triage Work Items rather than unconditional calls for every collected item. Prompts and outputs are versioned, structured and untrusted. Topic 6 decides batch formation and urgent exceptions.

**DISC-032 — Deferred full acquisition.** Discovery SHOULD use source-supplied metadata and minimum permitted changed fragments. Full evidence acquisition and retention begin only after Candidate admission, except for approved replay or evaluation fixtures.

**DISC-033 — Search-last, not search-zero.** The current proposal is a provider-neutral, separately metered search lane for roles later accepted in Topic 7. It MUST NOT become an unbounded firehose. Whether any recurring search participates at launch remains unresolved.

**DISC-034 — Search triggers.** Automated search MAY run only under a later accepted role and rule, such as an observed gap, failed selected path, missed planned release, authorised lead or bounded audit sample.

**DISC-035 — Enforced budget.** Every automated search provider MUST have an enforced request and cost budget. Exhaustion creates a visible outcome and cannot trigger unapproved provider switching or weaker gates.

**DISC-036 — Recall interpretation.** GDELT, media feeds and search indexes are not recall ground truth. Coverage evaluation combines bounded comparisons with reviewed missed-story decisions and Coverage Gaps.

### Basic safeguards and validation

**DISC-040 — No scoring decision.** This specification does not define numeric weights. Coverage, deterministic gates and editorial triage precede later prioritisation.

**DISC-041 — Origins, not volume.** Article or domain count does not establish newsworthiness or independent coverage. Common origins and dependencies must be distinguished.

**DISC-042 — No discovery quota.** Discovery and triage support zero Leads and zero Candidates. Beat balance, cadence or unused capacity cannot promote a weaker signal.

**DISC-050 — Shadow audit.** Any authorised shadow discovery retains enough exact lineage to compare portfolio paths and reviewed relevant misses. Topic 8 defines protocol and interpretation.

**DISC-051 — Source health.** Operational checks make failed or broken sources and bounded-search usage visible. Detailed objectives belong to Topic 9.

**DISC-052 — Shadow evaluation.** A proposed source portfolio and its adapters MUST pass owner-approved shadow evaluation before production authority. Committing a shortlist does not authorise execution.

**DISC-053 — Coverage feedback.** A relevant development found only through another permitted path may create a reviewed Coverage Gap. Closing it SHOULD improve coverage, source selection or workflow rather than create an unexamined dependency on broad search.

## Acceptance criteria

1. An unchanged selected source completes without a model call or Lead.
2. An invalid production source configuration fails closed instead of activating broad defaults.
3. A parser break remains a failure or quarantine and is not reported as no news or source change.
4. Repeated delivery creates at most one equivalent semantic transition while retaining Occurrences.
5. Clearly excluded entertainment may be rejected deterministically; ambiguous public-safety impact survives.
6. An official rule revision can be considered without several outlets repeating it.
7. Media, search and index results cannot enter an Evidence Package merely because discovery found them.
8. A missed Planned occurrence remains distinct from an unchanged check.
9. Search budget exhaustion is visible and cannot be bypassed.
10. A Candidate preserves exact contributing lineage while evidence acquisition creates its own Source Observations.
11. No source portfolio, shadow run or production implementation is authorised until the applicable source, change, triage, search, evaluation and operational decisions are accepted.

## Non-goals

This specification does not select implementation mechanisms, schedules, storage, evidence store or RAG technology.

It does not define evidence extraction, claim admission, drafting or publication gates beyond their boundary from discovery.

## Open questions

- Will the owner accept, amend or reject the proposed source roles, portfolio functions and candidate paths in Topic 4?
- What exact source-change and Planned Agenda semantics are required?
- How will triage form batches and Event Hypotheses?
- What role, if any, does recurring or on-demand search play at launch?
- What shadow method is sufficient to justify production authority?
