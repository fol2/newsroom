# Discovery specification review sequence

**Status:** Active review sequence  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Implementation authority:** None; this document organises owner review and does not authorise shadow or production implementation  
**Related proposal:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md)

## Purpose

Review news discovery in bounded topics so that research findings, product decisions, specifications, experiments and implementation plans are not collapsed into one approval. Each topic is reviewed and recorded before the next is treated as settled.

The final implementation plan will be written only after the required product, editorial, workflow and architecture decisions have been accepted.

## Decision labels

Each material item uses one of:

- **Agreed:** accepted by the product owner and eligible for an Accepted specification or ADR.
- **Rejected:** considered and explicitly not adopted.
- **Deferred:** intentionally left for a later topic.
- **Needs experiment:** cannot be resolved responsibly without bounded test or shadow evidence.
- **Unresolved:** still requires owner discussion; no default may be inferred.

A research recommendation, Draft specification, Proposed plan or Proposed ADR is not **Agreed** merely because it is committed.

## Review order

| Topic | Scope | Current state | Completion condition |
|---|---|---|---|
| 0. Decision-state repair | Correct false approval signals and establish the review sequence | Completed; ADR 0004 returned to Proposed | The proposal cannot be treated as owner-accepted |
| 1. Discovery coverage contract | Define Active, Best-effort, deferred and out-of-scope coverage | Completed and Accepted | Coverage classes, geography and launch obligations are Agreed |
| 2. End-to-end discovery workflow | Define source check through Candidate and evidence handoff | Completed and Accepted | Every transition has actor, input, output, authority and failure outcome |
| 3. Discovery record semantics | Define stable identities, versions, decisions and lineage | Completed and Accepted | Identity and immutability are Agreed without selecting a database |
| 4. Source roles and selection | Define source roles, portfolio functions, readiness gates and candidate paths | Completed and Accepted | Every Active obligation has a candidate Anchor or explicit launch-blocking gap |
| 5. Change and Planned Agenda semantics | Define source observation, revision, disappearance, state transition, schedule and missed-expectation meaning | Completed and Accepted | Change classes and downstream meaning are Agreed |
| 6. Triage and event grouping | Define Work Items, execution batches, retrieval, relationships, Hypotheses and Candidate formation | Completed and Accepted | Triage authority, grouping, outputs and failure handling are Agreed |
| 7. Search and coverage audit | Define search roles, query control, providers, budgets and audit interpretation | Drafted in `discovery-search-and-coverage-audit.md`; owner review pending | Search roles are bounded, measurable, rights-aware and do not become implicit coverage authority |
| 8. Shadow evaluation | Define experiments, comparisons, labels, metrics and source add/remove criteria | Pending | A shadow protocol produces interpretable evidence |
| 9. Reliability and operations | Define source health, parser contracts, quarantine, retry, alerting, replay and rollout | Pending | Operational failure cannot be confused with no news or source change |
| 10. Prioritisation and outcome vocabulary | Define decision order, scoring need, outcomes and reason vocabulary | Pending | Prioritisation is testable and cannot override scope or evidence gates |
| 11. Locality expansion | Decide selected localities or source classes based on coverage and shadow gaps | Pending | Any locality promise and deferred gap is explicit |
| 12. Implementation plan | Map accepted requirements to code, migration, tests, rollout and rollback | Blocked by Topics 7–11 | Plan cites exact accepted requirements and acceptance evidence |

## Topic boundaries

The following distinctions apply throughout:

- product scope is not launch monitoring completeness;
- a source interface is not a coverage strategy;
- a source role is not universal evidence authority;
- a Source Revision is not necessarily an editorially material change;
- absence from a feed is not necessarily deletion or resolution;
- a Planned Agenda expectation is not occurrence evidence;
- an execution batch is not an Event Hypothesis;
- retrieval similarity is not event identity;
- same-event relationship is not the same decision as Candidate creation;
- a search result is not publisher evidence or recall ground truth;
- a prospective audit is not a hindsight Gap investigation;
- discovery is not evidence acquisition;
- passing tests or committing documentation is not owner approval;
- a shadow experiment is not production authority; and
- a plan cannot create requirements that specifications or the owner have not accepted.

## Current record

### Topic 0 — Decision-state repair

- **Agreed:** discovery decisions are reviewed sequentially.
- **Agreed:** ADR 0004 remains Proposed until explicitly accepted, amended or rejected.
- **Agreed:** existing research, Draft specifications and the Proposed ADR authorise no shadow or production implementation.
- **Deferred:** migration changes to the legacy Brave/RSS/GDELT/Gemini pipeline.
- **Deferred cleanup:** the Proposed integrated architecture plan contains one stale parenthetical labelling ADR 0004 as Accepted. `docs/README.md` marks it non-authoritative; remove it when that plan is next revised.

### Topic 1 — Discovery coverage contract

- **Agreed:** responsibility classes are Active, Best effort, Explicit deferred gap and Out of scope.
- **Agreed:** the launch coverage matrix is independent from source or provider choices.
- **Agreed:** authoritative public-safety warnings and clearly major unscheduled incidents are Active; other verified unscheduled crime and incident discovery is Best effort.
- **Agreed:** Hong Kong Active coverage includes broad major public affairs and is not utility-only; district completeness is not promised.
- **Agreed:** exhaustive UK local-body and institution monitoring is an explicit deferred gap, with no mandatory launch locality.
- **Agreed:** ordinary global coverage requires material UK, Hong Kong or connected-family effect; genuinely exceptional events may enter Best-effort triage without invented relevance.
- **Agreed:** missing or systemically ineffective detection for an Active class blocks launch; an isolated miss normally creates a Coverage Gap and remediation decision.
- **Deferred:** exact detection paths, search roles, locality expansion, recall and detection-time commitments.

### Topic 2 — End-to-end discovery workflow

- **Agreed:** only deterministic Discovery and Candidate Admission controllers commit transitions; models and agents propose.
- **Agreed:** Check Request, Attempt and Outcome distinguish unchanged, change, partial, failure and quarantine before a Signal exists.
- **Agreed:** editorial ambiguity survives deterministic gates and normally becomes a Lead.
- **Agreed:** Lead routes include reject, watch or defer, association, supplemental discovery, operational hold, new-event Candidate and development Candidate.
- **Agreed:** potentially Urgent work cannot be blocked by an unbounded Routine backlog.
- **Agreed:** Candidate admission requires the `FLOW-060` handoff manifest and deterministic validation.
- **Agreed:** Evidence Intake requires durable acknowledgement; ambiguous outcomes remain pending and retryable; feedback does not rewrite history.
- **Agreed:** later-approved manual, reader, media, radar and search inputs receive no bypass.
- **Agreed:** watch or defer is a first-class retained outcome with a defined Watch Condition.
- **Deferred:** exact timing, batching, grouping, retry budgets and operational tooling.

### Topic 3 — Discovery record semantics

- **Agreed:** internal identities are separate from URLs, provider identifiers and content digests.
- **Agreed:** Source Definition and Version, Source Item and Revision, and Revision and Representation are separate contracts.
- **Agreed:** parser reprocessing of unchanged source state creates a Representation, not a Revision.
- **Agreed:** Check Request, Attempt and Outcome separate logical work, retries and immutable results.
- **Agreed:** one promoted Signal creates one Lead by default; later revisions and cross-source reports remain separate and explicitly related.
- **Agreed:** Lead routes are immutable disposition decisions, and watch or defer requires a Watch Condition.
- **Agreed:** Event Hypotheses remain unverified and distinct from canonical events, Stories, relations and evidence.
- **Agreed:** Candidates have stable identity and immutable versions allocated through deterministic admission and distinct from later Story identity.
- **Agreed:** each exact Candidate Version and Evidence Intake boundary has one semantic Handoff; attempts and acknowledgements are separate.
- **Agreed:** Coverage Gaps require reviewed miss decisions and separate isolated, systemic, Best-effort or deferred-gap assessment.
- **Agreed:** lineage is append-only, supersession and merge relationships are explicit, source and Newsroom times remain separate, and current status is rebuildable.
- **Deferred:** physical schema, retention, queue, transaction and storage mechanisms.

### Topic 4 — Source roles and selection

- **Agreed:** source role is separate from evidence authority, and “official” is not a sufficient source purpose.
- **Agreed:** non-search roles are Originating authority, Responsible operator, Planned agenda, Established media radar, Specialist or local radar, and Manual, editor or reader lead.
- **Agreed:** portfolio functions are Anchor, Complement, Comparator, Explicit contingency and Manual-only, with no silent fallback.
- **Agreed:** every Active class needs a credible candidate Anchor or launch-blocking gap; Planned coverage needs expectation and occurrence paths; guidance revisions need maintained-page monitoring; urgent unscheduled coverage needs a fast warning, operator or established-media path.
- **Agreed:** GOV.UK does not satisfy devolved coverage by default, and Hong Kong broad public affairs needs broad radar plus direct official and sector paths.
- **Agreed:** editorial, rights, technical, operational and evaluation gates precede executable shadow use.
- **Agreed:** one successful host response is research evidence only; TLS failure, missing credentials, unknown terms or missing identity and revision contracts keep a source Held.
- **Agreed:** `UK-01`–`UK-11`, `HK-01`–`HK-05`, RTHK and BBC UK form the initial adapter and workflow validation shortlist, not a completeness claim.
- **Agreed:** the coverage-completion shortlist and additional candidate paths are source-qualification work without automatic enablement.
- **Agreed:** BBC UK and RTHK are legitimate established-media radar and Comparator candidates while remaining inside the evidence boundary.
- **Agreed:** devolved administrations and warnings, courts and elections, UK–Hong Kong travel and aviation, Hong Kong courts and a global radar are mandatory unresolved pre-production source work.
- **Agreed:** final production portfolio follows Topic 8 shadow evidence and Topic 9 readiness; Topic 4 authorises no run.
- **Deferred:** final source versions, exact intervals, executable shadow set and production admission.

### Topic 5 — Change and Planned Agenda semantics

- **Agreed:** every Source Definition Version declares an observation model and inference is limited to it.
- **Agreed:** retrieval observation, Source Revision, observable transition and editorial interpretation are separate layers.
- **Agreed:** validators, timestamps, HTTP status and disappearance are inputs to source-specific rules, not standalone proof.
- **Agreed:** first observation, re-observation, Revision, Representation-only change, withdrawal, replacement, deletion, redirect, reappearance and linked-document follow-up remain distinct.
- **Agreed:** activation, escalation, de-escalation, resolution or clearance, expiry, cancellation, withdrawal and reactivation remain distinct.
- **Agreed:** absence ends active state only under successful complete-snapshot and confirmation rules; partial and rolling sources cannot clear state by absence.
- **Agreed:** baseline policy is source-specific and may record first-observed-active without claiming start time.
- **Agreed:** Planned Agenda Items and Versions are expectation records distinct from Signals, Leads, Candidates and occurrence evidence.
- **Agreed:** Planned coverage uses agenda and occurrence-confirmation paths; announcements may create both a Signal and an Agenda Item.
- **Agreed:** rescheduling and cancellation require source evidence and preserve schedule history.
- **Agreed:** missed expectation means not observed through required paths, not proof of non-occurrence, cancellation or delay; source failure remains separate and late occurrence preserves the miss.
- **Agreed:** clock passage alone creates no Lead, Candidate or reminder story.
- **Agreed:** every observable transition enters normal gates, triage and evidence acquisition; models cannot create source history.
- **Deferred:** exact grace periods, check schedules, retry policy and supplemental-search behaviour.

### Topic 6 — Triage and event grouping

- **Agreed:** Triage Work Items, Execution Batches and editorial event grouping are separate.
- **Agreed:** decision Leads and context-only Leads are distinct; every decision Lead gets one explicit disposition and context-only Leads cannot be mutated.
- **Agreed:** bounded retrieval supplies context only; empty retrieval does not force new event and score or confidence is non-authoritative.
- **Agreed:** Candidate admission requires a separate exact current Candidate and identity collision check.
- **Agreed:** relationship classes are same event state, development, correction or reversal, related but distinct, no adequate prior match and uncertain relationship.
- **Agreed:** relationship and Candidate creation are orthogonal; same-state repetition normally associates and material new state may create a development Candidate.
- **Agreed:** every development Candidate identifies exact earlier and proposed new state.
- **Agreed:** Hypothesis creation, association, versioning, consolidation and split are deterministic append-only decisions; destructive merge is prohibited.
- **Agreed:** several Leads may form one coherent Candidate with complete lineage; unrelated Leads remain separate and a multi-topic Lead cannot be model-split without approved distinct Signals.
- **Agreed:** Candidate formation has no minimum source or domain count at discovery.
- **Agreed:** Urgent Work Items may be expedited without lower standards; degraded advisory retrieval requires exact collision checks and later reconciliation.
- **Agreed:** proposals are structured and deterministically validated; confidence is metadata and timeout, refusal, malformed output and disagreement remain neutral.
- **Agreed:** non-material association need not version a Candidate; material Hypothesis, urgency, uncertainty or evidence-objective change does.
- **Agreed:** Topic 8 must replace or extend current clustering evaluation to test relationship and route classes, including false merge, snowball absorption, fragmentation and false development.
- **Deferred:** exact batch sizes, wait limits, model/provider selection, retrieval engine, degraded-operation timing and adjudication policy.

### Topic 7 — Search and coverage audit

The Draft in [`../specs/editorial-automation/discovery-search-and-coverage-audit.md`](../specs/editorial-automation/discovery-search-and-coverage-audit.md) is ready for owner review. Its search roles, provider boundaries, query controls, budgets and audit interpretation are not **Agreed** merely because they are committed.

## Change discipline

At the end of each topic:

1. update the topic specification or decision document;
2. record Agreed, Rejected, Deferred, Needs experiment and Unresolved items here;
3. update affected cross-references without silently expanding scope;
4. commit bounded changes to the review branch; and
5. do not open the final pull request until the owner says the review sequence is complete.
