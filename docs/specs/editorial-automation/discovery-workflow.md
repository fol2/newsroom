# Discovery workflow specification

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Accepted by owner:** 2026-07-15  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted coverage contract:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md)  
**Related discovery specification:** [`news-discovery.md`](news-discovery.md)  
**Supersedes:** None

## Purpose

Define the end-to-end workflow that takes an authorised discovery trigger through source checking, change detection, deterministic gates, lead triage and Story Candidate hand-off into governed evidence acquisition.

The workflow distinguishes no news from system failure, preserves potentially relevant ambiguity, prevents models from authorising their own output and ensures that discovery never becomes publication evidence merely because a source changed.

## Scope

This specification covers:

- semantic actors and decision authority;
- the lifecycle from trigger and source check to Discovery Signal, News Lead and Story Candidate;
- qualitative urgency routing and backpressure behaviour;
- model-assisted triage as an untrusted proposal step;
- Story Candidate admission and evidence-intake hand-off;
- retry, quarantine, stale-work, crash-replay and fail-closed behaviour; and
- feedback from evidence acquisition into discovery.

It does not define:

- the final identity, immutability or storage schema of each record; Topic 3 owns those semantics;
- concrete source roles or source selection; Topic 4 owns those decisions;
- exact new, revised, deleted, cancelled, rescheduled or state-transition semantics; Topic 5 owns those decisions;
- exact retrieval algorithms, batch composition, model prompts or event-grouping rules; Topic 6 owns those decisions;
- search roles, providers or budgets; Topic 7 owns those decisions;
- shadow metrics and release thresholds; Topic 8 owns those decisions;
- polling intervals, retry budgets, alert thresholds or operational tooling; Topic 9 owns those decisions;
- numeric scoring, ranking weights or final reason-code strings; Topic 10 owns those decisions; or
- evidence extraction, claim admission, drafting, validation or publication.

## Workflow principles

1. **Coverage precedes workflow.** A trigger or signal is evaluated against the accepted coverage contract; the workflow does not broaden product scope.
2. **Change precedes editorial work.** A successful unchanged check ends without a model call or News Lead.
3. **Operational truth stays distinct from editorial judgement.** Transport, parser, rights, policy and configuration failures are not no-news outcomes and are not editorial rejections.
4. **Ambiguity preserves recall.** Deterministic code may reject only what accepted rules establish without editorial inference. Ambiguous materiality or relevance proceeds to triage.
5. **Models propose; deterministic authority commits.** A model or agent may recommend a route but cannot mutate authoritative workflow state, create evidence or publish.
6. **Discovery is not evidence.** Signals, leads, triage proposals and Story Candidates carry hypotheses and lineage, not verified claims.
7. **At-least-once delivery must produce at-most-once semantic transitions.** Retrying a check or task must not create duplicate leads or candidates.
8. **Failures remain visible.** Timeouts, exhausted retries, quarantine and unavailable downstream services cannot silently discard work.

## Semantic actors

These are responsibility boundaries, not required deployment services. One implementation process may perform several roles provided it preserves the authority separation.

### Trigger Controller

Determines that an approved discovery path is due or has received an authorised event. Possible trigger types include scheduled checks, Planned Agenda windows, webhooks, approved manual inputs and later-approved radar or search activity.

The Trigger Controller creates work; it does not decide that news exists.

### Discovery Controller

The deterministic authority for discovery workflow transitions. It validates policy, rights, versions, identities, allowed routes and state preconditions before committing a Check Outcome, Discovery Signal, News Lead, triage outcome or hand-off state.

The Discovery Controller may be implemented through several deterministic components, but generative agents and models are outside this authority boundary.

### Source Adapter

Uses one approved access method to check a source or input channel, parse the permitted response and return a structured Check Outcome proposal. It does not decide newsworthiness or commit workflow state.

### Deterministic Gate Evaluator

Applies versioned integrity, identity, duplication, observable-newness, time-validity and unambiguous scope or exclusion rules before model work.

### Event Retrieval Component

Finds bounded candidate prior events or developments that may relate to one or more News Leads. Retrieval results are proposals for triage context, not authoritative event identity.

### Triage Worker

Assesses likely scope, utility, materiality, novelty, urgency and event relationship. It may be model-assisted or deterministic as later accepted. Its output is an untrusted Triage Proposal.

### Candidate Admission Controller

Deterministically validates an allowed Triage Proposal and either commits a permitted non-candidate outcome or admits one Story Candidate with complete lineage and hand-off data.

### Evidence Intake

Accepts an admitted Story Candidate into the separately governed evidence-acquisition workflow. Intake acknowledgement does not mean that evidence is sufficient or that the candidate will become a story.

### Authorised Operator

May resolve quarantines, policy conflicts or explicitly reviewable operational holds under later accepted permissions. Operator actions must be authenticated and audited and may not bypass coverage, rights, evidence or publication rules.

## Functional workflow artefacts

Topic 3 defines their stable identity and immutability. This workflow uses the following functional artefacts:

- **Check Attempt:** one authorised attempt to inspect one configured source scope or input channel under exact adapter, policy and rights versions.
- **Check Outcome:** the recorded result of a Check Attempt, including unchanged, observable change, partial or degraded result, blocked preflight or failure.
- **Discovery Signal:** one normalised candidate new item, revision or other later-approved observable source transition produced by a successful or explicitly partial check.
- **News Lead:** a Discovery Signal that survived the applicable deterministic gates and is eligible for editorial triage.
- **Triage Work Item:** one bounded unit containing one or more News Leads, lineage, coverage and urgency context, and retrieved event candidates.
- **Triage Proposal:** an untrusted recommended route produced by a Triage Worker.
- **Story Candidate:** an admitted hypothesis that one or more News Leads may justify governed evidence acquisition.
- **Evidence Handoff:** the exact candidate version and lineage submitted to Evidence Intake.
- **Operational Finding:** a visible source, adapter, policy, rights, queue or downstream failure that requires retry, quarantine, remediation or operator attention.

These names do not require one database table per artefact.

## End-to-end flow

```text
approved trigger
    |
    v
preflight: coverage path + source config + rights + versions + budget
    | blocked --------------------------------------> Operational Finding
    v
Check Attempt -> Source Adapter -> Check Outcome
    | unchanged ------------------------------------> terminal no-work
    | failed/invalid --------------------------------> retry, degrade or quarantine
    | observable change candidates
    v
normalise + stable identity + Discovery Signal admission
    | duplicate/already processed ------------------> terminal deduplicated
    | operationally incomplete ---------------------> blocked or quarantine
    | clearly excluded by accepted deterministic rule -> terminal reject
    v
News Lead
    |
    +--> Urgent lane when potentially urgent
    +--> Time-sensitive / Planned / Routine queue
    v
event retrieval + bounded Triage Work Item
    v
Triage Proposal
    | invalid/stale ---------------------------------> no state change; retry/re-evaluate
    | reject ----------------------------------------> terminal editorial reject
    | watch/defer -----------------------------------> retained pending a defined trigger
    | associate without new candidate --------------> terminal association outcome
    | approved supplemental discovery --------------> new trigger through same workflow
    | new event/development candidate
    v
Candidate Admission Controller -> Story Candidate
    v
Evidence Handoff
    | Evidence Intake unavailable ------------------> retained pending retry
    v
evidence-acquisition acknowledgement
    |
    +--> evidence workflow continues independently
    +--> structured feedback may return without rewriting history
```

## Semantic outcome distinctions

The labels below describe required distinctions. Topic 10 may choose final enum and reason-code names.

### Check Attempt outcomes

| Semantic outcome | Meaning | Downstream effect |
|---|---|---|
| Preflight blocked | Required coverage mapping, configuration, rights, policy, credential, budget or version is invalid or unavailable | No source access or model work; create an Operational Finding |
| Successful unchanged | The adapter contract completed and detected no candidate new or revised source state | End silently; no Discovery Signal and no model call |
| Successful with observable changes | The adapter contract completed and returned one or more candidate source changes | Normalise and attempt Discovery Signal admission |
| Partial or degraded | Some independently valid outputs are available but the check is known incomplete | Admit only independently valid signals; retain a visible Operational Finding and incompleteness marker |
| Retryable failure | A transient transport, provider, credential-refresh or downstream condition prevented a valid result | Retain attempt context and retry under policy |
| Quarantined or disabled | The adapter or source no longer satisfies its contract or permission | No further automatic processing until authorised recovery |

### Discovery Signal outcomes

| Semantic outcome | Meaning |
|---|---|
| Admitted | Stable enough to evaluate through deterministic gates |
| Deduplicated | The same source item or revision has already produced the same semantic transition |
| Operationally blocked | Identity, parsing, rights, version or policy integrity is insufficient |
| Deterministically excluded | An accepted non-editorial rule clearly establishes an exclusion |
| Promoted to News Lead | The signal survived all applicable deterministic gates, including ambiguous cases retained for triage |

### News Lead outcomes

| Semantic outcome | Meaning |
|---|---|
| Queued | Awaiting bounded triage in the appropriate urgency lane |
| Operational hold | Triage cannot safely proceed because required context, policy, tools or capacity are unavailable |
| Editorial reject | Triage establishes insufficient likely scope, utility, materiality or novelty |
| Watch or defer | The lead remains potentially relevant but needs a defined later trigger, update or corroborating lead before candidate admission |
| Associated without candidate | The lead likely relates to an existing event but does not contain enough new information to create a new Story Candidate |
| Supplemental discovery requested | A later-approved bounded discovery action is needed; its result re-enters as new signals and does not bypass gates |
| Story Candidate admitted | One new or development candidate has been deterministically admitted from the proposal |

### Story Candidate hand-off outcomes

| Semantic outcome | Meaning |
|---|---|
| Handoff pending | Candidate is admitted but Evidence Intake has not acknowledged receipt |
| Intake acknowledged | The exact candidate version is durably accepted for evidence work |
| Returned for discovery follow-up | Evidence work identifies a permitted need for additional public-source discovery |
| Closed without evidence progression | Evidence work finds the candidate duplicate, unsupported, out of scope or otherwise unable to proceed |

Closing or returning a candidate must not erase the candidate, its leads or the original decision record.

## Requirements

### Authority and ordering

**FLOW-001 — Accepted coverage contract.** Every trigger, deterministic gate, triage route and Story Candidate MUST identify the applicable accepted coverage obligation, best-effort class or other permitted basis. The workflow MUST NOT convert an explicit deferred gap or out-of-scope class into an active obligation by configuration alone.

**FLOW-002 — Deterministic transition authority.** Only the deterministic Discovery Controller and Candidate Admission Controller MAY commit workflow transitions. A source adapter, model, agent, retrieval component or search provider MUST NOT directly create an authoritative News Lead, Story Candidate or evidence record.

**FLOW-003 — Untrusted model output.** Model-assisted triage output MUST be treated as a proposal. It MUST pass schema validation, allowed-route validation, state-precondition checks and policy enforcement before any transition is committed.

**FLOW-004 — No discovery publication authority.** No discovery actor or artefact may authorise drafting, evidence admission or publication. Discovery credentials and tools MUST NOT include a public publishing credential.

**FLOW-005 — Version capture.** Every material transition MUST record the applicable coverage, policy, rights, adapter, gate, retrieval, triage and validator versions or immutable references needed to reconstruct the decision.

### Trigger and preflight

**FLOW-010 — Approved trigger only.** A Check Attempt MUST originate from a configured and later-approved trigger path. An agent MUST NOT create an unbounded recurring trigger merely because a source, query or tool is available.

**FLOW-011 — Preflight before access.** Before source access, the workflow MUST validate the applicable source or channel configuration, coverage role, rights decision, credentials, adapter version and enforced budget or rate limit where applicable.

**FLOW-012 — Preflight failure.** Missing or conflicting preflight authority MUST block the affected check and create a visible Operational Finding. It MUST NOT silently activate another source, broader query, weaker rights assumption or unapproved provider.

**FLOW-013 — No model in the collection pre-check.** Triggering, preflight, source checking, parsing and unchanged detection MUST be capable of completing without invoking a model. A model MUST NOT be woken merely to decide whether the source changed.

**FLOW-014 — Planned expectation is not occurrence.** A Planned Agenda trigger MAY open or adjust a monitoring window but MUST NOT create a News Lead or Story Candidate solely because an event was scheduled.

**FLOW-015 — Channel-neutral entry.** A later-approved manual, reader, media, operator, webhook, radar or search input MUST enter through the same Signal, gate, Lead and triage boundaries. No input channel receives an evidence or candidate bypass.

### Source checking and Check Outcomes

**FLOW-020 — Check Attempt record.** Every source access attempt MUST have an inspectable start, source scope, trigger, adapter version and terminal or retained outcome.

**FLOW-021 — Successful unchanged terminal.** A successful unchanged check MUST end without a Discovery Signal, News Lead, triage task or model call.

**FLOW-022 — Observable change output.** A successful changed check MAY produce zero, one or many candidate changes. The adapter MUST preserve enough source lineage to distinguish the outputs without deciding editorial materiality.

**FLOW-023 — Failure is not no news.** Timeout, transport failure, malformed content, parser failure, authentication failure, rights failure, rate-limit failure and quarantine MUST NOT be represented as a successful unchanged check.

**FLOW-024 — Partial-result honesty.** A partial result MAY emit independently valid candidate changes only when the adapter contract can prove their boundaries. The Check Outcome MUST remain marked incomplete, and the missing portion MUST create an Operational Finding. Otherwise the check fails as a whole.

**FLOW-025 — Explicit baseline policy.** First-run or reset baselining MUST use a later-approved, source-specific policy. The workflow MUST NOT silently emit an entire historical feed as current news or silently discard a required active-coverage window.

**FLOW-026 — Minimum necessary collection.** Discovery checking SHOULD retrieve and retain only the content permitted and necessary for source identity, observable-change detection, deterministic gates, triage and audit. Evidence acquisition remains separate.

### Discovery Signal admission and deterministic gates

**FLOW-030 — Signal admission.** Each candidate change MUST pass deterministic source-item or revision identity checks before it becomes an admitted Discovery Signal.

**FLOW-031 — Idempotent signal transition.** Repeating the same Check Attempt, provider delivery or source revision MUST produce at most one equivalent downstream semantic transition.

**FLOW-032 — No silent historical mutation.** A later observation or correction MUST create a new transition or relationship to prior work; it MUST NOT silently rewrite the earlier Check Outcome, Signal, Lead, proposal or Candidate. Topic 3 defines the exact identity model.

**FLOW-033 — Deterministic gate boundary.** Before model work, the workflow MUST evaluate adapter integrity, stable identity, exact or rule-defined duplication, observable newness, time and version validity, and any accepted scope or exclusion rule that requires no editorial inference.

**FLOW-034 — Ambiguous relevance survives.** Uncertainty about likely materiality, cross-geography effect, event relationship, novelty or another editorial judgement MUST NOT be used as a deterministic rejection. The signal MUST be promoted to a News Lead or placed in an explicit operational hold if safe triage is impossible.

**FLOW-035 — Clear exclusions.** A deterministic rejection MUST cite an accepted rule that unambiguously applies to the available metadata. Keyword absence, low media volume, lack of multiple domains or low model confidence MUST NOT by themselves create such a rejection.

**FLOW-036 — Duplicate suppression.** Exact or accepted rule-defined duplicates MUST be suppressed before triage while retaining lineage and occurrence information needed for audit and source-health analysis.

**FLOW-037 — Integrity block.** A signal with unresolved identity collision, corrupted extraction, prohibited rights state or missing required lineage MUST be blocked rather than promoted, rejected as editorially weak or submitted to a model.

### News Lead queueing and urgency

**FLOW-040 — Lead creation.** A Discovery Signal becomes a News Lead only after every applicable deterministic gate passes or preserves an editorial ambiguity for triage.

**FLOW-041 — Qualitative urgency route.** Each News Lead MUST carry the best supported Urgent, Time-sensitive, Planned or Routine workflow hint from the accepted coverage contract. Uncertainty MUST NOT silently demote a potentially urgent safety or public-health lead to Routine.

**FLOW-042 — Urgent isolation.** A potentially Urgent lead MUST have a route that does not require it to wait behind an unbounded Routine backlog or a fixed routine batch. Topic 6 defines the exact flush and grouping policy.

**FLOW-043 — No silent queue drop.** Capacity limits, provider outages and backpressure MUST retain a visible lead or Operational Finding. The system MUST NOT discard a lead merely because a batch, queue or model limit is reached.

**FLOW-044 — Non-urgent fairness.** Time-sensitive, Planned and Routine work MAY be batched, but the workflow MUST prevent indefinite starvation and MUST preserve deadline or expected-release context.

**FLOW-045 — Bounded work item.** Every Triage Work Item MUST be bounded in number and content size and MUST identify every included lead. Exact batch formation is deferred to Topic 6.

### Event retrieval and triage

**FLOW-050 — Retrieval is context, not authority.** Event Retrieval MAY provide candidate prior events, stories or developments with match signals. Retrieval MUST NOT itself merge events, classify a development or create a Story Candidate.

**FLOW-051 — Triage input contract.** Triage MUST receive the relevant lead metadata, source lineage, accepted coverage basis, urgency context, observable-change information, known prior-event candidates and explicit incompleteness or operational warnings.

**FLOW-052 — Permitted Triage Proposal routes.** A Triage Proposal MAY recommend only an allowed route: editorial reject; watch or defer; associate without a new candidate; request a later-approved bounded supplemental discovery action; propose a new-event Story Candidate; propose a development Story Candidate; or retain an operational hold. Topic 6 may refine these routes without weakening the evidence boundary.

**FLOW-053 — Proposal basis.** A proposal MUST identify which input leads and available facts support its recommended route and which material questions remain uncertain. It MUST NOT add a factual claim, identity, number, causal link or event relationship absent from the permitted input.

**FLOW-054 — Proposal validation.** Invalid, stale, out-of-contract or policy-conflicting proposals MUST create no workflow transition. They MAY be retried, repaired or sent through an authorised fallback, but timeout or invalid output MUST NOT count as rejection or approval.

**FLOW-055 — No-candidate is valid.** A News Lead MAY end without a Story Candidate because it is duplicate, non-material, insufficiently new, out of scope after editorial judgement or appropriately retained for watch. No quota may force candidate creation.

**FLOW-056 — Many-to-one candidate formation.** Several News Leads MAY support one Story Candidate. The admitted candidate MUST retain lineage to every contributing lead, while unrelated leads MUST NOT be combined merely to fill a batch.

**FLOW-057 — Supplemental discovery loops through gates.** A request for another source check, reader-lead follow-up, radar action or later-approved search MUST create a new authorised trigger. Its outputs MUST re-enter as Discovery Signals and MUST NOT be appended directly as evidence or unvalidated candidate content.

**FLOW-058 — Risk hints do not waive later gates.** Triage MAY attach sensitive-content, rights, legal, source-conflict or verification hints for Evidence Intake. Such hints neither establish the risk nor authorise publication.

### Story Candidate admission

**FLOW-060 — Candidate minimum hand-off content.** A Story Candidate MUST include, at minimum:

- the accepted coverage obligation or best-effort basis;
- every contributing News Lead and Discovery Signal lineage reference;
- a concise event or development hypothesis, explicitly labelled as unverified;
- the proposed geography, category and qualitative urgency;
- the likely substantive new information or change that justifies evidence work;
- the likely reader utility or materiality basis;
- known uncertainties, conflicts, missing primary material and operational limitations;
- the bounded evidence-acquisition objective or questions to resolve; and
- the policy, triage, retrieval and admission versions that produced it.

Topic 3 defines stable identities and Topic 6 may refine event-relationship fields.

**FLOW-061 — Candidate admission validation.** The Candidate Admission Controller MUST verify that the proposal uses an allowed route, references current leads, satisfies the accepted coverage contract, contains the minimum hand-off content and does not claim evidence or publication authority.

**FLOW-062 — Candidate is a hypothesis.** A Story Candidate MUST NOT label central facts as verified, convert source metadata into a Source Observation or imply that an evidence gate has passed.

**FLOW-063 — Candidate duplication control.** Concurrent or repeated triage of equivalent leads MUST NOT admit duplicate semantic Story Candidates. A conflict or uncertain match MUST be retained for resolution rather than silently creating or merging authority.

**FLOW-064 — Candidate versioning.** A material change to contributing leads, event hypothesis, urgency, evidence objectives or known uncertainty after admission MUST create a new candidate version or superseding record rather than silently mutating the hand-off already accepted by Evidence Intake.

**FLOW-065 — Stale-work revalidation.** A proposal created under an outdated coverage, policy, rights, source, triage or event state MUST be revalidated before candidate admission.

### Evidence hand-off and feedback

**FLOW-070 — Durable hand-off acknowledgement.** A Story Candidate is not considered handed off until Evidence Intake acknowledges the exact candidate version and idempotency identity.

**FLOW-071 — Intake unavailability.** If Evidence Intake is unavailable or returns an ambiguous outcome, the candidate MUST remain in a visible handoff-pending state and be retried idempotently. It MUST NOT be recreated, dropped or treated as evidence accepted.

**FLOW-072 — Independent evidence acquisition.** Evidence Intake MUST independently retrieve and govern the current permitted source material required to create Source Observations and an Evidence Package. It MUST NOT reuse a Discovery Signal or search snippet as evidence merely because discovery retained it.

**FLOW-073 — Structured feedback.** Evidence acquisition SHOULD return a structured outcome sufficient to distinguish intake accepted, duplicate or merged candidate, insufficient public evidence, out-of-scope finding, rights block, stale candidate, candidate closed and permitted request for supplemental discovery. Exact evidence states belong to the evidence specification.

**FLOW-074 — Feedback preserves history.** Evidence feedback MUST NOT rewrite the original Check Outcome, Signal, Lead, proposal or Candidate. It creates a later linked outcome that may inform quality evaluation, coverage review or a new discovery trigger.

**FLOW-075 — Supplemental evidence request boundary.** When evidence work needs additional public-source discovery, it MUST submit a bounded request through an approved trigger path. The discovery workflow MUST NOT contact private persons, solicit leaks or obtain private documents.

### Failure, retry and recovery

**FLOW-080 — Timeout neutrality.** A timeout or missing response at any stage MUST NOT be interpreted as unchanged, rejected, approved, handed off or completed.

**FLOW-081 — Retry preserves identity.** A retry MUST retain the semantic identity and version context of the original Check Attempt, Signal, Lead, Triage Work Item, Candidate or Evidence Handoff as applicable.

**FLOW-082 — Quarantine boundary.** Repeated parser-contract failure, unexplained source-shape drift, rights conflict or unsafe adapter behaviour MUST support quarantine of the affected source or adapter scope. Quarantine blocks new automatic work but preserves existing records and unrelated sources.

**FLOW-083 — Exhausted retry remains visible.** Exhausting a later-configured retry budget MUST create a durable Operational Finding or retained hold. It MUST NOT silently discard work or convert the failure into an editorial outcome.

**FLOW-084 — Crash-safe replay semantics.** A crash after source access, model invocation or downstream submission MUST be recoverable without duplicate semantic transitions. External calls that may have succeeded ambiguously require reconciliation or idempotent retry rather than blind duplication.

**FLOW-085 — Policy change during queued work.** Queued or in-progress work created under an older accepted policy or component version MUST be revalidated or explicitly handled under a compatibility rule before a later transition commits.

**FLOW-086 — Fail closed by affected scope.** Missing authority, rights, integrity, lineage or required policy MUST block only the affected scope where isolation is safe. It MUST NOT weaken gates globally or silently continue with incomplete authority.

**FLOW-087 — Audited operator recovery.** Manual retry, requeue, quarantine release, override of an operational hold or closure MUST record the actor, authority, reason, affected identity and before-and-after state. No operator action may turn discovery material into evidence or bypass a mandatory rejection.

### Concurrency and ordering

**FLOW-090 — One committed transition.** Concurrent workers MAY process the same at-least-once delivery, but only one valid transition for a given state version and semantic identity may commit.

**FLOW-091 — No implementation lock-in.** This specification does not require a particular queue, lease, database transaction or fencing mechanism. Topic 12 must select mechanisms that prove FLOW-090 and crash-safe replay.

**FLOW-092 — Ordered lineage.** A downstream transition MUST reference the exact committed upstream versions it consumed. It MUST NOT advance from an uncommitted, superseded or incompatible proposal.

**FLOW-093 — Work isolation.** Failure or quarantine of one source, adapter, batch, model provider or evidence hand-off MUST NOT corrupt unrelated committed work. Broader pause behaviour belongs to Topic 9 and the autonomy controls.

### Inspectability and feedback

**FLOW-100 — Inspectable path.** For any Story Candidate or terminal lead outcome, an operator MUST be able to reconstruct the trigger, Check Attempt, Check Outcome, Signals, deterministic gates, contributing Leads, retrieval context, Triage Proposal, validation and committed route.

**FLOW-101 — Operational and editorial outcomes remain separate.** Monitoring and evaluation MUST be able to distinguish operational blocks and failures from deterministic exclusions, editorial rejections, watch outcomes, associations and candidate admissions.

**FLOW-102 — Coverage feedback.** A relevant development found through another permitted path, or an evidence-stage finding that discovery systematically missed an accepted obligation, MUST be eligible to create a Coverage Gap under the accepted coverage contract.

## Acceptance criteria

1. A successful unchanged source check ends without a Discovery Signal, News Lead, Triage Work Item or model call.
2. A parser timeout creates a retryable failure or Operational Finding and cannot appear as no news.
3. One feed check returning five genuinely new items can create five Signals without five unconditional model calls.
4. Replaying the same source item and revision does not create a second semantic Lead or Candidate.
5. An ambiguous warning that may affect public safety survives deterministic gates and enters triage rather than being dropped for low confidence.
6. A clearly ordinary sports result can be deterministically excluded under the accepted coverage contract, while a stadium evacuation enters through safety coverage.
7. A potentially Urgent lead is not held behind an unbounded Routine batch.
8. A model may recommend a development candidate, but no Candidate exists until deterministic validation and admission succeed.
9. Invalid model JSON, model timeout or model refusal produces no rejection or candidate transition.
10. Several reports of one development may form one Candidate with all lead lineage; unrelated reports in the same batch cannot be combined.
11. Evidence Intake downtime leaves the exact Candidate hand-off pending and retryable without recreating the Candidate.
12. Evidence acquisition independently retrieves source material and cannot promote a search snippet or Signal into an Evidence Package.
13. Evidence-stage rejection or closure leaves the original Candidate and discovery decisions traceable.
14. A coverage or policy version change while work is queued forces revalidation before a later transition commits.
15. Quarantining one broken source does not turn its failures into unchanged checks and does not block unrelated healthy sources unless a broader accepted pause applies.
16. An isolated relevant miss can create a Coverage Gap, while a systemic inability to cover an Active class can block launch under COV-045.

## Completion record

The product owner accepted this workflow on 2026-07-15 with the following decisions:

- the deterministic Discovery Controller and Candidate Admission Controller are the only authorities that commit discovery workflow transitions; models and agents produce proposals only;
- the Check Attempt and Check Outcome boundary distinguishes unchanged, observable change, partial result, failure and quarantine before any Discovery Signal exists;
- editorial ambiguity survives deterministic gates and normally becomes a News Lead rather than a deterministic rejection;
- permitted News Lead routes include editorial reject, watch or defer, association without a new candidate, approved supplemental discovery, operational hold, new-event candidate and development candidate;
- potentially Urgent work has an isolated route that cannot be blocked by an unbounded Routine backlog, while exact timing and batching remain for Topics 6 and 9;
- Story Candidate admission requires the minimum hand-off content in FLOW-060 and deterministic validation;
- Evidence Intake requires durable acknowledgement, ambiguous outcomes remain pending and retryable, and evidence feedback does not rewrite discovery history;
- later-approved manual, reader, media, radar and search inputs use the same Signal-to-Candidate workflow and receive no bypass; and
- watch or defer is a first-class retained News Lead outcome, distinct from an Operational hold and from a terminal editorial rejection.
