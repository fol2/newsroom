# Discovery shadow-evaluation and release-evidence specification

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
**Related quality specification:** [`quality-evaluation-and-change-control.md`](quality-evaluation-and-change-control.md) (`Draft`)  
**Related current evaluation:** [`../../evaluation/clustering_eval_dataset_v1.md`](../../evaluation/clustering_eval_dataset_v1.md)  
**Implementation authority:** None. Acceptance defines evaluation semantics and release-evidence requirements; it authorises no source collection, search, model call, provider use, spending, shadow execution or production activation.  
**Supersedes:** None

## Purpose

Define how a discovery portfolio, source adapters, change semantics, deterministic gates, triage policy, event grouping and bounded search earn credible release evidence before production authority.

The protocol answers separate questions rather than collapsing quality into one score:

1. Did each adapter observe source state correctly?
2. Did the selected portfolio detect the in-scope developments it was expected to detect?
3. Did deterministic gates preserve relevant ambiguity and reject only clear exclusions?
4. Did triage route Leads and group events correctly without fragmentation or snowball absorption?
5. Did the system meet its latency, cost and operational-behaviour assumptions?
6. Which sources, Comparators, policies and components should be admitted, changed, retained only for evaluation or rejected?

No provider, media feed, legacy pipeline or union of paths is complete ground truth. Evaluation constructs a reviewable, prospective and versioned evidence universe from several permitted paths and authorised human adjudication.

## Scope

This specification defines:

- shadow isolation and absence of public authority;
- pre-registered Evaluation Plans and frozen Evaluation Epochs;
- fixture, replay, live-shadow, prospective-comparator and fault-injection phases;
- event-level review units and evaluation records;
- prospective versus retrospective evidence;
- contemporaneous and later-outcome labels;
- reviewer, blinding, second-review and adjudication rules;
- stage-specific coverage, transition, triage, grouping, latency, cost and operational metrics;
- zero-tolerance release blockers and pre-registered non-zero thresholds;
- source and provider contribution, ablation and add or remove decisions;
- rights-limited reproducibility and failed-run retention; and
- release-evidence outcomes before operational qualification.

It does not define production schedules, retry budgets, alerts or on-call operation, which belong to Topic 9; final outcome strings or prioritisation, which belong to Topic 10; locality expansion, which belongs to Topic 11; physical deployment and migration, which belong to Topic 12; or evidence, drafting and publication evaluation after discovery handoff.

Numerical thresholds for an executable qualification Epoch are set in an owner-approved Evaluation Plan before results are reviewed.

## Core principles

1. **Shadow has no public effect.** It cannot publish, notify readers or create production authority.
2. **No comparator is truth.** Search, media, GDELT, the legacy pipeline and editor-selected stories all have omissions and bias.
3. **Prospective precedes retrospective.** Quantitative coverage claims use methods fixed before outcomes are known.
4. **Events and transitions are the units.** Duplicate URLs and repeated results do not multiply discoveries.
5. **Stages remain attributable.** Adapter, change, gate, triage, grouping, Candidate and operational errors are measured separately.
6. **Labels are contemporaneous.** Primary expected decisions use information available at the cutoff; later truth is recorded separately.
7. **Epochs are frozen.** Material source, policy, adapter, parser, model, prompt, retrieval, query or threshold changes start another Epoch.
8. **Slices precede aggregates.** Aggregate strength cannot hide failure in a material language, geography, coverage, urgency or transition slice.
9. **Rights constrain evaluation.** Accessibility does not authorise retention, replay, model submission or reviewer display.
10. **Failures remain evidence.** Failed, inconclusive and superseded Runs remain traceable.
11. **Calendar duration is not sufficient exposure.** A long Run may still leave required classes unevaluated.
12. **Evaluation is bounded.** External calls, model work, storage, reviewer time and cost are pre-authorised and measured.

## Shadow authority and isolation

A shadow implementation operates in an evaluation authority scope distinct from production. It MUST NOT:

- hold or invoke public publishing credentials;
- create reader-visible stories, notifications or feeds;
- commit production Story Candidates, Evidence Packages or publication records;
- modify production source authority, coverage decisions, rights, Leads or Candidates;
- silently alter the legacy live pipeline;
- send reader or private data to evaluation providers; or
- convert a shadow outcome into production authority without a later release decision.

Evaluation-scoped Signals, Leads, Hypotheses and Candidate outcomes MAY mirror production semantics, but their identity and authority scope remain distinguishable.

A live shadow request is still a real external request. Source and search access therefore require accepted rights, access method, rate limit, budget, query-data and retention decisions. Where terms permit transient processing only, the evaluation MAY retain request, attempt, outcome, counts, cost, reviewer decision and independently obtained publisher records without retaining prohibited result content.

Bounded production or legacy history MAY be read under an approved purpose and access policy. Shadow MUST NOT rewrite it, treat legacy event identity as canonical truth or leak protected source material into an evaluation corpus.

## Evaluation records

These are semantic contracts, not required tables.

### Evaluation Plan

An immutable, owner-approved plan established before a qualification Run. It records:

- decision purpose and scope;
- candidate portfolio, Comparators and exact component versions;
- coverage, source roles, observation models, languages and urgency classes;
- phases and start or stop conditions;
- prospective windows and Search Requests;
- sampling and randomisation controls;
- label schema and reviewer instructions;
- second-review and adjudication policy;
- zero-tolerance blockers and non-zero thresholds;
- minimum sample or exposure conditions by material slice;
- rights, retention and reviewer-access rules;
- external-request, model, reviewer-time and monetary budgets;
- known excluded gaps and unresolved paths;
- incident and early-stop rules; and
- required report and release-decision format.

A material Plan change creates a new version. A Plan cannot be edited after results are known and retain the same prospective claim.

### Evaluation Epoch

A bounded period in which portfolio, sources, policies, adapters, parsers, observation models, retrieval, triage schema, workers, queries and thresholds are frozen. A material change closes the Epoch and starts another. Different Epochs may be compared but MUST NOT be pooled as one unchanged method.

### Evaluation Run

One execution under one Plan and Epoch, including environment, start and end, inputs, attempts, costs, deviations, incidents and artefacts.

A calibration Run MAY estimate volume, ambiguity and threshold behaviour, but it is not qualification evidence when its results informed threshold selection. A later frozen qualification Run is required.

### Evaluation Unit and Case

An Evaluation Unit may be one Check, Source Revision or transition, Signal, Gate Decision, Lead disposition, reviewed event or development, Event Hypothesis relationship, Candidate admission or omission, Planned expectation, Search Request or Operational Finding.

An Evaluation Case is an immutable manifest of the exact Unit, permitted material, contemporaneous cutoff, versions, rights, reviewer view, labels, disallowed errors and applicable requirements.

### Prospective Evaluation Event

A reviewed event- or development-level unit assembled during a pre-registered window from permitted Anchors, Complements, Comparators, Planned occurrence paths or pre-declared editor additions. Human review establishes whether it is a distinct development, its coverage class, available time, expected paths and desired discovery outcome.

### Label Set and Adjudication Decision

A Label Set is immutable. Corrections create later versions. An Adjudication Decision resolves disagreement, ambiguity or launch-blocking interpretation and may retain uncertainty or mark a Case unreviewable.

### Metric Report and Release-Evidence Decision

A Metric Report is reproducible and tied to exact Plan, Epoch, Run, Case labels and metric code.

A Discovery Release-Evidence Decision classifies scope as one of:

- not evaluated;
- inconclusive or insufficient exposure;
- failed and requiring remediation;
- continue in shadow;
- Comparator-only or Research-only;
- eligible for scoped operational qualification under Topic 9;
- source or component rejected or retired; or
- blocked by an unresolved Active-coverage deficiency.

It does not activate production.

## Evaluation phases

### Phase A — Contract and fixture qualification

Every source adapter, observation model and deterministic transition rule passes representative fixtures before live shadow use. Applicable fixtures include:

- unchanged and repeated delivery;
- genuinely new item or Revision;
- maintained-page revision;
- parser or normaliser change without source change;
- rolling-list disappearance;
- complete and partial current-state snapshots;
- activation, escalation, de-escalation, clearance, expiry, cancellation and reactivation;
- redirect, `404`, explicit tombstone, withdrawal and replacement;
- first-run baseline and reset;
- Agenda creation, reschedule, cancellation, occurrence, miss, failure and late occurrence;
- duplicate and shared-origin results;
- malformed, truncated, rate-limited and unavailable responses; and
- retry, replay and crash boundaries.

Fixture success proves contract behaviour for represented cases, not real-world coverage or latency.

### Phase B — Replay and regression

A versioned, rights-permitted corpus replays known source, gate, triage and grouping cases without external calls where possible.

It includes English, Hong Kong Traditional Chinese and mixed-language cases; same-state, development, correction, related-but-distinct, new and uncertain relationships; clear exclusions; ambiguous materiality; single-source direct Leads; dependent sources; false-merge and snowball challenges; and invalid or adversarial worker outputs.

The existing clustering evaluation MAY remain a legacy regression aid. It is insufficient qualification evidence because it collapses `development` and `new_event` labels and reflects legacy mutable grouping.

### Phase C — Live prospective shadow

A frozen candidate portfolio processes live permitted inputs with no public effect. The Run records Checks, transitions, Signals, gates, Leads, Work Items, attempts, proposals, dispositions, Hypotheses and shadow Candidate outcomes, including zero-work and failure paths.

Calendar duration alone does not establish comprehensive exposure.

### Phase D — Prospective comparator audit

Pre-registered media, search or index Comparators run under Topic 7 roles, rights and budgets. Methods are fixed before review. Late indexing, truncation, altered queries, rights blocks and provider failures remain distinguishable. Hits enter event-level review and do not automatically create Coverage Gaps.

### Phase E — Fault injection and degraded operation

Approved fixtures or isolated controls exercise source failure, partial snapshots, parser breaks, rate and budget limits, model timeout or malformed output, retrieval incompleteness, duplicate delivery, crash replay, ambiguous Evidence Intake and prohibited public-effect attempts.

Fault injection MUST NOT burden third-party services beyond approved methods.

### Phase F — Review, ablation and decision

Reviewers label the prospective universe and sampled stage outputs. Reports calculate stage metrics and source contribution. Ablation considers unique detection, timeliness, resilience, noise, cost and affected slices rather than raw volume. The Run ends with a retained explicit decision and never silently graduates into production.

## Evaluation universe and sampling

The prospective event-level universe is the deduplicated, reviewer-adjudicated union available within the Plan window from:

- candidate Anchors and Complements;
- approved media or specialist Comparators;
- pre-registered search or index audits;
- Planned occurrence paths;
- authorised editor additions under a pre-declared method; and
- source or operational incidents relevant to interpretation.

This union improves review coverage but is not complete real-world ground truth.

A source, story or query added after a known miss creates a retrospective Case and Gap investigation. It is excluded from prospective coverage denominators unless its acquisition method was pre-registered.

The Plan includes:

- all shadow Candidate admissions;
- all potentially Urgent Leads and launch-blocking findings;
- all plausibly in-scope Comparator-only events;
- all missed or unresolved Planned expectations;
- all high-risk or Active deterministic exclusions and a stratified sample of routine exclusions;
- stratified rejects, watch outcomes and associations;
- stratified successful unchanged checks;
- all false-clearance, identity-collision, duplicate-transition and public-effect findings; and
- sufficient source-role, language, geography, observation-model and transition slices for the claimed scope.

High-volume classes MAY be sampled, but denominator and weights remain visible. Rare classes absent from live shadow are tested by fixtures and replay while live exposure is reported as insufficient, not passed. An Active class without a credible path remains launch-blocking.

## Label contract

### Source and transition labels

Labels distinguish correct unchanged, real new item or Revision, Representation-only change, transition correctness, false activation or ending, missed Revision, baseline error, duplicate semantic emission and correct or incorrect operational-failure representation.

### Coverage and relevance labels

Each event-level Case records in-scope, out-of-scope or unreviewable status; Active, Best-effort, deferred or excluded basis; geography, content class and urgency; whether a Lead was expected; whether evidence acquisition was likely justified; and expected discovery paths.

### Relationship and route labels

Relationship labels are same event state, development, correction or reversal, related but distinct, no adequate prior match and uncertain.

Expected routes distinguish deterministic exclusion, editorial reject, watch or defer, association without Candidate, supplemental discovery, Operational hold, new-event Candidate, development Candidate and correction-oriented Candidate where applicable.

### Contemporaneous and later-outcome labels

Primary labels use information available at the evaluation cutoff. Later facts create separate later-outcome labels and do not rewrite or unfairly re-score the contemporaneous decision.

### Dependency, timeliness and unreviewable labels

Cases retain known wire, press-release, official-release, editorial-selection and later-republication dependencies. Timeliness uses the earliest credible permitted availability where it can be established; otherwise it remains unknown.

Rights, missing source content, conflicting identity or insufficient contemporaneous material MAY produce an explicit unreviewable result rather than a guessed label.

## Review and adjudication

Final release labels require authorised human review. A model MAY assist but cannot be sole ground truth or judge its own production eligibility.

Where practical, primary review conceals path, system confidence and committed outcome until the reviewer has judged relevance, relationship and expected route. Blinding must not remove material source-role context.

Independent second review or formal adjudication is required for:

- proposed launch-blocking Active misses;
- zero-tolerance failures;
- potentially Urgent material false negatives or false Candidates;
- disputed relationship decisions that affect release conclusions;
- proposed removal of an only or principal path; and
- a pre-registered ordinary sample for reviewer-consistency measurement.

Disagreement remains visible and cannot resolve automatically in favour of better metrics or higher model confidence.

## Metrics and required slices

Every metric records counts, denominator, sample or population status, versions, window and appropriate uncertainty.

### Adapter and change metrics

Measure unchanged correctness, new-item and Revision detection, false change, false transition or ending, Representation-only change reported as publisher activity, baseline re-emission, missed baseline-active state, duplicate transition, failure-as-unchanged and idempotent replay.

### Coverage metrics

Measure reviewed prospective detection coverage, Active misses, Best-effort contribution, Planned outcomes, Comparator-only relevant events, unique and earlier detection by source or role, overlap and dependency, and unresolved blockers. These are not absolute real-world recall claims.

### Gate, Lead, triage and Candidate metrics

Measure false deterministic exclusion, retained clear-exclusion noise, ambiguity preservation, expected and unnecessary Leads, Watch Condition validity, Operational-hold confusion, route agreement, justified Candidate precision, missed and unnecessary Candidates, same-state accuracy, false and missed development, false correction, false merge, fragmentation, snowball absorption, duplicate Candidate, related-but-distinct preservation and uncertain-relationship handling.

### Timeliness, efficiency, cost and operation

Where credible source time exists, measure source availability to observation, observation to Signal, Signal to Lead, Lead to disposition, Lead to Candidate and Planned window to occurrence detection.

Measure source checks, unchanged proportion, model wake-ups on unchanged checks, Leads and Candidates per transition, worker calls, tokens and retries, Search Requests by Purpose, gross cost before credits, reviewer time, cost per relevant event or justified Candidate and work amplification.

Operational metrics cover source, parser, rights, rate, model, retrieval and handoff failures; failure-to-no-news confusion; queue loss; duplicate execution; stale-version processing; unresolved Findings; quarantine and recovery; and authority-boundary attempts.

Reports separate at minimum:

- United Kingdom, Hong Kong and qualifying Global;
- England, Scotland, Wales and Northern Ireland where applicable;
- English, Hong Kong Traditional Chinese and mixed-language;
- Active, Best effort and deferred context;
- Urgent, Time-sensitive, Planned and Routine;
- source role and approved Search Purpose;
- Anchor, Complement and Comparator;
- append-only, maintained-document, complete-current-state, rolling-list, explicit-delta and Planned Agenda models;
- material transition classes; and
- retrieval and worker versions.

Insufficient exposure is reported as not evaluated or inconclusive, not pooled into an aggregate pass.

## Release blockers and thresholds

One confirmed occurrence of any following condition blocks qualification of the affected scope until remediation and a fresh qualifying Run:

- public publication, notification or reader-visible effect from shadow;
- shadow mutation of production discovery, evidence or publication authority;
- unapproved access, query data, retention, model submission or provider spending;
- failure, partial response or budget block represented as successful unchanged or zero-result editorial meaning;
- parser or normaliser change fabricated as publisher Revision;
- rolling-list or partial-snapshot absence used as withdrawal, deletion or clearance;
- duplicate semantic Lead or Candidate transition from retry or replay;
- destructive Event Hypothesis merge or lost predecessor lineage;
- Candidate admission without exact collision checks, lineage or deterministic validation;
- model, result text or agent bypass of policy, rights, budget or tool authority;
- search snippet or discovery record promoted directly into evidence;
- omitted decision Lead or untracked public-impacting uncertainty; or
- an Active class with no credible path or demonstrated systemic inability to cover it.

All non-zero thresholds are approved in the Evaluation Plan before qualification results are reviewed. A calibration Epoch may inform threshold selection but is not qualification evidence. Aggregate success cannot override a required-slice failure or missing exposure.

## Source and provider decisions

A source or Comparator MAY be proposed for a stronger role when it closes an Active blocker, adds unique or materially earlier detection, provides a distinct failure path, improves a required slice or supplies a necessary Agenda or occurrence path. Rights, noise, cost and Topic 9 readiness still apply.

A source MAY remain a Complement or Comparator for resilience, revision visibility, current-state confirmation or audit even without many unique events.

Removal or rejection may follow sufficient evidence of no justified contribution, pure duplication, disproportionate noise or burden, unreliability, unsafe operation, rights failure or loss of coverage mapping. A short quiet period is insufficient to remove a rare-event Anchor, and Anchor removal requires coverage-impact review.

Ablation reports event-level effects of removing each source, role, component or Search Purpose where data permits.

## Legacy, reproducibility and retention

The current Brave, RSS, GDELT and Gemini pipeline MAY be a rights-permitted legacy Comparator. It is not the correctness baseline, coverage definition or canonical event identity. Its scope mismatch, per-link model calls, forced new-event behaviour, mutable merges and evaluation-label limitations remain explicit.

Reports retain, subject to rights, Plan, Epoch, Run and component versions; source and provider versions; prospective windows and queries; sampling and reviewer assignment; labels and adjudications; metric code; environment and deviations; aggregate and slice results; incidents; cost; reviewer time; and release decision.

Protected source material MAY be represented through protected references, hashes, permitted extracts or independently reproducible fixtures. Public repository artefacts exclude secrets, prohibited expression, personal data and confidential review material.

Failed and superseded Runs remain traceable. Confirmed errors and material near misses SHOULD create rights-permitted regression Cases.

## Requirements

### Shadow boundary

**DEVAL-001 — No public effect.** Shadow MUST NOT publish, notify readers or create reader-visible effects.

**DEVAL-002 — Authority isolation.** Shadow records MUST remain distinguishable from production discovery, evidence and publication authority.

**DEVAL-003 — Real requests remain governed.** Live source and search requests MUST pass rights, privacy, rate and budget controls despite shadow status.

**DEVAL-004 — No silent production mutation.** Shadow MUST NOT modify production source, Lead, Candidate, evidence or publication state.

### Plan and Epoch

**DEVAL-010 — Pre-registered Plan.** Every qualification Run MUST have an immutable owner-approved Evaluation Plan before outcomes are reviewed.

**DEVAL-011 — Frozen Epoch.** Material component, source, query, threshold or policy change MUST start a new Epoch.

**DEVAL-012 — Calibration separation.** A Run used to choose thresholds MUST NOT also qualify those thresholds.

**DEVAL-013 — Duration is not sufficiency.** Calendar duration alone MUST NOT establish adequate exposure.

**DEVAL-014 — Early-stop evidence.** An early-stopped Run MUST retain a failed or inconclusive report.

### Universe, labels and review

**DEVAL-020 — Event-level universe.** Coverage comparison MUST deduplicate results into reviewed events or developments rather than count URLs.

**DEVAL-021 — No ground-truth provider.** No source, legacy pipeline, feed, search provider or index is complete ground truth.

**DEVAL-022 — Prospective separation.** Prospective methods MUST be fixed before review; retrospective additions remain separately labelled.

**DEVAL-023 — Contemporaneous label.** Primary route and relationship labels use information available at the cutoff.

**DEVAL-024 — Later outcome separate.** Later facts do not rewrite contemporaneous expected decisions.

**DEVAL-025 — Unreviewable allowed.** Rights or evidence limitations support explicit unreviewable status.

**DEVAL-026 — Negative and failure sampling.** Samples include unchanged, excluded, rejected, watched, associated and failed work, not only positive outcomes.

**DEVAL-030 — Human-reviewed labels.** Final release labels require authorised human review; models cannot be sole ground truth.

**DEVAL-031 — Blinding where practical.** Primary review SHOULD conceal path, confidence and system outcome where editorial context remains sufficient.

**DEVAL-032 — Second review.** Launch blockers, zero-tolerance failures, Urgent material errors and a planned ordinary sample require independent review or adjudication.

**DEVAL-033 — Disagreement retained.** Reviewer disagreement remains visible and does not resolve by model confidence or metric preference.

### Metrics and slices

**DEVAL-040 — Stage-specific metrics.** Adapter, transition, gate, triage, grouping, Candidate, latency, cost and operational metrics remain separately attributable.

**DEVAL-041 — Coverage is bounded.** Detection coverage is described within the reviewed prospective universe, not as absolute recall.

**DEVAL-042 — Counts with rates.** Every rate includes count, denominator, sampling method and uncertainty.

**DEVAL-043 — Required slices.** Aggregate results MUST NOT hide material slice failures.

**DEVAL-044 — Insufficient exposure.** Required slices without enough evidence are not evaluated or inconclusive.

**DEVAL-045 — Source contribution.** Evaluation distinguishes unique and earlier detection, resilience, overlap, dependency, noise and cost.

**DEVAL-046 — Triage error classes.** Evaluation measures false merge, fragmentation, snowball absorption, false or missed development, duplicate Candidate and unnecessary Candidate creation.

**DEVAL-047 — Efficiency and amplification.** Evaluation measures unchanged model wake-ups, worker and search amplification, gross cost and reviewer burden.

### Release blockers and decisions

**DEVAL-050 — Zero-tolerance enforcement.** Confirmed zero-tolerance failure blocks the affected scope pending remediation and fresh evidence.

**DEVAL-051 — Thresholds before results.** Non-zero thresholds require owner approval before qualification review.

**DEVAL-052 — No post-hoc pooling.** Materially different Epochs MUST NOT be pooled to manufacture a pass.

**DEVAL-053 — Slice can block.** Required slice failure may block release despite passing aggregate.

**DEVAL-054 — Active path blocker.** Missing or systemically ineffective Active coverage remains launch-blocking.

**DEVAL-060 — Evidence-based role change.** Source promotion, removal or role change cites event-level coverage, resilience, rights, cost and operational evidence.

**DEVAL-061 — Quiet-period guard.** A rare-event Anchor MUST NOT be removed solely because a short Run produced no unique event.

**DEVAL-062 — Comparator non-promotion.** A Comparator MUST NOT become an Anchor merely because it returns more results.

**DEVAL-063 — Search-purpose attribution.** Search value, noise and cost remain attributable to exact Purpose and provider version.

**DEVAL-064 — Rights-limited provider evaluation.** Provider data MUST NOT be retained for evaluation contrary to terms.

**DEVAL-070 — Reproducible report.** Every Run retains versions, methods, samples, labels, metrics, deviations, cost and environment sufficient for reasonable reproduction.

**DEVAL-071 — Failed runs retained.** Failed and superseded reports remain traceable.

**DEVAL-072 — Public-repository safety.** Public artefacts exclude secrets, prohibited expression, personal data and confidential material.

**DEVAL-073 — Explicit decision.** A completed Run ends with a retained owner decision or explicit unresolved status and never silently becomes production.

**DEVAL-074 — Regression learning.** Confirmed errors and material near misses SHOULD create rights-permitted regression Cases.

## Acceptance criteria

1. A shadow model cannot publish or create production Candidate authority.
2. A real shadow request remains blocked without required rights.
3. Thresholds chosen from calibration require a later frozen qualification Epoch.
4. A long Run without a required language or transition slice cannot claim that slice passed.
5. Duplicate articles become one reviewed event with dependencies retained.
6. A Comparator-only hit creates no Gap before relevance, timing, expected-path and health review.
7. A hindsight query is excluded from prospective coverage reporting.
8. Later truth does not automatically make a contemporaneously reasonable watch or hold wrong.
9. False clearance from a partial current-state snapshot is a zero-tolerance blocker.
10. Parser change fabricated as publisher activity is a zero-tolerance blocker.
11. Worker timeout remains operational failure and cannot improve editorial metrics.
12. Aggregate success cannot hide a material false-merge or Urgent Active failure.
13. A source with no unique event may remain for justified resilience.
14. A rare-event Anchor is not removed solely for a short quiet period.
15. Rights-restricted provider results are not retained in a prohibited persistent corpus.
16. The legacy pipeline may be compared but cannot define correctness.
17. Failed qualification evidence remains available after a later pass.
18. Topic 9 receives scoped eligibility, unresolved blockers and explicit operational evidence needs.
19. Acceptance authorises no source, search provider, model, schedule, spending, run or production activation.

## Completion record

The product owner accepted this specification on 2026-07-15 with these decisions:

- evaluation runs in a distinct authority scope with no public effect or production mutation;
- owner-approved Evaluation Plans and frozen Evaluation Epochs are required, and calibration is separate from qualification;
- the accepted phases are fixtures, replay, live prospective shadow, prospective comparator audit, fault injection, review and ablation;
- the prospective evaluation universe is event-level and assembled from several permitted paths without claiming complete ground truth;
- prospective and retrospective evidence remain separate, including exclusion of hindsight queries from prospective coverage claims;
- contemporaneous labels, later-outcome labels and explicit unreviewable outcomes remain distinct;
- final labels require authorised human review, practical blinding and second review for launch blockers, zero-tolerance and Urgent material cases;
- adapter, change, coverage, gate, triage, grouping, Candidate, timeliness, cost and operation are evaluated separately rather than through one composite score;
- detection coverage is bounded to the reviewed prospective universe and is not absolute recall;
- required geography, language, coverage, urgency, source-role, portfolio, observation-model, transition and component slices cannot be hidden by aggregate results;
- the accepted zero-tolerance blocker set includes public effect, rights or authority bypass, failure-as-no-news, false absence-based ending, fabricated Revision, duplicate transition, destructive merge, invalid Candidate admission and discovery-to-evidence bypass;
- non-zero thresholds are owner-approved before qualification review, calibration Runs are not release evidence and changed Epochs cannot be pooled post hoc;
- source contribution and ablation use unique and earlier detection, resilience, overlap, noise, rights, cost and reviewer burden rather than raw item count;
- Comparators and search providers do not become Anchors merely by returning more results, and rights-incompatible provider data cannot form a persistent evaluation corpus;
- the legacy pipeline and v1 clustering dataset are comparison or regression aids only and do not satisfy the accepted relationship and route evaluation contract;
- release-evidence outcomes are explicit and include insufficient, failed, continue shadow, Comparator-only, scoped Topic 9 eligibility, rejected and launch-blocked;
- reports are reproducible and rights-limited, failed Runs remain retained and confirmed errors feed regression Cases; and
- Topic 8 authorises no run. Execution still requires an approved Plan, rights, budgets and Topic 9 operational controls.
