# Discovery triage and event-grouping specification

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
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Decision state:** The triage, retrieval, batching, Event Hypothesis and Candidate-formation rules below are proposals. Committing this Draft does not authorise model calls, shadow operation or production use.  
**Supersedes:** None

## Purpose

Define how News Leads are assembled into bounded triage work, compared with prior discovery history, assigned an editorial disposition and, where justified, grouped into unverified Event Hypotheses and admitted Story Candidates.

The design separates computational batching from editorial grouping, event relationship from newsworthiness, retrieval from decision authority and model proposals from committed workflow state. It is intended to prevent both fragmentation and “snowball” grouping, where a broad or popular event absorbs distinct developments merely because they share vocabulary, entities or media volume.

## Scope

This specification defines:

- deterministic versus editorial triage responsibility;
- Triage Work Item and Triage Execution Batch formation;
- bounded retrieval of prior Leads, Event Hypotheses, Candidates and Story references;
- structured Triage Proposal requirements;
- same-state, development, correction, related-but-distinct, new and uncertain relationship semantics;
- Event Hypothesis creation, versioning, consolidation and split decisions;
- Story Candidate formation from one or several Leads;
- urgent, time-sensitive, Planned and Routine triage treatment;
- model failure, fallback, disagreement and degraded-retrieval behaviour; and
- evaluation hooks needed to test grouping and candidate quality later.

It does not define:

- model provider, exact prompt text, embedding model or retrieval engine;
- numeric similarity, confidence or materiality thresholds;
- queue wait times, batch sizes, retry budgets or service-level objectives, which belong to Topic 9;
- final outcome or reason-code strings, which belong to Topic 10;
- search providers or search-trigger rules, which belong to Topic 7;
- shadow datasets, metrics or production thresholds, which belong to Topic 8;
- evidence sufficiency, factual verification, drafting or publication; or
- physical database, graph, queue or transaction implementation.

## Current-system replacement boundary

The current legacy clustering path asks a model to choose `assign`, `development` or `new_event` for one link at a time. When retrieval returns no candidate, the prompt forces `new_event`; a later LLM merge pass can move links and remove losing event rows. Those behaviours are current-system implementation details, not the target contract. See [`../../../newsroom/event_manager.py`](../../../newsroom/event_manager.py).

The current v1 clustering evaluation also labels both `development` and `new_event` as `new_event`, so it cannot independently test development classification. Topic 8 must replace or extend that evaluation before the accepted distinctions in this specification can earn production authority. See [`../../evaluation/clustering_eval_dataset_v1.md`](../../evaluation/clustering_eval_dataset_v1.md).

## Core principles

1. **Batching is not grouping.** Several Work Items may share one model call for efficiency without implying that their Leads describe the same event.
2. **Relationship and newsworthiness are separate.** A Lead may concern the same event and still contain a material development; a distinct event may still be unworthy of a Candidate.
3. **Retrieval proposes context.** Similarity, category, recency and shared entities generate candidates for consideration but do not establish event identity.
4. **Every Lead receives an explicit disposition.** A batch-level answer cannot silently absorb, omit or discard an included decision Lead.
5. **Models propose; controllers commit.** No model output creates a Lead disposition, Event Hypothesis, relationship or Story Candidate until deterministic validation succeeds.
6. **No destructive merge.** Consolidation and split decisions preserve predecessor identities, versions, Leads, Candidates and handoffs.
7. **Urgency protects latency, not standards.** Urgent work may bypass Routine waiting but not coverage, rights, materiality, lineage or admission rules.
8. **No-candidate is healthy.** Reject, watch, association and operational hold are valid outcomes; volume or capacity never forces Candidate creation.
9. **One source is enough for discovery, not proof.** A direct official or operator Lead may justify evidence work without several media repetitions; the evidence workflow later decides authority and corroboration.
10. **Uncertainty is represented, not guessed away.** Uncertain event relation, retrieval incompleteness and conflicting proposals remain explicit.

## Triage stages

```text
queued News Leads
      |
      v
Work Item formation
  - decision Leads
  - context-only Leads
  - urgency and coverage
      |
      v
bounded retrieval
  - exact identifiers
  - prior hypotheses and candidates
  - multilingual/entity/time/place signals
      |
      v
Retrieval Context
      |
      v
Triage Proposal
  - one disposition per decision Lead
  - relationship proposals
  - candidate proposal where justified
      |
      v
deterministic validation
      |
      +--> reject / watch / associate / supplemental / hold
      |
      +--> Event Hypothesis decision or version
                         |
                         v
                Candidate Admission Decision
                         |
                         v
                  Story Candidate Version
```

## Triage work and batching

### Decision Lead and context-only Lead

A **decision Lead** is an exact News Lead version for which the Work Item must produce one committed disposition or no state change because validation failed.

A **context-only Lead** is supplied only to help assess relationship or history. It remains governed by its own current disposition and cannot be modified by the Work Item unless it is separately included as a decision Lead.

This distinction prevents a model from changing historical or concurrently owned Leads merely because they appeared in context.

### Triage Work Item

The accepted record semantics define a Triage Work Item as an immutable manifest. For Topic 6, every Work Item must include:

- one or more exact decision Lead versions;
- any context-only Leads, clearly marked;
- accepted coverage and qualitative urgency for each decision Lead;
- source role, dependency and observable-transition context;
- known incompleteness, rights or operational warnings;
- exact Retrieval Context identity or a declared retrieval-pending state;
- the allowed disposition and relationship vocabulary;
- component and policy versions; and
- size and content bounds.

A material change to membership, context or policy creates a new Work Item version or identity.

### Triage Execution Batch

A Triage Execution Batch is a transport and cost envelope containing one or more independent Work Items for one compatible worker invocation.

- Batch membership does not create an event relationship.
- Output remains separately addressable by Work Item and decision Lead.
- One Work Item may not use another Work Item's Leads unless those Leads are explicitly included in its manifest.
- Urgent Work Items cannot be delayed merely to fill a larger batch.
- A batch may mix languages only where the approved worker can preserve exact source text, translated context and identity without hiding uncertainty.

### Work Item formation

Work Items may be formed using deterministic exact identity, formal-process identifiers, Planned Agenda relationships, source links, prior Watch Conditions and bounded retrieval candidate generation.

Category, publisher, broad topic, time proximity or one shared person or organisation is insufficient by itself to place unrelated Leads in one editorial decision scope.

A Lead may be context for several Work Items, but one exact Lead version must not have competing active disposition authorities without an explicit concurrency policy.

### Multi-topic inputs

A Triage Worker must not split one Lead into several authoritative events merely because the source text contains several topics. Multiple Signals require an approved deterministic or source-specific extraction contract. Otherwise triage may reject, watch, request re-extraction or request bounded supplemental discovery.

## Retrieval semantics

### Retrieval purpose

Retrieval narrows the prior history that triage should inspect. It may consider:

- exact Source Item, formal process, case, bill, warning, route or Agenda identifiers;
- explicit predecessor, replacement, follow-up and Watch Condition links;
- entity aliases across English and Chinese;
- numbers, dates, thresholds and reference periods;
- time, geography, route, institution and affected-population compatibility;
- lexical or semantic similarity;
- active or recent Event Hypotheses;
- open or recently admitted Story Candidates;
- relevant prior Story identities or publication references, without importing them as evidence; and
- known source dependencies or shared originating material.

### Retrieval order and limits

Exact and source-native relationships should be considered before approximate similarity where available. Retrieval remains bounded and records its query, versions, scope, watermark, candidate set, scores, match signals and known omissions.

The candidate set must preserve a valid `no adequate prior match` possibility. A high retrieval score does not compel association, and an empty result does not prove a new event.

### Score non-authority

Retrieval score, embedding similarity, shared token count, recency bonus, category match or model confidence may rank context only. None may independently:

- establish `same event` or `development of`;
- create or merge an Event Hypothesis;
- reject a Lead;
- admit a Candidate; or
- substitute for an explicit decision basis.

### Retrieval completeness and degraded operation

Retrieval Context declares whether exact identity lookup, current Candidate collision checking and advisory semantic retrieval completed.

- Failure of the authoritative current Candidate or identity collision check blocks Candidate admission.
- Failure of advisory semantic retrieval does not become `no match`.
- A potentially Urgent Work Item may proceed under a later-approved degraded policy only if exact identity and current Candidate collision checks succeed, incompleteness is explicit and later reconciliation is mandatory.
- Non-urgent work with materially incomplete retrieval normally retries or enters Operational hold.

Exact degraded-operation mechanisms and timings belong to Topic 9.

## Editorial triage dimensions

Triage assesses only whether evidence acquisition is likely justified. It does not verify the event.

For each decision Lead, the Triage Proposal addresses:

- accepted coverage basis or exclusion;
- likely substantive new information;
- likely reader utility or material impact;
- qualitative urgency;
- source role and known dependency;
- likely relationship to prior Event Hypotheses, Candidates or Stories;
- whether the Lead is only another report of an existing state;
- whether a changed state, correction, reversal or resolution is proposed;
- known contradictions and uncertainty;
- whether bounded supplemental discovery is justified; and
- the recommended Lead disposition.

A proposal may conclude that information is insufficient. It must not manufacture missing facts to avoid an uncertain result.

## Relationship semantics

The following semantic relationships are proposals about discovery-level hypotheses, not canonical event or factual relations. Topic 10 may select final labels.

### Same event state

The Lead likely reports the same specific occurrence, decision, announcement or formal-process state already represented, without a material new state.

Indicators may include compatible formal identifier, decision, actors, place, time, affected scope and action. Shared topic, party, organisation or policy area alone is insufficient.

Typical disposition: associate without a new Candidate, while retaining source-specific lineage and any useful dependency or corroboration information.

### Development of

The Lead likely concerns the same continuing event or formal process but proposes a materially new state, outcome, escalation, de-escalation, implementation, verdict, resignation, charge, effective change, resolution or other substantive development.

A development proposal identifies:

- the exact prior Event Hypothesis Version or Candidate context;
- the earlier state;
- the proposed new state or fact;
- why the difference may satisfy the accepted substantive-new-information test; and
- remaining uncertainty.

Another outlet, angle, summary, commentary or repeated background is not a development.

### Correction, clarification or reversal of

The Lead proposes that a prior state, figure, instruction, schedule or account was corrected, qualified, withdrawn or reversed.

This remains an unverified discovery relationship. It may justify a development or correction-oriented Candidate, but it cannot rewrite the prior Hypothesis, Candidate, Story or source history.

### Related but distinct

The Lead shares context, actors, geography or policy area with an earlier event but concerns a separate occurrence, decision, case, release or process instance.

It may justify a new Event Hypothesis and Candidate if likely material. It must not be absorbed into a broad existing event merely to reduce fragmentation.

### No adequate prior match

No retrieved prior hypothesis adequately represents the proposed occurrence or process. This permits, but does not force, a new Event Hypothesis proposal.

### Uncertain relationship

Available context cannot safely distinguish same state, development, correction, related event or new event. The Lead normally enters watch, supplemental discovery or Operational hold unless a clearly justified Candidate can preserve the uncertainty without creating a false relationship.

## Event Hypothesis decisions

### Creation

An Event Hypothesis may be created for a new-event Candidate, a development Candidate, or a retained watch case where grouping future Leads is useful. Creation is a deterministic committed decision over one exact proposal and Work Item.

### Association

A Lead may be associated with an existing Event Hypothesis without creating a Candidate. Association records whether the Lead is a same-state report, context, possible corroboration, source dependency or other permitted relationship.

### Versioning

Adding or removing contributing Leads, changing the proposed event state, changing a relationship or materially changing uncertainty creates a new Event Hypothesis Version.

### Consolidation

When two Hypotheses are later judged to represent the same underlying event or process, a consolidation decision creates an explicit successor, preferred continuation or equivalence relationship. It does not delete either predecessor, move their history silently or retarget an acknowledged Candidate Handoff.

### Split

When one Hypothesis incorrectly combines distinct occurrences or processes, a split decision creates successor Hypotheses and explicit lineage. Historical proposals, decisions, Leads and Candidates remain reconstructable.

### Published and handed-off history

A later grouping decision must not mutate the exact Event Hypothesis Version or Candidate Version already handed to Evidence Intake or used by a Story. Downstream systems receive later linked correction, consolidation or relationship records.

## Lead dispositions and Candidate formation

### Editorial reject

Triage may recommend rejection where likely coverage, utility, materiality or novelty is insufficient. The proposal cites its basis. Evidence failure is not asserted because evidence acquisition has not begun.

### Watch or defer

The Lead remains potentially useful but needs a defined transition, corroborating Lead, occurrence, deadline, source update or review condition. A valid Watch Condition is mandatory.

### Associate without Candidate

The Lead is linked to an existing Hypothesis or Candidate context but does not justify new evidence work. This is the normal outcome for same-state reports and repeated coverage.

### Supplemental discovery

The Lead needs one bounded, later-approved source check, reader-lead follow-up, operator check or search action. The action creates a new trigger and normal Signals; no result is appended directly to the Candidate.

### Operational hold

Required retrieval, policy, rights, model, capacity or integrity context is unavailable. Operational hold is not an editorial rejection or watch judgement.

### New-event Candidate

A new Candidate may be proposed where no adequate prior Event Hypothesis represents the likely event or formal process and likely scope, utility, materiality and novelty justify evidence acquisition.

No minimum number of Leads or domains is required at discovery. A single direct authority, operator or high-value radar Lead may justify evidence work, subject to normal uncertainty and evidence boundaries.

### Development Candidate

A development Candidate requires an exact prior Hypothesis or Candidate context and a proposed new state. The Candidate Version records the earlier state, proposed change, contributing Leads and evidence questions. Later evidence must satisfy `EVID-046`; discovery does not claim that it already has.

### Correction-oriented Candidate

A correction, clarification, withdrawal or reversal may justify a Candidate where readers may need the changed state. The prior state and proposed correction remain explicit and unverified.

### Several Leads, one Candidate

Several Leads may support one Candidate only when they plausibly concern the same event or development hypothesis. Each Lead retains its own source lineage and disposition. Unrelated Leads cannot be combined because they share a batch, category or publisher.

### One Lead and several possible events

A single Lead normally receives one disposition in one Work Item. It cannot be authoritatively split into several Candidates without distinct Signals from an approved extraction contract. It may remain context-only for several later hypotheses.

### Existing Candidate supplementation

A same-state Lead may be associated as non-contributing context without changing the Candidate Version. If a Lead materially changes the Event Hypothesis, evidence objective, urgency or uncertainty, a new Candidate Version and, where required, a new Handoff are created under the accepted record semantics.

## Triage Proposal contract

Every Triage Proposal is immutable, untrusted and tied to one exact Work Item and Retrieval Context. It must:

- identify every decision Lead exactly once;
- distinguish context-only Leads;
- recommend one allowed disposition per decision Lead;
- identify any proposed Event Hypothesis and relationship targets;
- cite the exact input Leads, fields and match or contradiction signals used;
- state likely new information and materiality basis without presenting them as verified;
- list uncertainty, missing context and retrieval incompleteness;
- include a Watch Condition or bounded supplemental action where applicable;
- include the minimum Candidate manifest where admission is proposed;
- avoid factual claims, identities, numbers, causal links and relationships absent from permitted input; and
- follow a versioned structured schema.

A free-form explanation, batch-level label or confidence number alone is not a valid proposal.

## Deterministic proposal validation

Before committing any disposition, Event Hypothesis decision or Candidate admission, the controller validates:

- Work Item, Lead and Retrieval Context identities and versions;
- that every decision Lead has exactly one allowed route;
- that context-only Leads are not mutated;
- that proposed relationship targets were supplied or are explicitly proposed as new;
- coverage, rights and policy preconditions;
- schema, size and allowed-value constraints;
- Candidate minimum manifest and accepted urgency;
- exact current Candidate collision and stale-state checks;
- that no evidence or verification authority is claimed;
- that no omitted Lead, invented identifier or unapproved supplemental action appears; and
- that the proposal remains current at commit time.

Invalid or stale proposals produce no workflow transition. They may be retried, repaired or routed to an approved fallback.

## Urgency and Planned handling

### Potentially Urgent Leads

Potentially Urgent Leads receive an isolated or expedited Work Item and do not wait for an unbounded Routine batch. Directly related peer Leads already available may be included, but grouping wait must not become an artificial delay.

Urgency does not lower scope, novelty, relationship or Candidate-admission requirements. It may justify degraded advisory retrieval only under the guarded rule above.

### Time-sensitive and Planned Leads

Time-sensitive and Planned work preserves deadlines, expected windows, time zones and Watch Conditions. Batching cannot cause a Lead to pass its relevant action or confirmation window without a visible operational outcome.

An Agenda Item or missed-expectation finding alone is not a decision Lead unless a normal Signal and Lead exists. Occurrence Leads may carry Agenda context through Retrieval Context.

### Routine Leads

Routine Leads may wait for efficient bounded execution batches, subject to fairness and starvation controls defined later.

## Model, worker and fallback behaviour

### Deterministic resolution without a model

A Work Item may be resolved without a model only where an accepted deterministic triage rule fully determines the route and requires no editorial inference. Exact duplicate suppression and already-committed identity outcomes are examples; materiality and event relationship are not presumed deterministic merely for cost saving.

### Model-assisted triage

Models receive only the permitted Work Item and Retrieval Context. Retrieved source text is untrusted data, not instruction. Model output is a Triage Proposal and has no direct write capability.

### Confidence

A confidence field may be retained as model metadata, but no confidence threshold alone may approve, reject, merge, create a development or force a new event. Decision basis and deterministic preconditions remain required.

### Timeout, refusal and invalid output

Timeout, missing response, refusal, malformed output and schema failure create no editorial disposition or Candidate. The same Work Item may be retried or sent to an approved fallback while retaining attempt history.

### Conflicting proposals

Multiple proposals may be collected for evaluation or fallback. Conflict does not resolve automatically by majority vote or highest confidence unless a later accepted policy defines and evaluates that method. Unresolved conflict becomes retry, watch, supplemental discovery or Operational hold.

### Urgent worker failure

Potentially Urgent work cannot be silently dropped when a model is unavailable. It must use an approved alternate worker, bounded operator path or retained Operational hold. Urgency alone never authorises automatic Candidate admission.

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

**TRI-014 — Urgent batching guard.** Urgent work MUST NOT wait merely to fill a routine batch.

**TRI-015 — Grouping basis.** Category, publisher, topic or one shared entity MUST NOT alone place Leads in one editorial grouping scope.

**TRI-016 — Concurrent ownership.** Competing active disposition authority over one exact Lead version MUST be prevented or surfaced explicitly.

**TRI-017 — Multi-topic split guard.** Triage MUST NOT create several authoritative events from one Lead without distinct Signals produced under an approved extraction contract.

### Retrieval

**TRI-020 — Retrieval context only.** Retrieval generates bounded context and MUST NOT establish event identity or disposition.

**TRI-021 — Exact before approximate where available.** Source-native, formal-process and explicit lineage relationships SHOULD precede approximate similarity.

**TRI-022 — Bounded inspectable retrieval.** Retrieval MUST record query, scope, version, watermark, candidates, scores, signals and known omissions.

**TRI-023 — No-match option.** Retrieval MUST preserve the possibility that no prior hypothesis is adequate.

**TRI-024 — Empty retrieval is not new event.** No candidate returned MUST NOT force a new Event Hypothesis or Candidate.

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

**TRI-036 — No-candidate validity.** Reject, watch, association and hold are valid outcomes and no quota may override them.

### Event relationships and Hypotheses

**TRI-040 — Same-state test.** Same-event-state association requires compatible specific occurrence or process-state signals; shared subject alone is insufficient.

**TRI-041 — Development test.** A development proposal MUST identify exact prior context, earlier state, proposed new state and likely substantive difference.

**TRI-042 — Repetition is not development.** Another source, angle, recap, commentary or unchanged background MUST NOT be classified as a development solely for freshness.

**TRI-043 — Correction relationship.** Correction, clarification, withdrawal and reversal remain explicit unverified relationships and do not rewrite prior history.

**TRI-044 — Related but distinct protection.** A separate occurrence or process instance MUST NOT be absorbed into a broad prior event because of shared actors or topic.

**TRI-045 — New hypothesis not forced.** No adequate prior match permits but does not require new Hypothesis creation.

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

**TRI-057 — Candidate supplementation.** Non-material same-state association need not version a Candidate; material hypothesis, urgency, uncertainty or objective change does.

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

**TRI-083 — Cross-language and source-dependency slices.** Evaluation MUST include English, Chinese and mixed-language grouping and shared-origin media or official dependencies.

**TRI-084 — Urgent and failure slices.** Evaluation MUST include urgent queueing, retrieval incompleteness, invalid model output, timeout and fallback behaviour.

**TRI-085 — Current v1 evaluation insufficient.** The existing clustering dataset MUST NOT be treated as sufficient production evidence because it does not independently label development versus new event.

## Acceptance criteria

1. Five Work Items may share one model call without being treated as one event.
2. Every decision Lead receives one disposition; context-only Leads are unchanged.
3. Empty retrieval does not force new-event creation.
4. A high similarity score cannot merge two separate incidents involving the same organisation.
5. A second outlet repeating the same announcement associates with the same state and creates no Candidate solely because it is fresh.
6. A later verdict in the same case may become a development Candidate only with the prior and proposed new state identified.
7. A corrected official deadline may become a correction-oriented Candidate without overwriting the earlier Lead or Candidate.
8. Two incidents at the same place on different dates remain distinct unless specific evidence supports one continuing event.
9. A broad political topic cannot absorb separate bills, court cases or statements into one Event Hypothesis.
10. Several Leads about one warning escalation can support one Candidate with all source lineage.
11. One multi-topic briefing cannot be split into several Candidates by a model without distinct approved Signals.
12. A model timeout creates no reject, association or Candidate.
13. Model confidence below or above a threshold cannot by itself force new event, development or merge.
14. An Urgent Lead does not wait for a Routine batch but still passes the same Candidate requirements.
15. Advisory retrieval failure is not represented as no match; Candidate admission still requires exact collision checks.
16. Consolidating two duplicate Hypotheses preserves both predecessors and every acknowledged Handoff.
17. Splitting a snowball Hypothesis preserves historical decisions and creates explicit successors.
18. A same-state Lead may be associated without changing a Candidate Version; a materially changed hypothesis creates a new version.
19. Agenda context can help link an occurrence but cannot itself create a triage Lead.
20. Topic 8 can independently score same-state, development, related, new and uncertain outcomes rather than collapsing development into new event.

## Owner decisions required to complete Topic 6

The Draft recommends these decisions:

1. Accept the separation between Triage Work Item, Triage Execution Batch and editorial event grouping.
2. Accept decision Leads versus context-only Leads, with one explicit disposition for every decision Lead and no mutation of context-only Leads.
3. Accept bounded inspectable retrieval as context only; empty retrieval does not force a new event, and score or confidence is never decision authority.
4. Accept a mandatory exact current Candidate and identity collision check separate from advisory semantic retrieval.
5. Accept the proposed relationship set: same event state, development of, correction or reversal of, related but distinct, no adequate prior match and uncertain relationship.
6. Accept that same event relationship and Candidate creation are orthogonal: same-state repetition normally associates without a Candidate, while a materially new state may create a development Candidate.
7. Accept explicit earlier-state and proposed-new-state requirements for every development Candidate.
8. Accept Event Hypothesis creation, association, versioning, consolidation and split as deterministic, append-only decisions with no destructive merge.
9. Accept one coherent Candidate from several Leads with complete lineage, while unrelated Leads in one batch remain separate and a multi-topic Lead cannot be model-split without distinct Signals.
10. Accept that Candidate formation has no minimum source or domain count at discovery; evidence authority and corroboration remain downstream.
11. Accept expedited Urgent Work Items without lower editorial or admission standards, and guarded degraded advisory retrieval only when exact collision checks succeed and later reconciliation is required.
12. Accept structured per-Lead Triage Proposals, deterministic validation, confidence as non-authoritative metadata, and neutral handling of timeout, refusal, malformed output and disagreement.
13. Accept that non-material association need not version an existing Candidate, while material hypothesis, urgency, uncertainty or evidence-objective change creates a new Candidate Version.
14. Accept that Topic 8 must replace or extend the current clustering evaluation to distinguish relationship and route classes, including false merge, snowball, fragmentation and false development.
