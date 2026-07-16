# Discovery prioritisation and outcome-vocabulary specification

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Accepted by owner:** 2026-07-15  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Accepted record semantics:** [`discovery-record-semantics.md`](discovery-record-semantics.md)  
**Accepted source roles:** [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md)  
**Accepted change semantics:** [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md)  
**Accepted triage contract:** [`discovery-triage-and-event-grouping.md`](discovery-triage-and-event-grouping.md)  
**Accepted search contract:** [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md)  
**Accepted evaluation contract:** [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md)  
**Accepted operations contract:** [`discovery-reliability-and-operations.md`](discovery-reliability-and-operations.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Implementation authority:** None. Acceptance defines decision order, semantic outcomes, reasons and ordinal priority. It authorises no score, threshold, queue configuration, model call, source collection, shadow run, spending or production activation.  
**Supersedes:** None

## Purpose

Define a stable decision order and vocabulary for discovery outcomes, reasons and work priority without allowing one score, media volume, category quota, model confidence or queue pressure to override accepted coverage, authority, rights, integrity or editorial gates.

The system keeps four questions separate:

1. **Outcome:** what happened or was committed?
2. **Reason:** why was that outcome committed?
3. **Next action:** what retry, watch, hold, handoff or closure follows?
4. **Priority:** when should otherwise executable work be processed?

They MUST NOT be collapsed into one mutable status or global scalar score.

## Scope

This specification defines:

- non-bypassable decision order;
- canonical semantic outcome families;
- immutable decision, terminality and re-entry semantics;
- namespaced reason families and basis classes;
- ordinal priority lanes and within-lane ordering;
- fairness, deadline and starvation controls;
- prohibited ranking proxies and quota behaviour; and
- the boundary for any later stage-local numeric score.

It does not define numeric weights, queue times, service objectives, model or scheduler implementation, publication ordering, notification priority or locality expansion.

Exact timing belongs to approved Operational Profiles. Numeric prioritisation remains **Needs experiment** until an owner-approved evaluation shows that a bounded stage-local score improves on the ordinal baseline without violating this contract.

## Current-system replacement boundary

The legacy pool ranks daily Candidates mainly by trusted-domain count, unique-domain count, weighted source score and recency, then applies finance and category caps and one-to-two guaranteed Hong Kong slots. Hourly selection prioritises legacy child events and category diversity.

Those rules are not target authority:

- repeated media coverage is not newsworthiness or independent origin;
- one direct official Revision may justify evidence work;
- category or geography quotas can promote weak work or manufacture filler;
- a legacy `parent_event_id` does not prove a material development;
- freshness cannot overcome scope, novelty, rights or integrity failure; and
- domain prestige is not claim-specific authority.

Priority orders work only after applicable authority and eligibility preconditions pass.

## Core distinctions

### Outcome is not status

An outcome is one immutable result or decision for one exact input version. Current status is a rebuildable projection over outcomes, retries, supersession and Watch Conditions. It MUST NOT erase earlier history or reason.

### Reason is not outcome

An outcome states what was committed. A reason states the basis. A reason code cannot perform a transition.

### Priority is not eligibility

Priority affects when valid work runs. It cannot:

- turn an excluded Signal into a Lead;
- turn a reject into a Candidate;
- bypass rights, collision checks or Evidence Handoff;
- convert failure into no news;
- determine an Event Hypothesis relationship; or
- satisfy a missing Active coverage path.

### Urgency is not materiality

Urgency expresses harm from delay. Materiality expresses likely substantive reader impact. Urgency may expedite work but never lower gates.

### Source role is not newsworthiness

A direct authority or operator can make investigation efficient, but official status does not make every update material. A radar Lead may justify evidence work without being evidence itself.

### Queue order is not publication order

This contract orders discovery work. It does not determine article prominence, publication time, feed order or notifications.

## Non-bypassable decision order

A later stage cannot cure failure at an earlier mandatory stage.

1. **Authority, rights and integrity:** accepted versions, source or Search Purpose authority, rights, privacy, state store, audit, Operational Profile and security.
2. **Check and source transition:** no work due, preflight blocked, unchanged, changed, partial, failed or quarantined.
3. **Deterministic Signal gates:** identity, duplication, observable newness, time validity and clear scope or exclusion.
4. **Editorial Lead triage:** likely coverage, utility, materiality, novelty, urgency and evidence-work justification.
5. **Relationship and Event Hypothesis:** same state, development, correction or reversal, related but distinct, no adequate match or uncertain.
6. **Candidate admission:** exact manifest, collision checks, lineage, route, freshness and no evidence claim.
7. **Evidence Handoff:** exact Candidate Version remains pending until durable acknowledgement.
8. **Scheduling and optimisation:** only otherwise executable work enters priority lanes, batching and cost optimisation.

## Canonical outcome vocabulary

Implementations MAY use different strings only with a versioned one-to-one mapping that preserves every distinct meaning.

### Check and preflight

- `NO_WORK_DUE`
- `PREFLIGHT_BLOCKED`
- `CHECK_UNCHANGED`
- `CHECK_CHANGED`
- `CHECK_PARTIAL`
- `CHECK_FAILED_RETRYABLE`
- `CHECK_FAILED_BLOCKING`
- `CHECK_QUARANTINED`

`CHECK_UNCHANGED` requires a successful qualifying observation. Missing work, stale state, failed parsing and zero search results cannot use it.

### Signal gate

- `SIGNAL_SUPPRESSED_DUPLICATE`
- `SIGNAL_SUPPRESSED_NON_CHANGE`
- `SIGNAL_REJECTED_CLEAR_EXCLUSION`
- `SIGNAL_PROMOTED_TO_LEAD`
- `SIGNAL_OPERATIONAL_HOLD`

Weak media volume, one source, uncertain materiality or a low keyword score is not a deterministic exclusion.

### Lead disposition

- `LEAD_EDITORIAL_REJECT`
- `LEAD_WATCH_DEFER`
- `LEAD_ASSOCIATE_WITHOUT_CANDIDATE`
- `LEAD_SUPPLEMENTAL_DISCOVERY`
- `LEAD_OPERATIONAL_HOLD`
- `LEAD_ADMIT_NEW_CANDIDATE`
- `LEAD_ADMIT_DEVELOPMENT_CANDIDATE`
- `LEAD_ADMIT_CORRECTION_CANDIDATE`

### Relationship

- `REL_SAME_STATE`
- `REL_DEVELOPMENT_OF`
- `REL_CORRECTION_REVERSAL_OF`
- `REL_RELATED_DISTINCT`
- `REL_NO_ADEQUATE_PRIOR_MATCH`
- `REL_UNCERTAIN`

Relationship outcomes are unverified discovery semantics, not canonical factual relations.

### Candidate and Handoff

- `CANDIDATE_ADMITTED`
- `CANDIDATE_ADMISSION_INVALID`
- `CANDIDATE_ADMISSION_BLOCKED`
- `CANDIDATE_VERSION_SUPERSEDED`
- `HANDOFF_PENDING`
- `HANDOFF_ACKNOWLEDGED`
- `HANDOFF_RETRY_REQUIRED`
- `HANDOFF_OPERATIONAL_HOLD`
- `EVIDENCE_FEEDBACK_RECEIVED`

### Operational health

- `HEALTH_HEALTHY`
- `HEALTH_DEGRADED`
- `HEALTH_STALE`
- `HEALTH_UNAVAILABLE`
- `HEALTH_QUARANTINED`
- `HEALTH_BLOCKED`
- `HEALTH_UNKNOWN`

Health is dimension- and scope-specific. Transport may be healthy while parsing is unavailable.

### Coverage availability

- `COVERAGE_AVAILABLE`
- `COVERAGE_DEGRADED`
- `COVERAGE_BLOCKED`
- `COVERAGE_UNKNOWN`

A Comparator, broad query or result count cannot convert blocked Active coverage into available coverage.

## Terminality and re-entry

Every outcome declares whether it is:

- terminal for the exact version;
- pending until an inspectable condition;
- retryable for the same semantic request; or
- occurrence-only without another transition.

A later Source Revision, Lead version, Work Item, policy version or authorised re-evaluation creates a later decision rather than mutating the earlier one.

`LEAD_WATCH_DEFER` requires a Watch Condition. Operational holds and pending Handoffs require an owner, dependency, retry, review or expiry condition. Unowned indefinite pending states are invalid.

## Decision-reason contract

Every committed decision records:

- exact input identity and version;
- canonical outcome and terminality;
- one primary reason and optional supporting reasons;
- reason-basis class;
- exact observation, field, relationship, dependency or policy references;
- uncertainty and missing context;
- next action, Watch Condition, retry or closure;
- policy, taxonomy, component and model versions;
- actor and authoritative record time; and
- previous or superseded decision where applicable.

Free text MAY explain a decision but MUST NOT replace structured fields.

### Reason-basis classes

- `DETERMINISTIC_OBSERVATION`
- `DETERMINISTIC_POLICY`
- `SOURCE_ASSERTION`
- `EDITORIAL_ASSESSMENT`
- `OPERATIONAL_ASSESSMENT`
- `HUMAN_ADJUDICATION`
- `DOWNSTREAM_FEEDBACK`

A source assertion such as `cancelled` or `severe` remains attributed and is not converted into Newsroom verification by a reason code.

## Reason families

Reason codes are namespaced, versioned and append-only. Meaning cannot be repurposed after use; retired codes remain interpretable.

Minimum families are:

- `AUTH.*` — version, profile, policy, state-store and audit authority;
- `SCOPE.*` — Active, Best effort, deferred, excluded and geographic qualification;
- `CHANGE.*` — unchanged, new item, Revision, transition, withdrawal and Agenda change;
- `NOVELTY.*` — same-state repeat, likely development, likely new event or insufficient information;
- `UTILITY.*` — action, safety, service, household, travel and materiality basis;
- `REL.*` — relationship evidence and uncertainty;
- `TIME.*` — urgency, deadlines, Planned windows, Watch review and stale work;
- `SOURCE.*` — source role, directness, dependency, identity and publisher-check state;
- `RIGHTS.*` — retrieval, retention, model, query-data and use-scope restrictions;
- `OPS.*` — transport, parser, partial, retrieval, collision, model, queue, Handoff, quarantine and stale state;
- `CAPACITY.*` — search, model, queue, urgent-reserve and reviewer limits;
- `SEARCH.*` — zero, partial, provider failure, altered query, comparator and lead-only status; and
- `EVAL.*` — exposure, reviewability, blockers, slice failure and release-evidence outcomes.

Later accepted specifications MAY add versioned families or codes without changing existing meaning.

## Prioritisation model

### Ordinal lanes

1. `CONTAINMENT` — authority, integrity or coverage-loss work required to prevent unsafe or misleading operation;
2. `URGENT` — potential immediate safety, public-health or severe service-risk work;
3. `TIME_SENSITIVE` — actionable deadlines, rules, travel or service changes and developing disruption;
4. `PLANNED_WINDOW` — Agenda and occurrence-confirmation work in an active window;
5. `ROUTINE` — normal eligible discovery and triage work; and
6. `OPTIONAL_EVALUATION` — Comparators, optional audits and work reduced first under backpressure.

`CONTAINMENT` is an operational lane, not a claim that a story is editorially more important.

### Within-lane ordering

Where applicable and subject to the exact Operational Profile:

1. earliest hard safety, action, legal, Planned or Watch deadline;
2. consequence of delay, including sole-path Active coverage loss;
3. current-state staleness risk;
4. age and starvation protection;
5. dependency readiness and bounded ability to complete safely; and
6. stable deterministic identity as final tie-break.

Routine work receives fairness without processing stale, superseded or blocked work as current.

### Prohibited priority proxies

The following cannot independently establish priority, materiality, independence or Candidate eligibility:

- article, link, result or domain count;
- publisher prestige or domain tier;
- model confidence;
- embedding, similarity or retrieval score;
- search rank;
- category balance or guaranteed geography or finance slot;
- unused writing capacity;
- engagement, virality or social reaction;
- legacy child-event status; or
- being newly inserted into storage.

Hong Kong and other coverage obligations are protected by scope, source paths, evaluation and coverage posture, not by quotas that promote weaker work.

### Numeric scoring boundary

Launch uses semantic gates, routes and ordinal lanes rather than one global composite score.

A later stage-local score MAY support one bounded purpose, such as retrieval ranking, tie-breaking or evaluation sampling, only when it:

- declares what it may and may not decide;
- preserves mandatory gates and holds;
- uses inspectable, versioned factors;
- distinguishes unknown and not-applicable from zero;
- reports factor contributions;
- is evaluated by required slices against the ordinal baseline;
- avoids volume, prestige and popularity as utility substitutes;
- uses thresholds fixed before qualification results; and
- shows no material coverage, language, fairness or urgency regression.

Until then, numeric prioritisation remains **Needs experiment** and has no authority.

## Priority Decision contract

Every Priority Decision records exact work identity and version, lane, applicable deadline or Watch Condition, coverage consequence, freshness context, queue age, dependency readiness, governing Profile and policy versions, actor, time and previous decision.

A Priority Decision contains no factual verification and cannot change a Lead disposition, Event Hypothesis or Candidate outcome.

## Requirements

### Decision order and outcome integrity

**DOUT-001 — Ordered authority.** Mandatory authority, rights, integrity, source-transition, deterministic-gate, triage, relationship, Candidate-admission and Handoff stages MUST NOT be bypassed by priority, score, confidence or capacity.

**DOUT-002 — Outcome, reason and priority separation.** Outcome, reason, next action and processing priority MUST remain separate and inspectable.

**DOUT-003 — One outcome per decision scope.** One exact decision record MUST commit one canonical outcome for every exact input version it owns.

**DOUT-004 — Immutable outcome.** A committed outcome MUST NOT be overwritten; later decisions create later records and explicit supersession.

**DOUT-005 — Status is projection.** Current status MUST be rebuildable and MUST NOT be the sole authority.

**DOUT-006 — Exact terminality.** Terminality applies to one exact version, not automatically to later Revisions or authorised re-evaluations.

**DOUT-007 — Pending requires condition.** Watch, hold and pending outcomes MUST identify a resume, retry, review, expiry or owner condition.

**DOUT-008 — Operational and editorial separation.** Operational, rights, capacity and model failure MUST NOT be recorded as editorial rejection or no news.

### Canonical vocabulary

**DOUT-010 — Canonical mapping.** Implementations MUST preserve a versioned one-to-one mapping to canonical outcome semantics.

**DOUT-011 — Check distinctions.** No-work, blocked, unchanged, changed, partial, retryable failure, blocking failure and quarantine MUST remain distinct.

**DOUT-012 — Signal distinctions.** Duplicate suppression, non-change suppression, clear exclusion, Lead promotion and operational hold MUST remain distinct.

**DOUT-013 — Lead distinctions.** Reject, watch, association, supplemental discovery, Operational hold and Candidate-admission routes MUST remain distinct.

**DOUT-014 — Relationship distinctions.** Same state, development, correction or reversal, related-but-distinct, no adequate match and uncertain relation MUST remain distinct.

**DOUT-015 — Handoff distinctions.** Admission, invalid or blocked admission, pending, acknowledged, retry-required and held Handoff MUST remain distinct.

**DOUT-016 — Health and coverage distinction.** Component health and portfolio coverage availability MUST use separate scoped outcomes.

### Reasons

**DOUT-020 — Structured reason required.** Every decision MUST have one primary structured reason and MAY have supporting reasons.

**DOUT-021 — Basis class required.** Every reason MUST identify its basis class.

**DOUT-022 — Exact basis references.** Reasons MUST cite exact supporting inputs.

**DOUT-023 — No free-text-only decision.** Free text MUST NOT replace outcome, reason, basis or next action.

**DOUT-024 — Versioned append-only taxonomy.** Reason meaning MUST be versioned and never repurposed.

**DOUT-025 — Source assertion attribution.** Source labels MUST remain attributed and MUST NOT become verification through taxonomy.

**DOUT-026 — Sensitive-data restraint.** Records MUST avoid unnecessary personal, confidential or prohibited source expression.

### Priority

**DPRI-001 — Ordinal lanes.** Work MUST use the canonical lanes or an explicit equivalent mapping rather than an ungoverned global score.

**DPRI-002 — Gates precede priority.** Priority MUST NOT make blocked, rejected or unauthorised work eligible.

**DPRI-003 — Urgency preserves gates.** Urgent processing MAY reduce waiting but MUST NOT lower scope, rights, novelty, relationship, lineage, collision or admission requirements.

**DPRI-004 — Deadline first within lane.** Hard safety, action, legal, Planned and Watch deadlines SHOULD precede softer factors.

**DPRI-005 — Coverage consequence.** Sole- or principal-path Active coverage loss MAY raise operational priority without becoming an editorial materiality claim.

**DPRI-006 — Fairness and aging.** Routine work MUST have starvation protection, revalidation and explicit expiry or closure.

**DPRI-007 — Optional work yields first.** Comparator and optional work SHOULD reduce before required Anchor, Urgent, Time-sensitive or Planned work.

**DPRI-008 — Stable tie-break.** Equal-priority work MUST use a deterministic final tie-break.

**DPRI-009 — No volume authority.** Article, domain, result and repetition count MUST NOT independently establish priority, materiality, independence or eligibility.

**DPRI-010 — No quota promotion.** Category, geography, finance, Hong Kong or volume quotas MUST NOT promote weaker work.

**DPRI-011 — Confidence non-authority.** Confidence, similarity and retrieval scores MUST NOT independently determine lane, disposition, relationship or admission.

**DPRI-012 — Priority decision versioning.** Reprioritisation MUST create a later Priority Decision with exact basis and versions.

### Numeric scoring boundary

**DPRI-020 — No launch global scalar.** Launch discovery MUST NOT use one global composite score as the governing eligibility or disposition mechanism.

**DPRI-021 — Stage-local purpose only.** A later score MAY support one bounded function and MUST declare its non-authority boundaries.

**DPRI-022 — Evaluation before authority.** Numeric factors and thresholds remain **Needs experiment** until owner-approved evaluation compares them with the ordinal baseline.

**DPRI-023 — Missing is not zero.** Unknown, unavailable and not-applicable values MUST remain distinct from zero.

**DPRI-024 — Factor inspectability.** A scoring decision MUST retain version, factors, contributions, threshold and result.

**DPRI-025 — No post-hoc thresholds.** Thresholds MUST be approved before qualification results and cannot be tuned on the same Run used as release evidence.

**DPRI-026 — Slice protection.** Aggregate performance MUST NOT hide material language, geography, coverage, urgency or transition regression.

## Acceptance criteria

1. One authoritative guidance Revision may justify a Candidate with one source and no media repetition.
2. Duplicate articles cannot outrank an Urgent direct warning solely through volume.
3. Fresh out-of-scope content cannot pass because of recency or trusted domains.
4. A Run with no qualifying Hong Kong Candidate creates no guaranteed slot or filler.
5. A Hong Kong Lead is not rejected solely because it has no UK effect.
6. Urgent work cannot bypass rights, collision checks or admission validation.
7. Confidence cannot create a development, merge, reject or Candidate by itself.
8. Parser failure receives an operational outcome, not editorial rejection.
9. Watch without an inspectable condition is invalid.
10. Same-state repetition normally associates without a Candidate.
11. Collision-check outage blocks admission rather than forcing a new event.
12. Unchanged source and zero-result search remain distinct.
13. Later Source Revision creates a later decision and preserves earlier outcomes.
14. Current status can be rebuilt from immutable history.
15. Routine work receives processing opportunity without bypassing stale-work revalidation.
16. Optional Comparator work yields before required Urgent or Active-path work.
17. No score can overcome exclusion, rights block, quarantine or Operational hold.
18. Every reason identifies basis class and exact supporting input.
19. Retired reason codes remain interpretable.
20. Acceptance authorises no score, threshold, queue configuration, model call, source collection, shadow run or production activation.

## Completion record

The product owner accepted this specification on 2026-07-15 with these decisions:

- decision order is non-bypassable from authority and source semantics through Handoff;
- outcome, reason, next action, status and priority are separate;
- canonical Check, Signal, Lead, relationship, Candidate, Handoff, health and coverage families are accepted;
- outcomes are immutable for exact versions and later changes create later records;
- watch, hold and pending require inspectable conditions;
- reasons are namespaced, versioned and append-only with primary reason, optional supporting reasons, basis class and exact references;
- deterministic observation, deterministic policy, source assertion, editorial assessment, operational assessment, human adjudication and downstream feedback remain distinct;
- priority lanes are `CONTAINMENT`, `URGENT`, `TIME_SENSITIVE`, `PLANNED_WINDOW`, `ROUTINE` and `OPTIONAL_EVALUATION`;
- within-lane order uses deadlines, delay consequence, staleness risk, fairness, dependency readiness and deterministic tie-break;
- urgency expedites work but never lowers gates;
- volume, publisher tier, search rank, confidence, similarity, virality and legacy child-event status are non-authoritative proxies;
- target discovery quotas, finance caps, Hong Kong guarantees and filler promotion are removed;
- coverage obligations are protected through portfolio, scope, monitoring, evaluation and coverage posture;
- Routine fairness includes revalidation and explicit closure;
- launch uses no global composite score, while later stage-local scoring remains **Needs experiment** and cannot override gates;
- Priority Decisions are versioned and status is rebuildable; and
- Topic 10 authorises no score, threshold, queue, model, source, run, spending or activation.
