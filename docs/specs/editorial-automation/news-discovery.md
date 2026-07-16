# News discovery specification

**Status:** Draft pending ADR 0004 and Topic 13 implementation-plan decisions  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Active review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted GraphRAG contract:** [`governed-graphrag-and-knowledge-projection.md`](governed-graphrag-and-knowledge-projection.md)  
**Topic 13 Draft:** [`../../plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md`](../../plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md)  
**Accepted architecture decisions:** [`../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md)  
**Related Proposed decision:** [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md)  
**Supersedes:** None

## Purpose

Record cross-cutting discovery invariants spanning the Accepted Topic 1–12 specifications. This file does not replace those focused specifications and remains Draft until ADR 0004 and Topic 13 receive owner decisions.

It does not claim that the current Brave, RSS, GDELT and Gemini pool conforms and authorises no implementation or runtime action.

## Accepted foundations

The focused contracts for coverage, workflow, record semantics, source roles, change and Agenda, triage, search, evaluation, operations, outcomes, locality and governed GraphRAG are Accepted.

Where this Draft conflicts with a focused Accepted specification or Accepted ADR, the focused record controls.

## Cross-cutting requirements

### Source architecture

**DISC-001 — Portfolio-first discovery.** The proposed production boundary is an owner-approved source portfolio aligned to Accepted coverage and source-role contracts, not one recurring generic search query per beat. Final discovery architecture authority remains subject to ADR 0004.

**DISC-002 — Source purpose.** Every executable Source Definition Version identifies accepted coverage mapping, source role, portfolio function, geography, publisher, interface and permitted use.

**DISC-003 — Source-native transport.** An adapter should prefer a permitted API, webhook, calendar, RSS or Atom interface. Maintained-document or selector-based change detection may fill an explicit high-value gap. Whole-site crawling and general browser automation are not the default.

**DISC-004 — No silent broad fallback.** Missing or invalid production source configuration fails closed. Broad media feeds, generic search and weaker source roles are never substituted silently.

**DISC-005 — Rights before collection.** Every executable source and channel references an owner-approved permitted-use record. Public availability, official status and robots access do not independently authorise retrieval, retention, model submission, quotation or display.

**DISC-006 — Planned Agenda.** Known releases, proceedings, effective dates and deadlines use the Accepted Agenda identity, version and occurrence-confirmation semantics.

**DISC-007 — Smallest sufficient portfolio.** The portfolio is minimised only after coverage, resilience and evaluation needs are satisfied. Endpoint count cannot leave an Active obligation without a credible Anchor or explicit blocker.

**DISC-008 — Source readiness.** A source shortlist creates no authority. Executable use requires editorial, rights, technical, evaluation and operational gates.

### Change-driven collection

**DISC-010 — Change before editorial work.** Routine collection establishes an accepted candidate observable transition before downstream editorial work. A successful unchanged check invokes no model and creates no Lead.

**DISC-011 — Per-source state.** Each enabled source retains inspectable state sufficient to distinguish unchanged content, item or Revision change, current-state transition, Planned expectation and failed check.

**DISC-012 — Conditional retrieval.** Where supported, collectors use ETag or `Last-Modified` validators. Validators optimise retrieval and do not prove substantive change.

**DISC-013 — Failure honesty.** Parser, authentication, rights, transport, malformed-content, rate-limit, budget and quarantine outcomes remain distinct from unchanged, disappearance, zero results and missed expectation.

**DISC-014 — Delivery semantics.** Collection may be at least once, while semantic effects remain idempotent against Accepted identities and versions.

**DISC-015 — Quarantine.** A source or adapter outside its contract enters visible degraded or quarantined state. Parser failure and layout churn do not become publisher change.

**DISC-016 — Observation-model constraint.** Transition inference remains within the exact Source Definition Version's observation model. Rolling-list disappearance, partial snapshots and clock passage do not silently become withdrawal, ending or occurrence.

### Discovery states and authority

**DISC-020 — Discovery Signal.** Every accepted candidate transition enters through the Signal contract with exact source, Item, Revision, Representation and lineage. A Signal is not evidence.

**DISC-021 — Deterministic gates.** Before editorial triage, versioned integrity, identity, duplicate, observable-newness, time-validity and unambiguous exclusion checks run.

**DISC-022 — Ambiguity preserves recall.** Materiality, cross-geography relevance, development status and transition ambiguity do not become deterministic editorial rejection. They proceed to Lead triage or an Operational hold.

**DISC-023 — News Lead.** A Signal becomes a Lead only through a committed Gate Decision and retains exact lineage.

**DISC-024 — Story Candidate.** Leads become a Candidate only through bounded retrieval, structured proposal validation and deterministic Candidate admission.

**DISC-025 — Evidence boundary.** Discovery creates no Source Observation, Governed Claim, Evidence Package or publication authority. Evidence Intake independently retrieves and governs current permitted source material.

**DISC-026 — Inspectable outcome.** Every Check, Signal, Lead, Agenda expectation, triage decision, search request, evaluation decision, operational assessment, locality decision, graph proposal or admission and Candidate Handoff retains an inspectable outcome.

### Models, grouping and search

**DISC-030 — No model for an empty tick.** Due-work calculation, preflight, source checking, parsing, baselining and unchanged detection complete without waking a model merely to confirm no work.

**DISC-031 — Bounded triage.** Model assistance operates on bounded Triage Work Items. Execution batching does not imply event grouping. Output is structured, versioned and untrusted.

**DISC-032 — Deferred full acquisition.** Discovery uses permitted metadata and minimum necessary changed fragments. Full evidence acquisition begins after Candidate admission except for approved fixtures or replay.

**DISC-033 — Search is supplemental.** Search is provider-specific, separately metered and limited to Accepted Search Purposes. It is not an Active Anchor, generic firehose, evidence source or silent replacement.

**DISC-034 — Search control.** Automated search runs only through an authorised Search Request with privacy validation, rights and enforced budgets.

**DISC-035 — Hard search budget.** Request, result, expansion, retry, cost and downstream-work limits are enforced. Exhaustion remains visible and causes no provider switching.

**DISC-036 — Recall interpretation.** Search, media indexes, Comparators and the legacy pipeline are not ground truth. Coverage Gaps require reviewed prospective or explicitly retrospective evidence.

### Evaluation, operations, outcomes and locality

**DISC-040 — No governing global score.** Accepted gates, semantic routes and ordinal lanes govern launch. Any bounded stage-local score remains Needs experiment and cannot override gates.

**DISC-041 — Origins, not volume.** Article, result and domain count do not establish newsworthiness, independence, coverage, event identity or Candidate priority. Common origins remain visible.

**DISC-042 — No discovery quota.** Discovery supports zero Leads and zero Candidates. Beat, category, geography, finance, cadence and capacity quotas cannot promote weaker work or create filler.

**DISC-050 — Prospective evaluation.** Qualification uses an owner-approved Evaluation Plan, frozen Epoch, event-level prospective universe, authorised labels, required slices and explicit release-evidence decision.

**DISC-051 — Operational health.** Failed, partial, stale, rate-limited, blocked and broken paths remain distinct from successful silence under exact Operational Profiles.

**DISC-052 — Production evidence.** Source portfolio, observation models, triage policy, search roles, GraphRAG components and adapters pass Accepted evaluation and operational qualification before production authority.

**DISC-053 — Coverage feedback.** Relevant developments found through another permitted path may create reviewed Coverage Gaps. Remediation should improve sources, adapters or workflow rather than create an unexamined broad-search dependency.

**DISC-054 — Shadow is not authority.** A shortlist, shadow Run, Candidate outcome or Comparator result cannot publish, mutate production authority or graduate silently.

**DISC-055 — Operational Admission is scoped.** Production eligibility binds exact versions, Profiles, objectives, alerts, capacity, recovery, contingency, canary and rollback. Admission is not activation.

**DISC-056 — Outcome and priority separation.** Outcome, reason, next action, current status and processing priority remain separate. Priority and score cannot change eligibility or disposition.

**DISC-057 — Locality-aware boundary.** Material local UK stories remain eligible wherever discovered, while no fixed locality receives systematic all-topic monitoring without an exact Locality Coverage Decision.

**DISC-058 — Locality precision and source classes.** Locality labels use evidence-supported, versioned boundaries. Selecting one local source class does not select all local news.

**DISC-059 — Event-Scoped Local Watch.** A bounded local watch identifies exact event purpose, source set, owner, budget and expiry and creates no permanent locality promise.

### Governed GraphRAG boundary

**DISC-060 — Graph-aware canonical contract.** Graph-projection identities, trust, temporal and ordered-event contracts exist in canonical schema v1 rather than a later semantic migration.

**DISC-061 — Relational and object authority.** The relational editorial ledger owns authoritative Newsroom records and governed object storage owns exact retained permitted bytes and hashes. Graph, vector and full-text stores are rebuildable projections.

**DISC-062 — Proposal and admission.** Graphiti or another extractor may create entity and relation proposals but cannot write governed editorial relations directly. Separate admission decisions remain authoritative.

**DISC-063 — Hybrid retrieval.** Event and development retrieval combines exact, full-text, vector and bounded graph paths with trust-labelled provenance. Similarity and graph proximity remain context rather than authority.

**DISC-064 — Graph failure honesty.** Projection lag, gap or outage cannot be interpreted as no prior event or no relationship. Graph-dependent decisions use an accepted exact fallback or enter Watch or Operational Hold.

**DISC-065 — GraphRAG timing.** The graph ontology, projector, extraction governance, hybrid retrieval and evaluation path belong to the first implementation programme and must be included before complete live-shadow qualification.

**DISC-066 — Named read-only tools.** Agentic retrieval uses bounded named tools rather than unrestricted graph write access or general production Cypher authority.

### Migration boundary — proposed in Topic 13

**DISC-070 — Canonical schema v1.** Topic 13 proposes one graph-aware canonical schema and event contract shared by test, replay, shadow and later production environments.

**DISC-071 — Legacy non-authority.** Legacy links, event IDs, merges, scores and quotas may inform a Comparator but do not become target identity or correctness ground truth.

**DISC-072 — No silent dual-write.** New authoritative discovery and graph records are not written into legacy event authority silently. Any bridge is explicit, versioned and evaluated.

**DISC-073 — Evidence Intake dependency.** Complete production canary remains blocked until governed Evidence Intake exists. Discovery cannot bridge directly to publication.

**DISC-074 — Milestone authority.** Plan or code merge alone activates no source, provider, model, extractor, graph engine, shadow run, canary or production scope.

## Acceptance criteria

1. An unchanged source completes without model call or Lead.
2. Invalid configuration fails closed rather than activating broad defaults.
3. Parser failure remains failure or quarantine rather than no news or publisher change.
4. Repeated delivery produces at most one equivalent semantic transition while retaining Occurrences.
5. An official guidance Revision may proceed with one source and no media repetition.
6. Rolling-feed disappearance does not become withdrawal without a supporting source contract.
7. A partial snapshot cannot clear active state by absence.
8. Search and media results cannot enter evidence merely because discovery found them.
9. Agenda date does not become occurrence evidence or Candidate.
10. Execution Batch cannot establish one event.
11. Retrieval similarity cannot create a Hypothesis, merge or Candidate directly.
12. Generic search cannot be an Active Anchor.
13. Search exhaustion remains visible and cannot be bypassed.
14. Candidate preserves exact lineage while evidence creates its own observations.
15. Shadow creates no public effect or production Candidate authority.
16. Evaluation cannot claim absolute recall or pool changed Epochs silently.
17. Stale or failed source cannot be represented as healthy unchanged because it emitted no items.
18. Operational Admission cannot activate production by itself.
19. Media volume, quota and model confidence cannot override a gate.
20. Publishing a local story creates no locality-completeness promise.
21. Graphiti proposal cannot become an admitted relation through confidence alone.
22. Graph outage cannot become no prior match.
23. Graph rebuild cannot rerun extraction and silently rewrite historical relations.
24. Target implementation does not mutate legacy event authority silently.
25. No implementation is authorised until Topic 13 and ADR 0004 are decided and later milestone-specific gates pass.

## Open owner decisions

- Accept or amend the integrated Topic 13 implementation plan.
- Accept, amend, split or reject ADR 0004 against that plan.
- Determine whether this cross-cutting Draft should become Accepted or be superseded by the focused specifications plus ADRs.