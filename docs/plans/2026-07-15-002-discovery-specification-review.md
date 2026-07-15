# Discovery specification review sequence

**Status:** Active review sequence  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Implementation authority:** None; this document organises owner review and does not authorise shadow or production implementation  
**Related proposal:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md)

## Purpose

Review news discovery in bounded topics so that research findings, product decisions, specifications, experiments and implementation plans are not collapsed into one approval. Each topic is reviewed and recorded before the next topic is treated as settled.

The final implementation plan will be written only after the required product, editorial, workflow and architecture decisions have been accepted.

## Decision labels

Each material item uses one of these review labels:

- **Agreed:** accepted by the product owner and eligible to be reflected in an Accepted specification or ADR.
- **Rejected:** considered and explicitly not adopted.
- **Deferred:** intentionally left for a later topic because it does not block the current decision.
- **Needs experiment:** cannot be resolved responsibly without bounded test or shadow evidence.
- **Unresolved:** still requires owner discussion; no default may be inferred.

A research recommendation, Draft specification, Proposed plan or Proposed ADR is not **Agreed** merely because it is committed to the repository.

## Review order

| Topic | Scope | Current state | Completion condition |
|---|---|---|---|
| 0. Decision-state repair | Correct false approval signals and establish the review sequence | Completed; ADR 0004 returned to Proposed | The proposal cannot be treated as owner-accepted |
| 1. Discovery coverage contract | Define Active, Best-effort, deferred and out-of-scope coverage | Completed and Accepted | Coverage classes, geography and launch obligations are Agreed |
| 2. End-to-end discovery workflow | Define source check through Candidate and evidence handoff | Completed and Accepted | Every transition has actor, input, output, authority and failure outcome |
| 3. Discovery record semantics | Define stable identities, versions, decisions and lineage | Completed and Accepted | Identity and immutability are Agreed without selecting a database |
| 4. Source roles and selection | Define source roles, portfolio functions, readiness gates and candidate paths | Completed and Accepted | Every Active obligation has a candidate Anchor or explicit launch-blocking gap |
| 5. Change and Planned Agenda semantics | Define source observation, revision, disappearance, state transition, schedule and missed-expectation meaning | Drafted in `discovery-change-and-planned-agenda.md`; owner review pending | Change classes and downstream meaning are Agreed |
| 6. Triage and event grouping | Decide deterministic versus model judgement, batching, urgency and event/development grouping | Pending | Triage authority, outputs and failure handling are Agreed |
| 7. Search and coverage audit | Define outer radar, gap search, planned-release recovery, recall audit and budgets | Pending | Search roles are bounded, measurable and rights-aware |
| 8. Shadow evaluation | Define experiments, comparisons, labels, metrics and source add/remove criteria | Pending | A shadow protocol produces interpretable evidence |
| 9. Reliability and operations | Define source health, parser contracts, quarantine, retry, alerting, replay and rollout | Pending | Operational failure cannot be confused with no news or source change |
| 10. Prioritisation and outcome vocabulary | Define decision order, scoring need, outcomes and reason vocabulary | Pending | Prioritisation is testable and cannot override scope or evidence gates |
| 11. Locality expansion | Decide selected localities or source classes based on coverage and shadow gaps | Pending | Any locality promise and deferred gap is explicit |
| 12. Implementation plan | Map accepted requirements to code, migration, tests, rollout and rollback | Blocked by Topics 5–11 | Plan cites exact accepted requirements and acceptance evidence |

## Topic boundaries

The following distinctions apply throughout the review:

- product scope is not launch monitoring completeness;
- a source interface is not a coverage strategy;
- a source role is not universal evidence authority;
- a source revision is not necessarily an editorially material change;
- absence from a feed is not necessarily deletion or resolution;
- a Planned Agenda expectation is not occurrence evidence;
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
- **Agreed:** authoritative public-safety warnings and clearly major unscheduled incidents are Active; other unscheduled verified crime and incident discovery is Best effort.
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
- **Agreed:** parser reprocessing of unchanged source state creates a Representation, not a source Revision.
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
- **Agreed:** the final production portfolio is decided only after Topic 8 shadow evidence and Topic 9 operational readiness; Topic 4 authorises no run.
- **Deferred:** final source versions, exact intervals, executable shadow set and production admission.

### Topic 5 — Change and Planned Agenda semantics

The Draft in [`../specs/editorial-automation/discovery-change-and-planned-agenda.md`](../specs/editorial-automation/discovery-change-and-planned-agenda.md) is ready for owner review. Its observation models, transition meanings, baseline rules, Agenda lifecycle and missed-expectation semantics are not **Agreed** merely because they are committed.

## Change discipline

At the end of each topic:

1. update the topic specification or decision document;
2. record Agreed, Rejected, Deferred, Needs experiment and Unresolved items here;
3. update affected cross-references without silently expanding scope;
4. commit the bounded changes to the review branch; and
5. do not open the final pull request until the owner says the review sequence is complete.
