# Discovery change and Planned Agenda semantics specification

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Accepted record semantics:** [`discovery-record-semantics.md`](discovery-record-semantics.md)  
**Accepted source roles:** [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Decision state:** The source-change, state-transition, baseline and Planned Agenda semantics below are proposals. Committing this Draft does not authorise collection, schedules, search or production use.  
**Supersedes:** None

## Purpose

Define what the discovery system is allowed to conclude when a source appears, changes, disappears, is withdrawn, changes state or fails to produce an expected development.

The design prevents transport behaviour, rolling-feed disappearance, parser changes, timestamps, HTTP errors and elapsed calendar time from being mistaken for editorially meaningful news. It also defines Planned Agenda as an expectation-and-confirmation mechanism rather than a scheduled-story generator.

## Scope

This specification defines:

- source observation models and the inferences each model permits;
- first observation, re-observation, revision, withdrawal, replacement, disappearance and reappearance semantics;
- current-state warning, incident and service transitions;
- source-specific first-run and reset baselines;
- Planned Agenda identity, versioning, schedule changes, occurrence confirmation and missed expectations; and
- how observable transitions enter the accepted Signal-to-Candidate workflow.

It does not define:

- concrete source polling intervals, retry budgets or alert thresholds, which belong to Topic 9;
- exact Triage Work Item composition, model prompts or Event Hypothesis grouping, which belong to Topic 6;
- search-based recovery for a missed expectation, which belongs to Topic 7;
- shadow metrics or production thresholds, which belong to Topic 8;
- final enum names, reason strings or numeric prioritisation, which belong to Topic 10;
- evidence extraction or factual verification; or
- reader-facing reminder, notification or calendar features.

## Core distinctions

### Source state is not editorial meaning

The system keeps four layers separate:

1. **Retrieval and representation observation:** bytes, fields, validators, response shape and parser output observed by the Newsroom.
2. **Source Revision:** a deterministically distinct observed state of one Source Item under the accepted record semantics.
3. **Observable transition:** a source-specific interpretation such as first observed, revised, explicitly withdrawn, activated, escalated, cleared or rescheduled.
4. **Editorial interpretation:** whether the transition is in scope, substantive, material, urgent, a development of another event or worth evidence acquisition.

Layers 1–3 may be deterministic under an accepted source contract. Layer 4 belongs to gates and triage. A source revision does not by itself prove materiality, accuracy or newsworthiness.

### Absence is not one thing

A missing item may mean:

- it fell outside a rolling feed window;
- the source returned an incomplete snapshot;
- a filter or query changed;
- access failed;
- a page moved;
- the publisher removed or withdrew it;
- a current warning ended; or
- the source has not yet published an expected item.

The adapter may conclude withdrawal, clearance or cancellation only when the accepted source observation model and available source evidence support that conclusion.

### Schedule is not occurrence

A calendar entry, announced release date, proceeding listing, deadline or effective date records an expectation. Time passing does not prove the expected event occurred, failed, was cancelled or became news.

## Source observation models

Every Source Definition Version declares one primary observation model and any bounded secondary behaviour. The model controls which transitions may be inferred.

### Append-only or event stream

The source emits new entries or explicit events. Existing entries may not remain visible indefinitely.

- First delivery can establish a candidate new Source Item or transition.
- Re-delivery is an Occurrence, not another transition.
- Disappearance from the stream or feed window has no withdrawal meaning.
- Revisions require an explicit update event, stable item with changed revision, or another accepted rule.

### Mutable item or maintained document

The same logical Source Item can be retrieved repeatedly and revised in place.

- A changed accepted source-state digest or source-native revision token creates a new Source Revision.
- Before-and-after representations identify changed facets.
- URL stability does not imply content stability, and a changed URL does not alone determine item continuity.

### Complete current-state snapshot

Each successful response claims to enumerate the complete current set for a declared scope, such as active warnings.

- New presence may represent activation or first observation.
- Changed fields may represent escalation, de-escalation, scope change or instruction change.
- Confirmed absence may represent clearance or ending only under the accepted completeness and confirmation rule.
- Partial or degraded snapshots cannot establish absence-based transitions.

### Rolling or bounded listing

The source exposes only the newest, highest-priority or otherwise bounded subset.

- Presence and revision may be observed.
- Disappearance is ambiguous and cannot establish withdrawal, deletion, cancellation or ending.
- Coverage limits and truncation must remain explicit.

### Explicit delta or webhook source

The source emits typed create, update, cancel, delete or state-change messages.

- The source-reported transition may be recorded as asserted metadata.
- The Newsroom still validates identity, sequence, authenticity and version preconditions.
- Source-reported labels do not become verified facts or editorial decisions.

### Planned agenda source

The source publishes expectations, schedules, release windows, proceedings or deadlines.

- Schedule changes create new Planned Agenda Item Versions.
- The agenda does not prove occurrence.
- Planned obligations require a separately defined occurrence-confirmation path.

## Change facets

A Discovery Representation may classify changed facets deterministically where the source contract permits. Candidate facets include:

- title or descriptive label;
- publication, update, effective, expiry or deadline time;
- status, stage, severity or confidence label;
- geography, route, service, population or affected scope;
- instruction, required action, eligibility or process;
- number, amount, rate, threshold, unit or reference period;
- core narrative or structured factual content;
- linked document, attachment, dataset or dependency;
- replacement, withdrawal, supersession or cancellation marker;
- access or availability state; and
- presentation-only or metadata-only change.

A facet label describes what field changed. It does not establish the change's editorial significance.

## General source-change semantics

### First observation

First observation means the Newsroom has no earlier accepted observation of that Source Item within the applicable lineage. It does not prove the item was newly published at that moment.

The source's asserted publication time may support a source-specific freshness rule but remains distinct from Newsroom observation and recording time.

### Re-observation

Observing the same Source Revision again creates a Discovery Occurrence and source-health evidence. It does not create another equivalent Signal, Lead or Candidate transition.

### Revision

A new Source Revision means accepted source-state content or metadata changed under the source-specific revision rule.

A revision may produce no Signal when the versioned normalisation and change contract establishes that only ignored transport or presentation noise changed. If an editorially relevant facet might have changed, the revision proceeds through the normal Signal and gate workflow; the adapter does not decide final materiality.

### Representation-only change

Reprocessing unchanged source state under a new parser, normaliser or extraction version may create a new Discovery Representation. It must not create a Source Revision or be reported as publisher activity.

### Explicit withdrawal, supersession or replacement

An explicit source marker, authenticated delta or maintained-page statement may support an observable withdrawal, supersession or replacement transition.

The transition retains the prior and replacement identities where known. It does not delete the earlier Source Revision, Lead, Candidate or evidence history.

### Deletion or removal

A source-native tombstone or explicit deletion message may support a deletion transition. HTTP `410 Gone` may contribute to that conclusion under a source-specific rule.

HTTP `404`, an empty response, access denial, TLS failure, timeout or disappearance from a rolling listing does not by itself prove deletion or withdrawal. These outcomes remain locator ambiguity or operational failure until resolved.

### Redirect or locator movement

A redirect or changed canonical URL is a locator observation. It may indicate movement, replacement or a different item. The accepted identity rule or explicit decision determines continuity; the adapter must not silently choose.

### Reappearance and reissue

A previously absent or ended item that appears again creates a new occurrence and, where source state differs or the source asserts reactivation or reissue, a new Revision and transition.

The earlier ending, withdrawal or absence record remains. Reappearance must not erase it or automatically be treated as the same uninterrupted event.

### Linked or dependent material

A changed index, feed entry or landing page may point to an affected document without containing the substantive change itself.

The system may create a bounded supplemental Check Request for the linked item. It must not claim the linked document changed until that item is checked under its own Source Item and Revision contract.

## Current-state warning, incident and service semantics

Current-state sources require explicit transition meaning because they often expose only what is active now.

### Activation or opening

A newly present item in a complete current-state snapshot may represent activation. If the first observation occurs during initial baseline, it must be labelled as first observed active state unless the source supplies a reliable earlier start time.

### Escalation

A transition may be classified as escalation when the source explicitly raises severity or when a versioned deterministic rule identifies a materially broader affected scope, stronger instruction or more severe state.

The classification is source-state semantics. Editorial urgency and newsworthiness still require the accepted workflow.

### De-escalation

A lower severity, narrower scope or relaxed instruction may be classified separately from resolution. De-escalation does not mean the event ended.

### Resolution, clearance, expiry and cancellation

These meanings remain distinct:

- **Resolution or clearance:** the source reports that the active condition has ended or is no longer in force.
- **Expiry:** a source-declared validity period ends without evidence of renewal.
- **Cancellation:** the source withdraws an expected or active action before completion.
- **Withdrawal:** the publisher removes or disowns a document, decision or notice.

A source-specific adapter must not collapse these into generic deletion.

### Absence-based ending

Absence may support an ending transition only when:

- the source contract declares the snapshot complete for the exact scope;
- the check is successful and not partial or degraded;
- the prior active Source Item can be matched deterministically;
- the source-specific confirmation or grace rule passes; and
- no transport, filter, pagination or permission change explains the absence.

Otherwise the item enters an ambiguity or operational path rather than an ended transition.

### Reactivation

A cleared, expired or cancelled item that becomes active again creates a new observable transition. The system records whether the source treats it as the same Source Item with a new Revision or a new item linked to the earlier one.

## Baseline and reset semantics

Every source has an explicit first-run and reset policy appropriate to its observation model.

### Maintained documents

The initial successful capture normally establishes a baseline Source Revision and Representation. It does not imply that the document was newly published or revised at baseline time.

Later accepted state differences create revisions.

### Append-only or rolling feeds

The baseline policy defines a bounded freshness or backfill window. It must not silently emit the entire historical feed as current news or silently discard an Active-coverage interval that the owner expected to assess.

### Complete current-state sources

Existing active warnings or incidents at baseline may create explicitly labelled baseline-active Signals under a source-specific policy, particularly for Urgent coverage.

Such a Signal means “first observed active by the Newsroom”, not “started now”. If the source-provided start time is missing or uncertain, that uncertainty is retained.

### Planned agenda sources

Future items within the accepted planning horizon may be imported as Planned Agenda Items without becoming News Leads. Past entries do not become current occurrences merely because they are present during baseline.

### Reset and rebuild

A reset creates a new baseline decision or version and preserves prior baselines, revisions and occurrences. It must not cause uncontrolled re-emission of historical Signals or erase an unresolved active state.

## Planned Agenda semantics

### Planned Agenda Item

A Planned Agenda Item is a stable identity for one expected release, proceeding, effective date, deadline or other monitored future development.

It is not a scheduled Story Candidate, verified event or publication commitment.

### Planned Agenda Item Version

Each immutable version records, where available:

- the agenda source and exact Source Revision;
- accepted coverage basis;
- expected subject or development type;
- asserted schedule, time zone and earliest or latest expected window;
- provisional, confirmed, postponed or other source-reported schedule status;
- expected originating source or occurrence-confirmation path;
- relevant geography and qualitative urgency;
- linked prior or successor agenda items; and
- known uncertainty or dependency.

### Creation from a source announcement

A source announcement may do two separate things:

1. create a normal Discovery Signal and potentially a News Lead because the announcement itself contains actionable or material new information; and
2. create or update a Planned Agenda Item for later occurrence monitoring.

The agenda record does not replace the Signal or evidence workflow for the announcement.

### Schedule revision and rescheduling

An explicit schedule change creates a new Planned Agenda Item Version. The earlier expected window remains historical.

A valid reschedule received before the prior window closes prevents the old window from being classified as an unexplained missed expectation. A late reschedule is recorded alongside any earlier miss finding rather than rewriting it.

### Cancellation or withdrawal of the expected development

An explicit cancellation, postponement without a new date, or withdrawal creates a new Agenda Version and may independently create a Discovery Signal if the change could be in scope or material.

Cancellation is not inferred merely because the occurrence was not found.

### Occurrence confirmation

The actual release, decision, proceeding, effective change or other occurrence must enter through the accepted source-check, Signal, gate and triage workflow.

A deterministic or validated relationship may link the resulting Signal, Lead, Event Hypothesis or Candidate to the Planned Agenda Item. The agenda item does not bypass normal identity, rights, gates or evidence acquisition.

One Agenda Item may correspond to zero, one or several observed occurrences. One observed occurrence may satisfy several related Agenda Items only through explicit relationships.

### Expected window and due state

Opening or passing an expected window creates monitoring work, not news. The exact clock schedule, grace period and check frequency belong to Topics 6 and 9.

The system retains source-asserted time, time zone, provisional status and uncertainty. It must not silently convert a date-only schedule into an exact time.

### Missed expected occurrence

A missed expectation may be recorded only after:

- the accepted expected window and source-specific grace rule have passed;
- the occurrence-confirmation path has been checked as required;
- no accepted Agenda Version rescheduled or cancelled the expectation; and
- the relevant checks are not merely failed, partial or unavailable.

The result means “the Newsroom did not observe the expected occurrence through the required paths”. It does not prove that the event did not happen, was cancelled or was delayed.

A missed expectation creates an Operational Finding or dedicated Planned Expectation Finding under the later operational vocabulary. It does not automatically create a News Lead, Story Candidate or Coverage Gap.

### Failure versus miss

If the agenda or occurrence-confirmation source failed, the system records the source failure separately. It may also retain the expectation as unresolved, but it must not label a source outage as a clean missed release.

### Late occurrence

A later observed occurrence links to the Agenda Item and closes or supersedes the unresolved expectation through a later decision. The earlier missed finding remains historically visible.

### Supplemental discovery

A missed expectation or ambiguous agenda state may request a later-approved bounded supplemental discovery action. The request re-enters the accepted workflow and does not bypass Topic 7 search controls.

### No automatic reminder story

Approaching a deadline or effective date may schedule checks and preserve urgency context. Time passage alone does not create a News Lead or Candidate.

If a later editorial policy permits an actionable reminder story, it must use current permitted source material, normal gates and evidence acquisition rather than treating the calendar clock as evidence.

## Requirements

### Observation contracts and change layers

**CHG-001 — Declared observation model.** Every Source Definition Version MUST declare whether it behaves as an append-only stream, mutable item source, complete current-state snapshot, rolling listing, explicit delta source, Planned Agenda source or an explicitly bounded combination.

**CHG-002 — Inference limited by model.** An adapter MUST NOT infer withdrawal, ending, deletion, cancellation or completeness beyond what its accepted observation model supports.

**CHG-003 — Source Revision separation.** Transport, parser or normaliser changes MUST remain distinct from Source Revision and observable source transition.

**CHG-004 — Validator and timestamp limits.** ETag, `Last-Modified`, source-updated time and similar metadata MAY support retrieval or revision rules but MUST NOT alone prove substantive content change.

**CHG-005 — Exact comparison lineage.** A revision or transition decision MUST identify the exact prior and current Source Revisions and Discovery Representations compared, or the exact source-native delta that asserted it.

**CHG-006 — Facet classification is not materiality.** Deterministic change facets MAY guide gates and triage but MUST NOT establish newsworthiness, factual correctness or evidence sufficiency.

**CHG-007 — No model-created source history.** A model MAY assess likely editorial significance but MUST NOT allocate Source Revision identity or authoritatively declare that a source changed, withdrew, ended or rescheduled.

### Item and locator transitions

**CHG-010 — First observed is not necessarily newly published.** First Newsroom observation MUST remain distinct from source publication and effective time.

**CHG-011 — Re-observation is occurrence.** Re-observing the same Revision creates occurrence lineage and MUST NOT create another equivalent Signal.

**CHG-012 — Revision requires an accepted rule.** A new Source Revision MUST be established by a source-native revision token, permitted canonical source-state digest or another accepted deterministic rule.

**CHG-013 — Noise suppression is versioned.** Ignored presentation, tracking, ordering or transport noise MUST be defined by a versioned normalisation rule and remain inspectable.

**CHG-014 — Explicit withdrawal and replacement.** Withdrawal, supersession, replacement and deletion transitions require explicit source evidence or an accepted source-specific deterministic rule and retain predecessor lineage.

**CHG-015 — Disappearance is model-dependent.** Disappearance from an append-only stream or rolling listing MUST NOT establish withdrawal, deletion, cancellation or ending.

**CHG-016 — HTTP and access failures are not deletion.** `404`, timeout, TLS failure, authentication failure, access denial and malformed response MUST NOT be converted into deletion or withdrawal without the accepted source-specific evidence.

**CHG-017 — Redirect is locator evidence.** Redirect or canonical-URL change MUST NOT silently determine Source Item continuity.

**CHG-018 — Reappearance preserves history.** Reissue or reactivation creates a later occurrence, Revision or item relationship without erasing an earlier ending, withdrawal or absence.

**CHG-019 — Linked-document follow-up.** A changed index or landing page MAY create a bounded Check Request for linked material but MUST NOT claim that linked content changed before checking its own Source Item.

### Current-state sources

**CHG-020 — Activation semantics.** New presence in a complete current-state source MAY support an activation transition under the source identity contract.

**CHG-021 — Escalation and de-escalation remain distinct.** Severity, scope and instruction changes MAY support escalation or de-escalation semantics under versioned rules and MUST NOT be collapsed into generic revision.

**CHG-022 — Ending meanings remain distinct.** Resolution, clearance, expiry, cancellation, withdrawal and deletion MUST remain distinguishable where source evidence supports the distinction.

**CHG-023 — Absence-based ending guard.** Absence MAY support ending only after successful complete-snapshot, identity, confirmation and no-alternative-explanation checks.

**CHG-024 — Partial snapshots cannot clear state.** A partial, degraded, truncated or failed snapshot MUST NOT establish an absence-based ending.

**CHG-025 — Reactivation is a later transition.** Reactivation or reissue MUST create later source history and MUST NOT silently extend the earlier active interval.

**CHG-026 — State semantics do not bypass triage.** Activation, escalation, clearance or another source transition enters normal gates and triage and does not automatically create a Candidate.

### Baselines

**CHG-030 — Source-specific baseline policy.** Every executable Source Definition Version MUST have an approved first-run and reset policy appropriate to its observation model.

**CHG-031 — Maintained-page baseline.** Initial maintained-page capture establishes a baseline and MUST NOT be labelled newly published or revised solely because the Newsroom first saw it.

**CHG-032 — Bounded feed backfill.** Append-only and rolling sources MUST use an explicit freshness or backfill window and MUST NOT silently emit all history or discard an expected Active interval.

**CHG-033 — Baseline-active state.** A complete current-state source MAY emit an explicitly labelled first-observed-active Signal under an approved policy, without claiming the state started at baseline time.

**CHG-034 — Agenda baseline.** Future schedule entries MAY become Agenda Items without News Leads; past entries MUST NOT be treated as current occurrences merely because they appear at baseline.

**CHG-035 — Reset preserves history.** Reset or rebuild MUST preserve earlier baseline and state history and prevent uncontrolled duplicate emission.

### Planned Agenda

**AGEN-001 — Stable Agenda identity.** Each monitored expected release, proceeding, deadline, effective date or similar development MUST have a stable Planned Agenda Item identity and immutable versions.

**AGEN-002 — Expectation is not occurrence.** Agenda creation, window opening or clock passage MUST NOT by itself create a News Lead, Candidate or evidence record.

**AGEN-003 — Agenda minimum context.** An Agenda Version MUST identify its source revision, coverage basis, expected subject, asserted time or window, time zone, schedule status, occurrence path and known uncertainty where available.

**AGEN-004 — Time precision honesty.** Date-only, provisional, approximate and time-zone-ambiguous schedules MUST remain so. The system MUST NOT invent precision.

**AGEN-005 — Planned dual path.** Each Active Planned obligation MUST have an expectation path and a permitted occurrence-confirmation path, consistent with `SRC-011`.

**AGEN-006 — Announcement and agenda are separate.** A material source announcement MAY create a normal Signal and also create an Agenda Item; neither record substitutes for the other.

**AGEN-007 — Rescheduling creates a version.** An explicit schedule change creates a new Agenda Version and preserves the prior expected window.

**AGEN-008 — Cancellation requires source evidence.** Cancellation, postponement or withdrawal MUST NOT be inferred solely from non-observation.

**AGEN-009 — Occurrence enters normal workflow.** An observed occurrence MUST pass normal Source Item, Revision, Signal, gate, Lead, triage and evidence boundaries before being linked to an Agenda Item.

**AGEN-010 — Agenda-to-occurrence cardinality.** The model MUST support zero, one or several occurrences for one Agenda Item and explicit satisfaction of several Agenda Items by one occurrence where justified.

**AGEN-011 — Missed-expectation criteria.** A missed expectation MAY be recorded only after the accepted window, grace, confirmation checks and reschedule or cancellation checks pass.

**AGEN-012 — Miss does not prove non-occurrence.** A missed finding means the required paths did not observe the occurrence. It MUST NOT be represented as proof of cancellation, delay or non-occurrence.

**AGEN-013 — Failure remains separate.** Failed or partial agenda and confirmation checks MUST remain operational failures and MUST NOT be converted into clean missed-release findings.

**AGEN-014 — Late occurrence preserves the miss.** A later occurrence creates a linked resolution or supersession decision and MUST NOT erase the earlier missed finding.

**AGEN-015 — Bounded recovery only.** Supplemental discovery from a missed or ambiguous expectation MUST use an approved bounded trigger and remain subject to Topic 7.

**AGEN-016 — No clock-generated story.** Approaching or passing a date MUST NOT alone create a Lead or Candidate. Any later reminder policy requires current source material and the normal evidence workflow.

### Workflow, lineage and inspectability

**CHG-040 — Normal workflow entry.** Every accepted observable transition enters through the Discovery Signal and Gate Decision contracts and receives no Candidate or evidence bypass.

**CHG-041 — Source assertion versus Newsroom interpretation.** Source-reported labels such as cancelled, severe, resolved or final MUST remain attributed source metadata until the applicable workflow establishes its permitted use.

**CHG-042 — Change ambiguity remains visible.** When the source changed but the transition meaning is uncertain, the system MUST retain an explicit ambiguous-change or operational outcome rather than inventing withdrawal, ending or editorial materiality.

**CHG-043 — Watch conditions may target transitions.** A Watch Condition MAY await a defined Source Revision, Agenda window, corroborating Lead, occurrence confirmation or state transition and MUST remain inspectable.

**CHG-044 — Operational findings remain distinct.** Source-shape drift, missing snapshot completeness, identity collision, failed confirmation and missed expectation MUST remain distinguishable from editorial rejection and successful unchanged checks.

**CHG-045 — Versioned semantics.** Observation model, normalisation, revision, transition, baseline and agenda policies MUST be versioned. Re-evaluation under a new policy creates later decisions and does not rewrite prior history.

## Acceptance criteria

1. A GOV.UK guidance page changing a deadline creates a new Source Revision and changed-deadline path without relying on a new URL.
2. A parser upgrade extracting a new field from unchanged bytes creates a Representation change and no publisher revision.
3. An RSS item falling outside the feed window is not marked withdrawn or deleted.
4. A page returning `404` once creates locator or operational ambiguity rather than automatic withdrawal.
5. An explicit source statement that guidance is withdrawn may create a withdrawal transition while preserving earlier revisions and Leads.
6. A complete HKO warning snapshot adding a warning may create activation; a partial snapshot missing it cannot create clearance.
7. A warning severity decrease is distinguishable from resolution, and disappearance is clearance only after the complete-snapshot rule passes.
8. An active warning first seen during baseline is labelled first observed active and is not claimed to have started at baseline time.
9. Re-observing the same warning revision creates an Occurrence and not another equivalent Signal.
10. An ONS release rescheduled before its original window closes creates a new Agenda Version and not a false missed release.
11. An Agenda Item reaching its scheduled time creates monitoring work, not a Candidate.
12. Failure of the occurrence-confirmation source is recorded separately from a missed expected release.
13. A missed expectation does not state that the event was cancelled or did not happen.
14. A later release can resolve a missed expectation while leaving the earlier miss record visible.
15. A source announcement of a future deadline may both create a Lead about the announcement and create an Agenda Item for later monitoring.
16. Approaching a deadline does not create an automatic reminder story without a later accepted policy and current evidence.
17. A changed index may trigger a check of a linked document but cannot claim that document changed before checking it.
18. No source transition defined here is automatically a verified fact, Event Hypothesis, Story Candidate or publication authority.

## Owner decisions required to complete Topic 5

The Draft recommends the following decisions:

1. Accept the declared source observation models and limit adapter inference to the model each Source Definition Version declares.
2. Accept the four-layer separation between retrieval or representation observation, Source Revision, observable transition and editorial interpretation.
3. Accept that ETag, timestamps, HTTP status and listing disappearance are signals for source-specific rules, not standalone proof of substantive revision, withdrawal or ending.
4. Accept explicit semantics for first observation, re-observation, revision, representation-only change, withdrawal, replacement, deletion, redirect, reappearance and linked-document follow-up.
5. Accept distinct current-state transitions for activation, escalation, de-escalation, resolution or clearance, expiry, cancellation, withdrawal and reactivation.
6. Accept that absence can end an active state only under a successful complete-snapshot and confirmation contract; partial or rolling sources cannot clear state by absence.
7. Accept source-specific baseline policies, including first-observed-active handling for urgent current-state sources without claiming the state started at baseline time.
8. Accept Planned Agenda Item and immutable Version as expectation records distinct from Signals, Leads, Candidates and occurrence evidence.
9. Accept separate agenda and occurrence-confirmation paths, with source announcements able to create both a normal Signal and a future Agenda Item.
10. Accept reschedule and cancellation semantics that require source evidence and preserve earlier schedule history.
11. Accept that a missed expected occurrence is a visible finding meaning “not observed through required paths”, not proof of non-occurrence, cancellation or delay; source failure remains separate and late occurrence preserves the earlier finding.
12. Accept that clock passage alone never creates a News Lead, Candidate or reminder story; any future reminder policy requires current source material and the normal workflow.
13. Accept that every observable transition still enters through normal deterministic gates, triage and evidence acquisition and that model output cannot authoritatively create source history.
