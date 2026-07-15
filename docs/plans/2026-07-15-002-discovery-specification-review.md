# Discovery specification review sequence

**Status:** Active review sequence  
**Owner:** Product owner  
**Last updated:** 2026-07-15  
**Canonical language:** English  
**Implementation authority:** None; this document organises owner review and does not authorise shadow or production implementation  
**Related proposal:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md)

## Purpose

Review news discovery in bounded topics so that research findings, product decisions, specifications, experiments and implementation plans are not collapsed into one approval. Each topic is recorded before the next is treated as settled.

The implementation plan is written only after the required product, editorial, workflow, evaluation and operational decisions are accepted.

## Decision labels

- **Agreed:** accepted by the product owner and eligible for an Accepted specification or ADR.
- **Rejected:** considered and explicitly not adopted.
- **Deferred:** intentionally left for a later topic.
- **Needs experiment:** cannot be resolved responsibly without bounded evidence.
- **Unresolved:** still requires owner discussion; no default may be inferred.

A research recommendation, Draft specification, Proposed plan or Proposed ADR is not Agreed merely because it is committed.

## Review order

| Topic | Scope | Current state | Completion condition |
|---|---|---|---|
| 0. Decision-state repair | Correct false approval signals and establish sequence | Completed; ADR 0004 returned to Proposed | Proposal cannot be treated as owner-accepted |
| 1. Discovery coverage contract | Active, Best-effort, deferred and excluded coverage | Completed and Accepted | Coverage and launch obligations are Agreed |
| 2. End-to-end workflow | Source check through Candidate and evidence handoff | Completed and Accepted | Actors, transitions, authority and failure outcomes are Agreed |
| 3. Record semantics | Stable identities, versions, decisions and lineage | Completed and Accepted | Identity and immutability are Agreed without selecting storage |
| 4. Source roles and selection | Roles, portfolio functions, gates and candidate paths | Completed and Accepted | Every Active class has a candidate Anchor or explicit blocker |
| 5. Change and Planned Agenda | Observation, revision, state and schedule semantics | Completed and Accepted | Change and expectation meaning are Agreed |
| 6. Triage and event grouping | Work Items, retrieval, relationships and Candidate formation | Completed and Accepted | Triage, grouping and failure behaviour are Agreed |
| 7. Search and coverage audit | Search roles, query control, provider boundaries, budgets and audit | Completed and Accepted | Search is bounded, rights-aware and not implicit coverage authority |
| 8. Shadow evaluation | Plans, Epochs, review universe, labels, metrics, blockers and source decisions | Completed and Accepted | Evaluation produces prospective, reproducible and interpretable release evidence |
| 9. Reliability and operations | Profiles, schedules, health, retries, quarantine, queues, recovery and admission | Drafted in `discovery-reliability-and-operations.md`; owner review pending | Operational failure cannot be confused with no news, health and containment are scoped, and admission is evidence-backed |
| 10. Prioritisation and outcome vocabulary | Decision order, scoring need, outcomes and reasons | Pending | Prioritisation is testable and cannot override gates |
| 11. Locality expansion | Selected localities or source classes based on evidence | Pending | Any locality promise and deferred gap is explicit |
| 12. Implementation plan | Code, migration, tests, rollout and rollback | Blocked by Topics 9–11 | Plan cites accepted requirements and observable evidence |

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
- same-event relationship is not Candidate creation;
- a search result is not publisher evidence or recall ground truth;
- prospective audit is not hindsight investigation;
- a comparator union is not complete real-world ground truth;
- calendar duration is not sufficient evaluation exposure;
- healthy silence is not the same as a stale or failed source;
- source health is not portfolio coverage health;
- operational admission is not production activation;
- discovery is not evidence acquisition; and
- a plan cannot create requirements not accepted in specifications.

## Current record

### Topic 0 — Decision-state repair

- **Agreed:** discovery decisions are reviewed sequentially.
- **Agreed:** ADR 0004 remains Proposed until explicitly accepted, amended or rejected.
- **Agreed:** research and Draft or Proposed documents authorise no shadow or production implementation.
- **Deferred:** migration changes to the legacy Brave/RSS/GDELT/Gemini pipeline.
- **Deferred cleanup:** remove the stale ADR 0004 `Accepted` parenthetical from the large Proposed integrated plan when that plan is revised; it is non-authoritative now.

### Topic 1 — Discovery coverage contract

- **Agreed:** responsibility classes are Active, Best effort, Explicit deferred gap and Out of scope.
- **Agreed:** the coverage matrix is independent from source or provider choices.
- **Agreed:** authoritative public-safety warnings and clearly major unscheduled incidents are Active; other verified unscheduled crime and incidents are Best effort.
- **Agreed:** Hong Kong Active coverage includes broad major public affairs and is not utility-only; district completeness is not promised.
- **Agreed:** exhaustive UK local-body and institution monitoring is an explicit deferred gap with no mandatory launch locality.
- **Agreed:** ordinary global coverage requires material UK, Hong Kong or connected-family effect; exceptional events may enter Best-effort triage without invented relevance.
- **Agreed:** missing or systemically ineffective Active detection blocks launch; an isolated miss normally creates a Gap and remediation decision.
- **Deferred:** exact detection paths, locality expansion, recall and detection-time commitments.

### Topic 2 — End-to-end workflow

- **Agreed:** deterministic Discovery and Candidate Admission controllers commit transitions; models and agents propose.
- **Agreed:** Check Request, Attempt and Outcome distinguish unchanged, change, partial, failure and quarantine before a Signal exists.
- **Agreed:** editorial ambiguity survives deterministic gates and normally becomes a Lead.
- **Agreed:** Lead routes include reject, watch or defer, association, supplemental discovery, Operational hold, new-event Candidate and development Candidate.
- **Agreed:** potentially Urgent work cannot be blocked by an unbounded Routine backlog.
- **Agreed:** Candidate admission requires the `FLOW-060` handoff manifest and deterministic validation.
- **Agreed:** Evidence Intake requires durable acknowledgement; ambiguity remains pending and retryable; feedback does not rewrite history.
- **Agreed:** later-approved manual, reader, media, radar and search inputs receive no bypass.
- **Agreed:** watch or defer is a retained outcome with a defined Watch Condition.
- **Deferred:** exact timing, retry budgets and operational tooling.

### Topic 3 — Record semantics

- **Agreed:** internal identities are separate from URLs, provider identifiers and content digests.
- **Agreed:** Source Definition and Version, Source Item and Revision, and Revision and Representation are separate.
- **Agreed:** parser reprocessing of unchanged source state creates a Representation, not a Revision.
- **Agreed:** Check Request, Attempt and Outcome separate logical work, retries and immutable results.
- **Agreed:** one promoted Signal creates one Lead by default; later revisions and cross-source reports remain separate and related explicitly.
- **Agreed:** Lead routes are immutable disposition decisions, and watch or defer requires a Watch Condition.
- **Agreed:** Event Hypotheses remain unverified and distinct from canonical events, Stories, relations and evidence.
- **Agreed:** Candidates have stable identity and immutable versions allocated through deterministic admission and distinct from Story identity.
- **Agreed:** each exact Candidate Version and Evidence Intake boundary has one semantic Handoff; attempts and acknowledgements are separate.
- **Agreed:** Coverage Gaps require reviewed miss decisions and separate isolated, systemic, Best-effort or deferred-gap assessments.
- **Agreed:** lineage is append-only, relationship changes are explicit, source and Newsroom times remain separate, and current status is rebuildable.
- **Deferred:** physical schema, retention, queue, transaction and storage mechanisms.

### Topic 4 — Source roles and selection

- **Agreed:** source role is separate from evidence authority; `official` is not a sufficient purpose.
- **Agreed:** non-search roles are Originating authority, Responsible operator, Planned agenda, Established media radar, Specialist/local radar and Manual/editor/reader lead.
- **Agreed:** portfolio functions are Anchor, Complement, Comparator, Explicit contingency and Manual-only, with no silent fallback.
- **Agreed:** every Active class needs a candidate Anchor or blocker; Planned coverage needs expectation and occurrence paths; guidance needs maintained-page revision paths; Urgent unscheduled coverage needs a fast warning, operator or established-media path.
- **Agreed:** GOV.UK does not satisfy devolved coverage by default, and Hong Kong broad public affairs needs broad radar plus direct official and sector paths.
- **Agreed:** editorial, rights, technical, operational and evaluation gates precede executable shadow use.
- **Agreed:** one host `200` is research evidence only; TLS, credentials, terms or identity/revision blockers keep a source Held.
- **Agreed:** `UK-01`–`UK-11`, `HK-01`–`HK-05`, RTHK and BBC UK are an adapter/workflow shortlist, not completeness.
- **Agreed:** coverage-completion and additional candidate paths are qualification work without automatic enablement.
- **Agreed:** BBC UK and RTHK are legitimate radar and Comparator candidates within the evidence boundary.
- **Agreed:** devolved paths, courts/elections, UK–Hong Kong travel/aviation, Hong Kong courts and a global radar remain mandatory unresolved pre-production work.
- **Agreed:** final production portfolio follows Topic 8 evidence and Topic 9 readiness; Topic 4 authorises no run.
- **Deferred:** final source versions, intervals, executable set and production admission.

### Topic 5 — Change and Planned Agenda

- **Agreed:** every Source Definition Version declares an observation model and inference is limited to it.
- **Agreed:** retrieval observation, Source Revision, observable transition and editorial interpretation are separate layers.
- **Agreed:** validators, timestamps, HTTP status and disappearance are inputs, not standalone proof.
- **Agreed:** first observation, re-observation, Revision, Representation-only change, withdrawal, replacement, deletion, redirect, reappearance and linked-document follow-up remain distinct.
- **Agreed:** activation, escalation, de-escalation, clearance, expiry, cancellation, withdrawal and reactivation remain distinct.
- **Agreed:** absence ends active state only under complete-snapshot and confirmation rules; partial and rolling sources cannot clear state by absence.
- **Agreed:** baselines are source-specific and may record first-observed-active without claiming start time.
- **Agreed:** Agenda Items and Versions are expectation records distinct from Signals, Leads, Candidates and occurrence evidence.
- **Agreed:** Planned coverage uses expectation and occurrence paths; announcements may create both a Signal and Agenda Item.
- **Agreed:** rescheduling and cancellation require source evidence and preserve schedule history.
- **Agreed:** missed expectation means not observed through required paths, not proof of non-occurrence; failure remains separate and late occurrence preserves the miss.
- **Agreed:** clock passage alone creates no Lead, Candidate or reminder story.
- **Agreed:** every transition enters normal gates, triage and evidence; models cannot create source history.
- **Deferred:** grace periods, schedules, retry and supplemental-search timing.

### Topic 6 — Triage and event grouping

- **Agreed:** Work Items, Execution Batches and editorial grouping are separate.
- **Agreed:** decision Leads and context-only Leads are distinct; every decision Lead gets one disposition and context-only Leads are not mutated.
- **Agreed:** bounded retrieval supplies context only; empty retrieval does not force new event and scores are non-authoritative.
- **Agreed:** Candidate admission requires an exact current Candidate and identity collision check.
- **Agreed:** relationships are same state, development, correction/reversal, related but distinct, no adequate prior match and uncertain.
- **Agreed:** relationship and Candidate creation are orthogonal; same-state repetition normally associates and material new state may become a development Candidate.
- **Agreed:** every development Candidate identifies earlier and proposed new state.
- **Agreed:** Hypothesis creation, association, versioning, consolidation and split are append-only; destructive merge is prohibited.
- **Agreed:** coherent Leads may form one Candidate; unrelated Leads remain separate and a multi-topic Lead cannot be model-split without distinct Signals.
- **Agreed:** discovery Candidate formation has no minimum source or domain count.
- **Agreed:** Urgent Work Items may be expedited without lower standards; degraded advisory retrieval requires exact collision checks and later reconciliation.
- **Agreed:** proposals are structured and deterministically validated; confidence is metadata and failure or disagreement remains neutral.
- **Agreed:** non-material association need not version a Candidate; material Hypothesis, urgency, uncertainty or objective change does.
- **Agreed:** Topic 8 must test relationship and route classes, false merge, snowball absorption, fragmentation and false development.
- **Deferred:** batch sizes, wait limits, model/provider choice, retrieval engine and degraded-operation timing.

### Topic 7 — Search and coverage audit

- **Agreed:** search and media indexes are supplemental channels and Comparators, never the sole Active Anchor or primary generic clock.
- **Agreed:** bounded purposes are outer radar, recall audit, Gap investigation, Planned recovery, supplemental discovery, outage contingency and manual research.
- **Agreed:** recurring outer radar begins as Comparator or Best effort and requires Topic 8 contribution evidence and Topic 9 readiness before production.
- **Agreed:** Search Purpose, Request, Attempt, Outcome, Result Reference and Review Decision remain separate; zero, partial, rate-limit and failure are distinct.
- **Agreed:** queries are purpose-specific, versioned and bounded; one-query-per-beat and recursive agent search are prohibited.
- **Agreed:** models may propose but not execute or expand queries, and external query data excludes private, confidential and unnecessary sensitive information.
- **Agreed:** provider query-data, result retention, model use and underlying publisher rights are reviewed separately.
- **Agreed:** gross request, cost, pagination, expansion, retry and downstream-work budgets are hard and purpose-specific; silent provider switching is prohibited.
- **Agreed:** results enter normal workflow; rank and snippets are non-authoritative and duplicates or common origins do not multiply independence.
- **Agreed:** prospective and retrospective audit remain separate, and a Gap requires relevance, timing, expected-path and health review.
- **Agreed:** search is not recall ground truth; zero results are neutral and direct-source or workflow improvement is preferred after a reviewed Gap.
- **Agreed:** GDELT is a Held Comparator candidate; Brave is Rights Review Required; SearXNG and unofficial wrappers remain Research candidates.
- **Agreed:** Topic 7 authorises no provider, schedule, spending or run.
- **Deferred:** executable queries, providers, budgets and recurring production admission until Topics 8 and 9.

### Topic 8 — Shadow evaluation

- **Agreed:** evaluation has a separate authority scope with no public effect or production mutation.
- **Agreed:** owner-approved Evaluation Plans and frozen Epochs are required; calibration and qualification remain separate.
- **Agreed:** phases are fixtures, replay, live prospective shadow, prospective comparator audit, fault injection, review and ablation.
- **Agreed:** the prospective evaluation universe is event-level and assembled from several permitted paths without claiming complete ground truth.
- **Agreed:** prospective and retrospective evidence remain separate; hindsight queries do not enter prospective coverage claims.
- **Agreed:** contemporaneous labels, later-outcome labels and unreviewable outcomes remain distinct.
- **Agreed:** final labels require authorised human review, practical blinding and second review for launch blockers, zero-tolerance and Urgent material cases.
- **Agreed:** adapter, change, coverage, gate, triage, grouping, Candidate, timeliness, cost and operation are evaluated separately rather than by one composite score.
- **Agreed:** detection coverage is bounded to the reviewed prospective universe and is not absolute recall.
- **Agreed:** required geography, language, coverage, urgency, source-role, portfolio, observation-model, transition and component slices cannot be hidden by aggregates.
- **Agreed:** zero-tolerance blockers include public effect, rights or authority bypass, failure-as-no-news, false absence-based ending, fabricated Revision, duplicate transition, destructive merge, invalid Candidate admission and discovery-to-evidence bypass.
- **Agreed:** non-zero thresholds are approved before qualification review; calibration is not release evidence and changed Epochs cannot be pooled post hoc.
- **Agreed:** source contribution and ablation use unique and earlier detection, resilience, overlap, noise, rights, cost and reviewer burden rather than raw item count.
- **Agreed:** Comparators do not become Anchors because they return more results, and rights-incompatible provider data cannot form a persistent evaluation corpus.
- **Agreed:** the legacy pipeline and v1 clustering dataset are comparison or regression aids only.
- **Agreed:** release-evidence outcomes include insufficient, failed, continue shadow, Comparator-only, scoped Topic 9 eligibility, rejected and launch-blocked.
- **Agreed:** reports are reproducible and rights-limited, failed Runs remain retained and confirmed errors feed regression Cases.
- **Agreed:** Topic 8 authorises no run.
- **Needs experiment:** numerical qualification thresholds, minimum exposure and actual source or component promotion decisions require a future owner-approved Evaluation Plan and frozen qualification Epoch.

### Topic 9 — Reliability and operations

The Draft in [`../specs/editorial-automation/discovery-reliability-and-operations.md`](../specs/editorial-automation/discovery-reliability-and-operations.md) is ready for owner review. Its Operational Profiles, scheduling, health, retry, quarantine, capacity, monitoring, recovery, security and admission rules are not Agreed merely because they are committed.

## Change discipline

At the end of each topic:

1. update the topic specification;
2. record Agreed, Rejected, Deferred, Needs experiment and Unresolved items here;
3. update cross-references without silently expanding scope;
4. commit bounded changes to the review branch; and
5. do not open the final pull request until the owner says the sequence is complete.
