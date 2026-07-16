---
status: proposed
date: 2026-07-15
last_updated: 2026-07-16
owner_review: pending_graphrag_and_revised_plan
---

# Source-portfolio-first, change-driven news discovery

## Decision status

This ADR remains **Proposed**. The product owner accepted discovery Topics 1–11 but rejected deferring GraphRAG behind a separate discovery-only implementation.

Final review now depends on:

- [`../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md);
- ADR 0001's authority and rebuildable-projection boundary;
- ADR 0002's integrated SQLite-ledger decision; and
- a rewritten implementation and migration plan that delivers the relational ledger and GraphRAG workstreams from canonical schema v1.

Acceptance of this ADR would approve the discovery architecture boundary. It would not authorise implementation, graph-engine installation, source collection, search, extraction, embeddings, model calls, spending, shadow execution, canary or production activation.

## Context

The current Newsroom uses broad Brave queries, GDELT, broad media RSS feeds, one-link-per-call Gemini clustering, mutable event merges and source-count-based selection. It does not reliably distinguish a new item, maintained-page revision, successful silence, parser failure, source outage or Planned occurrence. Its default queries and quotas conflict with the utility-first coverage contract.

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

Those contracts replace the assumption that a source list, generic search loop or LLM clustering prompt can define discovery architecture.

The remaining architecture question is not whether discovery should use GraphRAG. The owner has required that graph-aware identity, temporal, trust, projection and hybrid-retrieval contracts exist from inception rather than being added after a separate discovery data model has already shipped.

## Proposed decision

Adopt a **source-portfolio-first, change-driven, graph-aware and scheduler-neutral discovery architecture** with the following boundaries.

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

Retrieval similarity, graph proximity, source count, domain prestige, confidence and recency may rank context but cannot create an Event Hypothesis, merge records, reject a Lead or admit a Candidate.

### Governed GraphRAG from canonical schema v1

The canonical identity, temporal, trust and ordered-event contract includes graph projection from its first schema version. The target does not plan a graph-less discovery model followed by later GraphRAG migration.

The authority boundary is:

```text
relational editorial ledger + governed object store
        ↓ ordered idempotent projection
knowledge graph + vector/full-text indexes
        ↓ bounded named retrieval tools
triage and research context
```

Graph, vector and full-text stores are rebuildable projections, not independent editorial or evidence authority.

Graphiti or another extractor creates immutable entity and relation proposals in an isolated workspace. A separate admission decision is required before governed projection. `OBSERVED`, `PROPOSED` and `ADMITTED` trust scopes remain explicit.

GraphRAG participates in initial event and development retrieval, long-running process timelines and source-revision impact analysis. It returns context and proposals; deterministic controllers retain Hypothesis and Candidate authority.

Graph outage, lag or projection gap is not `no match`. An approved exact fallback may be used for a bounded route; otherwise graph-dependent work enters Watch or Operational Hold.

### Discovery is not evidence

Signals, Leads, search results, media headlines, graph paths, Event Hypotheses and Story Candidates are discovery artefacts. Evidence Intake independently retrieves and governs current permitted source material.

Discovery and GraphRAG have no public publishing credential.

### Search is bounded and supplemental

Search and media indexes are supplemental channels and Comparators. They are not the sole Anchor for an Active obligation, the primary generic production clock, evidence or recall ground truth.

Every Search Request has one accepted purpose, versioned query, privacy validation, rights decision and hard request, result, expansion, cost and downstream-work budget. There is no silent provider switching.

### Planned Agenda is expectation plus confirmation

Known releases, proceedings, effective dates and deadlines use separate Agenda identities and occurrence-confirmation paths. Clock passage does not create a Lead, Candidate or reminder story.

### Health and coverage are separate

Successful silence requires a complete qualifying check. Last successful observation, last complete observation and last source change remain separate.

Component health, graph-projection health and portfolio Coverage Availability are evaluated separately. A Comparator cannot repair a failed Anchor. A graph gap cannot be hidden by a later checkpoint. Loss of every credible healthy path for an Active obligation triggers scoped containment.

### Evaluation precedes authority

Sources, adapters, observation models, triage policy, search roles, graph extraction, entity resolution, relation admission, projectors, retrieval tools and workers earn authority through pre-registered fixtures, replay, prospective shadow, ablation, fault injection and operational evidence.

No source, provider, graph engine, legacy pipeline or union of paths is complete ground truth. Shadow has no public effect and does not graduate silently into production.

The first GraphRAG qualification lane is Neo4j Community plus Graphiti. It is a compatibility-focused POC, not automatic production selection. A challenger is introduced only after a measured blocker or owner-approved comparison purpose.

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

### Scheduler neutrality

The semantic architecture does not require Hermes, cron or a particular agent framework. A repository-owned deterministic command surface may be invoked by approved orchestration later.

Scheduler neutrality does not imply storage or knowledge-contract neutrality. The ledger, object, graph projection and hybrid retrieval contracts must be decided before implementation.

## Implementation and migration boundary

The first Topic 12 implementation Draft is not accepted because it proposed a separate discovery-only SQLite sequence with GraphRAG deferred.

The revised plan must:

- implement one canonical identity, temporal, trust and ordered-event spine from schema v1;
- implement the relational authority and graph projection as one delivery programme;
- use separate target identities from legacy `links` and `events`;
- keep legacy outcomes read-only as Comparator context;
- implement graph ontology, projector, Graphiti proposal or admission and hybrid retrieval in the first architectural milestones;
- allow offline adapter fixtures before graph completion but require GraphRAG before complete live-shadow qualification;
- use an evaluation Evidence Intake sink before real downstream integration;
- require explicit Evaluation Plan, Operational Admission, canary and activation; and
- retire legacy paths explicitly and reversibly.

## Consequences

### Positive

- No model work is spent merely to prove nothing changed.
- Maintained guidance revisions and current-state transitions become first-class discovery inputs.
- Official changes need not wait for media repetition.
- Unscheduled incidents retain legitimate media and operator radar paths.
- GraphRAG improves cross-language event grouping, long-running process context and revision-impact discovery from the first target implementation.
- The graph contract does not require a later identity or event-model rewrite.
- Search remains useful without defining the coverage model or creating an uncontrolled cost centre.
- Failures, stale sources, partial responses and successful silence remain distinguishable.
- Every Candidate is reconstructable from exact upstream identities and versions.
- Hong Kong coverage is protected by real source and evaluation obligations rather than quotas.
- Local stories remain reportable without a false all-UK locality claim.
- The new system can be evaluated beside the legacy pipeline before cutover.

### Costs and trade-offs

- Canonical ontology, entity resolution, graph projection and retrieval governance increase the first implementation scope.
- Source qualification, rights review and source-specific identity rules require editorial and engineering work.
- Append-only semantics and projections are more complex than mutable link and event rows.
- Neo4j and Graphiti introduce another local process, resource footprint, licence review and operational surface.
- Human review is required to construct credible relation, entity, evaluation and Coverage Gap labels.
- Some exact polling, graph depth, threshold, source, model and provider decisions remain evidence-dependent.
- Two systems coexist during shadow and canary, increasing temporary operational complexity.
- Launch may remain blocked while an Active class or required GraphRAG slice lacks credible evidence.

## Rejected alternatives

### Keep generic search as the production clock

Rejected because it spends on unchanged periods, inherits index bias, cannot prove recall and conflicts with source-specific change and failure semantics.

### Official-only discovery

Rejected because unscheduled incidents, lived impact and official blind spots require established-media, operator or other permitted radar roles.

### RSS-only discovery

Rejected because RSS does not cover every maintained page, current-state API, Planned Agenda, webhook or service transition and does not define identity or revision meaning.

### Search-zero architecture

Rejected as a universal rule. Search remains permitted for bounded radar, audit, Gap, Planned recovery, supplemental and outage roles under strict controls.

### Graph-less discovery followed by later GraphRAG

Rejected because it would create a planned migration of identity, event, temporal and retrieval semantics after the core discovery implementation already exists.

### Make the graph authoritative

Rejected because probabilistic extraction, trust mixing and graph-engine recovery would enter the editorial correctness boundary.

### Synchronous ledger-and-graph co-authority

Rejected because partial failure would create irreconcilable truth without a distributed transaction.

### In-place mutation of the legacy pool

Rejected as the primary migration path because legacy URL, event, merge and ranking semantics conflict with Accepted identity, append-only, triage and outcome contracts.

### Big-bang replacement

Rejected because it would combine semantic, graph, source, model, evaluation, operational and cutover risk in one release.

### Global composite scoring and quotas

Rejected for launch because volume, confidence, recency, category and geography cannot compensate for failed scope, rights, integrity, novelty or evidence boundaries.

### Mandatory London-first locality

Rejected because no evidence yet justifies a fixed locality or source-class commitment and convenience is not a coverage decision.

## Non-decisions

This ADR does not finally select:

- exact sources or source versions;
- polling intervals, freshness objectives or retry thresholds;
- model, prompt, embedding or extraction version;
- final production graph engine or licence;
- search provider;
- scheduler or Hermes deployment;
- exact relational and graph physical schema;
- Evidence Intake transport;
- cloud, observability or on-call platform;
- Locality Coverage Unit; or
- production activation date.

Those decisions remain governed by the relevant Accepted contracts, GraphRAG review, Evaluation Plans, Operational Profiles and owner approvals.

## Owner decision required

This ADR is not ready for final acceptance until Topic 12, ADR 0001, ADR 0002 and the revised integrated implementation plan are reviewable together. Acceptance would still authorise no runtime action by itself.
