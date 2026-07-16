---
status: proposed
date: 2026-07-15
last_updated: 2026-07-16
owner_review: ready
---

# Source-portfolio-first, change-driven news discovery

## Decision status

This ADR is ready for the product owner's final decision after the Topic 1–11 discovery specifications were accepted. It remains **Proposed** until the owner explicitly accepts, amends, splits or rejects it.

Acceptance of this ADR would approve the architecture boundary. It would not authorise implementation, source collection, search, model calls, spending, shadow execution, canary or production activation. Those actions remain governed by the Accepted specifications and the Topic 12 implementation plan.

## Context

The current Newsroom uses broad Brave queries, GDELT, broad media RSS feeds, one-link-per-call Gemini clustering, mutable event merges and source-count-based selection. It does not reliably distinguish a new item, a maintained-page revision, successful silence, parser failure, source outage or planned occurrence. Its default queries and quotas also conflict with the utility-first coverage contract.

The owner-led review established Accepted contracts for:

1. coverage;
2. end-to-end workflow;
3. record identity and lineage;
4. source roles and selection;
5. source change and Planned Agenda;
6. triage and event grouping;
7. bounded search and coverage audit;
8. shadow evaluation;
9. reliability and operations;
10. outcomes and ordinal prioritisation; and
11. locality scope.

Those contracts replace the earlier assumption that a source list, one generic search loop or an LLM clustering prompt can define discovery architecture.

## Proposed decision

Adopt a **source-portfolio-first, change-driven, scheduler-neutral discovery architecture** with the following boundaries.

### Coverage before sources

An owner-approved coverage contract defines Active, Best-effort, explicit deferred and excluded development classes before source selection. Every Active class has a credible candidate Anchor or a visible launch-blocking gap.

### Versioned source portfolio

Discovery uses versioned Source Definitions with explicit source roles, portfolio functions, rights references, observation models and Operational Profiles.

The portfolio may include:

- originating authorities;
- responsible operators;
- Planned Agenda sources;
- established-media radar;
- justified specialist or local radar;
- manual, editor and reader lead channels; and
- bounded search or index roles accepted under the search contract.

`Official`, `media`, `RSS` and `search` are not sufficient purposes on their own.

### Source-native, selective transport

Prefer permitted APIs, webhooks, calendars, RSS or Atom interfaces. Use maintained-document or selector-based change detection only for an explicit high-value gap. Whole-site crawling and generic browser automation are not the default.

RSS is a transport, not a coverage model.

### Change before editorial work

Routine checking establishes a source-specific observable transition before downstream editorial work. Successful unchanged checks end without a Signal, Lead or model call.

Transport, parser, rights, authentication, rate, partial and quarantine failures remain distinct from unchanged and no-news conclusions.

### Append-only discovery semantics

The architecture separates and versions:

```text
Trigger
→ Check Request
→ Attempt
→ Outcome
→ Source Item
→ Source Revision
→ Representation
→ Occurrence
→ Discovery Signal
→ Gate Decision
→ News Lead
→ Triage Work Item
→ Triage Proposal
→ Event Hypothesis Version
→ Candidate Admission
→ Story Candidate Version
→ Evidence Handoff
```

Current status is rebuildable. Retries, later revisions, consolidation, split, feedback and correction do not erase earlier history.

### Models propose; controllers commit

Source adapters, retrieval components, models and agents do not create authoritative Leads, Event Hypotheses, Candidates, evidence or publication decisions directly.

Deterministic controllers validate and commit exact workflow transitions. Model output is structured, versioned and untrusted.

### Batching is not grouping

Several independent Work Items may share one worker invocation for efficiency. Batch membership does not establish event identity.

Retrieval similarity, source count, domain prestige, confidence and recency may rank context but cannot create an Event Hypothesis, merge records, reject a Lead or admit a Candidate.

### Discovery is not evidence

Signals, Leads, search results, media headlines, Event Hypotheses and Story Candidates are discovery artefacts. Evidence Intake independently retrieves and governs current permitted source material.

Discovery has no public publishing credential.

### Search is bounded and supplemental

Search and media indexes are supplemental channels and Comparators. They are not the sole Anchor for an Active obligation, the primary generic production clock, evidence or recall ground truth.

Every Search Request has one accepted purpose, versioned query, privacy validation, rights decision and hard request, result, expansion, cost and downstream-work budget. There is no silent provider switching.

### Planned Agenda is expectation plus confirmation

Known releases, proceedings, effective dates and deadlines use separate Agenda identities and occurrence-confirmation paths. Clock passage does not create a Lead, Candidate or reminder story.

### Health and coverage are separate

Successful silence requires a complete qualifying check. Last successful observation, last complete observation and last source change remain separate.

Component health and portfolio Coverage Availability are evaluated separately. A Comparator cannot repair the health of a failed Anchor. Loss of every credible healthy path for an Active obligation triggers scoped containment.

### Evaluation precedes authority

Sources, adapters, observation models, triage policy, search roles and workers earn authority through pre-registered fixture, replay, prospective shadow, comparator, fault-injection and operational evidence.

No source, provider, legacy pipeline or union of paths is complete ground truth. Shadow has no public effect and does not graduate silently into production.

### Ordinal priority, no discovery quotas

Discovery uses semantic outcomes, structured reasons and ordinal lanes:

```text
CONTAINMENT
URGENT
TIME_SENSITIVE
PLANNED_WINDOW
ROUTINE
OPTIONAL_EVALUATION
```

Priority never creates eligibility. Launch has no governing global composite discovery score, category quota, finance cap, Hong Kong guaranteed slot or filler target.

### Locality-aware, locality-uncommitted launch

Material local UK stories remain in scope wherever discovered, but no fixed UK locality receives systematic all-topic monitoring by default. Locality expansion requires an exact geography-plus-source-class decision and its own evidence.

Hong Kong remains one product geography without district filters or district-completeness promises.

### Scheduler and storage neutrality at the architecture layer

The semantic architecture does not require Hermes, cron, a particular agent framework, queue, database or cloud provider.

The Topic 12 plan proposes a repository-owned deterministic command surface and a separate SQLite-backed `DiscoveryStore` for offline, replay and shadow implementation. Those are scoped implementation choices and do not make Hermes or SQLite product-wide architectural requirements.

## Implementation and migration

Implementation follows [`../plans/2026-07-16-003-discovery-implementation-and-migration.md`](../plans/2026-07-16-003-discovery-implementation-and-migration.md).

The proposed migration is side-by-side:

- discovery v2 uses separate identities and a separate store;
- legacy `links` and `events` remain untouched initially;
- legacy outcomes may be read only as Comparator context;
- generic adapters and fixtures precede live source activation;
- an evaluation Evidence Intake sink precedes real downstream integration;
- live shadow requires an explicit Evaluation Plan;
- production requires separate operational admission, canary and activation; and
- legacy retirement is explicit and reversible.

## Consequences

### Positive

- No model work is spent merely to prove nothing changed.
- Maintained guidance revisions and current-state transitions become first-class discovery inputs.
- Official changes need not wait for media repetition.
- Unscheduled incidents retain legitimate media and operator radar paths.
- Search remains useful without defining the coverage model or creating an uncontrolled cost centre.
- Failures, stale sources, partial responses and successful silence remain distinguishable.
- Every Candidate is reconstructable from exact upstream identities and versions.
- Hong Kong coverage is protected by real source and evaluation obligations rather than quotas.
- Local stories remain reportable without a false all-UK locality claim.
- The new system can be evaluated beside the legacy pipeline before cutover.

### Costs and trade-offs

- Source qualification, rights review and source-specific identity rules require editorial and engineering work.
- Append-only semantics and projections are more complex than mutable link and event rows.
- Human review is required to construct credible evaluation labels and Coverage Gaps.
- Some exact polling, threshold, source and provider decisions remain evidence-dependent.
- Two systems coexist during shadow and canary, increasing temporary operational complexity.
- Launch may remain blocked while an Active class lacks a credible path.

## Rejected alternatives

### Keep generic search as the production clock

Rejected because it spends on unchanged periods, inherits index bias, cannot prove recall and conflicts with source-specific change and failure semantics.

### Official-only discovery

Rejected because unscheduled incidents, lived impact and official blind spots require established-media, operator or other permitted radar roles.

### RSS-only discovery

Rejected because RSS does not cover every maintained page, current-state API, Planned Agenda, webhook or service transition and does not itself define identity or revision meaning.

### Search-zero architecture

Rejected as a universal rule. Search remains permitted for bounded radar, audit, Gap, Planned recovery, supplemental and outage roles under strict controls.

### In-place mutation of the legacy pool

Rejected as the primary migration path because legacy URL, event, merge and ranking semantics conflict with the Accepted identity, append-only, triage and outcome contracts.

### Big-bang replacement

Rejected because it would combine semantic, source, model, evaluation, operational and cutover risk in one release.

### Global composite scoring and quotas

Rejected for launch because volume, confidence, recency, category and geography cannot compensate for failed scope, rights, integrity, novelty or evidence boundaries.

### Mandatory London-first locality

Rejected because no evidence yet justifies a fixed locality or source-class commitment and convenience is not a coverage decision.

## Non-decisions

This ADR does not select:

- exact sources or source versions;
- polling intervals, freshness objectives or retry thresholds;
- model, prompt or retrieval engine;
- search provider;
- scheduler or Hermes deployment;
- product-wide database architecture;
- Evidence Intake transport;
- cloud, observability or on-call platform;
- Locality Coverage Unit; or
- production activation date.

Those decisions remain governed by the relevant Accepted contracts, Evaluation Plans, Operational Profiles and owner approvals.

## Owner decision required

Accepting this ADR would approve the architecture above and allow the Topic 12 plan to organise implementation work. It would still authorise no runtime action by itself.
