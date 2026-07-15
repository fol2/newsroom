# Discovery record semantics specification

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Accepted workflow:** [`discovery-workflow.md`](discovery-workflow.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Decision state:** The record identities, versions and lineage rules below are proposals. Committing this Draft does not constitute owner acceptance or select a database.  
**Supersedes:** None

## Purpose

Define the conceptual identities, immutable versions, decision records and lineage required by the accepted discovery workflow without selecting a database, queue, serialization format or storage topology.

The objective is to prevent URLs, mutable rows, model output, parser output or content hashes from becoming accidental editorial identity. A later implementation may use different table, object or event names only if it preserves these semantics.

## Scope

This specification covers:

- source configuration identity and versioning;
- logical source items and observed revisions;
- discovery-only captures and normalised representations;
- logical check work, execution attempts and outcomes;
- Discovery Signals, deterministic gate decisions and News Leads;
- Triage Work Items, retrieval context, Triage Proposals and committed triage decisions;
- Event Hypotheses and Story Candidate identity and versions;
- Evidence Handoffs and intake acknowledgements;
- Operational Findings and Coverage Gaps; and
- exact, ordered lineage, supersession, duplication and temporal semantics.

It does not define:

- concrete source selection or source roles; Topic 4 owns those decisions;
- the editorial meaning of new, revised, deleted, withdrawn, cancelled, rescheduled, escalated or ended; Topic 5 owns those decisions;
- event-retrieval algorithms, model prompts, grouping thresholds or merge rules; Topic 6 owns those decisions;
- search providers or search-record retention; Topic 7 owns those decisions;
- shadow datasets, metrics or thresholds; Topic 8 owns those decisions;
- database tables, indexes, transaction mechanisms, queue technology, retention periods or backup; Topics 9 and 12 own those decisions;
- numeric prioritisation or final reason-code strings; Topic 10 owns those decisions; or
- Source Observation, Evidence Package, governed claim, story or publication identity, except for the discovery hand-off boundary.

## Record principles

1. **Logical identity is separate from location.** A URL, feed position, filename, search result rank or mutable provider locator is not by itself a stable Newsroom identity.
2. **Identity is separate from content digest.** A digest can identify exact bytes or a normalised representation but cannot replace a domain identity whose lifecycle includes movement, correction, supersession or relationships.
3. **Configuration and content are versioned independently.** Reprocessing unchanged source content under a new adapter or parser version does not prove that the source changed.
4. **Committed records are not silently rewritten.** Corrections, retries, merges, splits, dispositions and later observations create new records or explicit relationships.
5. **Current status is a read model.** A convenient current-state field may exist, but it must be derivable from retained immutable versions and decisions rather than being the only record of history.
6. **Lineage references exact versions.** A downstream decision consumes exact committed upstream identities and versions, not a title, URL or unversioned “latest” pointer.
7. **Cross-source grouping does not erase source lineage.** Dedupe and event association may suppress repeated work while retaining each source-specific item, revision, signal and occurrence.
8. **Discovery records remain non-evidence.** No identity or version defined here is a Source Observation, verified fact, Evidence Package, Story Version or publication authority.

## Conceptual record catalogue

The following records are semantic contracts, not required database tables.

### Source Definition

A stable Newsroom identity for one approved discovery endpoint, channel or bounded input scope and its editorial purpose. It remains the same logical source across configuration revisions when the monitored channel remains the same.

A Source Definition does not prove that the source is healthy, authoritative for every claim, permitted for every use or sufficient for a coverage obligation.

### Source Definition Version

An immutable configuration snapshot for one Source Definition. It identifies the endpoint or channel locator, adapter contract, extraction scope, source role when later accepted, rights reference, policy references and other material configuration used by a Check Request.

Changing a locator, selector, parser contract, rights decision or monitored scope creates a new Source Definition Version. A material change that actually represents a different channel or editorial purpose requires a new Source Definition identity rather than silently reusing the old one.

### Check Request

The stable semantic identity of one authorised obligation to inspect one Source Definition Version or approved input scope because of one trigger, expected window or bounded request.

A retry does not create a new Check Request. A later scheduled interval, webhook delivery, manual request or Planned Agenda window normally creates a new Check Request even when it checks the same source.

### Check Attempt

One execution attempt for one Check Request. Every retry has a distinct Check Attempt identity while retaining the Check Request identity and exact version context.

### Check Outcome

An immutable result recorded for one Check Attempt. It distinguishes unchanged, observable changes, partial or degraded result, blocked preflight, retryable failure and quarantine or disablement according to the accepted workflow.

A later successful retry does not overwrite an earlier failure. The effective resolution of a Check Request is derived from its attempts and outcomes.

### Discovery Capture

The minimum permitted source response, item fragment, structured fields, response digest or protected object reference retained for discovery change detection, parsing, replay or audit.

A Discovery Capture is not a Source Observation. It may be partial, rights-limited or ephemeral and must carry the Source Definition Version, Check Attempt and collection-time lineage that produced it.

### Source Item

A stable source-scoped identity for one logical entry, page, notice, warning, release, calendar item, case listing, message or other source-native unit monitored by discovery.

Source Item identity is scoped to its Source Definition. A URL may be one locator for a Source Item but is not automatically its identity. A reliable source-native identifier, such as a GUID, content identifier, UID or document identifier, may participate in identity under a versioned source-specific rule.

If identity continuity across a changed URL or changed native identifier is uncertain, the system creates separate Source Items and an explicit possible-replacement or possible-equivalence relationship. It must not silently merge them.

### Source Revision

An immutable identity for one observed source state of one Source Item. A revision may be established through a reliable source-native revision token, an approved digest of permitted source state or another source-specific deterministic rule.

Repeated checks that observe the same Source Revision do not create another revision. They create additional occurrences or lineage from their Check Outcomes.

A Source Revision records an observed source state; it does not mean the change is substantive, accurate, current for publication or editorially material.

### Discovery Representation

An immutable normalised representation extracted from one Source Revision under exact adapter, parser and normalisation versions. It contains the permitted structured fields used for deterministic gates and triage.

Reprocessing the same Source Revision with changed parsing or normalisation logic creates a new Discovery Representation, not a new Source Revision. A representation difference caused only by code change must not be reported as a source change.

### Discovery Occurrence

A record that one Check Outcome observed, delivered or re-observed one Source Item, Source Revision or other approved input identity. Occurrences preserve frequency, repeated delivery and source-health evidence even when semantic dedupe prevents another Signal.

### Discovery Signal

An immutable record that one exact Source Revision and Discovery Representation, or another later-approved channel input, exhibited one candidate observable transition worth applying deterministic discovery gates to.

One Source Revision may produce more than one Discovery Signal only when the signals have distinct, deterministic purposes or transition discriminators. A multi-topic page must not be split into arbitrary model-invented signals without an approved extraction contract.

A Signal identity is source-specific. Cross-source reports of the same possible event remain separate Signals and are related later through triage and Event Hypotheses.

### Gate Decision

An immutable deterministic decision for one exact Discovery Signal under exact coverage, policy, rights, gate and exclusion versions. It records promotion, deterministic exclusion, deduplication or operational block and its basis.

Re-evaluation under a changed accepted rule creates another Gate Decision. It does not rewrite the earlier decision.

### News Lead

A stable discovery identity created only when one exact Discovery Signal is promoted by a committed Gate Decision. The proposed default is one News Lead per promoted Discovery Signal.

A News Lead retains its originating Signal and does not absorb later source revisions. A later revision creates a new Signal and, if promoted, a new News Lead that may explicitly follow, corroborate or supersede the earlier lead.

### Lead Disposition Decision

An immutable committed route for one exact News Lead version or bounded set of News Leads after deterministic proposal validation. Permitted routes follow the accepted workflow: editorial reject, watch or defer, association without a new candidate, approved supplemental discovery, operational hold, new-event candidate or development candidate.

A Lead's convenient current disposition is derived from these decisions. A new decision must reference and supersede an applicable earlier decision rather than overwriting it.

### Watch Condition

An immutable condition attached by a Lead Disposition Decision when a News Lead is retained for watch or defer. It states the permitted future trigger, expected update, corroborating lead, deadline, expiry or review condition required for re-entry.

Exact scheduling and expiry behaviour remain for Topics 6 and 9, but a watch outcome without an inspectable resume or closure condition is invalid.

### Triage Work Item

An immutable bounded manifest of the exact News Leads, accepted coverage basis, urgency context, known incompleteness and retrieval context submitted for one triage operation.

Retries may reuse the same Triage Work Item. Adding or removing a Lead, changing material context or changing the permitted input requires a new Work Item version or identity.

### Retrieval Context

An immutable record of the bounded prior-event, prior-candidate or prior-story identities and match signals supplied to triage under an exact retrieval version and watermark.

Retrieval Context is untrusted context. It does not establish that two leads describe the same event or that one is a development of another.

### Triage Proposal

An immutable untrusted output for one exact Triage Work Item and Retrieval Context. Multiple workers or retries may produce multiple proposals. A proposal has no authoritative workflow effect until a deterministic controller validates and commits a Lead Disposition Decision or Story Candidate admission.

### Event Hypothesis

A stable discovery-level identity for an unverified proposition that one or more News Leads concern the same underlying event, formal process or material development.

An Event Hypothesis is not a canonical event, governed relation, verified fact or Story identity. `same_event`, `development_of`, possible replacement and similar relationships remain hypotheses until the separately governed downstream process establishes what it is authorised to establish.

### Event Hypothesis Version

An immutable snapshot of one Event Hypothesis's contributing Leads, proposed event summary, entities, time, geography, relationship to another hypothesis and known uncertainty.

Adding a Lead, changing the proposed relationship or materially changing the hypothesis creates a new version. Merge or split proposals require explicit decisions and never erase the predecessor hypotheses or versions.

### Story Candidate

A stable discovery identity allocated only by the Candidate Admission Controller for one admitted evidence-acquisition investigation concerning one proposed event or development.

A Story Candidate is not a Story, Story Version or approved article. Candidate identity must not be derived solely from a URL, headline, Event Hypothesis, model response or content digest.

### Story Candidate Version

An immutable admitted snapshot containing the exact Event Hypothesis Version, contributing News Leads and Signals, coverage basis, proposed geography and category, qualitative urgency, likely new information, reader-utility basis, uncertainties, evidence objectives and governing component versions required by FLOW-060.

Any material change to those fields creates a new Candidate Version. An already acknowledged Evidence Handoff continues to refer to the exact version it received.

### Candidate Admission Decision

An immutable deterministic decision that admits or refuses one exact candidate proposal under the current state, accepted coverage contract and governing versions. An accepting decision allocates or references the stable Story Candidate identity and exact Candidate Version.

Concurrent equivalent proposals may resolve to one Candidate identity through an explicit decision. They must not create duplicate candidates or be silently merged after the fact.

### Evidence Handoff

The stable semantic transfer identity for submitting one exact Story Candidate Version to one Evidence Intake boundary. Retries and transport attempts reuse the same Handoff identity and idempotency identity.

A later Candidate Version requires a new Evidence Handoff. A successful Handoff does not mean that evidence is sufficient.

### Evidence Intake Acknowledgement

An immutable response correlated to one exact Evidence Handoff. It records durable intake acceptance, duplicate or merge handling, return for permitted follow-up or another structured outcome allowed by the accepted workflow.

A missing or ambiguous response is not an acknowledgement. Later reconciliation or retry creates additional attempt or response records without changing the Handoff identity.

### Operational Finding

A stable case identity for a source, adapter, policy, rights, queue, model, hand-off or other operational problem requiring retry, quarantine, remediation or authorised review.

Each occurrence, assessment, remediation decision and closure is retained. Repeated failures may be grouped into one Finding through an explicit rule without erasing individual Check Attempts or outcomes. Exact alert and incident grouping remains for Topic 9.

### Coverage Gap

A stable review case identifying a relevant in-scope development that an accepted discovery path failed to detect and that another permitted path or evidence-stage review surfaced.

A Coverage Gap is created only after a reviewable relevance and miss assessment. A search result, media item or comparator hit alone is not a Coverage Gap.

A Coverage Gap references the accepted coverage obligation or best-effort class, missed Event Hypothesis or Candidate where available, expected discovery paths, actual discovery path, evaluation window and known operational conditions. Whether the miss is isolated or systemic is a separate assessment decision.

### Coverage Gap Assessment

An immutable decision that classifies a Coverage Gap as isolated, systemic, not a true miss, expected under Best effort, blocked by an accepted deferred gap or otherwise resolved under a later-approved vocabulary.

Remediation, acceptance or closure creates later linked decisions. It does not delete the original gap or comparator evidence.

## Requirements

### Identity foundations

**DREC-001 — Stable internal identity.** Every Source Definition, Check Request, Check Attempt, Check Outcome, Source Item, Source Revision, Discovery Representation, Signal, Lead, Triage Work Item, Proposal, Event Hypothesis, Story Candidate, Candidate Version, Evidence Handoff, Operational Finding and Coverage Gap MUST have a stable Newsroom identity appropriate to its lifecycle.

**DREC-002 — No external locator identity.** A URL, GUID, filename, provider cursor, calendar position, feed order, message subject, title or search rank MUST NOT be used as the sole global Newsroom identity. Approved source-native identifiers MAY participate in source-scoped identity rules.

**DREC-003 — Digest is not domain identity.** A content or payload digest MAY establish byte or representation equality, idempotency or integrity but MUST NOT replace a stable Source Item, Event Hypothesis, Story Candidate or other lifecycle identity.

**DREC-004 — No identifier reuse.** A stable identity MUST NOT be reassigned to a different logical source, item, lead, hypothesis, candidate, hand-off, finding or gap after deletion, closure, merge, split or supersession.

**DREC-005 — Explicit identity uncertainty.** When continuity or equivalence is uncertain, the system MUST retain separate identities and record the uncertainty or proposed relationship. It MUST NOT silently choose one identity merely to simplify deduplication.

**DREC-006 — Version immutability.** A committed version or decision defined by this specification MUST be immutable. A correction or material update creates a later version, decision or explicit relationship.

**DREC-007 — Current-state projection.** Any mutable current-status or current-version pointer MUST be a rebuildable projection or convenience index. It MUST NOT be the only record of historical state or authority.

### Source and revision identity

**DREC-010 — Versioned Source Definition.** Every Check Request MUST reference one exact Source Definition Version. A material configuration change MUST create a new version or, when the monitored logical channel changes, a new Source Definition.

**DREC-011 — Source-scoped item identity.** Every Source Item MUST be scoped to one Source Definition. Cross-source equivalence MUST be represented as a later relationship, not by reusing one item identity across publishers or channels.

**DREC-012 — Locator movement.** A changed URL or locator MUST NOT automatically create a new Source Item or automatically preserve the old identity. A source-specific deterministic identity rule or explicit identity decision must establish the relationship.

**DREC-013 — Revision equality.** Repeated observations of the same approved source-native revision or permitted canonical source-state digest MUST resolve to the same Source Revision identity.

**DREC-014 — Revision is not materiality.** A new Source Revision establishes an observable source-state difference only. It MUST NOT by itself establish newsworthiness, factual correctness, substantive change or evidence sufficiency.

**DREC-015 — Representation separation.** Reprocessing one Source Revision under a changed parser, adapter or normalisation version MUST create a new Discovery Representation when output changes. It MUST NOT fabricate a new Source Revision.

**DREC-016 — Rights-limited identity.** Source Item, Revision and representation identity MUST be supportable using only content and metadata permitted by the applicable rights and retention decisions. This specification does not require retaining prohibited full source bytes.

**DREC-017 — Current-state sources.** A source that exposes only current state, such as an active-warning payload, MUST still use stable Source Item and Source Revision semantics. Topic 5 determines the meaning of state openings, escalations, cancellations and endings.

### Checks, attempts and occurrences

**DREC-020 — Logical check versus attempt.** One logical Check Request MAY have multiple Check Attempts. A retry MUST create a new Attempt while preserving the Check Request identity and exact source, trigger and policy context.

**DREC-021 — Immutable outcomes.** Every Check Outcome MUST reference one exact Check Attempt and MUST remain immutable. A later retry or recovery does not overwrite an earlier outcome.

**DREC-022 — Occurrence retention.** Repeated delivery or observation of an existing Source Revision MAY be semantically deduplicated while retaining a Discovery Occurrence sufficient for audit, source health and evaluation.

**DREC-023 — Baseline lineage.** A source baseline MUST identify the Check Request, Source Definition Version, item and revision identities included or excluded and the governing baseline policy. Baselining MUST NOT erase prior observations.

### Signals, gates and Leads

**DREC-030 — Signal source basis.** Every Discovery Signal MUST reference one exact Source Revision and Discovery Representation or one later-approved channel-input identity with equivalent version and lineage controls.

**DREC-031 — Deterministic signal discriminator.** When one Source Revision yields several Signals, each Signal MUST have a stable deterministic purpose or transition discriminator. Model-generated topic splitting alone is insufficient identity.

**DREC-032 — Signal immutability.** A later source revision, parser output, gate rule or editorial judgement MUST NOT mutate an existing Signal. It creates a new Signal, Representation or Decision as applicable.

**DREC-033 — One Lead per promoted Signal.** The default discovery contract is one News Lead identity for one promoted Discovery Signal. Several Signals MUST remain several Leads until an explicit triage or candidate relationship groups them.

**DREC-034 — Gate Decision lineage.** A News Lead MUST reference the exact committed Gate Decision that promoted its Signal and the governing coverage, rights, policy and gate versions.

**DREC-035 — Cross-source dedupe preservation.** Cross-source or cross-channel deduplication MUST NOT delete or collapse source-specific Signals and Leads. It may prevent duplicate Candidate admission while retaining every lineage path.

**DREC-036 — Disposition as decision.** Editorial reject, watch or defer, association, supplemental discovery, operational hold and Candidate routes MUST be committed as immutable Lead Disposition Decisions. A bare mutable Lead status is insufficient authority.

**DREC-037 — Watch condition.** Every watch or defer decision MUST carry an inspectable Watch Condition or reference to one. The current Lead state MUST distinguish awaiting that condition from operational blockage.

### Triage and Event Hypotheses

**DREC-040 — Work Item manifest.** Every Triage Work Item MUST identify the exact Lead identities or versions, Retrieval Context, coverage basis, urgency context, known incompleteness and component versions supplied to the worker.

**DREC-041 — Proposal immutability.** A Triage Proposal MUST reference one exact Work Item and worker or model version and MUST be retained separately from the committed decision that accepts or rejects its route.

**DREC-042 — Retrieval non-authority.** Retrieval results and similarity scores MUST remain inside versioned Retrieval Context. They MUST NOT allocate Event Hypothesis identity, merge records or establish `same_event` or `development_of` authority by themselves.

**DREC-043 — Event Hypothesis boundary.** An Event Hypothesis and each version MUST be explicitly marked unverified and discovery-level. It MUST NOT be presented as a canonical event, governed relation, Source Observation or verified fact.

**DREC-044 — Hypothesis versioning.** Adding or removing Leads, changing a material event summary, changing a proposed event relationship or changing known uncertainty MUST create a new Event Hypothesis Version.

**DREC-045 — Explicit merge and split.** Merging or splitting Event Hypotheses MUST create an explicit decision and successor or relationship records. Predecessor hypotheses, versions and lineage MUST remain reconstructable.

### Story Candidates and hand-off

**DREC-050 — Candidate identity on admission.** A stable Story Candidate identity MAY be allocated only through a committed Candidate Admission Decision. A Triage Proposal, Event Hypothesis, URL or model response MUST NOT directly create that identity.

**DREC-051 — Candidate version manifest.** Every Story Candidate Version MUST reference the exact Event Hypothesis Version, contributing Leads and Signals, admission decision, accepted coverage basis, urgency, uncertainties, evidence objectives and governing versions it contains.

**DREC-052 — Candidate is not Story identity.** Story Candidate identity MUST remain distinct from any later Story, Story Version, Evidence Package or publication identity. Evidence acquisition may close, merge or reject a Candidate without creating a Story.

**DREC-053 — Candidate change creates version.** A material change to contributing lineage, event hypothesis, geography, category, urgency, likely new information, uncertainty or evidence objective MUST create a new Candidate Version or superseding Candidate decision.

**DREC-054 — Equivalent admission control.** Concurrent or repeated equivalent proposals MUST resolve through one explicit admission or deduplication decision. They MUST NOT create duplicate Candidate identities or be silently coalesced through mutable status.

**DREC-055 — One semantic Handoff.** One exact Story Candidate Version and Evidence Intake boundary MUST have one stable semantic Evidence Handoff identity. Retries use separate transport attempts or responses but reuse the Handoff and idempotency identity.

**DREC-056 — Acknowledgement correlation.** Every Evidence Intake Acknowledgement MUST correlate to one exact Evidence Handoff. A timeout, missing response or ambiguous transport result MUST NOT create an acknowledgement or a second Handoff.

**DREC-057 — Feedback is later history.** Evidence-stage feedback, closure, merge, rights block or supplemental discovery request MUST create a later linked record and MUST NOT mutate the original Candidate Version or Handoff.

### Findings and Coverage Gaps

**DREC-060 — Operational Finding separation.** Operational Findings MUST remain distinct from editorial rejections, successful unchanged checks, Coverage Gaps and evidence outcomes.

**DREC-061 — Finding occurrences.** Grouping repeated failures into one Operational Finding MUST retain each contributing Check Attempt, outcome or downstream failure occurrence.

**DREC-062 — Gap requires review.** A comparator result or later-discovered story MUST NOT automatically create a Coverage Gap. A committed review must establish that the development was relevant, within the accepted coverage contract and missed by the expected paths.

**DREC-063 — Gap lineage.** Every Coverage Gap MUST identify the applicable coverage class, missed development hypothesis or candidate where available, expected paths, discovering path, evaluation window and relevant operational conditions.

**DREC-064 — Isolated versus systemic decision.** Whether a Coverage Gap is isolated, systemic, expected under Best effort or explained by an accepted deferred gap MUST be recorded in a separate Coverage Gap Assessment. It MUST NOT be inferred merely from source count.

**DREC-065 — Gap history.** Remediation, accepted risk, reclassification and closure MUST create later linked records. They MUST NOT erase the original Gap or the evidence used to assess it.

### Lineage and time

**DREC-070 — Exact upstream references.** Every downstream record or decision MUST reference the exact committed upstream identities and versions it consumed. Bare URLs, titles, timestamps or mutable “latest” aliases are insufficient lineage.

**DREC-071 — Ordered causation.** The record chain MUST preserve the difference between trigger, Check Request, Attempt, Outcome, Capture, Item, Revision, Representation, Occurrence, Signal, Gate Decision, Lead, Work Item, Proposal, committed disposition, Event Hypothesis, Candidate Version, Handoff and feedback.

**DREC-072 — Many-to-many lineage.** The model MUST support one Check Outcome producing several Signals, repeated Outcomes observing one Revision, several Leads supporting one Candidate and one Lead participating in later Candidate Versions without duplicating or erasing identity.

**DREC-073 — Supersession is explicit.** Supersession, replacement, correction, merge, split, follow-up, corroboration and possible-equivalence relationships MUST be directional, versioned and attributable. They MUST NOT be inferred solely from current status.

**DREC-074 — Time separation.** Records MUST keep source-asserted publication, update or effective times distinct from Newsroom observation time, collection time and authoritative recording time. Missing or conflicting times MUST remain explicit.

**DREC-075 — Source time is untrusted metadata.** A source-asserted date or update time MAY support change detection under a source-specific rule but MUST NOT be treated as authoritative Newsroom recording time or sufficient proof that content changed.

**DREC-076 — Version provenance.** Every normalised representation, gate decision, retrieval context, proposal and admission decision MUST identify the exact producer, parser, model, policy or validator version that created or governed it.

**DREC-077 — Rebuildable current view.** Operators MAY use current-status projections for efficient work, but audit and replay MUST be able to reconstruct that view from retained identities, versions, decisions and relationships subject to lawful retention limits.

## Acceptance criteria

1. Changing the URL of a GOV.UK page does not automatically prove that it is a new Source Item or the same Source Item; the source-specific identity rule or explicit decision determines the relationship.
2. Observing the same feed GUID and source revision five times creates repeated Occurrences but at most one equivalent Signal transition.
3. A parser upgrade that extracts a new field from unchanged bytes creates a new Discovery Representation and does not fabricate a source revision.
4. A source changing existing guidance creates a new Source Revision and Signal path without overwriting the earlier revision or Lead.
5. Two publishers reporting the same incident retain separate Source Items, Revisions, Signals and Leads even when triage later groups them into one Event Hypothesis and Candidate.
6. A model's `same_event` output is a Triage Proposal and cannot allocate a canonical event or Candidate identity.
7. Adding a corroborating Lead to an Event Hypothesis creates a new hypothesis version; an acknowledged earlier Candidate Handoff remains pinned to its exact Candidate Version.
8. A Candidate rejected by evidence acquisition remains a distinct Candidate with retained admission and hand-off history and does not become a Story.
9. Retrying an ambiguous Evidence Handoff reuses the semantic Handoff identity and cannot create a duplicate Candidate or intake request.
10. A search hit found during recall audit does not become a Coverage Gap until a reviewed decision establishes a relevant miss.
11. Closing an Operational Finding or Coverage Gap does not delete its occurrences, assessments, remediation decisions or upstream lineage.
12. An operator can reconstruct a Candidate from exact upstream versions without relying on a current mutable status row, title or URL.
13. Source-published time, source-updated time, Newsroom observation time and authoritative recording time cannot silently overwrite one another.
14. No discovery record defined here is represented as a Source Observation, Evidence Package, verified fact, Story Version or publication authority.

## Owner decisions required to complete Topic 3

The Draft recommends the following decisions:

1. Accept stable internal identities that remain separate from URLs, provider identifiers and content digests.
2. Accept the separation between Source Definition and Version, Source Item and Revision, and Source Revision and Discovery Representation.
3. Accept that parser or normaliser reprocessing of unchanged source state creates a new Representation, not a new source Revision.
4. Accept the Check Request, Check Attempt and Check Outcome separation so retries preserve logical work identity while each execution and result remains inspectable.
5. Accept one News Lead per promoted Discovery Signal by default, with later revisions and cross-source reports remaining separate Leads linked explicitly rather than absorbed or erased.
6. Accept immutable Lead Disposition Decisions and a required Watch Condition for the accepted watch or defer workflow outcome.
7. Accept Event Hypothesis and Event Hypothesis Version as unverified discovery identities, distinct from canonical event, relation, Story and evidence identity.
8. Accept stable Story Candidate identity with immutable Candidate Versions, allocated only by deterministic admission and kept distinct from later Story identity.
9. Accept one semantic Evidence Handoff per exact Candidate Version and intake boundary, with retries and acknowledgements represented separately.
10. Accept that Coverage Gaps require a reviewed relevant-miss decision and retain separate assessments for isolated, systemic, Best-effort or deferred-gap interpretation.
11. Accept append-only lineage, explicit supersession or merge relationships, separate source-observed and Newsroom-recorded times, and current status as a rebuildable view rather than sole authority.
