# Discovery change and Planned Agenda semantics specification

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
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Implementation authority:** None. Acceptance defines source-change and Planned Agenda semantics; it does not authorise collection, schedules, search, shadow operation or production use.  
**Supersedes:** None

## Purpose

Define what discovery may conclude when a source appears, changes, disappears, is withdrawn, changes state or fails to produce an expected development.

The specification prevents transport behaviour, rolling-list disappearance, parser changes, timestamps, HTTP errors and elapsed calendar time from being mistaken for publisher action or editorially meaningful news. Planned Agenda is an expectation-and-confirmation mechanism, not a scheduled-story generator.

## Scope

This specification defines:

- source observation models and the inferences each model permits;
- first observation, re-observation, revision, withdrawal, replacement, disappearance and reappearance semantics;
- current-state warning, incident and service transitions;
- source-specific first-run and reset baselines;
- Planned Agenda identity, versioning, schedule changes, occurrence confirmation and missed expectations; and
- how observable transitions enter the accepted Signal-to-Candidate workflow.

It does not define polling intervals, retry budgets, alert thresholds, Triage Work Item composition, model prompts, Event Hypothesis grouping, search recovery, shadow thresholds, final reason strings, evidence verification or reader-facing reminder features.

## Core distinctions

### Four separate layers

The system keeps these layers separate:

1. **Retrieval and representation observation:** bytes, fields, validators, response shape and parser output observed by the Newsroom.
2. **Source Revision:** a deterministically distinct observed state of one Source Item.
3. **Observable transition:** a source-specific interpretation such as first observed, revised, withdrawn, activated, escalated, cleared or rescheduled.
4. **Editorial interpretation:** whether the transition is in scope, substantive, material, urgent, a development of another event or worth evidence acquisition.

Layers 1–3 may be deterministic under an accepted source contract. Layer 4 belongs to gates and triage. A Source Revision does not itself prove materiality, accuracy or newsworthiness.

### Absence is ambiguous unless the source contract proves otherwise

A missing item may have fallen outside a rolling window, been omitted from an incomplete response, moved, become inaccessible, been removed, ended or simply not yet been published. Withdrawal, clearance, cancellation and deletion may be concluded only where the declared observation model and exact source evidence support that inference.

### Schedule is not occurrence

A calendar entry, announced date, proceeding listing, deadline or effective date records an expectation. Clock passage does not prove that the expected event occurred, failed, was cancelled or became news.

## Source observation models

Every Source Definition Version declares one primary observation model and any bounded secondary behaviour.

### Append-only or event stream

The source emits entries or explicit events.

- First delivery may establish a candidate item or transition.
- Re-delivery is an Occurrence, not another transition.
- Disappearance from the stream or feed window has no withdrawal meaning.
- Revision requires an explicit update event, stable item with changed revision or another accepted rule.

### Mutable item or maintained document

The same logical Source Item may be revised in place.

- A changed accepted source-state digest or source-native revision token creates a new Source Revision.
- Before-and-after Representations identify changed facets.
- Stable URL does not imply stable content; changed URL does not determine item continuity.

### Complete current-state snapshot

Each successful response claims to enumerate the complete current set for a declared scope.

- New presence may represent activation.
- Changed fields may represent escalation, de-escalation, scope change or instruction change.
- Confirmed absence may represent ending only under the accepted completeness and confirmation rule.
- Partial or degraded snapshots cannot establish absence-based transitions.

### Rolling or bounded listing

The source exposes only a newest, highest-priority or otherwise bounded subset.

- Presence and revision may be observed.
- Disappearance is ambiguous and cannot establish withdrawal, deletion, cancellation or ending.
- Truncation and coverage limits remain explicit.

### Explicit delta or webhook source

The source emits typed create, update, cancel, delete or state-change messages.

- The source-reported transition is retained as attributed metadata.
- Identity, sequence, authenticity and version preconditions are still validated.
- Source labels do not become verified facts or editorial decisions.

### Planned Agenda source

The source publishes expectations, schedules, proceedings or deadlines.

- Schedule changes create new Planned Agenda Item Versions.
- The agenda does not prove occurrence.
- Active Planned obligations require a separate occurrence-confirmation path.

## Change facets

A Discovery Representation may classify changed facets deterministically where the source contract permits, including title, effective time, deadline, status, stage, severity, geography, route, affected population, instruction, eligibility, amount, rate, threshold, reference period, core content, attachment, dependency, replacement marker, access state or presentation-only change.

A facet says what changed. It does not establish editorial significance.

## General source-change semantics

### First observation

First observation means no earlier accepted observation exists in the applicable lineage. It does not prove the item was newly published at that moment. Source-asserted publication time remains distinct from Newsroom observation and recording time.

### Re-observation

Observing the same Source Revision creates an Occurrence and source-health evidence, not another equivalent Signal, Lead or Candidate transition.

### Revision

A new Source Revision means accepted source-state content or metadata changed under a source-specific deterministic rule. Ignored presentation or transport noise may produce no Signal. A potentially editorial facet proceeds through the normal workflow; the adapter does not decide final materiality.

### Representation-only change

Reprocessing unchanged source state under a new parser or normaliser may create a new Discovery Representation. It is not publisher activity and does not create a Source Revision.

### Withdrawal, supersession, replacement and deletion

An explicit marker, authenticated delta, maintained-page statement, tombstone or accepted source-specific rule may support the applicable transition. Prior Revisions, Leads, Candidates and evidence history remain retained.

HTTP `404`, empty response, access denial, TLS failure, timeout or rolling-list disappearance does not alone prove deletion or withdrawal. `410 Gone` may contribute only under a source-specific rule.

### Redirect or locator movement

Redirect or canonical-URL change is locator evidence. Identity continuity, replacement or separation is determined by the accepted identity rule or an explicit decision.

### Reappearance and reissue

A previously absent or ended item appearing again creates a later Occurrence and, where state differs or reactivation is asserted, a new Revision and transition. Earlier ending or withdrawal history remains.

### Linked or dependent material

A changed index or landing page may create a bounded Check Request for linked material. It cannot establish that the linked document changed before that Source Item is checked under its own contract.

## Current-state warning, incident and service semantics

The following transitions remain distinct:

- **Activation or opening:** a newly present item in a complete snapshot may become active.
- **Escalation:** severity, affected scope or instruction becomes stronger under an explicit or versioned deterministic rule.
- **De-escalation:** severity, scope or instruction becomes less severe without establishing ending.
- **Resolution or clearance:** the source reports the condition ended or is no longer in force.
- **Expiry:** a declared validity period ends without renewal.
- **Cancellation:** an expected or active action is withdrawn before completion.
- **Withdrawal:** the publisher disowns or removes a document, decision or notice.
- **Reactivation:** a cleared, expired or cancelled state becomes active again as later source history.

Absence may support ending only when the snapshot is complete for the exact scope, the check is successful and not partial, prior identity matches deterministically, the source-specific confirmation or grace rule passes, and no transport, filter, pagination or permission change explains the absence. Otherwise the result remains ambiguous or operational.

## Baseline and reset semantics

Every executable Source Definition Version has an approved first-run and reset policy.

- **Maintained documents:** initial capture establishes a baseline; it is not labelled newly published or revised merely because the Newsroom first saw it.
- **Append-only or rolling sources:** an explicit freshness or backfill window prevents both historical flooding and silent loss of an expected Active interval.
- **Complete current-state sources:** existing urgent states may create an explicitly labelled first-observed-active Signal, without claiming they started at baseline time.
- **Planned Agenda sources:** future entries within the planning horizon may become Agenda Items without Leads; past entries do not become current occurrences.
- **Reset or rebuild:** a new baseline decision preserves prior baselines, Revisions and Occurrences and prevents uncontrolled re-emission.

## Planned Agenda semantics

### Planned Agenda Item and Version

A Planned Agenda Item is the stable identity of one expected release, proceeding, effective date, deadline or other future development. It is not a scheduled Story Candidate, verified event or publication commitment.

Each immutable Version records, where available, the agenda source and Revision, coverage basis, expected subject, asserted schedule and time zone, earliest or latest window, provisional or confirmed status, expected occurrence path, geography, qualitative urgency, relationships and uncertainty.

### Announcement and agenda are separate

A material announcement may create a normal Signal and Lead about what was announced and separately create or update a future Agenda Item. Neither record substitutes for the other.

### Rescheduling and cancellation

An explicit schedule change creates a new Agenda Version and preserves the earlier window. A valid reschedule received before the prior window closes prevents a false missed expectation. A late reschedule is linked to any prior miss rather than rewriting it.

Cancellation, postponement without a new date or withdrawal requires source evidence. Non-observation alone does not establish cancellation.

### Occurrence confirmation

The actual release, decision, proceeding or effective change enters through normal Source Item, Revision, Signal, gate, Lead, triage and evidence boundaries. A validated relationship may link it to the Agenda Item.

One Agenda Item may have zero, one or several observed occurrences. One occurrence may satisfy several Agenda Items only through explicit relationships.

### Expected window and missed expectation

Opening or passing an expected window creates monitoring work, not news. Date-only, provisional and time-zone-ambiguous schedules retain their uncertainty.

A missed expectation may be recorded only after the expected window and source-specific grace rule pass, occurrence-confirmation paths were checked, no accepted Version rescheduled or cancelled it, and the relevant checks were not failed, partial or unavailable.

The finding means: **the Newsroom did not observe the expected occurrence through the required paths**. It does not prove non-occurrence, cancellation or delay. Source failure remains separate. A late occurrence creates a linked resolution while the earlier finding remains visible.

A missed or ambiguous expectation may request a later-approved bounded supplemental action. It does not bypass search controls.

### No clock-generated story

Approaching or passing a date may schedule checks and preserve urgency context, but time passage alone creates no Lead, Candidate or reminder story. A future reminder policy would require current permitted source material and the normal evidence workflow.

## Requirements

### Observation contracts and change layers

**CHG-001 — Declared observation model.** Every Source Definition Version MUST declare its append-only, mutable-item, complete-snapshot, rolling-list, explicit-delta, Planned-Agenda or bounded combined model.

**CHG-002 — Inference limited by model.** An adapter MUST NOT infer withdrawal, ending, deletion, cancellation or completeness beyond its accepted model.

**CHG-003 — Source Revision separation.** Transport, parser and normaliser changes remain distinct from Source Revision and source transition.

**CHG-004 — Validator and timestamp limits.** ETag, `Last-Modified`, source-updated time and similar metadata MAY support retrieval or revision rules but MUST NOT alone prove substantive change.

**CHG-005 — Exact comparison lineage.** A revision or transition decision MUST identify exact prior and current Revisions and Representations, or the exact authenticated delta.

**CHG-006 — Facet classification is not materiality.** Change facets MAY guide triage but do not establish newsworthiness, correctness or evidence sufficiency.

**CHG-007 — No model-created source history.** A model MAY assess significance but MUST NOT allocate Source Revision identity or authoritatively declare source change, withdrawal, ending or rescheduling.

### Item and locator transitions

**CHG-010 — First observed is not newly published.** First Newsroom observation remains distinct from source publication and effective time.

**CHG-011 — Re-observation is occurrence.** Re-observing the same Revision creates occurrence lineage and no equivalent new Signal.

**CHG-012 — Revision requires accepted rule.** A new Revision requires a source-native token, permitted canonical digest or other accepted deterministic rule.

**CHG-013 — Noise suppression is versioned.** Ignored presentation, tracking, ordering and transport noise is defined by an inspectable versioned rule.

**CHG-014 — Explicit withdrawal and replacement.** Withdrawal, supersession, replacement and deletion require source evidence or an accepted source-specific rule and preserve predecessor lineage.

**CHG-015 — Disappearance is model-dependent.** Disappearance from append-only or rolling sources does not establish ending or removal.

**CHG-016 — HTTP and access failures are not deletion.** `404`, timeout, TLS, authentication, denial and malformed response do not become deletion or withdrawal without accepted evidence.

**CHG-017 — Redirect is locator evidence.** Redirect or canonical-URL change does not silently determine item continuity.

**CHG-018 — Reappearance preserves history.** Reissue or reactivation creates later history and does not erase earlier ending or withdrawal.

**CHG-019 — Linked-document follow-up.** A changed index MAY trigger a bounded linked-item check but cannot assert linked content changed before that check.

### Current-state sources

**CHG-020 — Activation semantics.** New presence in a complete current-state source MAY support activation under the source identity contract.

**CHG-021 — Escalation and de-escalation remain distinct.** Severity, scope and instruction changes are not collapsed into generic revision.

**CHG-022 — Ending meanings remain distinct.** Resolution, clearance, expiry, cancellation, withdrawal and deletion remain distinguishable.

**CHG-023 — Absence-based ending guard.** Absence supports ending only after successful complete-snapshot, identity, confirmation and no-alternative-explanation checks.

**CHG-024 — Partial snapshots cannot clear state.** Partial, degraded, truncated or failed snapshots cannot establish ending by absence.

**CHG-025 — Reactivation is later history.** Reactivation or reissue creates a later transition and does not extend the prior interval silently.

**CHG-026 — State semantics do not bypass triage.** Activation, escalation, clearance and other transitions receive normal gates and triage.

### Baselines

**CHG-030 — Source-specific baseline policy.** Every executable Source Definition Version has an approved first-run and reset policy.

**CHG-031 — Maintained-page baseline.** Initial capture is not labelled new or revised solely because the Newsroom first saw it.

**CHG-032 — Bounded feed backfill.** Append-only and rolling sources use an explicit freshness or backfill window.

**CHG-033 — Baseline-active state.** A complete current-state source MAY emit first-observed-active under an approved policy without claiming the state started then.

**CHG-034 — Agenda baseline.** Future entries MAY become Agenda Items without Leads; past entries do not become current occurrences at baseline.

**CHG-035 — Reset preserves history.** Reset and rebuild preserve prior baseline and state history and prevent uncontrolled duplicate emission.

### Planned Agenda

**AGEN-001 — Stable Agenda identity.** Each monitored expected development has a stable Agenda Item and immutable Versions.

**AGEN-002 — Expectation is not occurrence.** Agenda creation, window opening and clock passage do not create a Lead, Candidate or evidence record.

**AGEN-003 — Agenda minimum context.** A Version identifies source Revision, coverage, subject, asserted time or window, time zone, schedule status, occurrence path and uncertainty where available.

**AGEN-004 — Time precision honesty.** Date-only, provisional, approximate and time-zone-ambiguous schedules remain so.

**AGEN-005 — Planned dual path.** Each Active Planned obligation has expectation and occurrence-confirmation paths.

**AGEN-006 — Announcement and agenda are separate.** An announcement MAY create both a normal Signal and an Agenda Item; neither substitutes for the other.

**AGEN-007 — Rescheduling creates a version.** Explicit schedule change creates a new Version and preserves the prior window.

**AGEN-008 — Cancellation requires source evidence.** Cancellation, postponement and withdrawal are not inferred solely from non-observation.

**AGEN-009 — Occurrence enters normal workflow.** An occurrence passes normal Item, Revision, Signal, gate, Lead, triage and evidence boundaries.

**AGEN-010 — Agenda-to-occurrence cardinality.** The model supports zero, one or several occurrences per Agenda Item and explicit satisfaction of several items by one occurrence.

**AGEN-011 — Missed-expectation criteria.** A missed expectation is recorded only after accepted window, grace, confirmation and schedule-change checks pass.

**AGEN-012 — Miss does not prove non-occurrence.** A miss means required paths did not observe the occurrence, not that it was cancelled, delayed or absent.

**AGEN-013 — Failure remains separate.** Failed or partial agenda and confirmation checks do not become clean missed findings.

**AGEN-014 — Late occurrence preserves the miss.** A later occurrence links a resolution and does not erase the earlier finding.

**AGEN-015 — Bounded recovery only.** Supplemental discovery uses an approved bounded trigger and remains subject to Topic 7.

**AGEN-016 — No clock-generated story.** Approaching or passing a date does not alone create a Lead or Candidate.

### Workflow, lineage and inspectability

**CHG-040 — Normal workflow entry.** Every observable transition enters through the Signal and Gate Decision contracts with no Candidate or evidence bypass.

**CHG-041 — Source assertion versus Newsroom interpretation.** Source labels such as cancelled, severe, resolved or final remain attributed metadata until the workflow establishes their permitted use.

**CHG-042 — Change ambiguity remains visible.** Uncertain transition meaning remains ambiguous or operational rather than becoming invented source history or editorial materiality.

**CHG-043 — Watch conditions may target transitions.** A Watch Condition MAY await a defined Revision, Agenda window, corroborating Lead, confirmation or state transition.

**CHG-044 — Operational findings remain distinct.** Shape drift, missing completeness, identity collision, failed confirmation and missed expectation remain separate from editorial rejection and successful unchanged checks.

**CHG-045 — Versioned semantics.** Observation, normalisation, revision, transition, baseline and Agenda policies are versioned; later evaluation does not rewrite history.

## Acceptance criteria

1. A maintained guidance page changing a deadline creates a new Revision path without a new URL.
2. A parser upgrade on unchanged bytes creates a Representation change, not publisher revision.
3. An RSS item leaving a feed window is not marked withdrawn.
4. One `404` creates ambiguity or failure, not automatic withdrawal.
5. Explicit withdrawal preserves earlier revisions and Leads.
6. A complete warning snapshot may activate or clear state; a partial snapshot cannot clear it.
7. Severity decrease is distinguishable from resolution.
8. A baseline-active warning is not claimed to have started at baseline time.
9. Re-observation creates an Occurrence, not another equivalent Signal.
10. Rescheduling before the original window closes avoids a false miss.
11. A scheduled time creates monitoring work, not a Candidate.
12. Confirmation-source failure remains separate from missed expectation.
13. A missed expectation does not claim cancellation or non-occurrence.
14. A late release resolves without erasing the miss.
15. One announcement may create a Lead and a future Agenda Item.
16. Clock passage does not create an automatic reminder story.
17. A changed index cannot assert linked-document change before checking it.
18. No transition defined here is automatically a verified fact, Event Hypothesis, Candidate or publication authority.

## Completion record

The product owner accepted this specification on 2026-07-15 with these decisions:

- each Source Definition Version declares an observation model and adapter inference is limited to it;
- retrieval observation, Source Revision, observable transition and editorial interpretation are separate layers;
- validators, timestamps, HTTP status and disappearance are inputs to source-specific rules, not standalone proof;
- first observation, re-observation, revision, Representation-only change, withdrawal, replacement, deletion, redirect, reappearance and linked-document follow-up have distinct semantics;
- activation, escalation, de-escalation, resolution or clearance, expiry, cancellation, withdrawal and reactivation remain distinct;
- absence ends an active state only under successful complete-snapshot and confirmation rules;
- baselines are source-specific and may represent first-observed-active without claiming start time;
- Planned Agenda Items and Versions are expectation records distinct from Signals, Leads, Candidates and occurrence evidence;
- Planned coverage uses separate agenda and occurrence paths, while announcements may create both a Signal and an Agenda Item;
- rescheduling and cancellation require source evidence and preserve schedule history;
- a missed expected occurrence means not observed through required paths, not proof of non-occurrence, cancellation or delay; failure remains separate and late occurrence preserves the miss;
- clock passage alone never creates a Lead, Candidate or reminder story; and
- every transition enters normal gates, triage and evidence acquisition, while model output cannot authoritatively create source history.
