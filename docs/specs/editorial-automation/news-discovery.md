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
**Accepted change semantics:** [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md)  
**Accepted triage contract:** [`discovery-triage-and-event-grouping.md`](discovery-triage-and-event-grouping.md)  
**Accepted search contract:** [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md)  
**Related evaluation draft:** [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md)  
**Related architecture plan:** [`../../plans/2026-07-15-001-integrated-newsroom-architecture.md`](../../plans/2026-07-15-001-integrated-newsroom-architecture.md)  
**Related reference:** [`../../reference/editorial/product-editorial-charter.zh-HK.md`](../../reference/editorial/product-editorial-charter.zh-HK.md), sections 3–6 and 13  
**Related proposal:** [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md) (`Proposed`; owner review pending)  
**Decision state:** Topics 1–7 are Accepted. Shadow evaluation, operations, outcome vocabulary, locality and the final architecture decision remain under sequential owner review.  
**Supersedes:** None

## Purpose

Define cross-cutting discovery controls for monitoring the accepted coverage boundary through the accepted workflow, identity, source-role, change, triage and search contracts without treating discovery as evidence or spending model work merely to prove nothing changed.

This document does not replace the focused specifications. It records the architectural invariants that span them and remains Draft until the remaining evaluation and operational decisions permit ADR 0004 to be reconsidered.

## Scope

This specification covers source-architecture controls, change-driven collection, bounded search, coverage auditing and cross-cutting safeguards.

Detailed semantics are defined in the focused Topic 1–7 specifications. Topic 8 owns release evidence; Topic 9 operations; Topic 10 final outcomes and prioritisation; Topic 11 locality; and Topic 12 implementation planning.

It does not claim that the current Brave-, RSS-, GDELT- and Gemini-based pool conforms and authorises no implementation.

## Review state

The Accepted Topic 1–7 contracts are mandatory bases for later work. Requirements below remain Draft where they depend on unresolved shadow thresholds, operations, final source admission or the complete architecture decision.

ADR 0004 remains Proposed.

## Requirements

### Source architecture

**DISC-001 — Portfolio-first discovery.** The proposed primary production boundary is an owner-approved source portfolio aligned to accepted coverage and source-role contracts, not one recurring broad search query per beat. Final acceptance remains subject to ADR 0004 review.

**DISC-002 — Source purpose.** Every enabled Source Definition Version MUST identify accepted coverage mapping, source role, portfolio function, geography, publisher, interface and permitted use.

**DISC-003 — Source-native transport.** An adapter SHOULD prefer a permitted API, webhook, calendar, RSS or Atom interface. Selector-based change detection MAY fill an explicit high-value gap. Whole-site crawling and general browser automation MUST NOT be the default.

**DISC-004 — No silent broad fallback.** Missing or invalid production source configuration MUST fail closed. A collector MUST NOT substitute broad media feeds, generic search or a weaker source role silently.

**DISC-005 — Rights before collection.** Every executable Source Definition Version MUST reference an owner-approved rights and permitted-use record. Public availability, official status and robots access do not independently authorise retrieval, retention, model submission, quotation or display.

**DISC-006 — Planned Agenda.** Known releases, proceedings, effective dates and deadlines within accepted coverage use the Accepted Agenda and occurrence-confirmation semantics.

**DISC-007 — Smallest sufficient portfolio.** A portfolio is minimised only after accepted obligations, resilience and evaluation needs are met. Endpoint count MUST NOT be reduced by leaving an Active obligation without a credible Anchor or explicit blocker.

**DISC-008 — Source readiness.** Acceptance of roles or a shortlist does not authorise collection. Executable sources must pass editorial, rights, technical, evaluation and operational gates.

### Change-driven collection

**DISC-010 — Change before editorial work.** Routine collection MUST establish an accepted candidate observable transition before downstream editorial work. A successful unchanged check MUST NOT invoke a model.

**DISC-011 — Per-source state.** Each enabled source MUST retain inspectable state sufficient to distinguish unchanged content, item or Revision change, current-state transition, Planned expectation and failed check.

**DISC-012 — Conditional retrieval.** Where supported, collectors SHOULD use ETag and `Last-Modified` validators. Validators are retrieval optimisations, not proof of substantive change.

**DISC-013 — Failure semantics.** Parser, authentication, rights, transport, malformed-content, rate-limit and quarantine outcomes remain distinct from unchanged, disappearance, zero-result and missed-expectation outcomes.

**DISC-014 — Delivery semantics.** Collection MAY be at least once, but semantic transitions MUST remain idempotent against Accepted identities and versions.

**DISC-015 — Quarantine.** A source or adapter outside its contract enters visible degraded or quarantined state. Parser failure and layout churn MUST NOT be emitted as publisher change.

**DISC-016 — Observation-model constraint.** Transition inference MUST remain within the observation model for the exact Source Definition Version. Feed-window disappearance, partial snapshots and clock passage cannot become withdrawal, ending or occurrence silently.

### Discovery states, gates and triage

**DISC-020 — Discovery Signal.** Every candidate observable transition enters through the Accepted Signal contract with exact source, item, Revision, Representation and lineage references. A Signal is not evidence.

**DISC-021 — Deterministic gates.** Before editorial triage, the system applies versioned integrity, identity, duplicate, observable-newness, time-validity and unambiguous scope or exclusion checks.

**DISC-022 — Ambiguity preserves recall.** Materiality, cross-geography relevance, development status and transition ambiguity MUST NOT become deterministic editorial rejection silently. They proceed to Lead triage or Operational hold.

**DISC-023 — News Lead.** A Signal becomes a Lead only through a committed Gate Decision. It retains exact lineage and is not evidence.

**DISC-024 — Story Candidate.** Leads become a Candidate only through Accepted bounded retrieval, structured proposal validation and deterministic Candidate admission.

**DISC-025 — Evidence boundary.** Discovery MUST NOT create Source Observations, Governed Claims, Evidence Packages or publication authority. Evidence acquisition independently retrieves and governs current permitted source material.

**DISC-026 — Inspectable outcome.** Every Check, Signal, Lead, Agenda expectation, triage decision, search request and Candidate handoff retains an inspectable outcome.

### Model, batching and search

**DISC-030 — No model for an empty tick.** Scheduling, preflight, collection, parsing, baseline comparison and unchanged detection MUST complete without waking a model merely to confirm no work.

**DISC-031 — Bounded triage.** Model assistance operates on bounded Triage Work Items. Execution batching does not imply event grouping. Prompts and outputs are versioned, structured and untrusted.

**DISC-032 — Deferred full acquisition.** Discovery SHOULD use source metadata and minimum permitted changed fragments. Full evidence acquisition begins after Candidate admission except for approved replay or evaluation fixtures.

**DISC-033 — Search is supplemental.** Search is provider-specific, separately metered and limited to the Accepted Topic 7 purposes. It MUST NOT become an Active Anchor, generic firehose or silent source replacement.

**DISC-034 — Search triggers.** Automated search runs only through an Accepted Search Purpose, authorised Request, privacy validation and enforced budget.

**DISC-035 — Enforced budget.** Search request, result, expansion, retry, cost and downstream-work limits are hard. Exhaustion is visible and cannot cause unapproved provider switching.

**DISC-036 — Recall interpretation.** Search, media indexes, Comparators and the legacy pipeline are not ground truth. Coverage Gaps require reviewed prospective or explicitly retrospective evidence.

### Evaluation and safeguards

**DISC-040 — No scoring decision.** This specification defines no numeric prioritisation weights. Coverage, deterministic gates and editorial triage precede later scoring decisions.

**DISC-041 — Origins, not volume.** Article, result or domain count does not establish newsworthiness, independence, coverage or event identity. Common origins and dependencies remain visible.

**DISC-042 — No discovery quota.** Discovery and triage support zero Leads and zero Candidates. Beat balance, cadence and capacity cannot promote weaker work.

**DISC-050 — Prospective evaluation.** Any authorised shadow evaluation MUST use a pre-registered Evaluation Plan, frozen Epoch and rights-permitted prospective methods as defined by Topic 8 when Accepted.

**DISC-051 — Source and provider health.** Failed, partial, stale, rate-limited and broken source or provider paths remain visible. Detailed objectives belong to Topic 9.

**DISC-052 — Production evidence.** Source portfolio, observation model, triage policy, search role and adapters MUST pass owner-approved evaluation and operational qualification before production authority.

**DISC-053 — Coverage feedback.** A relevant development found through another permitted path may create a reviewed Coverage Gap. Remediation SHOULD improve source roles, adapters or workflow rather than create an unexamined broad-search dependency.

**DISC-054 — Shadow is not authority.** A shadow shortlist, Run, Candidate outcome or Comparator result MUST NOT publish, mutate production authority or graduate silently into production.

## Acceptance criteria

1. An unchanged source completes without model call or Lead.
2. Invalid source configuration fails closed instead of activating broad defaults.
3. Parser failure remains failure or quarantine rather than no news or publisher change.
4. Repeated delivery produces at most one equivalent semantic transition while retaining Occurrences.
5. An official rule Revision can proceed without media repetition.
6. Rolling-feed disappearance cannot become withdrawal without a supporting source contract.
7. A partial snapshot cannot clear an active warning by absence.
8. Search and media results cannot enter evidence merely because discovery found them.
9. An Agenda date does not become occurrence evidence or Candidate.
10. An Execution Batch cannot establish one event.
11. Retrieval similarity cannot create a Hypothesis, merge or Candidate directly.
12. A generic search cannot be an Active Anchor.
13. Search exhaustion remains visible and cannot be bypassed.
14. A Candidate preserves exact lineage while evidence creates its own Source Observations.
15. Shadow produces no public effect and cannot create production Candidate authority.
16. No production implementation is authorised until evaluation, operations, prioritisation and locality decisions are completed as applicable.

## Non-goals

This specification does not select implementation mechanisms, schedules, storage, evidence store, RAG, model provider or deployment technology. It does not define evidence extraction, drafting or publication beyond the discovery boundary.

## Open questions

- Will the owner accept, amend or reject the Topic 8 evaluation protocol?
- Which operational objectives and containment rules will Topic 9 set?
- What final outcomes, reasons and prioritisation will Topic 10 define?
- What locality scope, if any, will Topic 11 add?
