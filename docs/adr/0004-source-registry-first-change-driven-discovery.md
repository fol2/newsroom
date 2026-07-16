---
status: proposed
date: 2026-07-15
last_updated: 2026-07-16
owner_review: ready_final
---

# Source-portfolio-first, change-driven and natively GraphRAG news discovery

## Decision status

This ADR remains **Proposed** and now requires only the product owner's explicit final decision.

The product owner has accepted:

- discovery Topics 1–11;
- the governed and native-production GraphRAG contracts;
- ADR 0001, ADR 0002 and ADR 0005; and
- the native GraphRAG production implementation plan.

Those accepted records establish the authority, native-production, migration and implementation boundaries on which this ADR depends.

Acceptance of this ADR would approve the consolidated discovery architecture boundary. It would authorise no code, source collection, search, graph installation, extraction, embeddings, model calls, spending, shadow execution, canary or production activation.

## Context

The current Newsroom relies on broad Brave queries, GDELT, broad media RSS, one-link-per-call Gemini clustering, mutable event merges and source-count-based selection. It does not reliably distinguish:

- a new source item from a maintained-page revision;
- successful silence from source, parser or scheduler failure;
- a current-state transition from feed disappearance;
- a Planned Agenda expectation from occurrence evidence;
- same-state repetition from a development;
- media density from reader utility; or
- retrieval similarity from event identity.

The accepted review also established that event identity, multilingual entities, long-running policies and cases, source dependencies and revision impact cannot be safely added after a graph-less product has already fixed a different semantic model.

## Proposed decision

Adopt a **source-portfolio-first, change-driven, natively GraphRAG and scheduler-neutral discovery architecture**.

### Coverage before sources

The owner-approved coverage contract defines Active, Best-effort, explicit deferred and excluded development classes before source selection.

Every Active class has a credible candidate Anchor or a visible launch-blocking gap. A source, endpoint, query, graph result or model prompt cannot create or silently broaden product scope.

### Versioned source portfolio

Every executable Source Definition Version declares:

- coverage mapping;
- source role and portfolio function;
- rights and permitted use;
- observation model;
- item and Revision identity;
- Operational Profile; and
- failure and coverage consequence.

The portfolio may include originating authorities, responsible operators, Planned Agenda sources, established-media radar, justified specialist or local radar, manual or reader channels and bounded search or index roles.

`Official`, `media`, `RSS` and `search` are not sufficient purposes.

### Source-native and selective collection

Prefer permitted APIs, webhooks, calendars, RSS or Atom. Use maintained-document or selector-based change detection for an explicit high-value gap.

Whole-site crawling, generic browser automation and one broad recurring search query per beat are not defaults. RSS is a transport, not a coverage model.

### Change before editorial work

Routine checking establishes a source-specific observable transition before editorial work.

A successful unchanged check creates no Signal, Lead or model call. Transport, parser, rights, authentication, rate-limit, budget, partial, stale and quarantine outcomes remain distinct from unchanged and no-news conclusions.

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

Current status is rebuildable. Retries, later Revisions, correction, consolidation, split and downstream feedback do not erase earlier history.

### Canonical relational authority

The accepted SQLite ledger owns the Newsroom's authoritative identities, versions, proposals, admission decisions, outcomes and ordered history. Governed content-addressed objects own exact retained permitted bytes and hashes.

There is one canonical identity, temporal, trust and ordered-event contract from schema v1. Test, replay, shadow and production environments use the same migrations and event semantics for their implemented scope.

### Native GraphRAG production subsystem

Graph, vector and full-text stores are rebuildable projections, but GraphRAG is a mandatory native subsystem of the first production deployment.

The project owns:

- graph ontology and event mapping;
- graph, vector and full-text projectors;
- explicit `OBSERVED`, `PROPOSED` and `ADMITTED` trust scopes;
- entity-resolution proposals and decisions;
- reified editorial relation proposals and assertions;
- isolated Graphiti extraction;
- separate admission before governed projection;
- checkpoints, gaps, dead letters and generations;
- exact, full-text, vector and bounded graph retrieval; and
- named read-only tools.

There is no graph-less production, canary or complete live-shadow target and no later GraphRAG graduation decision.

Neo4j Community plus Graphiti is the accepted initial production-target implementation under ADR 0005 and the native-production contract. Qualification decides whether the exact versions are ready. Failure requires repair or replacement before activation and does not permit a graph-less release.

Mandatory production deployment does not make the graph authoritative. Graphiti, embeddings, similarity and graph paths remain proposals or Retrieval Context.

### Models and extractors propose; authorities commit

Source adapters, retrieval components, models, extractors and agents do not directly create authoritative Leads, admitted entities or relations, Event Hypotheses, Candidates, evidence or publication decisions.

Deterministic or authorised controllers validate and commit transitions and admission decisions. Output remains structured, versioned, attributable and untrusted.

### Batching is not grouping

Several Work Items may share one invocation for efficiency. Batch membership does not establish event identity.

Retrieval rank, graph path, source count, domain prestige, confidence and recency may rank context but cannot merge records, reject a Lead, create a development or admit a Candidate.

### Discovery is not evidence

Signals, Leads, search results, media headlines, graph proposals, Event Hypotheses and Story Candidates remain discovery artefacts.

Evidence Intake independently retrieves and governs current permitted source material before creating Source Observations, claims or Evidence Packages. Discovery and GraphRAG have no public publishing credential.

### Search is bounded and supplemental

Search and media indexes are supplemental channels and Comparators. They are not the sole Anchor for an Active obligation, the generic production clock, publication evidence or recall ground truth.

Every Search Request has one accepted purpose, versioned query, privacy validation, rights decision and hard request, result, expansion, cost and downstream-work budgets. There is no silent provider switching.

### Planned Agenda is expectation plus confirmation

Known releases, proceedings, effective dates and deadlines use separate Agenda identities and occurrence-confirmation paths. Clock passage creates monitoring work, not a Lead, Candidate or reminder story.

### Health and coverage are separate

Successful silence requires a complete qualifying check. Source health, graph health and portfolio Coverage Availability are separate assessments.

Graph outage, lag or gap never becomes no prior match. Safe collection may continue, while graph-dependent work uses an accepted exact fallback or enters Watch or Operational Hold. Temporary outage is degraded operation in the mandatory GraphRAG deployment, not a graph-free product profile.

### Evaluation precedes activation

Sources, adapters, observation models, triage, extractors, graph projectors, retrieval tools and search roles earn exact-version authority through pre-registered fixture, replay, integrated shadow, comparator, fault-injection, security, rights and operational evidence.

Qualification verifies mandatory components. It does not decide whether GraphRAG exists.

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

Priority never creates eligibility. There is no governing global composite score, category or finance cap, Hong Kong guaranteed slot or filler target.

### Locality-aware and locality-uncommitted launch

Material UK local stories remain in scope wherever discovered, but no fixed UK locality receives systematic all-topic monitoring by default. Hong Kong remains one product geography without district filters or completeness promises.

### Scheduler-neutral orchestration

The semantic architecture does not depend on Hermes, cron or another scheduler. The repository owns deterministic commands that an approved scheduler invokes.

### Side-by-side migration

The target is built beside the legacy pipeline:

- legacy IDs, clusters, merge winners, scores and quotas are not canonical authority;
- no silent dual write exists;
- legacy data may be used only as attributed Comparator context;
- canonical schema v1 is created directly;
- complete shadow and canary include the native GraphRAG subsystem;
- production activation is explicit; and
- legacy retirement is explicit and reversible.

## Consequences

### Positive

- unchanged periods consume no model work;
- maintained guidance and current-state transitions become first-class;
- direct official changes do not wait for media repetition;
- unscheduled incidents retain legitimate operator and media radar;
- event identity and long-running context are graph-aware from schema v1;
- GraphRAG is part of the project and production deployment rather than an external experiment;
- failures, gaps, stale data and successful silence remain distinguishable;
- every Candidate remains reconstructable; and
- no later graph semantic migration is planned.

### Costs and trade-offs

- the initial programme must build and operate both authority and knowledge-projection planes;
- ontology, entity resolution, proposal admission and projection recovery add complexity;
- Neo4j, Graphiti, embeddings and retrieval require licence, resource, security and quality evidence;
- source qualification and rights review remain substantial work;
- two runtime systems coexist during shadow and canary; and
- production remains blocked if a mandatory GraphRAG implementation or Active coverage path is not ready.

## Rejected alternatives

- generic search as production clock;
- official-only or RSS-only discovery;
- search-zero as a universal rule;
- mutable in-place migration of the legacy pool;
- global scoring and quotas;
- mandatory London-first locality;
- graph as editorial authority;
- synchronous SQLite-and-graph co-authority writes;
- GraphRAG as a POC, optional plugin or later product stage; and
- activating graph-less production after a graph-engine qualification failure.

## Non-decisions

This ADR does not by itself select or activate exact:

- source versions;
- polling intervals and thresholds;
- model, prompt, embedding or chunking versions;
- search provider;
- Neo4j edition, packaging or backup mechanism;
- final admitted graph-engine version;
- scheduler deployment;
- Evidence Intake transport;
- hosting and observability services;
- Locality Coverage Unit; or
- production activation date.

## Owner decision required

The supporting specifications, architecture ADRs and implementation plan are Accepted. The product owner must now explicitly accept, amend, split or reject this consolidated discovery architecture. Any acceptance still authorises no runtime action.
