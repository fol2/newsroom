# Discovery prioritisation and outcome-vocabulary specification

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
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
**Decision state:** The decision order, canonical outcome semantics, reason taxonomy and prioritisation rules below are proposals. Committing this Draft does not authorise scoring, thresholds, queue configuration, model calls, source collection, shadow execution or production use.  
**Supersedes:** None

## Purpose

Define a stable decision order and vocabulary for discovery outcomes, reasons and work priority without allowing one score, media volume, category quota, model confidence or queue pressure to override accepted coverage, authority, rights, integrity or editorial gates.

The specification answers four separate questions:

1. **What happened operationally or semantically?** — outcome.
2. **Why was that outcome committed?** — reason and decision basis.
3. **What should happen next?** — disposition, Watch Condition, retry, handoff or closure.
4. **When should otherwise eligible work be processed?** — priority lane and ordering factors.

These questions must not be collapsed into one mutable status or scalar score.

## Scope

This specification defines:

- non-bypassable decision order;
- canonical semantic outcomes across Check, Signal, Lead, Candidate, Handoff, health and coverage posture;
- immutable decision, terminality and re-entry semantics;
- namespaced reason families and required decision basis;
- ordinal priority lanes and within-lane ordering;
- fairness, deadline and starvation controls at the vocabulary level;
- prohibited ranking proxies and quota behaviour;
- conditions under which a later stage-local score may be considered; and
- acceptance and evaluation requirements for outcome and priority behaviour.

It does not define:

- exact numeric weights, score thresholds, queue wait times or service objectives;
- model provider, prompt, scheduler, queue or database implementation;
- evidence sufficiency, story drafting, publication ordering or reader-facing urgency labels;
- notification priority; or
- locality expansion.

Exact operational timing belongs to approved Operational Profiles. Any numeric prioritisation remains **Needs experiment** until a later owner-approved evaluation establishes that it improves on the accepted ordinal baseline without violating these rules.

## Current-system replacement boundary

The current pool ranks daily Candidates primarily by trusted-domain count, unique-domain count, weighted source score and recency, then applies a finance cap, a per-category cap and one-to-two guaranteed Hong Kong slots. Hourly selection puts child developments first and adds category diversity. See [`../../../newsroom/news_pool_db.py`](../../../newsroom/news_pool_db.py).

Those behaviours are legacy implementation details, not the target contract:

- repeated media coverage is not newsworthiness or independent origin;
- a direct official revision may deserve evidence work with one source;
- a category or geography quota can promote a weaker item or manufacture filler;
- a `parent_event_id` does not prove a material development;
- freshness cannot overcome scope, novelty, rights or integrity failure; and
- source-domain prestige is not claim-specific authority.

The target uses accepted coverage, change, triage and evidence boundaries first. Priority determines processing order only after the relevant authority and eligibility preconditions are satisfied.

## Core distinctions

### Outcome is not status

An outcome is one immutable decision or observed result for one exact record version. A current status is a rebuildable projection over outcomes, supersession, Watch Conditions, retries and later decisions.

A status field must not erase why an earlier outcome occurred.

### Reason is not outcome

The outcome states what was committed. A reason states the basis. For example:

```text
Outcome: LEAD_WATCH_DEFER
Primary reason: NOVELTY.INSUFFICIENT_CURRENT_INFORMATION
Supporting reason: TIME.AWAITING_PLANNED_OCCURRENCE
```

The same reason may support different outcomes under different policy and context. A reason code cannot itself perform a transition.

### Priority is not eligibility

Priority affects when valid work is processed. It cannot:

- turn an excluded Signal into a Lead;
- turn an editorial reject into a Candidate;
- bypass rights, collision checking or evidence handoff;
- convert failure into no news;
- change an Event Hypothesis relationship; or
- satisfy a missing Active coverage path.

### Urgency is not materiality

Urgency expresses time sensitivity or potential harm from delay. Materiality expresses likely substantive reader impact. Either may be high while the other is low. Urgency can expedite review but cannot lower gates.

### Source confidence is not newsworthiness

A direct authority or operator may make a Lead efficient to investigate, but official status does not make every update material. Conversely, a high-impact media Lead may justify evidence acquisition despite lacking a primary source at discovery time.

### Queue order is not publication order

This specification orders discovery work. It does not decide article prominence, feed ordering, notification dispatch or publication timing after evidence and publication control.

## Non-bypassable decision order

The target decision sequence is ordered. A later stage cannot cure failure at an earlier mandatory stage.

### Stage 0 — Authority, rights and integrity preconditions

Confirm accepted versions, source or Search Purpose authority, rights, privacy, state-store availability, operational Profile and required security controls.

Failure produces a blocked, failed, degraded or quarantined operational outcome. It does not produce an editorial reject or no-news conclusion.

### Stage 1 — Check and source-transition result

Determine whether no work was due, preflight blocked, the source was successfully unchanged, an observable transition occurred, the result was partial, or the check failed.

Only an accepted candidate observable transition may proceed to a Discovery Signal.

### Stage 2 — Deterministic Signal gates

Apply accepted identity, duplicate, observable-newness, time-validity and unambiguous scope or exclusion rules.

Clear deterministic exclusion may reject the Signal. Editorial ambiguity must survive to Lead triage or an operational hold.

### Stage 3 — Editorial Lead triage

Assess likely coverage, utility, materiality, novelty, urgency and relationship only to decide whether evidence acquisition appears justified.

The valid routes are reject, watch or defer, associate without Candidate, supplemental discovery, Operational hold, new-event Candidate, development Candidate and correction-oriented Candidate.

### Stage 4 — Relationship and Event Hypothesis decision

Commit same-state, development, correction or reversal, related-but-distinct, no-adequate-match or uncertain relationships through the accepted append-only Event Hypothesis contract.

Relationship does not decide Candidate admission by itself.

### Stage 5 — Candidate admission

Validate the exact Candidate manifest, current Candidate and identity collision checks, coverage basis, lineage, allowed route, freshness and absence of evidence claims.

Invalid or stale proposals create no Candidate.

### Stage 6 — Evidence handoff

The exact Candidate Version remains pending until durable Evidence Intake acknowledgement. Timeout or ambiguity does not create another Candidate or imply evidence acceptance.

### Stage 7 — Work scheduling and resource optimisation

Only otherwise executable work is ordered through the accepted priority lanes. Batching, caching and cost optimisation occur within, not above, the preceding authority and decision sequence.

## Canonical outcome vocabulary

The labels below are canonical semantic labels. An implementation MAY encode them differently only when it maintains an explicit, versioned one-to-one mapping and does not combine distinct semantics.

### Check and preflight outcomes

| Canonical outcome | Meaning | Next boundary |
|---|---|---|
| `NO_WORK_DUE` | The exact scope was not due; no Check Request was required | End |
| `PREFLIGHT_BLOCKED` | Authority, rights, configuration, budget, security or dependency precondition blocked execution | Operational remediation |
| `CHECK_UNCHANGED` | A successful qualifying check established no accepted source-state transition | End |
| `CHECK_CHANGED` | A successful check established at least one candidate observable transition | Signal formation |
| `CHECK_PARTIAL` | Some result was independently valid but the complete contract did not pass | Valid partial Signals plus visible Finding, or hold |
| `CHECK_FAILED_RETRYABLE` | The Attempt failed under a retryable classification | Bounded retry or hold |
| `CHECK_FAILED_BLOCKING` | The Attempt failed under a non-retryable or authority-blocking classification | Remediation or containment |
| `CHECK_QUARANTINED` | The exact source, adapter or dependency scope is quarantined | Authorised repair and canary |

`CHECK_UNCHANGED` is available only after a successful qualifying observation. Missing work, failure, stale state and zero search results cannot use it.

### Signal-gate outcomes

| Canonical outcome | Meaning |
|---|---|
| `SIGNAL_SUPPRESSED_DUPLICATE` | The same semantic transition was already committed; occurrence lineage remains |
| `SIGNAL_SUPPRESSED_NON_CHANGE` | A Representation or transport difference did not establish an accepted source transition |
| `SIGNAL_REJECTED_CLEAR_EXCLUSION` | A versioned deterministic rule established an unambiguous exclusion |
| `SIGNAL_PROMOTED_TO_LEAD` | Deterministic gates passed and the Signal became one News Lead |
| `SIGNAL_OPERATIONAL_HOLD` | Integrity, rights, identity or required context prevented a safe gate decision |

A low keyword score, one source, weak media volume or uncertain materiality is not a valid deterministic exclusion reason.

### Lead-disposition outcomes

| Canonical outcome | Meaning |
|---|---|
| `LEAD_EDITORIAL_REJECT` | Likely coverage, utility, materiality or novelty did not justify evidence work |
| `LEAD_WATCH_DEFER` | The Lead remains potentially useful and has an inspectable Watch Condition |
| `LEAD_ASSOCIATE_WITHOUT_CANDIDATE` | The Lead adds same-state, context, dependency or possible corroboration lineage but no new evidence objective |
| `LEAD_SUPPLEMENTAL_DISCOVERY` | One bounded approved discovery action is required and re-enters the normal workflow |
| `LEAD_OPERATIONAL_HOLD` | Required rights, retrieval, model, policy, capacity or integrity context is unavailable |
| `LEAD_ADMIT_NEW_CANDIDATE` | A new-event Candidate passed deterministic admission |
| `LEAD_ADMIT_DEVELOPMENT_CANDIDATE` | A Candidate with exact earlier and proposed new state passed admission |
| `LEAD_ADMIT_CORRECTION_CANDIDATE` | A correction, clarification, withdrawal or reversal Candidate passed admission |

An outcome applies to one exact Lead version. A later Source Revision creates new upstream records and may receive another decision.

### Relationship outcomes

| Canonical outcome | Meaning |
|---|---|
| `REL_SAME_STATE` | Same specific event or process state, without material new state |
| `REL_DEVELOPMENT_OF` | Same continuing event or process with a proposed material new state |
| `REL_CORRECTION_REVERSAL_OF` | A prior state is proposed as corrected, qualified, withdrawn or reversed |
| `REL_RELATED_DISTINCT` | Shared context but a separate occurrence or process instance |
| `REL_NO_ADEQUATE_PRIOR_MATCH` | No retrieved prior Hypothesis adequately represents the proposed event |
| `REL_UNCERTAIN` | Available context cannot support a safe relationship conclusion |

Relationship outcomes are unverified discovery semantics, not canonical factual relations.

### Candidate and handoff outcomes

| Canonical outcome | Meaning |
|---|---|
| `CANDIDATE_ADMITTED` | One immutable Candidate Version was created through deterministic admission |
| `CANDIDATE_ADMISSION_INVALID` | The proposal failed schema, identity, lineage, allowed-route or freshness validation |
| `CANDIDATE_ADMISSION_BLOCKED` | A required authority, rights, exact collision or state precondition was unavailable |
| `CANDIDATE_VERSION_SUPERSEDED` | A later material Candidate Version exists; the earlier version remains historical |
| `HANDOFF_PENDING` | The exact Candidate Version has no durable Evidence Intake acknowledgement yet |
| `HANDOFF_ACKNOWLEDGED` | Evidence Intake durably acknowledged the exact Candidate Version and Handoff identity |
| `HANDOFF_RETRY_REQUIRED` | Delivery failed or was ambiguous and the same semantic Handoff requires idempotent retry or reconciliation |
| `HANDOFF_OPERATIONAL_HOLD` | The Evidence Intake boundary cannot safely accept work |
| `EVIDENCE_FEEDBACK_RECEIVED` | Downstream feedback was linked without rewriting discovery history |

Evidence acceptance, claim verification and publication eligibility belong to downstream specifications.

### Operational-health outcomes

| Canonical outcome | Meaning |
|---|---|
| `HEALTH_HEALTHY` | Required qualifying observations and dependencies are within Profile objectives |
| `HEALTH_DEGRADED` | Some capability or resilience is impaired but bounded operation remains authorised |
| `HEALTH_STALE` | Required successful observation or processing age exceeds the Profile objective |
| `HEALTH_UNAVAILABLE` | The component or path cannot perform its accepted function |
| `HEALTH_QUARANTINED` | Automatic processing is disabled for integrity, rights or safety reasons |
| `HEALTH_BLOCKED` | Authority, rights, budget, store or policy preconditions prohibit operation |
| `HEALTH_UNKNOWN` | Available observations are insufficient for a defensible assessment |

These outcomes are dimension- and scope-specific. One component may be transport-healthy and parser-unavailable.

### Coverage-availability outcomes

| Canonical outcome | Meaning |
|---|---|
| `COVERAGE_AVAILABLE` | At least one credible healthy accepted path currently supplies the required capability |
| `COVERAGE_DEGRADED` | Coverage remains partly available but a capability, role or resilience path is lost |
| `COVERAGE_BLOCKED` | An Active obligation has no credible healthy path and its containment policy applies |
| `COVERAGE_UNKNOWN` | Health, authority or dependency information is insufficient to assess availability |

A Comparator, broad query or result volume cannot turn `COVERAGE_BLOCKED` into `COVERAGE_AVAILABLE`.

## Outcome terminality and re-entry

Every committed outcome declares one of these semantic terminality classes:

- **Terminal for exact version:** the exact Signal, Lead, Proposal or Candidate Version receives no competing disposition. Examples include deterministic exclusion, editorial reject, association and Candidate admission.
- **Retained pending condition:** watch, operational hold and handoff pending remain open only through an inspectable condition, retry or reconciliation rule.
- **Operationally superseded:** a later health, coverage, Profile or Candidate decision supersedes current projection but preserves the earlier outcome.
- **Occurrence-only:** re-observation or duplicate delivery records occurrence without another semantic transition.

A new Source Revision, Lead version, Work Item, policy version or authorised re-evaluation may create a later decision. It does not mutate the earlier outcome.

`LEAD_WATCH_DEFER` requires a Watch Condition. `LEAD_OPERATIONAL_HOLD`, `SIGNAL_OPERATIONAL_HOLD`, `HANDOFF_PENDING` and `HANDOFF_OPERATIONAL_HOLD` require an owner, dependency or automatic recheck condition. Indefinite unowned pending states are invalid.

## Decision-reason contract

Every committed decision carries:

- exact input identity and version;
- canonical outcome;
- terminality class;
- one primary reason code;
- zero or more supporting reason codes;
- reason-basis class;
- exact observations, fields, relationships or policy clauses used;
- uncertainty and known missing context;
- next action, Watch Condition, retry or closure where applicable;
- policy, taxonomy, component and model versions;
- decision actor and authoritative record time; and
- previous or superseded decision reference where applicable.

Free text may explain a decision but cannot replace structured reasons.

### Reason-basis classes

Each reason is classified as one of:

- `DETERMINISTIC_OBSERVATION`;
- `DETERMINISTIC_POLICY`;
- `SOURCE_ASSERTION`;
- `EDITORIAL_ASSESSMENT`;
- `OPERATIONAL_ASSESSMENT`;
- `HUMAN_ADJUDICATION`; or
- `DOWNSTREAM_FEEDBACK`.

A source assertion such as `cancelled` or `severe` remains attributed. It cannot be recorded as a Newsroom-verified fact merely by choosing a reason code.

## Canonical reason families

Reason codes are namespaced, versioned and append-only. A code's meaning cannot be repurposed after use. New codes may be added under review; retired codes remain interpretable.

The minimum families are:

### `AUTH.*` — authority and governing preconditions

Examples:

- `AUTH.VERSION_NOT_ACCEPTED`
- `AUTH.PROFILE_NOT_APPROVED`
- `AUTH.POLICY_CONFLICT`
- `AUTH.STATE_STORE_UNAVAILABLE`
- `AUTH.AUDIT_UNAVAILABLE`

### `SCOPE.*` — coverage and exclusion

Examples:

- `SCOPE.ACTIVE_OBLIGATION`
- `SCOPE.BEST_EFFORT`
- `SCOPE.EXPLICIT_DEFERRED_GAP`
- `SCOPE.OUT_OF_SCOPE`
- `SCOPE.CLEAR_EXCLUSION`
- `SCOPE.GEOGRAPHIC_RELEVANCE_AMBIGUOUS`
- `SCOPE.HONG_KONG_INTRINSIC_VALUE`
- `SCOPE.GLOBAL_QUALIFICATION_NOT_ESTABLISHED`

### `CHANGE.*` — source and transition meaning

Examples:

- `CHANGE.UNCHANGED`
- `CHANGE.NEW_ITEM`
- `CHANGE.REVISION`
- `CHANGE.REPRESENTATION_ONLY`
- `CHANGE.ACTIVATION`
- `CHANGE.ESCALATION`
- `CHANGE.DEESCALATION`
- `CHANGE.CLEARANCE`
- `CHANGE.WITHDRAWAL`
- `CHANGE.RESCHEDULE`
- `CHANGE.MISSED_EXPECTATION`
- `CHANGE.AMBIGUOUS_TRANSITION`

### `NOVELTY.*` — editorial newness

Examples:

- `NOVELTY.SAME_STATE_REPEAT`
- `NOVELTY.SUBSTANTIVE_DEVELOPMENT_LIKELY`
- `NOVELTY.NEW_EVENT_LIKELY`
- `NOVELTY.CORRECTION_OR_REVERSAL_LIKELY`
- `NOVELTY.INSUFFICIENT_CURRENT_INFORMATION`
- `NOVELTY.UNCHANGED_BACKGROUND`

### `UTILITY.*` — likely reader impact and materiality

Examples:

- `UTILITY.ACTION_REQUIRED`
- `UTILITY.MATERIAL_SAFETY_EFFECT`
- `UTILITY.MATERIAL_SERVICE_DISRUPTION`
- `UTILITY.HOUSEHOLD_OR_WORK_EFFECT`
- `UTILITY.UK_HK_TRAVEL_EFFECT`
- `UTILITY.EXCEPTIONAL_PUBLIC_IMPORTANCE`
- `UTILITY.MATERIALITY_NOT_ESTABLISHED`
- `UTILITY.ORDINARY_SERVICE_NOISE`

### `REL.*` — Event Hypothesis relationship basis

Examples:

- `REL.SAME_STATE`
- `REL.DEVELOPMENT`
- `REL.CORRECTION_OR_REVERSAL`
- `REL.RELATED_DISTINCT`
- `REL.NO_ADEQUATE_PRIOR_MATCH`
- `REL.UNCERTAIN`
- `REL.SHARED_TOPIC_ONLY`
- `REL.FORMAL_IDENTIFIER_MATCH`

### `TIME.*` — urgency, deadline and timeliness

Examples:

- `TIME.URGENT_PUBLIC_RISK`
- `TIME.ACTION_DEADLINE`
- `TIME.PLANNED_WINDOW_OPEN`
- `TIME.ROUTINE`
- `TIME.WATCH_REVIEW_DUE`
- `TIME.STALE_WORK_REQUIRES_REVALIDATION`
- `TIME.MISSED_PROCESSING_WINDOW`

### `SOURCE.*` — source role and dependency

Examples:

- `SOURCE.ORIGINATING_AUTHORITY`
- `SOURCE.RESPONSIBLE_OPERATOR`
- `SOURCE.ESTABLISHED_MEDIA_RADAR`
- `SOURCE.SINGLE_DIRECT_LEAD`
- `SOURCE.SHARED_ORIGIN`
- `SOURCE.EDITORIALLY_CURATED_FEED`
- `SOURCE.IDENTITY_UNCERTAIN`
- `SOURCE.UNDERLYING_PUBLISHER_NOT_CHECKED`

### `RIGHTS.*` — permitted-use boundary

Examples:

- `RIGHTS.RETRIEVAL_BLOCKED`
- `RIGHTS.RETENTION_BLOCKED`
- `RIGHTS.MODEL_SUBMISSION_BLOCKED`
- `RIGHTS.QUERY_DATA_BLOCKED`
- `RIGHTS.REVIEW_EXPIRED`
- `RIGHTS.USE_SCOPE_MISMATCH`

### `OPS.*` — operational cause

Examples:

- `OPS.TRANSPORT_FAILURE`
- `OPS.PARSER_FAILURE`
- `OPS.PARTIAL_RESPONSE`
- `OPS.SNAPSHOT_COMPLETENESS_UNKNOWN`
- `OPS.RETRIEVAL_INCOMPLETE`
- `OPS.COLLISION_CHECK_UNAVAILABLE`
- `OPS.MODEL_TIMEOUT`
- `OPS.INVALID_MODEL_OUTPUT`
- `OPS.QUEUE_BACKPRESSURE`
- `OPS.HANDOFF_AMBIGUOUS`
- `OPS.QUARANTINED`
- `OPS.STALE_SOURCE`

### `CAPACITY.*` — budget and resource limits

Examples:

- `CAPACITY.SEARCH_BUDGET_EXHAUSTED`
- `CAPACITY.MODEL_BUDGET_EXHAUSTED`
- `CAPACITY.URGENT_RESERVE_REQUIRED`
- `CAPACITY.QUEUE_LIMIT_REACHED`
- `CAPACITY.REVIEW_CAPACITY_UNAVAILABLE`

### `SEARCH.*` — search-specific interpretation

Examples:

- `SEARCH.ZERO_RESULTS`
- `SEARCH.PARTIAL_OR_TRUNCATED`
- `SEARCH.PROVIDER_FAILED`
- `SEARCH.QUERY_ALTERED`
- `SEARCH.PROSPECTIVE_COMPARATOR`
- `SEARCH.RETROSPECTIVE_GAP_INVESTIGATION`
- `SEARCH.RESULT_LEAD_ONLY`

### `EVAL.*` — evaluation and release evidence

Examples:

- `EVAL.INSUFFICIENT_EXPOSURE`
- `EVAL.UNREVIEWABLE`
- `EVAL.ZERO_TOLERANCE_FAILURE`
- `EVAL.SLICE_FAILED`
- `EVAL.CONTINUE_SHADOW`
- `EVAL.COMPARATOR_ONLY`
- `EVAL.OPERATIONAL_QUALIFICATION_ELIGIBLE`

## Prioritisation model

### Priority lanes

Priority is ordinal. The canonical lanes are:

1. `CONTAINMENT` — authority, integrity or coverage-loss work required to prevent unsafe or misleading operation;
2. `URGENT` — potential immediate safety, public-health or severe service-risk Leads and current-state checks;
3. `TIME_SENSITIVE` — actionable deadlines, rules, travel or service changes and developing disruptions;
4. `PLANNED_WINDOW` — Agenda and occurrence-confirmation work within an active expected window;
5. `ROUTINE` — eligible normal discovery and triage work; and
6. `OPTIONAL_EVALUATION` — Comparators, optional audits and other work that may be reduced under backpressure.

`CONTAINMENT` is an operational control lane, not an editorial claim that a story is more important.

A work item may move lanes only through a versioned Priority Decision. Lane changes do not alter its editorial outcome.

### Within-lane ordering

Subject to exact Operational Profiles, work is ordered by transparent factors in this sequence where applicable:

1. earliest hard safety, action, legal, Planned or Watch deadline;
2. consequence of delay, including sole-path Active coverage loss;
3. risk that current-state information becomes stale;
4. age and starvation protection;
5. dependency readiness and bounded opportunity to complete safely; and
6. deterministic stable identity as a final tie-breaker.

No tie-breaker may weaken a gate or hide capacity shortage.

### Required fairness

Routine work cannot starve indefinitely because new Urgent or Time-sensitive work keeps arriving. Operational Profiles define aging, revalidation and closure behaviour. Fairness does not require processing stale, superseded or rights-blocked work as though current.

### Prohibited priority proxies

The following cannot independently raise editorial or Candidate priority:

- article, link, query-result or domain count;
- publisher prestige or domain tier;
- model confidence;
- embedding or retrieval score;
- search rank;
- category balance;
- a guaranteed Hong Kong, UK, finance or other slot;
- unused writing capacity;
- engagement, clicks, virality or social reaction;
- a legacy `parent_event_id`; or
- the fact that an item is new to the database.

Hong Kong intrinsic coverage is achieved through accepted source paths, scope rules and evaluation slices, not a quota that promotes a weaker Candidate. Category and geography counts may be monitored for coverage diagnostics but cannot manufacture a Lead or Candidate.

### No global composite score

The launch target uses gates, semantic routes and ordinal lanes rather than one global discovery score.

A later stage-local score MAY be proposed only for one bounded purpose such as retrieval ranking, queue tie-breaking or evaluation sampling. Before adoption it must:

- identify the exact decision it supports and decisions it cannot make;
- preserve all mandatory gates and holds;
- use interpretable, versioned factors;
- distinguish missing or unknown data from zero;
- report factor contributions;
- be calibrated and evaluated by required slices;
- compare against the accepted ordinal baseline;
- avoid source count, domain prestige or popularity as a substitute for utility or authority;
- use owner-approved thresholds fixed before qualification results; and
- demonstrate no material fairness, coverage, language or urgency regression.

Until that evidence exists, numeric prioritisation is **Needs experiment** and has no authority.

## Priority Decision contract

Every committed Priority Decision records:

- exact work identity and version;
- canonical priority lane;
- applicable hard deadline, expected window or Watch Condition;
- coverage role and consequence of delay;
- source-state freshness or staleness context;
- queue age and fairness context;
- dependency readiness or degraded-operation state;
- governing Operational Profile and priority-policy versions;
- actor and authoritative time; and
- previous Priority Decision where applicable.

A Priority Decision contains no factual verification and cannot change a Lead disposition, Event Hypothesis or Candidate outcome.

## Requirements

### Decision order and outcome integrity

**DOUT-001 — Ordered authority.** Mandatory authority, rights, integrity, source-transition, deterministic-gate, triage, relationship, Candidate-admission and handoff stages MUST NOT be bypassed by priority, score, confidence or capacity.

**DOUT-002 — Outcome, reason and priority separation.** Outcome, reason, next action and processing priority MUST remain separate inspectable fields or records.

**DOUT-003 — One outcome per decision scope.** One exact decision record MUST commit one canonical outcome for each exact input version it owns.

**DOUT-004 — Immutable outcome.** A committed outcome MUST NOT be overwritten; later decisions create later records and explicit supersession.

**DOUT-005 — Status is projection.** Current status MUST be rebuildable from immutable outcomes and MUST NOT be the only authority.

**DOUT-006 — Exact terminality.** Terminality applies to the exact record version, not automatically to future Source Revisions, Lead versions or authorised re-evaluations.

**DOUT-007 — Pending requires condition.** Watch, hold and pending outcomes MUST identify an inspectable resume, retry, review, expiry or owner condition.

**DOUT-008 — Operational and editorial separation.** Operational failure, rights block, capacity shortage and model failure MUST NOT be recorded as editorial rejection or no news.

### Canonical vocabulary

**DOUT-010 — Canonical mapping.** Implementations MUST preserve a versioned one-to-one mapping to the canonical outcome semantics in this specification.

**DOUT-011 — Check distinctions.** No-work, preflight blocked, unchanged, changed, partial, retryable failure, blocking failure and quarantine MUST remain distinct.

**DOUT-012 — Signal distinctions.** Duplicate suppression, non-change suppression, clear exclusion, Lead promotion and operational hold MUST remain distinct.

**DOUT-013 — Lead distinctions.** Editorial reject, watch, association, supplemental discovery, Operational hold and three Candidate-admission routes MUST remain distinct.

**DOUT-014 — Relationship distinctions.** Same state, development, correction or reversal, related-but-distinct, no adequate match and uncertain relation MUST remain distinct.

**DOUT-015 — Handoff distinctions.** Candidate admission, invalid or blocked admission, pending, acknowledged, retry-required and held handoff MUST remain distinct.

**DOUT-016 — Health and coverage distinction.** Component health and portfolio coverage availability MUST use separate scoped outcomes.

### Reason vocabulary

**DOUT-020 — Structured reason required.** Every committed decision MUST have one primary structured reason and MAY have supporting reasons.

**DOUT-021 — Basis class required.** Every reason MUST identify whether it is deterministic observation, deterministic policy, source assertion, editorial assessment, operational assessment, human adjudication or downstream feedback.

**DOUT-022 — Exact basis references.** Reasons MUST cite the exact observation, field, relationship, policy or dependency state used.

**DOUT-023 — No free-text-only decision.** Free text MUST NOT substitute for outcome, reason, basis class or next action.

**DOUT-024 — Versioned append-only taxonomy.** Reason-code meaning MUST be versioned and MUST NOT be repurposed after use.

**DOUT-025 — Source assertion attribution.** A source-reported label MUST remain attributed and MUST NOT become Newsroom verification through a reason code.

**DOUT-026 — Sensitive-data restraint.** Outcome and reason records MUST avoid unnecessary personal, confidential or prohibited source expression.

### Prioritisation

**DPRI-001 — Ordinal lanes.** Discovery work MUST use the canonical semantic lanes or an explicit equivalent mapping rather than an ungoverned global score.

**DPRI-002 — Gates precede priority.** Priority MUST NOT make ineligible, blocked, rejected or unauthorised work eligible.

**DPRI-003 — Urgency preserves gates.** Urgent processing MAY reduce waiting but MUST NOT lower scope, rights, novelty, relationship, lineage, collision or admission requirements.

**DPRI-004 — Deadline first within lane.** Hard safety, action, legal, Planned and Watch deadlines SHOULD precede softer ordering factors within a compatible lane.

**DPRI-005 — Coverage consequence.** Loss of a sole or principal Active path MAY raise operational priority without becoming an editorial materiality claim.

**DPRI-006 — Fairness and aging.** Routine work MUST have starvation protection, subject to revalidation and explicit expiry or closure.

**DPRI-007 — Optional work yields first.** Comparator, optional audit and other non-required work SHOULD be reduced before required Anchor, Urgent, Time-sensitive or Planned work under backpressure.

**DPRI-008 — Stable tie-break.** Equal-priority work MUST use a deterministic final tie-break rather than nondeterministic model order.

**DPRI-009 — No volume authority.** Article, domain, result or repetition count MUST NOT independently establish priority, materiality, independence or Candidate eligibility.

**DPRI-010 — No quota promotion.** Category, geography, finance, Hong Kong or publication-volume quotas MUST NOT promote a weaker Signal, Lead or Candidate.

**DPRI-011 — Confidence non-authority.** Model confidence, similarity and retrieval scores MAY inform review but MUST NOT independently determine lane, disposition, relationship or Candidate admission.

**DPRI-012 — Priority decision versioning.** Reprioritisation MUST create a later Priority Decision with exact basis and governing versions.

### Numeric scoring boundary

**DPRI-020 — No launch global scalar.** The target discovery system MUST NOT use one global composite score as the governing eligibility or disposition mechanism.

**DPRI-021 — Stage-local purpose only.** A later score MAY support only one bounded stage-local function and MUST declare its non-authority boundaries.

**DPRI-022 — Evaluation before authority.** Numeric factors and thresholds MUST remain **Needs experiment** until owner-approved evaluation compares them with the ordinal baseline.

**DPRI-023 — Missing is not zero.** A score MUST preserve unknown, unavailable and not-applicable data rather than silently mapping all to zero.

**DPRI-024 — Factor inspectability.** A scoring decision MUST retain version, factors, contributions, threshold and result.

**DPRI-025 — No post-hoc thresholds.** Thresholds MUST be approved before qualification results and cannot be tuned on the same Run used as release evidence.

**DPRI-026 — Slice protection.** Aggregate scoring performance MUST NOT hide a material language, geography, coverage, urgency or transition regression.

## Acceptance criteria

1. One authoritative guidance revision may receive a Candidate outcome with one source and no media repetition.
2. Ten duplicate articles cannot outrank one Urgent direct warning solely through volume.
3. Fresh out-of-scope entertainment cannot pass a gate because it has high recency or trusted domains.
4. A run with no qualifying Hong Kong Candidate creates no forced Hong Kong slot or filler.
5. A Hong Kong Lead is not rejected solely because no UK effect is shown.
6. Urgent processing cannot bypass rights, exact collision checks or Candidate validation.
7. A model confidence value cannot create a development, merge, reject or Candidate by itself.
8. Parser failure produces an operational outcome and reason, not editorial rejection.
9. A Watch outcome without a condition is invalid.
10. Same-state repeated coverage normally associates without a Candidate.
11. Candidate admission blocked by collision-check outage remains operationally blocked rather than becoming new event.
12. An unchanged source and a zero-result search retain different outcomes.
13. A later Source Revision creates a later decision and does not rewrite the earlier reject, watch or association.
14. A current `open` or `closed` projection can be rebuilt from immutable outcome history.
15. Routine work eventually receives processing opportunity without bypassing stale-work revalidation.
16. Optional Comparator work yields before required Urgent or Active-path work under backpressure.
17. No score can overcome a clear exclusion, rights block, quarantine or Operational hold.
18. A reason code identifies its basis class and exact supporting input.
19. Retired reason codes remain interpretable and are not reused with a new meaning.
20. Acceptance of this specification authorises no score, threshold, queue configuration, model call, source collection, shadow run or production activation.

## Owner decisions required to complete Topic 10

The Draft recommends these decisions:

1. Accept the non-bypassable decision order from authority and source semantics through deterministic gates, editorial triage, relationship, Candidate admission and Evidence Handoff.
2. Accept that outcome, reason, next action, current status and processing priority are separate concepts and records.
3. Accept the canonical Check, Signal, Lead, relationship, Candidate, Handoff, health and coverage-availability outcome families.
4. Accept immutable outcomes and terminality for one exact version, with later records rather than mutation when a new Revision, policy or authorised re-evaluation occurs.
5. Accept that every watch, hold and pending outcome requires an inspectable condition, owner, retry or expiry path.
6. Accept namespaced, versioned, append-only reason families with one primary reason, optional supporting reasons, basis class and exact input references.
7. Accept explicit separation of deterministic observation, deterministic policy, source assertion, editorial assessment, operational assessment, human adjudication and downstream feedback.
8. Accept the ordinal priority lanes `CONTAINMENT`, `URGENT`, `TIME_SENSITIVE`, `PLANNED_WINDOW`, `ROUTINE` and `OPTIONAL_EVALUATION`.
9. Accept within-lane ordering by hard deadline, consequence of delay, staleness risk, fairness or age, dependency readiness and deterministic tie-break where applicable.
10. Accept that urgency expedites work but never lowers scope, rights, novelty, relationship, lineage, collision or admission gates.
11. Accept that article count, domain count, publisher tier, search rank, model confidence, similarity, virality and legacy event-child status are non-authoritative priority proxies.
12. Accept removal of target discovery quotas and guaranteed slots: category balance, finance caps, Hong Kong guarantees and unused capacity cannot promote weaker work or create filler.
13. Accept that Hong Kong and other coverage obligations are protected through source portfolio, scope, monitoring, evaluation and coverage posture rather than Candidate quotas.
14. Accept fairness and aging for Routine work, with stale-work revalidation and explicit closure rather than starvation or silent dropping.
15. Accept no global composite discovery score for launch; any later stage-local score and numeric threshold remains **Needs experiment**, requires owner-approved evaluation against the ordinal baseline and cannot override gates.
16. Accept versioned Priority Decisions and rebuildable current status rather than mutable priority or status as sole authority.
17. Accept that Topic 10 authorises no score, threshold, queue configuration, model, source, shadow run, spending or production activation.
