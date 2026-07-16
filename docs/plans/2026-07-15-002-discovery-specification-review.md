# Discovery specification review sequence

**Status:** Active review sequence  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None; this document organises owner review and authorises no shadow or production implementation  
**Related proposal:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md)

## Purpose

Review news discovery in bounded topics so research findings, product decisions, specifications, experiments and implementation plans are not collapsed into one approval. Each topic is recorded before the next is treated as settled.

The implementation plan is written only after product, editorial, workflow, evaluation, operational, prioritisation and locality decisions are accepted.

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
| 9. Reliability and operations | Profiles, schedules, health, retries, quarantine, queues, recovery and admission | Completed and Accepted | Operational failure cannot be confused with no news; health, recovery and admission are scoped |
| 10. Prioritisation and outcomes | Decision order, outcomes, reasons, ordinal priority and scoring boundary | Completed and Accepted | Priority cannot override gates and outcomes remain inspectable |
| 11. Locality scope and expansion | Launch locality boundary, event-scoped watch and evidence-based expansion | Drafted in `discovery-locality-scope-and-expansion.md`; owner review pending | Any locality promise, selected source class and deferred gap is explicit |
| 12. Implementation plan | Code, migration, tests, evaluation, rollout and rollback | Blocked by Topic 11 | Plan cites Accepted requirements and observable evidence |

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
- healthy silence is not a stale or failed source;
- source health is not portfolio coverage health;
- operational admission is not production activation;
- outcome, reason, status and priority are separate;
- priority is not eligibility;
- a local story label is not a systematic locality-coverage promise;
- an event-scoped local watch is not permanent locality selection;
- nation-level UK coverage is not locality expansion;
- discovery is not evidence acquisition; and
- a plan cannot create requirements not accepted in specifications.

## Current record

### Topic 0 — Decision-state repair

- **Agreed:** discovery decisions are reviewed sequentially.
- **Agreed:** ADR 0004 remains Proposed until explicitly accepted, amended or rejected.
- **Agreed:** research and Draft or Proposed documents authorise no shadow or production implementation.
- **Deferred:** migration changes to the legacy Brave/RSS/GDELT/Gemini pipeline.
- **Deferred cleanup:** remove the stale ADR 0004 `Accepted` parenthetical from the large Proposed integrated plan when it is revised; it is non-authoritative now.

### Topic 1 — Discovery coverage contract

- **Agreed:** responsibility classes are Active, Best effort, Explicit deferred gap and Out of scope.
- **Agreed:** the coverage matrix is independent from source or provider choices.
- **Agreed:** authoritative public-safety warnings and clearly major unscheduled incidents are Active; other verified unscheduled crime and incidents are Best effort.
- **Agreed:** Hong Kong Active coverage includes broad major public affairs and is not utility-only; district completeness is not promised.
- **Agreed:** exhaustive UK local-body and institution monitoring is an explicit deferred gap with no mandatory launch locality.
- **Agreed:** ordinary global coverage requires material UK, Hong Kong or connected-family effect; exceptional events may enter Best-effort triage without invented relevance.
- **Agreed:** missing or systemically ineffective Active detection blocks launch; an isolated miss normally creates a Gap and remediation decision.

### Topic 2 — End-to-end workflow

- **Agreed:** deterministic Discovery and Candidate Admission controllers commit transitions; models and agents propose.
- **Agreed:** Check Request, Attempt and Outcome distinguish unchanged, change, partial, failure and quarantine before a Signal exists.
- **Agreed:** editorial ambiguity survives deterministic gates and normally becomes a Lead.
- **Agreed:** Lead routes include reject, watch or defer, association, supplemental discovery, Operational hold and Candidate routes.
- **Agreed:** potentially Urgent work cannot be blocked by unbounded Routine backlog.
- **Agreed:** Candidate admission is deterministic and Evidence Intake requires durable acknowledgement.
- **Agreed:** manual, reader, media, radar and search inputs receive no bypass.
- **Agreed:** watch or defer requires a Watch Condition.

### Topic 3 — Record semantics

- **Agreed:** internal identities are separate from URLs, provider identifiers and content digests.
- **Agreed:** Source Definition and Version, Source Item and Revision, and Revision and Representation are separate.
- **Agreed:** parser reprocessing of unchanged source state creates a Representation, not a Revision.
- **Agreed:** logical work, Attempts and Outcomes remain distinct.
- **Agreed:** one promoted Signal creates one Lead by default; later revisions and cross-source reports retain separate lineage.
- **Agreed:** Event Hypotheses remain unverified and Candidates have immutable versions distinct from Stories.
- **Agreed:** each exact Candidate Version has one semantic Evidence Handoff.
- **Agreed:** Coverage Gaps require reviewed miss decisions.
- **Agreed:** lineage is append-only and current status is rebuildable.
- **Deferred:** physical schema, retention, queue, transaction and storage mechanisms.

### Topic 4 — Source roles and selection

- **Agreed:** source role is separate from evidence authority; `official` is not a sufficient purpose.
- **Agreed:** source roles and portfolio functions are explicit, with no silent fallback.
- **Agreed:** every Active class needs a candidate Anchor or launch blocker; Planned, maintained-page and Urgent paths have distinct requirements.
- **Agreed:** GOV.UK does not satisfy devolved coverage by default, and Hong Kong needs broad radar plus direct sector paths.
- **Agreed:** editorial, rights, technical, operational and evaluation gates precede executable use.
- **Agreed:** the initial tested interfaces are a validation shortlist, not completeness.
- **Agreed:** devolved paths, courts and elections, UK–Hong Kong travel and aviation, Hong Kong courts and a global radar remain required source-qualification work.

### Topic 5 — Change and Planned Agenda

- **Agreed:** every Source Definition Version declares an observation model and inference is limited to it.
- **Agreed:** retrieval observation, Source Revision, observable transition and editorial interpretation are separate.
- **Agreed:** validators, timestamps, HTTP status and disappearance are inputs, not standalone proof.
- **Agreed:** source transition types, current-state lifecycle and baselines remain distinct.
- **Agreed:** partial and rolling sources cannot clear state by absence.
- **Agreed:** Agenda Items are expectation records distinct from occurrence evidence.
- **Agreed:** rescheduling and cancellation require source evidence and preserve history.
- **Agreed:** missed expectation means not observed through required paths, not proof of non-occurrence.
- **Agreed:** clock passage alone creates no Lead, Candidate or reminder story.

### Topic 6 — Triage and event grouping

- **Agreed:** Work Items, Execution Batches and editorial grouping are separate.
- **Agreed:** decision Leads and context-only Leads are distinct; every decision Lead gets one disposition.
- **Agreed:** retrieval supplies context only; empty retrieval does not force new event and scores are non-authoritative.
- **Agreed:** Candidate admission requires exact current Candidate and identity collision checks.
- **Agreed:** same state, development, correction or reversal, related but distinct, no adequate prior match and uncertain remain distinct.
- **Agreed:** relationship and Candidate creation are orthogonal.
- **Agreed:** Hypothesis changes are append-only and destructive merge is prohibited.
- **Agreed:** coherent Leads may form one Candidate; unrelated Leads remain separate.
- **Agreed:** Candidate formation has no minimum source or domain count.
- **Agreed:** Urgent work may be expedited without lower standards.
- **Agreed:** proposals are structured and deterministically validated; confidence is metadata and failure is neutral.

### Topic 7 — Search and coverage audit

- **Agreed:** search and media indexes are supplemental channels and Comparators, never the sole Active Anchor or primary generic clock.
- **Agreed:** Search Purposes are bounded and every Request, Attempt, Outcome, Result Reference and review remains distinct.
- **Agreed:** one-query-per-beat and recursive agent search are prohibited.
- **Agreed:** models may propose but not execute or expand queries.
- **Agreed:** provider query data, result retention, model use and publisher rights are reviewed separately.
- **Agreed:** budgets are hard, purpose-specific and cannot trigger silent switching.
- **Agreed:** results enter normal workflow; ranks and snippets are non-authoritative.
- **Agreed:** prospective and retrospective audit remain separate and Gaps require review.
- **Agreed:** GDELT is Held, Brave is Rights Review Required and SearXNG or unofficial wrappers remain Research candidates.
- **Agreed:** Topic 7 authorises no provider, schedule, spending or run.

### Topic 8 — Shadow evaluation

- **Agreed:** evaluation has a separate authority scope with no public effect or production mutation.
- **Agreed:** owner-approved Plans and frozen Epochs are required; calibration and qualification remain separate.
- **Agreed:** fixtures, replay, live prospective shadow, prospective comparator audit, fault injection, review and ablation are distinct phases.
- **Agreed:** the event-level prospective universe uses several permitted paths without claiming complete ground truth.
- **Agreed:** prospective, retrospective, contemporaneous, later-outcome and unreviewable evidence remain distinct.
- **Agreed:** final labels require authorised human review and material blockers receive second review.
- **Agreed:** adapter, change, coverage, gate, triage, grouping, Candidate, timeliness, cost and operations are measured separately.
- **Agreed:** required slices cannot be hidden by aggregates and zero-tolerance failures block qualification.
- **Agreed:** source contribution uses event-level value, resilience, noise, rights, cost and reviewer burden.
- **Agreed:** the legacy pipeline and v1 dataset are comparison or regression aids only.
- **Needs experiment:** qualification thresholds, minimum exposure and actual promotion decisions require a future approved Plan and frozen Epoch.

### Topic 9 — Reliability and operations

- **Agreed:** every executable scope has a versioned Operational Profile; exact numerical objectives are approved separately.
- **Agreed:** due-work, jitter, missed-schedule, catch-up, leases and reconciliation prevent duplicate work and historical storms.
- **Agreed:** health is multidimensional and healthy unchanged requires a successful qualifying observation.
- **Agreed:** source health and portfolio Coverage Availability remain distinct; loss of every Active path triggers scoped containment.
- **Agreed:** strict access, transport, parser, egress and delivered-input controls apply.
- **Agreed:** retries, circuit breakers, quarantine and contingencies are bounded, explicit and role-aware.
- **Agreed:** queues preserve or explicitly close work, reserve Urgent capacity and revalidate stale work.
- **Agreed:** transition delivery is durable or reconcilable; store and audit failure fail closed.
- **Agreed:** backup, restore, replay, catch-up, monitoring, alerts, runbooks, security, canary and rollback are required.
- **Needs experiment:** cadence, freshness, retry, queue, capacity and alert numbers are set by a later qualification and admission package.
- **Agreed:** Operational Admission is evidence-backed, scoped and separate from activation.

### Topic 10 — Prioritisation and outcome vocabulary

- **Agreed:** authority, source semantics, deterministic gates, triage, relationship, Candidate admission and Handoff form a non-bypassable order.
- **Agreed:** outcome, reason, next action, status and processing priority are separate.
- **Agreed:** canonical Check, Signal, Lead, relationship, Candidate, Handoff, health and coverage-availability families are accepted.
- **Agreed:** outcomes are immutable for exact versions; later Revisions and re-evaluations create later decisions.
- **Agreed:** watch, hold and pending require inspectable conditions.
- **Agreed:** reasons are namespaced, versioned and append-only with explicit basis class and input references.
- **Agreed:** priority lanes are `CONTAINMENT`, `URGENT`, `TIME_SENSITIVE`, `PLANNED_WINDOW`, `ROUTINE` and `OPTIONAL_EVALUATION`.
- **Agreed:** deadlines, delay consequence, staleness, fairness, dependency readiness and deterministic identity order work within a lane.
- **Agreed:** urgency expedites work but never lowers gates.
- **Agreed:** volume, publisher tier, search rank, confidence, similarity, virality and legacy child status are non-authoritative proxies.
- **Agreed:** target discovery quotas, finance caps, Hong Kong guarantees and filler promotion are removed.
- **Agreed:** coverage is protected through scope, source portfolio, evaluation and coverage posture rather than Candidate quotas.
- **Agreed:** launch uses no global composite score.
- **Needs experiment:** any later stage-local scoring and thresholds require owner-approved evaluation against the ordinal baseline.
- **Agreed:** Topic 10 authorises no score, threshold, queue, model, source, run, spending or activation.

### Topic 11 — Locality scope and expansion

The Draft in [`../specs/editorial-automation/discovery-locality-scope-and-expansion.md`](../specs/editorial-automation/discovery-locality-scope-and-expansion.md) is ready for owner review. Its locality-uncommitted launch boundary, Locality Coverage Units, Event-Scoped Local Watch, selection criteria and Hong Kong district boundary are not Agreed merely because they are committed.

## Change discipline

At the end of each topic:

1. update the topic specification;
2. record Agreed, Rejected, Deferred, Needs experiment and Unresolved items here;
3. update cross-references without silently expanding scope;
4. commit bounded changes to the review branch; and
5. do not open the final pull request until the owner says the sequence is complete.
