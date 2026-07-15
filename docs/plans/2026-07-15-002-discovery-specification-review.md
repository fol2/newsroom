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

Each material item must use one of these review labels:

- **Agreed:** accepted by the product owner and eligible to be reflected in an Accepted specification or ADR.
- **Rejected:** considered and explicitly not adopted.
- **Deferred:** intentionally left for a later topic because it does not block the current decision.
- **Needs experiment:** cannot be resolved responsibly without a bounded test or shadow evidence.
- **Unresolved:** still requires owner discussion; no default may be inferred.

A research recommendation, Draft specification, Proposed plan or Proposed ADR is not **Agreed** merely because it is committed to the repository.

## Review order

| Topic | Scope | Current state | Completion condition |
|---|---|---|---|
| 0. Decision-state repair | Correct false approval signals and establish the review sequence | Completed on `agent/discovery-coverage-review`; ADR 0004 returned to Proposed | The ADR and documentation map no longer permit the proposal to be treated as owner-accepted |
| 1. Discovery coverage contract | Define Active, Best-effort, deferred and out-of-scope coverage | Completed and Accepted in `discovery-coverage-contract.md` | Coverage classes, geography and launch obligations are Agreed |
| 2. End-to-end discovery workflow | Define source check through Story Candidate and evidence handoff | Completed and Accepted in `discovery-workflow.md` | Every transition has an actor, input, output, authority and failure outcome |
| 3. Discovery record semantics | Define stable identities, versions, decisions and lineage | Completed and Accepted in `discovery-record-semantics.md` | Conceptual identity and immutability rules are Agreed without selecting a database |
| 4. Source roles and selection | Decide source roles, portfolio functions, readiness gates and candidate paths | Drafted in `discovery-source-roles-and-selection.md`; owner review pending | Every Active obligation has a justified candidate Anchor or explicit launch-blocking gap |
| 5. Change and Planned Agenda semantics | Define new, revised, deleted, cancelled, rescheduled, escalated, ended and missed-release behaviour | Next after Topic 4 | Change classes and downstream meaning are Agreed |
| 6. Triage and event grouping | Decide deterministic versus model judgement, batching, urgency and event/development grouping | Pending | Triage authority, outputs and failure handling are Agreed |
| 7. Search and coverage audit | Define outer radar, gap search, planned-release recovery, recall audit and budgets | Pending | Search roles are bounded, measurable and rights-aware |
| 8. Shadow evaluation | Define experiments, comparison, labels, metrics and source add/remove criteria | Pending | A shadow protocol produces interpretable evidence rather than an unstructured trial |
| 9. Reliability and operations | Define source health, parser contracts, quarantine, retry, alerting, replay and rollout | Pending | Operational failure cannot be confused with no news or source change |
| 10. Prioritisation and outcome vocabulary | Define decision order, scoring need, outcomes and reason vocabulary | Pending | Prioritisation is testable and cannot override scope or evidence gates |
| 11. Locality expansion | Decide selected localities or source classes based on coverage and shadow gaps | Pending | Any locality promise and deferred gap is explicit |
| 12. Implementation plan | Map accepted requirements to code, migration, tests, rollout and rollback | Blocked by Topics 4–11 | Plan cites exact accepted requirements and acceptance evidence |

## Topic boundaries

The following distinctions apply throughout the review:

- product scope is not the same as launch monitoring completeness;
- a source interface is not a coverage strategy;
- a source role is not universal evidence authority;
- a source change is not necessarily an editorially material development;
- discovery is not evidence acquisition;
- passing tests or committing documentation is not owner approval;
- a shadow experiment is not production authority; and
- a plan cannot create requirements that the specifications or owner have not accepted.

## Current record

### Topic 0 — Decision-state repair

- **Agreed:** discovery decisions will be reviewed sequentially.
- **Agreed:** ADR 0004 remains Proposed until the owner explicitly accepts, amends or rejects it.
- **Agreed:** existing research, Draft specifications and the Proposed ADR authorise no discovery shadow or production implementation.
- **Deferred:** implementation and migration changes to the legacy Brave/RSS/GDELT/Gemini pipeline.
- **Deferred cleanup:** the Proposed integrated architecture plan contains one stale parenthetical labelling ADR 0004 as Accepted. `docs/README.md` marks it non-authoritative; remove it when that large plan is next revised.

### Topic 1 — Discovery coverage contract

- **Agreed:** the four responsibility classes are Active, Best effort, Explicit deferred gap and Out of scope.
- **Agreed:** the accepted launch coverage matrix is independent from source or provider choices.
- **Agreed:** authoritative public-safety warnings and clearly major unscheduled incidents are Active; other unscheduled verified crime and incident discovery is Best effort.
- **Agreed:** Hong Kong Active coverage includes broad major public affairs and is not utility-only; district completeness is not promised.
- **Agreed:** exhaustive UK local-body and institution monitoring is an explicit deferred gap, with no mandatory launch locality under this contract.
- **Agreed:** ordinary global coverage requires a UK, Hong Kong or connected-family material effect; genuinely exceptional international events may enter Best-effort triage without invented relevance.
- **Agreed:** missing or systemically ineffective detection for an Active class blocks launch; an isolated miss normally creates a Coverage Gap and remediation decision.
- **Deferred:** exact detection paths, sources, search roles, locality expansion, recall and detection-time commitments.

### Topic 2 — End-to-end discovery workflow

- **Agreed:** only deterministic Discovery and Candidate Admission controllers commit discovery transitions; models and agents propose.
- **Agreed:** Check Request/Attempt/Outcome semantics distinguish unchanged, change, partial, failure and quarantine before a Signal exists.
- **Agreed:** editorial ambiguity survives deterministic gates and normally becomes a News Lead.
- **Agreed:** Lead routes include reject, watch/defer, association, supplemental discovery, operational hold, new-event Candidate and development Candidate.
- **Agreed:** potentially Urgent work cannot be blocked by an unbounded Routine backlog.
- **Agreed:** Story Candidate admission requires the `FLOW-060` handoff manifest and deterministic validation.
- **Agreed:** Evidence Intake requires durable acknowledgement; ambiguity remains pending and retryable; feedback does not rewrite discovery history.
- **Agreed:** later-approved manual, reader, media, radar and search inputs receive no workflow bypass.
- **Agreed:** watch/defer is a first-class retained outcome with a defined condition, distinct from operational hold and terminal reject.
- **Deferred:** exact timing, batching, grouping, retry budgets and operational tooling.

### Topic 3 — Discovery record semantics

- **Agreed:** internal identities are separate from URLs, provider identifiers and content digests.
- **Agreed:** Source Definition/Version, Source Item/Revision and Source Revision/Discovery Representation are separate contracts.
- **Agreed:** parser or normaliser reprocessing of unchanged source state creates a Representation, not a source Revision.
- **Agreed:** Check Request, Check Attempt and Check Outcome separate logical work, retries and immutable results.
- **Agreed:** one promoted Signal creates one Lead by default; later revisions and cross-source reports remain separate and explicitly related.
- **Agreed:** Lead routes are immutable disposition decisions, and watch/defer requires an inspectable Watch Condition.
- **Agreed:** Event Hypotheses and versions remain unverified and distinct from canonical events, Stories, relations and evidence.
- **Agreed:** Story Candidates have stable identity and immutable versions allocated only through deterministic admission and distinct from later Story identity.
- **Agreed:** each exact Candidate Version and Evidence Intake boundary has one semantic Handoff; attempts and acknowledgements are separate.
- **Agreed:** Coverage Gaps require reviewed relevant-miss decisions and separate isolated, systemic, Best-effort or deferred-gap assessments.
- **Agreed:** lineage is append-only, supersession and merge relationships are explicit, source and Newsroom times remain separate, and current status is rebuildable rather than sole authority.
- **Deferred:** physical schema, retention, queue, transaction and storage mechanisms.

### Topic 4 — Source roles and selection

The Draft in [`../specs/editorial-automation/discovery-source-roles-and-selection.md`](../specs/editorial-automation/discovery-source-roles-and-selection.md) is ready for owner review. Its source roles, portfolio functions, readiness gates and candidate shortlist are not **Agreed** merely because they are committed.

## Change discipline

At the end of each topic:

1. update the topic specification or decision document;
2. record Agreed, Rejected, Deferred, Needs experiment and Unresolved items here;
3. update affected cross-references without silently expanding scope;
4. commit the bounded changes to the review branch; and
5. do not open the final pull request until the owner says the review sequence is complete.
