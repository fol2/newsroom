# Discovery record semantics specification

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Accepted by owner:** 2026-07-15  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Supersedes:** None

## Purpose

Define the conceptual identities, immutable versions, decisions and lineage required by the accepted discovery workflow without selecting a database, queue, serialisation format or storage topology.

The design prevents URLs, mutable rows, model output, parser output and content hashes from becoming accidental editorial identity. An implementation MAY use different table, object or event names only if it preserves these semantics.

## Scope

This specification covers:

- source configuration identity and versioning;
- logical source items and observed revisions;
- discovery-only captures and normalised representations;
- logical check work, execution attempts and outcomes;
- Discovery Signals, deterministic Gate Decisions and News Leads;
- Triage Work Items, Retrieval Context, Triage Proposals and committed dispositions;
- Event Hypotheses and Story Candidate identity and versions;
- Evidence Handoffs and intake acknowledgements;
- Operational Findings and Coverage Gaps; and
- exact, ordered lineage, supersession, duplication and temporal semantics.

It does not define concrete source selection, source-change meaning, retrieval algorithms, model prompts, search providers, evaluation thresholds, physical storage, retention periods, numeric scoring or downstream evidence and publication identities.

## Record principles

1. **Logical identity is separate from location.** A URL, feed position, filename, provider cursor or search rank is not by itself a stable Newsroom identity.
2. **Identity is separate from content equality.** A digest may identify bytes or a representation but cannot replace a domain identity whose lifecycle includes movement, correction, supersession or relationships.
3. **Configuration and source state are versioned independently.** Reprocessing unchanged source content under a new adapter or parser does not prove that the source changed.
4. **Committed history is not silently rewritten.** Corrections, retries, merges, splits, dispositions and later observations create new records or explicit relationships.
5. **Current status is a rebuildable view.** A mutable convenience field may exist, but it is not the sole record of authority or history.
6. **Lineage references exact versions.** Downstream decisions consume exact committed inputs, not an unversioned “latest” pointer.
7. **Grouping never erases source lineage.** Dedupe and event association may suppress repeated work while retaining each source-specific item, revision, signal and occurrence.
8. **Discovery records remain non-evidence.** Nothing defined here is a Source Observation, verified fact, Evidence Package, Story Version or publication authority.

## Conceptual record catalogue

These records are semantic contracts, not a requirement for one database table per concept.

### Source Definition and Source Definition Version

A **Source Definition** is the stable Newsroom identity for one approved discovery endpoint, channel or bounded input scope and its editorial purpose. It remains the same logical source across configuration changes only while the monitored channel and purpose remain materially the same.

A **Source Definition Version** is an immutable configuration snapshot identifying the locator, adapter contract, extraction scope, rights reference, policy references and other material configuration used by a Check Request. Changing a locator, selector, parser contract, rights decision or monitored scope creates a new version. A change that represents a different channel or editorial purpose creates a new Source Definition.

A Source Definition does not by itself prove source health, universal evidential authority, permitted use or coverage sufficiency.

### Check Request, Check Attempt and Check Outcome

A **Check Request** is the stable semantic identity of one authorised obligation to inspect one Source Definition Version or approved input scope because of one trigger, expected window or bounded request.

A retry does not create a new Check Request. A later schedule interval, webhook delivery, manual request or Planned Agenda window normally does.

A **Check Attempt** is one execution attempt for one Check Request. Each retry has its own Attempt identity while preserving the logical request and exact version context.

A **Check Outcome** is the immutable result of one Attempt. It distinguishes unchanged, observable changes, partial or degraded result, blocked preflight, retryable failure and quarantine or disablement. A later success does not overwrite an earlier failure; the effective request result is derived from retained attempts and outcomes.

### Discovery Capture

A **Discovery Capture** is the minimum permitted response, item fragment, structured fields, response digest or protected object reference retained for change detection, parsing, replay or audit.

A Capture is not a Source Observation. It may be partial, rights-limited or short-lived and must retain the Source Definition Version, Check Attempt and collection lineage that produced it.

### Source Item and Source Revision

A **Source Item** is a stable source-scoped identity for one logical entry, page, notice, warning, release, calendar item, case listing, message or other source-native unit.

A URL may locate an Item but is not automatically its identity. A reliable GUID, UID, content ID or document ID may participate in a versioned source-specific identity rule. When continuity across a changed locator or native identifier is uncertain, the system retains separate Items and records a possible-replacement or possible-equivalence relationship rather than silently merging them.

A **Source Revision** is one immutable observed source state of one Source Item. It may be established through a reliable source-native revision token, an approved digest of permitted source state or another source-specific deterministic rule.

Repeated checks of the same Revision create additional Occurrences, not another Revision. A new Revision establishes only an observable source-state difference; it does not establish substantive change, factual correctness, newsworthiness or evidence sufficiency.

### Discovery Representation and Discovery Occurrence

A **Discovery Representation** is an immutable normalised output extracted from one Source Revision under exact adapter, parser and normalisation versions. It contains the permitted structured fields used for deterministic gates and triage.

Reprocessing the same Source Revision with changed code may create a new Representation but never fabricates a new source Revision.

A **Discovery Occurrence** records that one Check Outcome observed, delivered or re-observed a Source Item, Source Revision or equivalent approved input identity. Occurrences preserve delivery frequency and source-health evidence even when semantic dedupe prevents another Signal.

### Discovery Signal and Gate Decision

A **Discovery Signal** is an immutable record that one exact Source Revision and Discovery Representation, or another later-approved channel input with equivalent controls, exhibited one candidate observable transition to evaluate through deterministic gates.

One Revision may produce several Signals only when each has a stable deterministic purpose or transition discriminator. A multi-topic page must not be split into arbitrary model-invented Signals without an approved extraction contract. Cross-source reports remain separate Signals.

A **Gate Decision** is an immutable deterministic decision for one exact Signal under exact coverage, policy, rights, gate and exclusion versions. It records promotion, deterministic exclusion, deduplication or operational block. Re-evaluation under a changed rule creates a later decision and does not rewrite the earlier one.

### News Lead, Lead Disposition Decision and Watch Condition

A **News Lead** is a stable discovery identity created only when one exact Signal is promoted by a committed Gate Decision. The accepted default is one News Lead per promoted Discovery Signal.

A Lead retains its originating Signal and does not absorb later source revisions or cross-source reports. Those create separate Signals and Leads that may later be related as follow-up, corroborating, superseding or event-related inputs.

A **Lead Disposition Decision** is an immutable committed route for one exact Lead version or bounded set of Leads after deterministic proposal validation. Permitted routes follow the accepted workflow: editorial reject, watch or defer, association without a new candidate, approved supplemental discovery, operational hold, new-event candidate or development candidate.

A **Watch Condition** is the inspectable condition attached to a watch or defer decision. It identifies a permitted future trigger, expected update, corroborating lead, deadline, expiry or review condition. A watch outcome with no resume or closure condition is invalid.

### Triage Work Item, Retrieval Context and Triage Proposal

A **Triage Work Item** is an immutable bounded manifest of the exact News Leads, accepted coverage basis, urgency context, known incompleteness and Retrieval Context supplied for one triage operation. Retries may reuse it; adding or removing material input requires a new Work Item version or identity.

**Retrieval Context** is the immutable bounded set of prior-event, prior-candidate or prior-story identities and match signals supplied under an exact retrieval version and watermark. It is context, not event identity or relationship authority.

A **Triage Proposal** is an immutable untrusted output for one exact Work Item and Retrieval Context. Multiple workers or retries may produce several proposals. A proposal has no workflow effect until a deterministic controller commits a disposition or Candidate Admission Decision.

### Event Hypothesis and Event Hypothesis Version

An **Event Hypothesis** is a stable discovery-level identity for the unverified proposition that one or more News Leads concern the same underlying event, formal process or material development.

It is not a canonical event, governed relation, verified fact or Story identity. `same_event`, `development_of`, possible replacement and similar relationships remain hypotheses at this boundary.

An **Event Hypothesis Version** is an immutable snapshot of contributing Leads, proposed summary, entities, time, geography, proposed relationships and known uncertainty. Adding or removing a Lead, materially changing the summary or relationship, or changing a material uncertainty creates a new version. Merge and split decisions retain predecessor identities and lineage.

### Story Candidate, Story Candidate Version and Candidate Admission Decision

A **Story Candidate** is a stable discovery identity allocated only by the Candidate Admission Controller for one admitted evidence-acquisition investigation concerning one proposed event or development.

It is not a Story, Story Version or approved article, and its identity is not derived solely from a URL, headline, Event Hypothesis, model response or digest.

A **Story Candidate Version** is an immutable admitted snapshot containing the exact Event Hypothesis Version, contributing Leads and Signals, coverage basis, proposed geography and category, urgency, likely new information, reader-utility basis, uncertainties, evidence objectives and governing versions required by `FLOW-060`.

A material change to those fields creates a new Candidate Version. An acknowledged Handoff remains pinned to the version it received.

A **Candidate Admission Decision** is the immutable deterministic decision that admits or refuses one exact candidate proposal under the current state and governing rules. An accepting decision allocates or references the stable Candidate identity and exact Candidate Version. Concurrent equivalent proposals resolve through an explicit admission or deduplication decision, never silent mutable coalescing.

### Evidence Handoff and Evidence Intake Acknowledgement

An **Evidence Handoff** is the stable semantic transfer identity for submitting one exact Story Candidate Version to one Evidence Intake boundary. Retries and transport attempts reuse the Handoff and idempotency identity. A later Candidate Version requires a new Handoff.

An **Evidence Intake Acknowledgement** is an immutable response correlated to one exact Handoff. It may record durable intake acceptance, duplicate or merge handling, permitted return for follow-up or another structured workflow outcome. A missing or ambiguous response is not an acknowledgement; reconciliation and retry create later attempt or response records without changing the Handoff identity.

### Operational Finding

An **Operational Finding** is a stable case identity for a source, adapter, policy, rights, queue, model, handoff or other operational problem requiring retry, quarantine, remediation or authorised review.

Every contributing occurrence, assessment, remediation decision and closure remains retained. Grouping repeated failures must not erase individual attempts or outcomes.

### Coverage Gap and Coverage Gap Assessment

A **Coverage Gap** is a stable review case identifying a relevant in-scope development that an accepted discovery path failed to detect and that another permitted path or evidence-stage review surfaced.

A comparator hit alone is not a Coverage Gap. A reviewable decision must establish relevance, expected path and miss. The Gap identifies the coverage class, missed hypothesis or Candidate where available, expected paths, discovering path, evaluation window and operational conditions.

A **Coverage Gap Assessment** is a separate immutable decision classifying a Gap as isolated, systemic, not a true miss, expected under Best effort, explained by an accepted deferred gap or another later-approved outcome. Remediation and closure are later linked decisions and do not delete the original Gap or comparison evidence.

## Requirements

### Identity foundations

**DREC-001 — Stable internal identity.** Every Source Definition, Check Request, Check Attempt, Check Outcome, Source Item, Source Revision, Discovery Representation, Signal, Lead, Triage Work Item, Proposal, Event Hypothesis, Story Candidate, Candidate Version, Evidence Handoff, Operational Finding and Coverage Gap MUST have a stable Newsroom identity appropriate to its lifecycle.

**DREC-002 — No external locator identity.** A URL, GUID, filename, provider cursor, calendar position, feed order, message subject, title or search rank MUST NOT be the sole global Newsroom identity. Approved source-native identifiers MAY participate in source-scoped identity rules.

**DREC-003 — Digest is not domain identity.** A digest MAY establish equality, idempotency or integrity but MUST NOT replace a stable Source Item, Event Hypothesis, Story Candidate or other lifecycle identity.

**DREC-004 — No identifier reuse.** A stable identity MUST NOT be reassigned to a different logical record after deletion, closure, merge, split or supersession.

**DREC-005 — Explicit identity uncertainty.** When continuity or equivalence is uncertain, separate identities and the uncertainty MUST be retained. The system MUST NOT silently choose one identity for deduplication convenience.

**DREC-006 — Version immutability.** A committed version or decision defined here MUST be immutable. A correction or material update creates a later version, decision or explicit relationship.

**DREC-007 — Current-state projection.** A mutable current-status or current-version pointer MUST be rebuildable and MUST NOT be the only record of historical state or authority.

### Source and revision identity

**DREC-010 — Versioned Source Definition.** Every Check Request MUST reference one exact Source Definition Version. A material configuration change creates a new version or, when the logical channel changes, a new Source Definition.

**DREC-011 — Source-scoped item identity.** Every Source Item MUST be scoped to one Source Definition. Cross-source equivalence is a later relationship, not shared item identity.

**DREC-012 — Locator movement.** A changed URL or locator MUST NOT automatically create a new Source Item or automatically preserve the old identity. A source-specific rule or explicit identity decision establishes the relationship.

**DREC-013 — Revision equality.** Repeated observations of the same approved source-native revision or permitted canonical source-state digest MUST resolve to the same Source Revision identity.

**DREC-014 — Revision is not materiality.** A new Source Revision establishes an observable source-state difference only. It does not establish newsworthiness, factual correctness, substantive change or evidence sufficiency.

**DREC-015 — Representation separation.** Reprocessing one Revision under changed parser, adapter or normalisation logic creates a new Representation when output changes and MUST NOT fabricate a new Revision.

**DREC-016 — Rights-limited identity.** Identity MUST be supportable using only content and metadata permitted by applicable rights and retention decisions. Full source bytes are not required when prohibited.

**DREC-017 — Current-state sources.** A source exposing only current state MUST still use stable Item and Revision semantics. Topic 5 defines the editorial meaning of openings, escalations, cancellations and endings.

### Checks, attempts and occurrences

**DREC-020 — Logical check versus attempt.** One Check Request MAY have multiple Check Attempts. A retry creates a new Attempt while preserving the Request and exact source, trigger and policy context.

**DREC-021 — Immutable outcomes.** Every Check Outcome MUST reference one exact Attempt and remain immutable. Later recovery does not overwrite it.

**DREC-022 — Occurrence retention.** Repeated delivery or observation MAY be semantically deduplicated while retaining a Discovery Occurrence sufficient for audit, source health and evaluation.

**DREC-023 — Baseline lineage.** A baseline MUST identify the Check Request, Source Definition Version, item and revision identities included or excluded and the governing baseline policy. Baselining MUST NOT erase prior observations.

### Signals, gates and Leads

**DREC-030 — Signal source basis.** Every Signal MUST reference one exact Source Revision and Representation or an approved channel-input identity with equivalent controls.

**DREC-031 — Deterministic signal discriminator.** Several Signals from one Revision require stable deterministic purposes or transition discriminators. Model-generated topic splitting alone is insufficient.

**DREC-032 — Signal immutability.** A later revision, parser output, gate rule or editorial judgement MUST NOT mutate an existing Signal.

**DREC-033 — One Lead per promoted Signal.** The default is one News Lead identity for one promoted Signal. Signals remain separate Leads until explicit triage or Candidate relationships group them.

**DREC-034 — Gate Decision lineage.** A Lead MUST reference the exact committed Gate Decision and governing coverage, rights, policy and gate versions that promoted it.

**DREC-035 — Cross-source dedupe preservation.** Dedupe MUST NOT delete or collapse source-specific Signals and Leads. It may prevent duplicate Candidate admission while preserving every lineage path.

**DREC-036 — Disposition as decision.** Reject, watch or defer, association, supplemental discovery, operational hold and Candidate routes MUST be immutable Lead Disposition Decisions. A bare mutable Lead status is insufficient authority.

**DREC-037 — Watch condition.** Every watch or defer decision MUST carry an inspectable Watch Condition. Current state MUST distinguish waiting for that condition from operational blockage.

### Triage and Event Hypotheses

**DREC-040 — Work Item manifest.** Every Triage Work Item MUST identify exact Leads, Retrieval Context, coverage and urgency basis, known incompleteness and component versions supplied to the worker.

**DREC-041 — Proposal immutability.** A Triage Proposal MUST reference one exact Work Item and worker or model version and remain separate from the committed decision.

**DREC-042 — Retrieval non-authority.** Retrieval results and similarity scores remain in versioned Retrieval Context and MUST NOT allocate Event Hypothesis identity, merge records or establish event relationships by themselves.

**DREC-043 — Event Hypothesis boundary.** Event Hypotheses and versions MUST be explicitly unverified and discovery-level, never canonical events, governed relations, Source Observations or verified facts.

**DREC-044 — Hypothesis versioning.** Adding or removing Leads, changing a material summary or relationship, or changing known material uncertainty creates a new Event Hypothesis Version.

**DREC-045 — Explicit merge and split.** Merge or split creates an explicit decision and successor or relationship records. Predecessor hypotheses, versions and lineage remain reconstructable.

### Story Candidates and handoff

**DREC-050 — Candidate identity on admission.** A Candidate identity MAY be allocated only through a committed Candidate Admission Decision. A Proposal, Hypothesis, URL or model response MUST NOT directly create it.

**DREC-051 — Candidate version manifest.** Every Candidate Version MUST reference exact Hypothesis Version, Leads and Signals, admission decision, coverage basis, urgency, uncertainties, evidence objectives and governing versions.

**DREC-052 — Candidate is not Story identity.** Candidate identity remains distinct from any later Story, Story Version, Evidence Package or publication identity.

**DREC-053 — Candidate change creates version.** A material change to lineage, hypothesis, geography, category, urgency, likely new information, uncertainty or evidence objective creates a new Candidate Version or superseding decision.

**DREC-054 — Equivalent admission control.** Concurrent or repeated equivalent proposals resolve through one explicit admission or deduplication decision, not duplicate Candidate identities or silent coalescing.

**DREC-055 — One semantic Handoff.** One exact Candidate Version and Evidence Intake boundary have one stable semantic Handoff. Retries reuse its identity and idempotency key.

**DREC-056 — Acknowledgement correlation.** Every acknowledgement correlates to one exact Handoff. Timeout, missing response or ambiguity creates neither acknowledgement nor a second Handoff.

**DREC-057 — Feedback is later history.** Evidence feedback, closure, merge, rights block or supplemental request creates a later linked record and MUST NOT mutate the Candidate Version or Handoff.

### Findings and Coverage Gaps

**DREC-060 — Operational Finding separation.** Operational Findings remain distinct from editorial rejections, successful unchanged checks, Coverage Gaps and evidence outcomes.

**DREC-061 — Finding occurrences.** Grouping repeated failures retains each contributing occurrence.

**DREC-062 — Gap requires review.** A comparator result or later-discovered story MUST NOT automatically create a Coverage Gap. A committed review establishes relevance and miss.

**DREC-063 — Gap lineage.** Every Gap identifies the coverage class, missed development where available, expected paths, discovering path, evaluation window and relevant operational conditions.

**DREC-064 — Isolated versus systemic decision.** Gap interpretation is a separate Coverage Gap Assessment and MUST NOT be inferred from source count.

**DREC-065 — Gap history.** Remediation, accepted risk, reclassification and closure create later linked records and do not erase the original Gap or assessment evidence.

### Lineage and time

**DREC-070 — Exact upstream references.** Every downstream record or decision references the exact committed upstream identities and versions it consumed. Bare URLs, titles, timestamps or mutable aliases are insufficient.

**DREC-071 — Ordered causation.** Lineage preserves the difference between trigger, Request, Attempt, Outcome, Capture, Item, Revision, Representation, Occurrence, Signal, Gate Decision, Lead, Work Item, Proposal, committed disposition, Event Hypothesis, Candidate Version, Handoff and feedback.

**DREC-072 — Many-to-many lineage.** The model supports one Outcome producing several Signals, repeated Outcomes observing one Revision, several Leads supporting one Candidate and one Lead participating in later Candidate Versions without duplicating or erasing identity.

**DREC-073 — Supersession is explicit.** Supersession, replacement, correction, merge, split, follow-up, corroboration and possible-equivalence relationships are directional, versioned and attributable.

**DREC-074 — Time separation.** Source-asserted publication, update and effective times remain distinct from Newsroom observation, collection and authoritative recording times. Missing or conflicting time remains explicit.

**DREC-075 — Source time is untrusted metadata.** A source timestamp MAY support change detection under a source-specific rule but is not authoritative Newsroom recording time or sufficient proof of content change.

**DREC-076 — Version provenance.** Every Representation, Gate Decision, Retrieval Context, Proposal and Admission Decision identifies the exact producer, parser, model, policy or validator version that created or governed it.

**DREC-077 — Rebuildable current view.** Operators MAY use current-state projections, but audit and replay MUST reconstruct them from retained identities, versions, decisions and relationships, subject to lawful retention limits.

## Acceptance criteria

1. Moving a GOV.UK page does not automatically prove that it is a new or unchanged Source Item.
2. Observing one feed GUID and Revision five times creates repeated Occurrences but at most one equivalent Signal transition.
3. A parser upgrade that extracts a new field from unchanged source state creates a new Representation, not a Revision.
4. Revising existing guidance creates a new Revision and Signal path without overwriting the earlier Revision or Lead.
5. Two publishers reporting one incident retain separate Items, Revisions, Signals and Leads even when triage later groups them.
6. A model's `same_event` output cannot allocate a canonical event or Candidate identity.
7. Adding a corroborating Lead creates a new Hypothesis version; an earlier acknowledged Handoff stays pinned to its Candidate Version.
8. A Candidate closed by evidence acquisition remains a distinct Candidate and does not become a Story.
9. Retrying an ambiguous Handoff reuses its semantic identity.
10. A search or comparator hit does not become a Coverage Gap until a reviewed decision establishes a relevant miss.
11. Closing a Finding or Gap does not delete its occurrences, assessments or remediation history.
12. A Candidate can be reconstructed from exact upstream versions without relying on a mutable current row, title or URL.
13. Source-published, source-updated, Newsroom-observed and authoritative-recorded times cannot silently overwrite one another.
14. No discovery record defined here is represented as evidence or publication authority.

## Completion record

The product owner accepted this specification on 2026-07-15 with the following decisions:

- stable internal identities remain separate from URLs, provider identifiers and content digests;
- Source Definition and Version, Source Item and Revision, and Source Revision and Discovery Representation are separate contracts;
- parser or normaliser reprocessing of unchanged source state creates a new Representation, not a Revision;
- Check Request, Check Attempt and Check Outcome separate logical work, retries and immutable results;
- one promoted Discovery Signal creates one News Lead by default, while later revisions and cross-source reports remain separate and explicitly related;
- Lead routes are immutable Lead Disposition Decisions, and watch or defer requires an inspectable Watch Condition;
- Event Hypotheses and versions are unverified discovery identities distinct from canonical events, relations, Stories and evidence;
- Story Candidates have stable identity and immutable versions allocated only by deterministic admission and distinct from later Story identity;
- each exact Candidate Version and Evidence Intake boundary has one semantic Evidence Handoff, with retries and acknowledgements recorded separately;
- Coverage Gaps require a reviewed relevant-miss decision and separate isolated, systemic, Best-effort or deferred-gap assessment; and
- lineage is append-only, supersession and merge relationships are explicit, source time and Newsroom time remain separate, and current status is a rebuildable view rather than sole authority.
