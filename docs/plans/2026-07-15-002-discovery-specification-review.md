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
| 0. Decision-state repair | Correct false approval signals and establish the review sequence | Completed on `agent/discovery-coverage-review`; ADR 0004 returned to Proposed | The ADR and documentation authority map no longer permit the discovery proposal to be treated as owner-accepted |
| 1. Discovery coverage contract | Define what launch discovery must actively seek, what is best effort, what is an explicit gap and what is out of scope | Completed and Accepted in `discovery-coverage-contract.md` on 2026-07-15 | Coverage classes, geography treatment and launch obligations are Agreed |
| 2. End-to-end discovery workflow | Define the path from source check to Story Candidate and evidence hand-off, including failures and retries | Drafted in `discovery-workflow.md`; owner review pending | Every transition has an actor, input, output, decision authority and failure outcome |
| 3. Discovery record semantics | Define source item, revision, Discovery Signal, News Lead, event hypothesis, Story Candidate, Coverage Gap and lineage | Pending | Stable conceptual identities and immutability rules are Agreed without selecting a database |
| 4. Source roles and selection | Decide the roles of official sources, responsible operators, media, specialist/local sources, reader leads and search; then select candidates | Pending | Every active coverage obligation has a justified source role and candidate path |
| 5. Change and Planned Agenda semantics | Define new, revised, deleted, cancelled, rescheduled, escalated, ended and missed-expected-release behaviour | Pending | Change classes and their downstream meaning are Agreed |
| 6. Triage and event grouping | Decide deterministic versus model judgement, batching, urgent handling, ambiguity and event/development grouping | Pending | Triage authority, outputs and failure handling are Agreed |
| 7. Search and coverage audit | Define outer radar, explicit gap search, planned-release recovery, recall audit and budgets | Pending | Search roles are bounded, measurable and rights-aware |
| 8. Shadow evaluation | Define experiments, comparison methods, labels, metrics and source add/remove criteria | Pending | A shadow protocol can produce interpretable evidence rather than an unstructured trial |
| 9. Reliability and operations | Define source health, parser contracts, quarantine, retry, alerting, replay and version rollout | Pending | Operational failure cannot be confused with no news or a substantive change |
| 10. Prioritisation and outcome vocabulary | Define decision order, later scoring need, outcome semantics and reason vocabulary | Pending | Prioritisation is testable and cannot override scope or evidence gates |
| 11. Locality expansion | Decide selected localities or source classes based on the agreed coverage contract and shadow gaps | Pending | Any locality promise and deferred gap is explicit |
| 12. Implementation plan | Map accepted requirements to code, migration, tests, rollout and rollback | Blocked by Topics 2–11 | Plan cites exact accepted requirements and observable acceptance evidence |

## Topic boundaries

The following distinctions apply throughout the review:

- product scope is not the same as launch monitoring completeness;
- a source interface is not a coverage strategy;
- a source change is not necessarily an editorially material development;
- discovery is not evidence acquisition;
- passing tests or committing documentation is not owner approval;
- a shadow experiment is not production authority; and
- a plan cannot create requirements that the specifications or owner have not accepted.

## Current record

### Topic 0 — Decision-state repair

- **Agreed:** discovery decisions will be reviewed sequentially.
- **Agreed:** ADR 0004 must remain Proposed until the owner explicitly accepts, amends or rejects it.
- **Agreed:** no discovery shadow or production implementation is authorised by the existing research, Draft specification or Proposed ADR.
- **Deferred:** exact implementation and migration changes to the legacy Brave/RSS/GDELT/Gemini pipeline.
- **Deferred cleanup:** the Proposed integrated architecture plan still contains one stale parenthetical that labels ADR 0004 as Accepted. `docs/README.md` explicitly marks that parenthetical non-authoritative and superseded by the ADR's current status. The parenthetical should be removed when that large plan is next revised; it does not restore decision authority.

### Topic 1 — Discovery coverage contract

- **Agreed:** the four responsibility classes are Active coverage obligation, Best effort, Explicit deferred gap and Out of scope.
- **Agreed:** the accepted launch coverage matrix in `discovery-coverage-contract.md` defines the coverage baseline independently from source or provider choices.
- **Agreed:** authoritative public-safety warnings and clearly major unscheduled incidents are Active; other unscheduled verified crime and incident discovery is Best effort.
- **Agreed:** Hong Kong active coverage includes broad major public affairs and is not utility-only; district-level completeness is not promised.
- **Agreed:** exhaustive UK local-body and institution monitoring is an explicit deferred gap, with no mandatory launch locality under this contract.
- **Agreed:** ordinary global coverage requires a UK, Hong Kong or connected-family material effect; genuinely exceptional international events may enter Best effort triage without invented relevance.
- **Agreed:** missing or systemically ineffective detection for an Active class blocks launch; an isolated miss normally creates a Coverage Gap and remediation decision.
- **Deferred:** exact detection paths, sources, search roles, locality expansion, quantitative recall and detection-time commitments belong to later topics.

### Topic 2 — End-to-end discovery workflow

The Draft workflow is ready for owner review in [`../specs/editorial-automation/discovery-workflow.md`](../specs/editorial-automation/discovery-workflow.md). Its workflow authority, semantic outcomes, queueing, triage routes and evidence hand-off are not yet **Agreed** merely because they are present on this branch.

## Change discipline

At the end of each topic:

1. update the topic's specification or decision document;
2. record Agreed, Rejected, Deferred, Needs experiment and Unresolved items here;
3. update affected cross-references without silently expanding scope;
4. commit the bounded topic changes to the review branch; and
5. do not open the final pull request until the owner says the review sequence is complete.
