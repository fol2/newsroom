# Discovery triage and event-grouping specification

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
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Implementation authority:** None. Acceptance defines triage and grouping semantics; it does not authorise model calls, search, shadow operation or production use.  
**Supersedes:** None

## Purpose

Define how News Leads are assembled into bounded triage work, compared with prior discovery history, assigned an editorial disposition and, where justified, grouped into unverified Event Hypotheses and admitted Story Candidates.

The contract separates computational batching from editorial grouping, event relationship from newsworthiness, retrieval from decision authority and model proposals from committed workflow state. It prevents both fragmentation and snowball grouping, where a broad event absorbs distinct developments merely because they share vocabulary, entities or media volume.

## Scope

This specification defines:

- Triage Work Items and Triage Execution Batches;
- decision Leads and context-only Leads;
- bounded retrieval of prior Leads, Event Hypotheses, Candidates and Story references;
- structured Triage Proposals and deterministic validation;
- same-state, development, correction, related-but-distinct, new and uncertain relationship semantics;
- Event Hypothesis creation, association, versioning, consolidation and split decisions;
- Story Candidate formation from one or several Leads;
- Urgent, Time-sensitive, Planned and Routine triage treatment;
- worker failure, fallback, disagreement and degraded-retrieval behaviour; and
- evaluation requirements for later shadow validation.

It does not select a model provider, prompt, embedding model, retrieval engine, numeric threshold, queue timing, batch size, retry budget, search provider, physical database or production release threshold.

## Current-system replacement boundary

The current legacy path asks a model to choose `assign`, `development` or `new_event` for one link at a time. Empty retrieval forces `new_event`, and a later LLM merge pass may move links and remove losing event rows. Those behaviours are implementation details, not this target contract.

The existing clustering evaluation also collapses `development` and `new_event` into the same label. It therefore cannot prove conformance with this specification and must be replaced or extended under Topic 8.

## Core principles

1. **Batching is not grouping.** Several Work Items may share one worker call without implying that their Leads concern the same event.
2. **Relationship and newsworthiness are separate.** A Lead may concern the same event and still contain a material development; a distinct event may still not justify evidence work.
3. **Retrieval provides context, not authority.** Similarity, recency, category and shared entities do not establish event identity.
4. **Every decision Lead receives one explicit disposition.** A batch-level answer cannot omit or absorb an included Lead.
5. **Models propose; deterministic controllers commit.** No model output directly creates a disposition, relationship, Event Hypothesis or Candidate.
6. **Grouping is append-only.** Consolidation and split preserve all predecessor identities, versions, Leads, Candidates and Handoffs.
7. **Urgency protects latency, not standards.** Urgent work may bypass Routine waiting but not scope, materiality, lineage or admission rules.
8. **No-Candidate is a healthy outcome.** Reject, watch, association and hold remain valid.
9. **One source may justify evidence work, not publication.** Discovery has no minimum outlet or domain count; evidence authority and corroboration remain downstream.
10. **Uncertainty remains explicit.** Uncertain relation, incomplete retrieval and conflicting proposals are not guessed away.

## Triage work model

### Decision Lead

A decision Lead is an exact News Lead version for which the Work Item must produce one committed disposition, or no state change because validation failed.

### Context-only Lead

A context-only Lead is supplied only to assess history or relationship. It cannot receive a new disposition through that Work Item unless separately included as a decision Lead.

### Triage Work Item

A Triage Work Item is an immutable editorial-decision manifest containing:

- one or more exact decision Lead versions;
- any context-only Leads, explicitly marked;
- accepted coverage and qualitative urgency for each decision Lead;
- source role, dependency and observable-transition context;
- known incompleteness, rights and operational warnings;
- exact Retrieval Context identity or a declared retrieval-pending state;
- the allowed disposition and relationship vocabulary;
- component and policy versions; and
- size and content bounds.

Changing membership, material context or governing policy creates a new Work Item version or identity.

### Triage Execution Batch

A Triage Execution Batch is only a transport and cost envelope containing one or more independent, compatible Work Items.

- Batch membership creates no relationship.
- Outputs remain addressable by Work Item and decision Lead.
- One Work Item cannot consume another Work Item's Leads unless explicitly included.
- Urgent Work Items cannot wait merely to fill a batch.
- Mixed-language batching is allowed only where exact source text, translation context and uncertainty remain attributable.

### Multi-topic inputs

A worker cannot split one Lead into several authoritative events merely because the source contains several topics. Multiple authoritative Signals require an approved deterministic or source-specific extraction contract. Otherwise the Lead may be rejected, watched, re-extracted or sent for bounded supplemental discovery.

## Retrieval contract

Retrieval may consider:

- exact Source Item, formal-process, case, bill, warning, route and Agenda identifiers;
- predecessor, replacement, follow-up and Watch Condition relationships;
- English and Chinese entity aliases;
- dates, numbers, thresholds and reference periods;
- time, geography, route, institution and affected-population compatibility;
- lexical or semantic similarity;
- active or recent Event Hypotheses;
- open or recently admitted Candidates;
- relevant prior Story references, without importing them as evidence; and
- known source dependencies or shared originating material.

Exact and source-native relationships should precede approximate similarity where available. Retrieval remains bounded and records its query, scope, version, watermark, candidate set, scores, match signals and known omissions.

The result set must preserve `no adequate prior match` as a valid possibility. A high score does not compel association; an empty result does not prove a new event.

Retrieval Context distinguishes:

1. exact identity lookup;
2. current Candidate and identity collision checking; and
3. advisory semantic retrieval.

Candidate admission is blocked when exact identity or current Candidate collision checking fails. Advisory retrieval failure is not represented as `no match`. A potentially Urgent Work Item may proceed without advisory retrieval only under an accepted degraded policy, after exact checks succeed, with explicit incompleteness and mandatory later reconciliation.

## Editorial triage dimensions

Triage assesses whether evidence acquisition is likely justified. It does not verify the event.

For every decision Lead, a proposal addresses:

- accepted coverage basis or exclusion;
- likely substantive new information;
- likely reader utility or material impact;
- qualitative urgency;
- source role and dependency;
- likely relationship to prior Hypotheses, Candidates or Stories;
- whether it is another report of an existing state;
- whether a changed state, correction, reversal or resolution is proposed;
- contradictions, uncertainty and retrieval incompleteness;
- whether bounded supplemental discovery is justified; and
- the recommended Lead disposition.

Insufficient information is a valid conclusion. Missing facts cannot be manufactured to avoid uncertainty.

## Discovery-level relationship semantics

These relationships are unverified hypotheses, not canonical event or factual relations.

### Same event state

The Lead likely reports the same specific occurrence, decision, announcement or formal-process state already represented, without a material new state. Shared topic, organisation or policy area alone is insufficient.

The normal disposition is association without a new Candidate.

### Development of

The Lead likely concerns the same continuing event or formal process but proposes a materially new state, outcome, escalation, de-escalation, implementation, verdict, charge, resignation, effective change, resolution or similar development.

Every development proposal identifies:

- exact predecessor context;
- the earlier state;
- the proposed new state or fact;
- why the difference may be substantive; and
- remaining uncertainty.

Another outlet, angle, recap, commentary or repeated background is not a development.

### Correction, clarification or reversal of

The Lead proposes that an earlier state, figure, instruction, schedule or account was corrected, qualified, withdrawn or reversed. This may justify a correction-oriented Candidate but cannot rewrite prior history.

### Related but distinct

The Lead shares context, actors, geography or policy area but concerns a separate occurrence, decision, case, release or process instance. It must not be absorbed into a broad prior event merely to reduce fragmentation.

### No adequate prior match

No retrieved prior Hypothesis adequately represents the proposed occurrence or process. This permits, but does not require, a new Hypothesis proposal.

### Uncertain relationship

Available context cannot safely distinguish same state, development, correction, related event or new event. The normal route is watch, supplemental discovery or Operational hold, unless a Candidate can preserve the uncertainty without inventing a relationship.

## Event Hypothesis decisions

### Creation and association

An Event Hypothesis may be created for a new-event Candidate, development Candidate or retained watch case. A Lead may be associated with an existing Hypothesis without creating a Candidate, with the association type recorded.

### Versioning

Adding or removing contributing Leads, changing the proposed state, changing a relationship or materially changing uncertainty creates a new Event Hypothesis Version.

### Consolidation

When two Hypotheses are later judged to represent the same event or process, a deterministic consolidation decision creates an explicit successor, preferred continuation or equivalence relationship. Neither predecessor is deleted, silently moved or retargeted.

### Split

When one Hypothesis combines distinct occurrences or processes, a deterministic split decision creates successor Hypotheses and explicit lineage. Historical proposals, decisions, Leads, Candidates and Handoffs remain reconstructable.

Later grouping decisions cannot mutate an exact Hypothesis Version or Candidate Version already handed to Evidence Intake or used downstream.

## Lead dispositions and Candidate formation

Permitted outcomes are:

- **Editorial reject:** likely coverage, utility, materiality or novelty is insufficient.
- **Watch or defer:** the Lead needs a defined transition, corroborating Lead, occurrence, deadline, source update or review condition; a Watch Condition is mandatory.
- **Associate without Candidate:** the Lead concerns an existing state and does not justify new evidence work.
- **Supplemental discovery:** one bounded, approved action creates a new trigger and normal Signals.
- **Operational hold:** required retrieval, policy, rights, model, capacity or integrity context is unavailable.
- **New-event Candidate:** no adequate prior Hypothesis exists and likely scope, utility, materiality and novelty justify evidence acquisition.
- **Development Candidate:** exact predecessor context and a proposed changed state justify evidence acquisition.
- **Correction-oriented Candidate:** a correction, clarification, withdrawal or reversal may materially affect readers.

Several Leads may support one Candidate only through a coherent Event Hypothesis and complete lineage. Unrelated Leads cannot be combined because they share a batch, category or publisher.

A single Lead normally receives one disposition. It cannot be authoritatively split into several Candidates without distinct Signals from an approved extraction contract.

A non-material same-state Lead may be associated without changing an existing Candidate Version. A material change to the Hypothesis, urgency, uncertainty or evidence objective creates a new Candidate Version and, where required, a new Handoff.

## Triage Proposal contract

Every Triage Proposal is immutable, untrusted and tied to one exact Work Item and Retrieval Context. It must:

- identify every decision Lead exactly once;
- distinguish context-only Leads;
- recommend one allowed disposition per decision Lead;
- identify proposed Hypotheses and relationship targets;
- cite exact input Leads, fields and match or contradiction signals;
- state likely new information and materiality without presenting them as verified;
- list uncertainty, missing context and retrieval incompleteness;
- include a Watch Condition or bounded supplemental action where applicable;
- include the minimum Candidate manifest where admission is proposed;
- avoid facts, identities, numbers, causation and relationships absent from permitted input; and
- follow a versioned structured schema.

A free-form explanation, batch-level label or confidence number alone is not a valid proposal.

## Deterministic validation

Before committing any disposition, Hypothesis decision or Candidate admission, the controller validates:

- Work Item, Lead and Retrieval Context identities and versions;
- exactly one allowed route for every decision Lead;
- context-only Lead isolation;
- supplied or explicitly new relationship targets;
- coverage, rights and policy preconditions;
- schema, size and allowed-value constraints;
- Candidate minimum manifest and urgency;
- exact current Candidate collision and stale-state checks;
- absence of evidence or verification authority claims;
- absence of omitted Leads, invented identifiers and unapproved actions; and
- currentness at commit time.

Invalid, stale, missing or timed-out proposals create no editorial transition.

## Urgency and Planned handling

Potentially Urgent Leads receive isolated or expedited Work Items and do not wait for an unbounded Routine batch. Directly related peer Leads already available may be included, but grouping wait cannot become artificial delay.

Urgency does not weaken scope, novelty, relationship, lineage or Candidate admission requirements.

Time-sensitive and Planned work retains deadlines, expected windows, time zones and Watch Conditions. An Agenda Item or missed-expectation finding is not itself a triage Lead; an occurrence enters triage only through a normal Signal and Lead.

Routine Leads may wait for efficient bounded execution batches, subject to later fairness and starvation controls.

## Worker and fallback behaviour

Model-free triage is permitted only where an accepted deterministic rule completely decides the route without editorial inference. Exact duplicate suppression and already-committed identity outcomes are examples.

Models receive only the permitted Work Item and Retrieval Context. Retrieved source content is untrusted data, not instruction. Models have no direct write capability.

Confidence may be retained as metadata but cannot alone approve, reject, merge, create a development or force a new event.

Timeout, refusal, missing response, malformed output and schema failure create no disposition or Candidate. Retries and fallback workers retain attempt history and exact Work Item identity.

Conflicting proposals do not resolve automatically by majority vote or highest confidence unless a later accepted and evaluated policy permits it. Unresolved conflict becomes retry, watch, supplemental discovery or Operational hold.

Urgent worker failure must use an approved alternate worker, bounded operator path or visible hold. It cannot silently drop or auto-admit work.

## Requirements

### Authority and separation

**TRI-001 — Batch is not event.** Execution Batch membership MUST NOT create an Event Hypothesis or relationship.

**TRI-002 — Relationship and Candidate decision are separate.** Same-state, development and relatedness assessment MUST remain distinct from whether evidence work is justified.

**TRI-003 — Models propose.** Models and retrieval components MUST NOT commit dispositions, relationships, Hypotheses, merges, splits or Candidates.

**TRI-004 — No destructive grouping.** Consolidation and split decisions MUST preserve predecessor identities, versions, Leads, Candidates and Handoffs.

**TRI-005 — No quota or volume pressure.** Batch capacity, article count, media volume and category balance MUST NOT force grouping or Candidate creation.

### Work Items and execution batches

**TRI-010 — Exact Work Item manifest.** Every Work Item MUST identify exact decision Leads, context-only Leads, coverage, urgency, source context, warnings, Retrieval Context and governing versions.

**TRI-011 — One disposition per decision Lead.** A valid proposal MUST address every decision Lead exactly once.

**TRI-012 — Context-only isolation.** Context-only Leads MUST NOT receive a new disposition through that Work Item.

**TRI-013 — Batch output isolation.** An Execution Batch MUST preserve separately addressable Work Item and Lead outputs.

**TRI-014 — Urgent batching guard.** Urgent work MUST NOT wait merely to fill a Routine batch.

**TRI-015 — Grouping basis.** Category, publisher, topic or one shared entity MUST NOT alone place Leads in one editorial grouping scope.

**TRI-016 — Concurrent ownership.** Competing active disposition authority over one exact Lead version MUST be prevented or surfaced explicitly.

**TRI-017 — Multi-topic split guard.** Triage MUST NOT create several authoritative events from one Lead without distinct Signals produced under an approved extraction contract.

### Retrieval

**TRI-020 — Retrieval context only.** Retrieval generates bounded context and MUST NOT establish event identity or disposition.

**TRI-021 — Exact before approximate where available.** Source-native, formal-process and explicit-lineage relationships SHOULD precede approximate similarity.

**TRI-022 — Bounded inspectable retrieval.** Retrieval MUST record query, scope, version, watermark, candidates, scores, signals and known omissions.

**TRI-023 — No-match option.** Retrieval MUST preserve the possibility that no prior Hypothesis is adequate.

**TRI-024 — Empty retrieval is not new event.** No returned candidate MUST NOT force a new Hypothesis or Candidate.

**TRI-025 — Score non-authority.** Similarity, category, recency, token overlap and confidence MAY rank context only.

**TRI-026 — Collision check required.** Candidate admission requires a successful exact current Candidate and identity collision check.

**TRI-027 — Retrieval failure honesty.** Incomplete retrieval MUST be explicit and MUST NOT be represented as no match.

**TRI-028 — Guarded urgent degradation.** Urgent work MAY proceed without advisory semantic retrieval only under an accepted degraded policy, successful exact collision checks and mandatory later reconciliation.

### Proposal and editorial judgement

**TRI-030 — Likely-not-verified standard.** Triage assesses likely coverage, utility, materiality, novelty, urgency and relationship only to decide whether evidence acquisition is justified.

**TRI-031 — Structured proposal.** Every proposal MUST satisfy the Triage Proposal contract and cite exact permitted inputs.

**TRI-032 — No invented basis.** A proposal MUST NOT add facts, identities, numbers, causation or relationships absent from input.

**TRI-033 — Confidence is metadata.** Confidence alone MUST NOT determine a route or relationship.

**TRI-034 — Invalid proposal neutrality.** Invalid, stale, missing or timed-out output produces no editorial transition.

**TRI-035 — Uncertainty preserved.** Unresolved relationship or materiality uncertainty MUST remain explicit through watch, supplemental discovery, guarded Candidate uncertainty or Operational hold.

**TRI-036 — No-Candidate validity.** Reject, watch, association and hold are valid outcomes and no quota may override them.

### Event relationships and Hypotheses

**TRI-040 — Same-state test.** Same-event-state association requires compatible specific occurrence or process-state signals; shared subject alone is insufficient.

**TRI-041 — Development test.** A development proposal MUST identify exact prior context, earlier state, proposed new state and likely substantive difference.

**TRI-042 — Repetition is not development.** Another source, angle, recap, commentary or unchanged background MUST NOT be classified as a development solely for freshness.

**TRI-043 — Correction relationship.** Correction, clarification, withdrawal and reversal remain explicit unverified relationships and do not rewrite prior history.

**TRI-044 — Related-but-distinct protection.** A separate occurrence or process instance MUST NOT be absorbed into a broad prior event because of shared actors or topic.

**TRI-045 — New Hypothesis not forced.** No adequate prior match permits but does not require new Hypothesis creation.

**TRI-046 — Uncertain relation route.** Uncertain relation normally uses watch, supplemental discovery or hold unless a Candidate can preserve uncertainty without a false relationship.

**TRI-047 — Explicit consolidation.** Hypothesis consolidation requires a committed decision and preserves predecessors.

**TRI-048 — Explicit split.** Hypothesis split requires a committed decision and reconstructable successor lineage.

**TRI-049 — Historical pinning.** Later grouping MUST NOT mutate Hypothesis or Candidate Versions already handed off or used downstream.

### Lead dispositions and Candidates

**TRI-050 — Association without Candidate.** Same-state or repeated coverage normally associates lineage without creating new evidence work.

**TRI-051 — New-event Candidate basis.** A new-event Candidate requires likely accepted coverage, utility, materiality and novelty plus no adequate prior Hypothesis.

**TRI-052 — Development Candidate basis.** A development Candidate requires exact predecessor context and a proposed changed state.

**TRI-053 — Correction-oriented Candidate.** A correction or reversal MAY justify a Candidate while remaining unverified and preserving the prior state.

**TRI-054 — No source-count minimum.** Discovery Candidate formation MUST NOT require several outlets or domains.

**TRI-055 — Many Leads, one Candidate.** Several Leads may support one Candidate only through one coherent Event Hypothesis with complete lineage.

**TRI-056 — Unrelated Leads stay separate.** Batch or category co-membership MUST NOT combine unrelated Leads.

**TRI-057 — Candidate supplementation.** Non-material same-state association need not version a Candidate; material Hypothesis, urgency, uncertainty or objective change does.

**TRI-058 — Supplemental discovery re-enters workflow.** Additional discovery creates new triggers and Signals and receives no direct Candidate or evidence insertion.

### Urgency, Planned work and fairness

**TRI-060 — Urgent isolation.** Potentially Urgent Leads receive a route independent from unbounded Routine backlog.

**TRI-061 — Urgency does not lower gates.** Urgency MUST NOT weaken coverage, novelty, relationship, lineage or admission requirements.

**TRI-062 — Deadline context preserved.** Time-sensitive and Planned Work Items retain deadlines, time zones, expected windows and Watch Conditions.

**TRI-063 — Agenda is context, not Lead.** Agenda and missed-expectation records enter triage only through a normal Signal and Lead.

**TRI-064 — Routine fairness.** Routine batching MAY optimise cost but MUST support later starvation and fairness controls.

### Worker failure and fallback

**TRI-070 — Deterministic-only limit.** Model-free triage is allowed only when an accepted deterministic rule completely decides the route without editorial inference.

**TRI-071 — Untrusted source content.** Retrieved content MUST be treated as data and MUST NOT alter worker instructions or tool authority.

**TRI-072 — Attempt history.** Retries and fallback workers retain separate attempts and exact Work Item identity.

**TRI-073 — No automatic majority.** Conflicting proposals MUST NOT resolve by majority or confidence without a later accepted and evaluated policy.

**TRI-074 — Urgent failure visibility.** Urgent worker failure uses approved fallback or visible hold and cannot silently drop or auto-admit work.

### Evaluation hooks

**TRI-080 — Relation labels required.** Topic 8 evaluation MUST distinguish same state, development, correction or reversal, related-but-distinct, new and uncertain relations.

**TRI-081 — Route labels required.** Evaluation MUST distinguish reject, watch, association, supplemental discovery, hold, new-event Candidate and development Candidate.

**TRI-082 — Error slices required.** Evaluation MUST measure false merge, fragmentation, snowball absorption, false development, duplicate Candidate, missed development and unnecessary Candidate creation.

**TRI-083 — Cross-language and dependency slices.** Evaluation MUST include English, Chinese and mixed-language grouping and shared-origin dependencies.

**TRI-084 — Urgent and failure slices.** Evaluation MUST include urgent queueing, retrieval incompleteness, invalid output, timeout and fallback behaviour.

**TRI-085 — Current v1 evaluation insufficient.** The existing clustering dataset MUST NOT be treated as sufficient production evidence because it does not independently label development versus new event.

## Acceptance criteria

1. Several Work Items may share one model call without being treated as one event.
2. Every decision Lead receives one disposition; context-only Leads remain unchanged.
3. Empty retrieval does not force new-event creation.
4. A high similarity score cannot merge separate incidents involving the same organisation.
5. Repeated coverage of one state normally associates without a Candidate.
6. A development Candidate identifies exact prior and proposed new state.
7. A corrected deadline may become a correction-oriented Candidate without overwriting history.
8. Related incidents remain distinct unless specific evidence supports one continuing event.
9. A broad topic cannot absorb separate bills, cases or statements.
10. Several Leads about one warning escalation may support one Candidate with full lineage.
11. A multi-topic briefing cannot be model-split without approved distinct Signals.
12. Timeout, refusal and invalid output create no editorial transition.
13. Confidence cannot force new event, development or merge.
14. Urgent work bypasses Routine waiting but passes the same admission requirements.
15. Advisory retrieval failure is not represented as no match; exact collision checks remain mandatory.
16. Consolidation and split preserve predecessors and acknowledged Handoffs.
17. Non-material association need not change a Candidate Version; a material change does.
18. Agenda context may help relationship assessment but cannot create a Lead.
19. Topic 8 can independently score relationship and route classes rather than collapsing development into new event.

## Completion record

The product owner accepted this specification on 2026-07-15 with these decisions:

- Triage Work Items, Triage Execution Batches and editorial event grouping are separate;
- decision Leads and context-only Leads are distinct, every decision Lead requires one explicit disposition and context-only Leads cannot be mutated;
- bounded retrieval supplies context only, empty retrieval does not force a new event and scores or confidence are non-authoritative;
- Candidate admission requires a separate exact current Candidate and identity collision check;
- accepted relationships are same event state, development, correction or reversal, related but distinct, no adequate prior match and uncertain relationship;
- event relationship and Candidate creation are orthogonal, with same-state repetition normally associated and material new state eligible for a development Candidate;
- every development Candidate states the exact earlier state and proposed new state;
- Event Hypothesis creation, association, versioning, consolidation and split are deterministic append-only decisions with no destructive merge;
- several Leads may form one coherent Candidate with complete lineage, unrelated Leads remain separate and a multi-topic Lead cannot be model-split without distinct approved Signals;
- Candidate formation has no minimum source or domain count at discovery;
- Urgent Work Items may be expedited without lower standards, and advisory-retrieval degradation requires exact collision checks and later reconciliation;
- proposals are structured and validated deterministically, confidence is metadata and timeout, refusal, malformed output and disagreement remain neutral;
- non-material association need not version a Candidate, while material Hypothesis, urgency, uncertainty or evidence-objective change creates a new Candidate Version; and
- Topic 8 must replace or extend current clustering evaluation to test relationship and route classes, including false merge, snowball absorption, fragmentation and false development.
