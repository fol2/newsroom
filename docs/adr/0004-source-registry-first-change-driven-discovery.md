---
status: proposed
date: 2026-07-15
last_updated: 2026-07-16
owner_review: ready_with_topic_13
---

# Source-portfolio-first, change-driven and graph-aware news discovery

## Decision status

This ADR is ready for the product owner's final decision together with the integrated Topic 13 implementation plan.

The product owner has already accepted:

- discovery Topics 1–11;
- the governed GraphRAG and knowledge-projection specification;
- ADR 0001, which makes the relational ledger and governed objects authoritative and graph or indexes rebuildable projections; and
- ADR 0002, which selects SQLite for the initial canonical single-host ledger while requiring the graph workstream in the same programme.

This ADR remains **Proposed** until explicitly accepted, amended, split or rejected.

Acceptance would approve the discovery architecture boundary. It would not authorise code, source collection, search, graph installation, extraction, embedding, model calls, spending, shadow execution, canary or production activation.

## Context

The current Newsroom uses broad Brave queries, GDELT, broad media RSS feeds, one-link-per-call Gemini clustering, mutable event merges and source-count-based selection. It does not reliably distinguish:

- a new source item from a maintained-page revision;
- successful silence from source, parser or scheduler failure;
- a current-state transition from feed disappearance;
- a Planned Agenda expectation from occurrence evidence;
- same-state repetition from a development;
- media density from reader utility; or
- retrieval similarity from event identity.

Its default queries and quota-driven selection conflict with the Accepted utility-first coverage and prioritisation contracts.

The accepted review established that discovery must also avoid a second failure: building a graph-less relational model and adding GraphRAG later through a semantic migration. News event identity, long-running policy or case timelines, source dependencies and revision impact require graph-aware identities, trust states and ordered events from canonical schema v1.

## Proposed decision

Adopt a **source-portfolio-first, change-driven, graph-aware and scheduler-neutral discovery architecture**.

### Coverage before sources

An owner-approved coverage contract defines Active, Best-effort, explicit deferred and excluded development classes before source selection.

Every Active class has a credible candidate Anchor or a visible launch-blocking gap. A source, endpoint, query or model prompt cannot create or silently broaden the product scope.

### Versioned source portfolio

Discovery uses versioned Source Definitions with explicit:

- coverage mappings;
- source roles;
- portfolio functions;
- permitted-use references;
- observation models;
- identity and revision rules;
- Operational Profiles; and
- failure consequences.

The portfolio may include originating authorities, responsible operators, Planned Agenda sources, established-media radar, justified specialist or local radar, manual or reader channels and bounded search or index roles.

`Official`, `media`, `RSS` and `search` are transports or labels, not sufficient purposes.

### Source-native and selective collection

Prefer permitted APIs, webhooks, calendars, RSS or Atom interfaces. Use maintained-document or selector-based change detection only for an explicit high-value gap.

Whole-site crawling, generic browser automation and one recurring broad search query per beat are not the default.

RSS is a transport, not a coverage model.

### Change before editorial work

Routine checking establishes a source-specific observable transition before downstream editorial work.

A successful unchanged check ends without a Signal, Lead or model call.

Transport, parser, rights, authentication, rate-limit, budget, partial, stale and quarantine outcomes remain distinct from unchanged and no-news conclusions.

### Canonical append-only semantics

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

### Canonical relational authority from schema v1

The Newsroom uses one canonical identity, temporal, trust and ordered-event contract from schema v1.

The accepted SQLite relational ledger owns authoritative Newsroom records. Governed content-addressed object storage owns exact retained permitted bytes and hashes. Test, replay, shadow and later production use separate physical environments created from the same canonical migrations and event contract.

There is no discovery-only authority model followed by a graph-aware semantic migration.

### Governed GraphRAG from the initial programme

Graph, vector and full-text stores are rebuildable projections delivered in the same initial programme.

The initial GraphRAG lane includes:

- graph ontology and ledger-event projection mappings;
- explicit `OBSERVED`, `PROPOSED` and `ADMITTED` trust scopes;
- first-class entity-resolution proposals and decisions;
- reified editorial relation proposals and assertions;
- isolated Graphiti extraction;
- separate admission before governed projection;
- idempotent projectors with contiguous checkpoints and visible gaps;
- hybrid exact, full-text, vector and bounded graph retrieval; and
- named read-only retrieval tools.

Neo4j Community plus Graphiti is the first compatibility-focused proof-of-concept baseline. It is not automatic production admission.

Graphiti, similarity and graph proximity create proposals or Retrieval Context. They do not allocate authoritative entity, Event Hypothesis or Candidate identity and do not establish evidence.

### Models and extractors propose; deterministic authorities commit

Source adapters, retrieval components, models, extractors and agents do not create authoritative Leads, admitted entity or relation state, Event Hypotheses, Candidates, evidence or publication decisions directly.

Deterministic or authorised controllers validate and commit exact workflow transitions and admission decisions. Model and extraction output is structured, versioned, attributable and untrusted.

### Batching is not grouping

Several independent Work Items may share one worker invocation for efficiency. Batch membership does not establish event identity.

Retrieval score, graph path, source count, domain prestige, confidence and recency may rank context but cannot merge records, reject a Lead, create a development or admit a Candidate.

### Discovery is not evidence

Signals, Leads, search results, media headlines, Event Hypotheses, graph proposals and Story Candidates are discovery artefacts.

Evidence Intake independently retrieves and governs current permitted source material before creating Source Observations, claims or Evidence Packages.

Discovery, GraphRAG and retrieval actors have no public publishing credential.

### Search is bounded and supplemental

Search and media indexes are supplemental channels and Comparators. They are not:

- the sole Anchor for an Active obligation;
- the generic production clock;
- publication evidence; or
- recall ground truth.

Every Search Request has one accepted purpose, versioned query, privacy validation, rights decision and hard request, result, expansion, cost and downstream-work budgets. There is no silent provider switching.

### Planned Agenda is expectation plus confirmation

Known releases, proceedings, effective dates and deadlines use separate Agenda identities and occurrence-confirmation paths.

Clock passage opens or changes monitoring work. It does not create a Lead, Candidate or reminder story.

### Health and coverage are separate

Successful silence requires a complete qualifying check. Last successful observation, last complete observation and last source change remain separate.

Component health and portfolio Coverage Availability are evaluated separately. A Comparator cannot repair a failed Anchor's health. Loss of every credible healthy path for an Active obligation triggers scoped containment.

Graph projection health is also separate. Projection lag, gap or outage is never represented as no prior event or no relationship.

### Graph-degraded operation

Healthy scheduling, source collection, change detection, deterministic gates and durable Lead creation may continue when the graph is unavailable and their own dependencies are healthy.

Graph-dependent work uses an approved exact relational fallback or enters Watch or Operational Hold. Candidate admission never treats graph outage as no match. Exact identity and Candidate-collision checks remain relational authority.

Graph independence is a resilience boundary, not permission to postpone GraphRAG.

### Evaluation before authority

Sources, adapters, observation models, triage policy, search roles, entity resolution, relation extraction, projectors and retrievers earn authority through pre-registered fixture, replay, prospective shadow, comparator, fault-injection and operational evidence.

No source, provider, model, graph engine, legacy pipeline or union of paths is complete ground truth.

Complete end-to-end live-shadow qualification includes the governed graph, hybrid retrieval, projection-gap behaviour and GraphRAG evaluation. Adapter-only checks may occur earlier but do not qualify the complete target architecture.

### Ordinal priority and no quotas

Discovery uses semantic outcomes, structured reasons and ordinal lanes:

```text
CONTAINMENT
URGENT
TIME_SENSITIVE
PLANNED_WINDOW
ROUTINE
OPTIONAL_EVALUATION
```

Priority never creates eligibility.

Launch has no governing global composite discovery score, category quota, finance cap, Hong Kong guaranteed slot or filler target.

### Locality-aware, locality-uncommitted launch

Material local UK stories remain in scope wherever discovered, but no fixed UK locality receives systematic all-topic monitoring by default.

Locality expansion requires an exact geography-plus-source-class decision and its own evidence. Hong Kong remains one product geography without district filters or district-completeness promises.

### Scheduler neutrality

The semantic architecture does not require Hermes, cron or another agent framework.

The implementation plan provides a repository-owned deterministic command surface. Hermes or another scheduler may invoke bounded commands and named retrieval tools without becoming authority.

## Implementation and migration

Implementation follows [`../plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md`](../plans/2026-07-16-004-integrated-discovery-graphrag-implementation.md).

The proposed migration is side-by-side:

- canonical schema v1 is created directly;
- legacy `links` and `events` remain untouched initially;
- legacy records may be read only as attributed Comparator context;
- SQLite authority and graph-aware event contracts are implemented together;
- graph projection begins before live source activation;
- generic adapters and fixtures precede named live sources;
- entity and relation proposals, admission and hybrid retrieval precede complete live shadow;
- an evaluation Evidence Intake sink precedes real downstream integration;
- production requires separate Evaluation Plan, Operational Admission, graph admission, canary and activation; and
- legacy retirement is explicit and reversible.

## Positive consequences

- No model work is spent merely to prove nothing changed.
- Maintained guidance revisions and current-state transitions become first-class inputs.
- Official changes need not wait for media repetition.
- Unscheduled incidents retain legitimate media and operator radar paths.
- Search remains useful without defining coverage or uncontrolled cost.
- Failures, stale sources, partial responses and successful silence remain distinguishable.
- Every Candidate is reconstructable from exact upstream versions.
- GraphRAG supports multilingual event identity, long-running timelines, source dependencies and revision impact from the initial programme.
- Graph or index replacement does not migrate editorial authority.
- Hong Kong coverage is protected by real source and evaluation obligations rather than quotas.
- Local stories remain reportable without a false all-UK locality claim.
- The new system can be evaluated beside the legacy pipeline before cutover.

## Costs and trade-offs

- Source qualification, rights review and source-specific identity rules require editorial and engineering work.
- Append-only authority, graph proposals, projectors and rebuilds are more complex than mutable event rows.
- GraphRAG adds ontology, entity-resolution, embedding, model, licence and operational evaluation work.
- Human review is required for credible evaluation labels, relation admission and Coverage Gaps.
- Two systems coexist during shadow and canary.
- Launch may remain blocked while an Active class or required graph capability lacks a credible path.

## Rejected alternatives

### Generic search as production clock

Rejected because it spends on unchanged periods, inherits index bias, cannot prove recall and conflicts with source-specific change and failure semantics.

### Official-only discovery

Rejected because unscheduled incidents, lived impact and official blind spots require media, operator or other permitted radar roles.

### RSS-only discovery

Rejected because RSS does not cover every maintained page, current-state API, Agenda, webhook or service transition and does not define identity or revision meaning.

### Search-zero architecture

Rejected as a universal rule. Search remains permitted for bounded radar, audit, Gap, Planned recovery, supplemental and outage roles.

### Graph as authoritative truth

Rejected because probabilistic extraction, trust mixing and graph-engine recovery cannot enter the editorial authority boundary.

### Graph-less implementation followed by GraphRAG

Rejected because it creates a planned semantic migration in identity, ontology, event history, retrieval and source-revision impact.

### Relational and graph synchronous co-authority

Rejected because partial failure creates irreconcilable truth and graph replacement becomes an authority migration.

### In-place mutation of the legacy pool

Rejected because legacy URL, event, merge and ranking semantics conflict with Accepted identity, append-only, triage, GraphRAG and outcome contracts.

### Big-bang replacement

Rejected because it combines source, semantic, graph, model, evaluation, operational and cutover risk in one release. Dependency-ordered pull requests remain part of one target architecture and one final activation boundary.

### Global composite scoring and quotas

Rejected for launch because volume, confidence, recency, category and geography cannot compensate for failed scope, rights, integrity, novelty or evidence boundaries.

### Mandatory London-first locality

Rejected because no evidence justifies a fixed locality or source-class commitment and convenience is not coverage.

## Non-decisions

This ADR does not select:

- exact source versions;
- polling, freshness or retry values;
- final ontology details;
- model, prompt, embedding or chunking versions;
- final graph engine or commercial licence approval;
- exact Neo4j deployment;
- retrieval thresholds, graph depth or tool budgets;
- search provider;
- scheduler deployment;
- Evidence Intake transport;
- cloud, observability or on-call platform;
- Locality Coverage Unit; or
- production activation date.

Those decisions remain governed by Accepted specifications, the Topic 13 plan, Evaluation Plans, Operational Profiles and explicit owner approvals.

## Owner decision required

Accepting this ADR would approve the architecture above and allow the Topic 13 plan to organise implementation work. It would still authorise no runtime action by itself.