# Discovery shadow-evaluation and release-evidence specification

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
**Related quality specification:** [`quality-evaluation-and-change-control.md`](quality-evaluation-and-change-control.md) (`Draft`)  
**Related current evaluation:** [`../../evaluation/clustering_eval_dataset_v1.md`](../../evaluation/clustering_eval_dataset_v1.md)  
**Decision state:** The evaluation protocol, review units, labels, metrics, blockers and decision rules below are proposals. Committing this Draft does not authorise source collection, search, model calls, shadow operation, provider use, spending or production activation.  
**Supersedes:** None

## Purpose

Define how the proposed discovery portfolio, source adapters, change semantics, deterministic gates, triage policy, event grouping and bounded search earn credible release evidence before production authority.

The protocol must answer six different questions without collapsing them into one score:

1. Did each source adapter observe source state correctly?
2. Did the selected portfolio detect the in-scope developments it was expected to detect?
3. Did deterministic gates preserve relevant ambiguity and reject only clear exclusions?
4. Did triage route Leads and group events correctly without fragmentation or snowball absorption?
5. Did the system meet its cost, latency and operational-behaviour assumptions?
6. Which sources, Comparators, policies and components should be admitted, changed, retained for evaluation only or rejected?

No provider, legacy system or media feed is treated as complete ground truth. Evaluation constructs a reviewable, prospective and versioned evidence universe from several permitted paths and explicit human adjudication.

## Scope

This specification defines:

- shadow isolation and absence of public authority;
- pre-registered Evaluation Plans and frozen Evaluation Epochs;
- fixture, replay, live-shadow, prospective-comparator and fault-injection phases;
- evaluation records and event-level review units;
- prospective and retrospective evidence separation;
- contemporaneous and later-outcome labels;
- reviewer, blinding, second-review and adjudication rules;
- stage-specific coverage, transition, triage, grouping, latency, cost and operational metrics;
- zero-tolerance release blockers and pre-registered non-zero thresholds;
- source and provider contribution, ablation and add/remove decisions;
- rights-limited reproducibility and failed-run retention; and
- the release-evidence package needed before Topic 9 operational admission and an owner activation decision.

It does not define:

- production polling intervals, retry budgets, alert thresholds, on-call processes or automatic containment, which belong to Topic 9;
- final reason-code strings or prioritisation scores, which belong to Topic 10;
- locality expansion, which belongs to Topic 11;
- physical storage, deployment or migration, which belong to Topic 12;
- evidence sufficiency, drafting or publication evaluation beyond the discovery hand-off; or
- numerical thresholds for an actual qualification epoch, which must be owner-approved in its Evaluation Plan before results are reviewed.

## Core principles

1. **Shadow means no public effect.** A shadow run cannot publish, notify readers, alter production evidence or create production authority.
2. **No single comparator is truth.** Search, GDELT, media feeds, the legacy pipeline and editor-selected stories all have omissions and biases.
3. **Prospective before retrospective.** Quantitative coverage claims use methods fixed before outcomes are known. Hindsight investigation is labelled separately.
4. **Events and transitions, not result volume.** Ten duplicate URLs do not become ten discoveries, and one direct revision may be more valuable than broad media volume.
5. **Stage-specific accountability.** Adapter, change, gate, triage, grouping, Candidate and operational errors are measured separately.
6. **Contemporaneous fairness.** The primary label uses information reasonably available at the decision cutoff; later truth is recorded separately.
7. **Frozen epochs.** Material source, policy, adapter, parser, model, prompt, retrieval, query or threshold changes start a new Evaluation Epoch.
8. **Slices before aggregates.** A strong total score cannot hide failure in Hong Kong Chinese, an Active class, Urgent work, maintained-page revisions or another material slice.
9. **Rights constrain evaluation.** Public accessibility does not authorise retention, replay, model submission or reviewer display.
10. **Failures remain evidence.** Failed, inconclusive and superseded runs remain traceable and cannot be deleted because a later run passes.
11. **Calendar duration is not sufficiency.** Running for a week or month does not prove readiness if required cases, slices or source states were not observed.
12. **Evaluation itself is bounded.** Reviewer workload, source calls, search calls, model work, storage and cost are pre-authorised and measured.

## Shadow authority and isolation

### Evaluation-only execution boundary

A shadow implementation may use the accepted semantic contracts but must operate in an evaluation authority scope distinct from production.

It must not:

- hold or invoke public publishing credentials;
- create reader-visible stories, notifications or feeds;
- commit production Story Candidates, Evidence Packages or publication records;
- modify production Source Definition authority, coverage decisions or source rights;
- silently affect the legacy live pipeline;
- send reader or private data to evaluation providers; or
- turn a shadow decision into production authority without a later release decision.

Evaluation-scoped Signals, Leads, Hypotheses and Candidate outcomes may mirror production semantics for testing, but their identities and authority scope remain distinguishable from production records.

### Live external effects

A live shadow source check or search request is still a real external request. It requires accepted rights, access method, rate limit, budget, query-data and retention decisions before execution.

A rights restriction may require transient result processing or metadata-only retention. In that case the evaluation may retain request, attempt, outcome, counts, costs, reviewer decision and independently obtained publisher records without retaining prohibited result payloads.

### Production history access

A shadow evaluator may read bounded production or legacy history only under an approved purpose and access policy. It must not rewrite that history, treat legacy event identity as canonical truth or leak protected source material into an evaluation corpus.

## Evaluation records

These are conceptual contracts, not required tables.

### Evaluation Plan

An immutable, owner-approved plan established before a qualification run. It records:

- evaluation purpose and decision scope;
- candidate portfolio, Comparators and exact component versions;
- coverage classes, source roles, observation models, languages and urgency classes in scope;
- evaluation phases and start or stop conditions;
- prospective windows and Search Requests;
- sampling frames and randomisation controls;
- label schema and reviewer instructions;
- review, second-review and adjudication policy;
- zero-tolerance blockers and non-zero thresholds;
- minimum sample or exposure conditions by material slice;
- rights, retention and reviewer-access rules;
- request, model, reviewer-time and monetary budgets;
- known excluded gaps and unresolved source paths;
- incident and early-stop rules; and
- required report and release-decision format.

A material plan change creates a new Plan version. A plan cannot be edited after results are known and still claim the same prospective method.

### Evaluation Epoch

A bounded period in which the evaluated portfolio, policy, adapters, parsers, observation models, retrieval, triage schema, model or worker, query methods and thresholds are frozen.

A material change closes the current Epoch and starts another. Results from different Epochs may be compared but must not be pooled as if the method were unchanged.

### Evaluation Run

One execution under one Plan and Epoch, including environment, start and end, actual inputs, attempts, costs, deviations, incidents and result artefacts.

A calibration Run estimates volume, label ambiguity and metric behaviour but cannot be used as qualification evidence if its results were used to set thresholds. A later frozen qualification Run is required.

### Evaluation Unit

A unit selected for review. Depending on the stage, it may be:

- one Check Request or Check Outcome;
- one Source Item, Revision, Representation or observable transition;
- one Discovery Signal or Gate Decision;
- one News Lead disposition;
- one reviewed event or material development;
- one Event Hypothesis relationship decision;
- one Story Candidate admission or omission;
- one Planned Agenda expectation and occurrence outcome;
- one Search Request or comparator result set; or
- one Operational Finding or fault-injection case.

### Prospective Evaluation Event

A reviewed event- or development-level unit assembled from permitted paths during a pre-registered window. It may be surfaced by an Anchor, Complement, Comparator, manual review or Planned Agenda occurrence.

It is not automatically in scope or a missed story. Human review establishes whether it represents one distinct development, its coverage class, available time, expected discovery paths and desired discovery outcome.

### Evaluation Case

An immutable manifest containing the exact Evaluation Unit, allowed source or representation material, contemporaneous cutoff, versions, rights, reviewer view, labels, disallowed errors and applicable requirements.

### Label Set

An immutable set of reviewer labels for one Case. A later corrected label creates another version and preserves the earlier review and reason.

### Adjudication Decision

A retained decision resolving reviewer disagreement, ambiguity or launch-blocking interpretation. It records the available material, reviewers, rationale, final label or `unreviewable` outcome and affected metrics.

### Metric Report

A reproducible report tied to one Plan, Epoch, Run, dataset or live ledger, label version and calculation version.

### Discovery Release-Evidence Decision

An owner decision that may classify the evaluated scope as:

- not evaluated;
- inconclusive or insufficient exposure;
- failed and requiring remediation;
- continue in shadow;
- Comparator-only or Research-only;
- eligible for scoped operational qualification under Topic 9;
- source or component rejected or retired; or
- blocked by an unresolved Active-coverage deficiency.

This decision does not itself activate production.

## Evaluation phases

### Phase A — Contract and fixture qualification

Every source adapter, observation model and deterministic transition rule must pass representative fixtures before live shadow use.

Required fixture classes include, where applicable:

- unchanged response and repeated delivery;
- genuinely new item;
- maintained-page revision;
- parser or normaliser change without source change;
- rolling-feed disappearance;
- complete and partial current-state snapshots;
- activation, escalation, de-escalation, clearance, expiry, cancellation and reactivation;
- redirect, `404`, explicit tombstone, withdrawal and replacement;
- first-run baseline and reset;
- Agenda creation, reschedule, cancellation, occurrence, miss, failure and late occurrence;
- duplicate or shared-origin results;
- malformed, truncated, rate-limited and unavailable source responses; and
- retry, replay and crash boundaries.

Fixture success proves contract behaviour for those cases, not real-world coverage or timeliness.

### Phase B — Replay and regression

A versioned, rights-permitted corpus replays known source, gate, triage and grouping cases without external calls where possible.

The regression corpus must include English, Hong Kong Traditional Chinese and mixed-language cases; same-state, development, correction, related-but-distinct, new and uncertain relationships; clear exclusions; ambiguous materiality; single-source direct Leads; multi-source dependencies; false-merge and snowball challenges; and invalid or adversarial worker outputs.

The existing clustering evaluation may be retained as a legacy regression aid, but it is insufficient as qualification evidence because it collapses `development` and `new_event` labels and reflects legacy event mutation semantics.

### Phase C — Live prospective shadow

The frozen candidate portfolio processes live permitted inputs without public effect.

The Run records every source check, transition, Signal, gate, Lead, Work Item, worker attempt, proposal, disposition, Hypothesis and shadow Candidate outcome, including zero-work and failure paths.

A live Run must not be described as comprehensive merely because it lasted a set number of days. Required exposure and label conditions in the Plan determine whether evidence is sufficient.

### Phase D — Prospective comparator audit

Pre-registered media, search or index Comparators run under the accepted Topic 7 roles, rights and budgets.

Comparator methods are fixed before review. Late-indexed, truncated, altered-query, rights-blocked and provider-failed results remain distinguishable. Comparator hits enter event-level review and do not automatically become Coverage Gaps.

### Phase E — Fault injection and degraded operation

Approved fixtures or isolated test controls exercise:

- source timeouts and malformed responses;
- partial snapshots;
- parser contract breaks;
- rate limits and budget exhaustion;
- model timeout, refusal, malformed and adversarial output;
- retrieval incompleteness;
- duplicate delivery and crash replay;
- Evidence Intake ambiguity; and
- prohibited public-effect attempts.

Fault injection must not target or burden third-party production services beyond approved methods.

### Phase F — Review, ablation and decision

Reviewers label the prospective universe and sampled stage outputs. Reports calculate stage metrics and source contribution. Ablation analysis considers the effect of removing each source, role or component without claiming that a short zero-yield period proves permanent uselessness.

The Run ends with a retained report and explicit decision. It does not silently graduate into production.

## Evaluation universe and sampling

### Prospective universe

The prospective event-level universe is the deduplicated, reviewer-adjudicated union of permitted items available within the Plan window from:

- candidate Anchors and Complements;
- approved media or specialist Comparators;
- pre-registered search or index audits;
- Planned Agenda occurrence paths;
- authorised editor-added events identified during the same window under a pre-declared method; and
- source or operational incidents relevant to coverage interpretation.

The union improves review coverage but is not claimed to represent every real-world event.

### Retrospective additions

A story, source or query added after a known miss may create a retrospective Case and Gap investigation. It is excluded from prospective recall denominators unless the Plan explicitly defined that acquisition method before the window.

### Stage samples

The Plan must include:

- all shadow Story Candidate admissions;
- all potentially Urgent Leads and all launch-blocking findings;
- all comparator-only events plausibly in scope;
- all missed or unresolved Planned expectations;
- all deterministic exclusions in high-risk or Active slices, plus a stratified sample of routine exclusions;
- a stratified sample of rejects, watch outcomes and associations;
- a stratified sample of successful unchanged checks;
- all false-clearance, identity-collision, duplicate-transition and public-effect findings; and
- source-role, language, geography, observation-model and transition slices sufficient for the Plan's claims.

The Plan may review high-volume routine classes by sampling, but must report the sampling denominator and weight. It cannot sample away every negative or operational case.

### Rare and absent classes

Rare Urgent incidents, cancellations, withdrawals or court outcomes may not occur during one live window. Replay and fixture cases test semantics, while the report marks live coverage exposure as insufficient rather than claiming a pass.

An Active class with no credible path remains launch-blocking under `COV-045` regardless of aggregate results.

## Label contract

### Source and transition labels

Review or fixture truth distinguishes:

- correct unchanged;
- correct new item or Revision;
- representation-only change;
- correct or false transition classification;
- false activation, escalation, clearance, cancellation, withdrawal or deletion;
- missed revision or transition;
- baseline misclassification;
- duplicate semantic emission; and
- operational failure represented correctly or incorrectly.

### Coverage and relevance labels

Each event-level Case records:

- in scope, out of scope or unreviewable;
- Active, Best effort, deferred gap or excluded basis;
- geography and content class;
- Urgent, Time-sensitive, Planned or Routine context;
- whether discovery should have produced a Lead;
- whether evidence acquisition was likely justified; and
- which selected paths were reasonably expected to detect it.

### Relationship labels

Topic 6 labels remain separate:

- same event state;
- development of;
- correction, clarification or reversal of;
- related but distinct;
- no adequate prior match; and
- uncertain relationship.

### Route labels

Expected Lead route is one of:

- deterministic exclusion;
- editorial reject;
- watch or defer;
- associate without Candidate;
- supplemental discovery;
- Operational hold;
- new-event Candidate;
- development Candidate; or
- correction-oriented Candidate where applicable.

### Contemporaneous and later-outcome labels

The primary expected route uses only information available at the evaluation cutoff. A later outcome may record that an event proved larger, smaller, false, corrected or more important.

Later information must not rewrite the contemporaneous label or unfairly credit a system for facts unavailable at decision time.

### Dependency and timeliness labels

Cases record common wire, press release, official release, editorial-selection and later-republication dependencies where known.

A discovery-time label identifies the earliest credible permitted availability, the first selected-path detection, the first Lead and the first Candidate. If earliest availability cannot be established reliably, latency remains unknown rather than invented.

### Unreviewable

A reviewer may label a Case unreviewable because rights, missing source content, conflicting identity, insufficient contemporaneous material or another explicit limitation prevents a defensible answer. The system must not force a guessed label merely to complete metrics.

## Review and adjudication

### Reviewer authority

Final evaluation labels are made by authorised human reviewers or delegated editors under versioned instructions. A model may assist with candidate labels or summaries but cannot be the sole ground truth or judge the production eligibility of itself.

### Blinding

Where practical, the primary reviewer should label event relevance, relationship and expected route without seeing which path found the event, the system's confidence or its committed outcome. Path and system output may then be revealed for error analysis.

Blinding must not hide source role or material needed to make the editorial decision.

### Second review

The Plan requires independent second review or explicit adjudication for:

- every proposed launch-blocking Active miss;
- every zero-tolerance failure;
- every potentially Urgent false negative or false Candidate;
- disputed same-state, development, correction or related-but-distinct decisions affecting release conclusions;
- every proposed source removal where it is the only or principal path for an obligation; and
- a pre-registered sample of ordinary Cases to estimate reviewer consistency.

### Reviewer disagreement

Disagreement remains visible. It does not resolve by model confidence, majority vote without policy or selecting the label that improves metrics.

The adjudicator may choose a final label, retain uncertainty or mark the Case unreviewable. Agreement and adjudication rates are reported.

## Metrics

Every metric identifies its denominator, sample or full-population status, versions, observation window and uncertainty. Counts accompany rates.

### Adapter and change metrics

- successful unchanged correctness;
- new-item and Revision detection on fixtures and reviewed live cases;
- false-change and false-transition rate;
- false clearance or false deletion rate;
- representation-only change incorrectly reported as publisher change;
- baseline historical re-emission and missed baseline-active state;
- duplicate semantic transition rate;
- partial or failed check incorrectly reported as unchanged; and
- idempotent replay correctness.

### Coverage metrics

- reviewed prospective detection coverage within the constructed evaluation universe;
- reviewed Active-class misses;
- Best-effort detections and limitations;
- Planned occurrence detected, missed, unresolved, late and source-failed outcomes;
- comparator-only relevant events;
- unique and materially earlier detections by Source Definition, source role and portfolio function;
- overlap and dependency between paths; and
- unresolved launch-blocking coverage gaps.

These metrics are not described as absolute real-world recall.

### Gate and Lead metrics

- false deterministic exclusion;
- clear-exclusion retention noise;
- ambiguous-relevance preservation;
- Lead creation where expected;
- unnecessary Lead rate by source and class;
- watch outcomes with valid Watch Conditions; and
- operational holds incorrectly represented as editorial decisions.

### Triage and Candidate metrics

- expected-route agreement;
- Candidate justification precision within reviewed Cases;
- missed Candidate opportunity within the prospective universe;
- unnecessary Candidate admission;
- same-state association correctness;
- false development and missed development;
- false correction or reversal classification;
- false merge, fragmentation and snowball absorption;
- duplicate Candidate admission;
- related-but-distinct preservation;
- uncertain relationship handling; and
- Candidate Version changes caused by material versus non-material additions.

### Timeliness metrics

Where a credible availability time exists, reports measure:

- source availability to first selected-path observation;
- observation to Signal;
- Signal to Lead;
- Lead to disposition;
- Lead to Candidate; and
- Planned expected window to occurrence detection.

Timeliness is reported by urgency, coverage class, source role and geography. Topic 9 later sets operational objectives.

### Efficiency and cost metrics

- checks per source and successful unchanged proportion;
- model wake-ups per successful unchanged check;
- Leads, Work Items and Candidates per source item or transition;
- worker calls, tokens and retries per Lead and Candidate;
- search requests and results by Search Purpose;
- gross source, provider and model cost before credits;
- reviewer time;
- cost per reviewed relevant event, unique detection and justified Candidate; and
- work amplification from one source item or search result.

### Operational metrics

- source, parser, rights, rate-limit, model, retrieval and handoff failure counts;
- failure-to-no-news confusion;
- queue or Work Item loss;
- duplicate execution and semantic transition;
- stale-version processing;
- unresolved Operational Findings;
- quarantine and recovery behaviour; and
- public-effect or authority-boundary attempts.

### Required slices

Reports separate at minimum:

- United Kingdom, Hong Kong and qualifying Global;
- England, Scotland, Wales and Northern Ireland where applicable;
- English, Hong Kong Traditional Chinese and mixed-language;
- Active, Best effort and deferred-gap context;
- Urgent, Time-sensitive, Planned and Routine;
- Originating authority, Responsible operator, Planned agenda, Established media radar, Specialist/local radar and approved Search Purpose;
- Anchor, Complement and Comparator;
- append-only, maintained-document, complete current-state, rolling-list, explicit-delta and Planned Agenda models;
- new item, Revision, activation, escalation, de-escalation, clearance, cancellation, withdrawal, reschedule and missed expectation; and
- exact retrieval, degraded advisory retrieval and model or worker version.

A slice with insufficient exposure is reported as not evaluated or inconclusive, not silently pooled into an aggregate pass.

## Release blockers and thresholds

### Zero-tolerance blockers

One confirmed occurrence blocks qualification of the affected scope until remediation and a fresh qualifying Run:

- any public publication, notification or reader-visible effect from shadow;
- shadow mutation of production discovery, evidence or publication authority;
- unapproved source access, query data, retention, model submission or provider spending;
- operational failure, partial response or budget block represented as successful unchanged or zero-result editorial meaning;
- parser or normaliser change fabricated as publisher Revision;
- rolling-list or partial-snapshot absence used to create withdrawal, deletion or clearance;
- duplicate semantic Lead or Candidate transition from retry or replay;
- destructive Event Hypothesis merge or loss of predecessor lineage;
- Candidate admission without exact collision checks, required lineage or deterministic validation;
- model, result text or agent bypass of policy, rights, budget or tool authority;
- search snippet or discovery record promoted directly into evidence;
- omitted decision Lead or untracked public-impacting uncertainty; or
- an Active coverage class with no credible candidate path or a demonstrated systemic inability to cover it.

### Non-zero thresholds

Every other pass threshold is set in the Evaluation Plan before qualification results are reviewed. Thresholds identify scope, metric, minimum count or exposure, allowed uncertainty and slice behaviour.

A calibration Epoch may inform threshold selection but cannot count as qualification evidence. After thresholds are fixed, component or method changes require a new qualification Epoch.

### Statistical honesty

Reports include counts and uncertainty appropriate to the sample. A small sample cannot support a precise percentage claim merely because the calculated rate is high.

Aggregate success cannot override a failed required slice. Missing exposure is not a passing result.

## Source and provider contribution decisions

### Add or promote

A source or Comparator may be proposed for a stronger role when evidence shows one or more of:

- it closes an Active launch-blocking gap;
- it provides unique relevant detections;
- it detects materially earlier than existing paths;
- it provides a distinct failure mode or resilience path;
- it improves a required language, geography, observation-model or event-class slice; or
- it supplies a necessary Agenda or occurrence-confirmation path.

Rights, noise, cost and Topic 9 readiness must still pass.

### Retain as Complement or Comparator

A source may remain valuable without many unique events when it supplies justified resilience, current-state confirmation, revision visibility or a prospective audit function.

A Comparator does not become production coverage merely because it finds more results.

### Remove, retire or reject

A source may be proposed for removal or rejection when it:

- contributes no justified coverage or resilience after sufficient exposure;
- duplicates another path without distinct value;
- creates disproportionate noise, false change, cost or reviewer burden;
- is unreliable or operationally unsafe;
- cannot satisfy rights or provider terms; or
- no longer maps to accepted coverage.

A short quiet period is insufficient to remove a rare-event Anchor. Removal of an Anchor requires a coverage-impact assessment and cannot hide the resulting gap.

### Ablation

Reports show the event-level effect of excluding each source, role, model or search Purpose where data permits. Ablation considers unique detections, earlier detection, resilience, noise, cost and affected slices; it is not based only on total item count.

## Legacy and comparator interpretation

The current Brave, RSS, GDELT and Gemini pipeline may be run as a rights-permitted legacy Comparator if the Plan chooses. It is not a correctness baseline, coverage definition or source of authoritative event identity.

Its scope mismatch, per-link model calls, forced new-event behaviour, mutable merges and existing evaluation-label limitations remain explicit.

Existing production or legacy outcomes may reveal overlap, regressions or operational cost, but a disagreement is adjudicated against accepted contracts and review material rather than resolved automatically in favour of either system.

## Reproducibility and retention

Every report retains, subject to rights:

- Plan, Epoch, Run and component versions;
- source and provider versions;
- exact prospective windows and query methods;
- sampling frames, random seeds and reviewer assignment;
- label and adjudication versions;
- metric code and configuration;
- environment and known deviations;
- aggregate and slice results;
- zero-tolerance incidents and remediation links;
- cost and reviewer-time records; and
- release, rejection or continuation decision.

Rights-limited source material may be represented by protected references, hashes, permitted extracts or independently reproducible fixtures. The public repository must not contain prohibited content, secrets, personal data or confidential review material.

Failed and superseded Runs remain traceable. A later pass does not erase earlier evidence.

Confirmed incidents, false merges, false clearances, missed revisions, missed Candidates and material near misses should create or update stable regression Cases where rights permit.

## Requirements

### Shadow boundary

**DEVAL-001 — No public effect.** Shadow execution MUST NOT publish, notify readers or create a reader-visible effect.

**DEVAL-002 — Authority isolation.** Shadow records MUST remain distinguishable from production discovery, evidence and publication authority.

**DEVAL-003 — Real requests remain governed.** Live source and search requests MUST pass rights, privacy, rate and budget controls despite shadow status.

**DEVAL-004 — No silent production mutation.** Shadow MUST NOT modify production source, Lead, Candidate, evidence or publication state.

### Plan and Epoch

**DEVAL-010 — Pre-registered Plan.** Every qualification Run MUST have an immutable owner-approved Evaluation Plan before outcomes are reviewed.

**DEVAL-011 — Frozen Epoch.** Material component, source, query, threshold or policy change MUST start a new Epoch.

**DEVAL-012 — Calibration separation.** A Run used to choose thresholds MUST NOT also serve as the qualification Run for those thresholds.

**DEVAL-013 — Duration is not sufficiency.** Calendar time alone MUST NOT establish adequate evaluation exposure.

**DEVAL-014 — Early-stop evidence.** A zero-tolerance failure MAY stop a Run early but MUST still produce a retained failed report.

### Evaluation universe and labels

**DEVAL-020 — Event-level universe.** Coverage comparison MUST deduplicate results into reviewed event or development units rather than count URLs or provider results.

**DEVAL-021 — No ground-truth provider.** No source, legacy pipeline, media feed, search provider or index MUST be treated as complete ground truth.

**DEVAL-022 — Prospective separation.** Prospective methods MUST be fixed before review; retrospective additions MUST remain separately labelled.

**DEVAL-023 — Contemporaneous label.** Primary route and relationship labels MUST use information available at the evaluation cutoff.

**DEVAL-024 — Later outcome separate.** Later facts MUST create later outcome labels and MUST NOT rewrite contemporaneous expected decisions.

**DEVAL-025 — Unreviewable allowed.** Rights or evidence limitations MUST support an explicit unreviewable label rather than forced judgement.

**DEVAL-026 — Negative and failure sampling.** The sample MUST include unchanged, excluded, rejected, watched, associated and failed work, not only Candidates or positive comparator hits.

### Review and adjudication

**DEVAL-030 — Human-reviewed labels.** Final release labels MUST receive authorised human review; a model MAY assist but MUST NOT be sole ground truth.

**DEVAL-031 — Blinding where practical.** Primary review SHOULD conceal path, confidence and system outcome where doing so does not remove necessary editorial context.

**DEVAL-032 — Second review.** Launch-blocking Gaps, zero-tolerance failures, Urgent material errors and a planned ordinary sample MUST receive independent review or adjudication.

**DEVAL-033 — Disagreement retained.** Reviewer disagreement MUST remain visible and MUST NOT resolve automatically in favour of better metrics or model confidence.

### Metrics and slices

**DEVAL-040 — Stage-specific metrics.** Adapter, transition, gate, triage, grouping, Candidate, latency, cost and operational metrics MUST remain separately attributable.

**DEVAL-041 — Coverage is bounded.** Reported detection coverage MUST be described as coverage within the reviewed prospective universe, not absolute real-world recall.

**DEVAL-042 — Counts with rates.** Every rate MUST report its count, denominator, sampling method and applicable uncertainty.

**DEVAL-043 — Required slices.** Aggregate results MUST NOT hide material language, geography, coverage, urgency, source-role, observation-model or transition failures.

**DEVAL-044 — Insufficient exposure.** A required slice without enough evidence MUST be reported as not evaluated or inconclusive.

**DEVAL-045 — Source contribution.** Evaluation MUST distinguish unique detection, earlier detection, resilience, overlap, dependency, noise and cost by source and portfolio function.

**DEVAL-046 — Triage error classes.** Evaluation MUST measure false merge, fragmentation, snowball absorption, false development, missed development, duplicate Candidate and unnecessary Candidate creation.

**DEVAL-047 — Efficiency and amplification.** Evaluation MUST measure no-change model wake-ups, worker and search amplification, gross cost and reviewer burden.

### Release blockers and thresholds

**DEVAL-050 — Zero-tolerance enforcement.** A confirmed zero-tolerance failure MUST block qualification of the affected scope until remediation and fresh evidence.

**DEVAL-051 — Thresholds before results.** Non-zero thresholds MUST be owner-approved before qualification results are reviewed.

**DEVAL-052 — No post-hoc pooling.** Runs from materially different Epochs MUST NOT be pooled to manufacture a pass.

**DEVAL-053 — Slice can block.** A required slice failure MAY block release despite a passing aggregate.

**DEVAL-054 — Active path blocker.** Missing or systemically ineffective Active coverage remains launch-blocking regardless of other metrics.

### Source and provider decisions

**DEVAL-060 — Evidence-based role change.** Source promotion, removal or role change MUST cite event-level contribution, coverage, resilience, rights, cost and operational evidence.

**DEVAL-061 — Quiet-period guard.** A rare-event Anchor MUST NOT be removed solely because a short Run produced no unique event.

**DEVAL-062 — Comparator non-promotion.** A Comparator MUST NOT become an Anchor merely because it returns more results.

**DEVAL-063 — Search-purpose attribution.** Search value, noise, cost and misses MUST remain attributable to exact Search Purpose and provider version.

**DEVAL-064 — Rights-limited provider evaluation.** A provider that prohibits retained evaluation data MUST NOT be used to create a persistent corpus contrary to its terms.

### Reproducibility and decisions

**DEVAL-070 — Reproducible report.** Every Run MUST retain versions, methods, samples, labels, metrics, deviations, cost and environment sufficient for reasonable reproduction.

**DEVAL-071 — Failed runs retained.** Failed and superseded reports MUST remain traceable.

**DEVAL-072 — Public-repository safety.** Public artefacts MUST exclude secrets, prohibited source expression, personal data and confidential material.

**DEVAL-073 — Explicit decision.** A completed Run MUST end with a retained owner decision or an explicit unresolved status; it MUST NOT silently become production.

**DEVAL-074 — Regression learning.** Confirmed errors and material near misses SHOULD create or update rights-permitted regression Cases.

## Acceptance criteria

1. A shadow model cannot publish or create production Candidate authority even when it proposes approval.
2. A real source request in shadow remains blocked when its rights record is missing.
3. A threshold chosen after seeing calibration results requires a later frozen qualification Epoch.
4. A week-long Run with no Hong Kong Chinese or maintained-page revision exposure cannot claim those slices passed.
5. Ten articles about one event become one reviewed prospective event, with dependencies retained.
6. A comparator-only hit creates no Gap until in-scope relevance, timing, expected path and health are reviewed.
7. A retrospective query written after a miss is excluded from prospective recall reporting.
8. An item later proven false does not automatically make the contemporaneous watch or hold decision wrong if that was the appropriate decision at the cutoff.
9. A partial HKO snapshot that falsely clears a warning is a zero-tolerance blocker.
10. A parser upgrade that fabricates publisher activity is a zero-tolerance blocker.
11. One model timeout remains an operational failure and cannot improve reject or no-news metrics.
12. A high aggregate score cannot hide a false-merge problem in Hong Kong Chinese or an Active Urgent slice.
13. A source with no unique event may still be retained when it provides a justified independent failure path.
14. A rare-event Anchor is not removed solely because no rare event occurred during a short Run.
15. Brave results are not retained in a persistent corpus unless approved terms permit that use.
16. The legacy pipeline may be compared but cannot define correctness or canonical event identity.
17. A failed qualification report remains available after a later pass.
18. Topic 9 receives an explicit list of eligible scopes, unresolved blockers, source health assumptions and operational evidence needs rather than a generic pass statement.
19. No source, search provider, model, schedule, spending or production activation is authorised merely by accepting this specification.

## Owner decisions required to complete Topic 8

The Draft recommends these decisions:

1. Accept an evaluation-only authority scope with no public effects, production Candidate authority or silent production mutation.
2. Accept owner-approved Evaluation Plans and frozen Evaluation Epochs, with calibration separated from qualification and material changes starting a new Epoch.
3. Accept the phased protocol: contract fixtures, replay regression, live prospective shadow, prospective comparator audit, fault injection, review and ablation.
4. Accept an event-level prospective evaluation universe built from several permitted paths, while explicitly refusing to call any provider, legacy pipeline or union complete ground truth.
5. Accept prospective versus retrospective separation, including exclusion of hindsight queries and later-added stories from prospective recall claims.
6. Accept contemporaneous primary labels, separate later-outcome labels and an explicit unreviewable result where defensible review is impossible.
7. Accept authorised human final labels, practical blinding, mandatory second review for launch-blocking, zero-tolerance and Urgent material cases, and visible reviewer disagreement.
8. Accept stage-specific metrics for adapter and change correctness, coverage, gates, triage, grouping, Candidate quality, timeliness, cost and operations rather than one composite score.
9. Accept reviewed-prospective-universe detection coverage as a bounded metric rather than a claim of absolute recall.
10. Accept required slices by geography, language, coverage class, urgency, source role, portfolio function, observation model, transition class and component version, with insufficient exposure reported as not evaluated.
11. Accept the zero-tolerance blocker set, including public effect, rights or authority bypass, failure-as-no-news, false absence-based ending, fabricated Revision, duplicate semantic transition, destructive merge, invalid Candidate admission and discovery-to-evidence bypass.
12. Accept owner-approved non-zero thresholds before qualification review, with calibration Runs ineligible as release evidence and no post-hoc pooling across changed Epochs.
13. Accept event-level source contribution and ablation decisions that consider unique and earlier detections, resilience, overlap, noise, rights, cost and reviewer burden rather than raw item count.
14. Accept that Comparators and search providers do not become Anchors merely by returning more results, and that rights-incompatible provider data cannot be used to build a persistent evaluation corpus.
15. Accept that the legacy clustering pipeline and v1 dataset are comparison and regression aids only; Topic 8 requires relationship and route labels that distinguish development from new event and test snowball, false merge and fragmentation.
16. Accept explicit release-evidence outcomes—insufficient, failed, continue shadow, Comparator-only, scoped Topic 9 eligibility, rejected or launch-blocked—with no silent graduation into production.
17. Accept reproducible, rights-limited reports, retention of failed Runs and creation of regression Cases from confirmed errors and near misses.
18. Accept that Topic 8 itself authorises no run; an executable Evaluation Plan, source and provider rights, budgets and Topic 9 operational controls remain separately required.
