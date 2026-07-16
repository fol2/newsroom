# Governed GraphRAG and knowledge-projection specification

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted discovery contracts:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md), [`discovery-workflow.md`](discovery-workflow.md), [`discovery-record-semantics.md`](discovery-record-semantics.md), [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md), [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md), [`discovery-triage-and-event-grouping.md`](discovery-triage-and-event-grouping.md), [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md), [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md), [`discovery-reliability-and-operations.md`](discovery-reliability-and-operations.md), [`discovery-prioritisation-and-outcomes.md`](discovery-prioritisation-and-outcomes.md), [`discovery-locality-scope-and-expansion.md`](discovery-locality-scope-and-expansion.md)  
**Related research:** [`../../research/2026-07-15-local-agentic-graph-rag-database-options.md`](../../research/2026-07-15-local-agentic-graph-rag-database-options.md), [`../../research/2026-07-15-database-architecture.md`](../../research/2026-07-15-database-architecture.md)  
**Related proposed decisions:** [`../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md), [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md)  
**Decision state:** The authority boundary, graph ontology, extraction and admission model, projection contract, hybrid retrieval role, initial proof-of-concept engine and implementation timing below are proposals. Committing this Draft does not install a graph engine, select a production licence, authorise source access, submit content to a model, run Graphiti, spend money, start shadow operation or activate production.  
**Supersedes:** The assumption in the first Topic 12 Draft that GraphRAG could be deferred until after a separate discovery-only implementation.

## Purpose

Define GraphRAG as a first-class part of the Newsroom's initial target architecture rather than a later enhancement, while preserving a deterministic and reconstructable authority boundary.

The specification prevents two opposite failures:

1. building a relational discovery system whose identities, event model and retrieval contracts must later be redesigned for a graph; and
2. making an LLM-extracted graph the authoritative record for source history, editorial decisions, evidence or publication.

The target is:

> **One canonical identity, temporal, trust and ordered-event contract from schema v1; a relational editorial ledger and governed object store as authority; and graph, vector and full-text retrieval projections implemented in the same initial delivery programme.**

GraphRAG is therefore neither a backlog item nor the system of record.

## Scope

This specification defines:

- the authority boundary between the relational ledger, retained objects and graph-related projections;
- the requirement that graph contracts exist from canonical schema v1;
- graph trust states and proposal or admission semantics;
- deterministic structural graph data versus editorially meaningful relation assertions;
- entity resolution and relation extraction governance;
- temporal and provenance requirements;
- ordered graph projection, checkpoint, gap and rebuild behaviour;
- hybrid exact, full-text, vector and graph retrieval;
- read-only agent and Hermes tool boundaries;
- GraphRAG use inside discovery triage and event grouping;
- degraded behaviour when graph or indexes are stale or unavailable;
- the first proof-of-concept engine and framework lane;
- required GraphRAG evaluation and ablation; and
- the implementation timing gate before end-to-end live shadow qualification.

It does not define:

- final physical ledger or graph schema;
- final production graph engine or commercial licence approval;
- final model provider, embedding model or Graphiti prompt;
- arbitrary document chat or reader-facing graph exploration;
- publication eligibility, evidence sufficiency or public related-story rendering;
- numerical retrieval thresholds, graph depth, latency objectives or resource limits; or
- production activation.

Those exact values and engine admissions require owner-approved implementation, evaluation and operational evidence.

## Correction to the first implementation Draft

The first Topic 12 Draft proposed a separate discovery-only SQLite store and postponed governed graph work until a later product-wide decision. That approach is rejected for the target architecture because it would create a planned semantic migration:

```text
Discovery-only identities and retrieval
        ↓ later
Graph-aware identities, ontology and retrieval
```

The corrected direction is:

```text
Canonical identity, trust, temporal and event contract
        ├── relational authority and object store
        ├── graph projection
        ├── vector/full-text indexes
        └── named hybrid retrieval tools
```

Code may be delivered in dependency order, but the graph contract, ontology, projection event mapping and GraphRAG acceptance proof belong to the first implementation programme and precede full end-to-end live shadow qualification.

## Terminology

### Graph database

A storage and query engine for nodes, relationships and properties.

### Knowledge graph

The governed domain model and data concerning sources, revisions, entities, events, claims, stories and relationships. A knowledge graph is not identical to its database engine.

### GraphRAG

Retrieval and context construction that use graph structure together with exact, lexical and vector retrieval. In this specification, GraphRAG does not mean that the Microsoft GraphRAG package or community-summary pipeline is mandatory.

### Agentic retrieval

An agent or controller selecting among bounded named retrieval tools. The agent is not the database and receives no unrestricted write or query authority.

### Governed graph projection

A rebuildable graph representation derived from authoritative ledger records, retained extraction proposals and explicit admission decisions. It is not an independent editorial authority.

## Architecture boundary

```text
Permitted source capture or discovery record
                    |
                    v
Relational editorial ledger + governed object store
  - canonical IDs and versions
  - source and discovery history
  - proposals and admission decisions
  - ordered ledger events
  - exact retained permitted bytes and hashes
                    |
          +---------+---------+
          |                   |
          v                   v
Graphiti proposal       Deterministic projector
workspace               consumes ledger events
  - entity proposals             |
  - relation proposals           v
          |             Governed Neo4j graph
          v             + vector/full-text indexes
Relational proposal and             |
admission records                   v
          |               Named read-only retrieval tools
          +-------------------------+
                                    |
                                    v
                          bounded triage or research context
```

The relational ledger records the Newsroom's authoritative system history. The governed object store is authoritative for exact retained bytes and hashes, not for whether a source claim is true. Graph, vector and full-text structures remain projections.

## Authority and recovery

### Relational authority

The canonical ledger owns stable identity, versions, source and discovery observations, proposals, admission decisions, outcomes, audit ordering, graph-projection events and later evidence or publication records.

The graph must not become the only place that records:

- a Source Revision;
- an Event Hypothesis or Candidate Version;
- an entity-resolution decision;
- a relation proposal or admission decision;
- a claim-to-evidence link;
- a source-revision impact decision;
- a story or publication version; or
- a correction, withdrawal or supersession decision.

### Governed objects

Large source bodies, source passages, retained extraction input, immutable evaluation artefacts and future publication payloads belong in content-addressed governed object storage where permitted. The graph stores identifiers, short derived fields, hashes, rights state and provenance references rather than becoming another uncontrolled full-text archive.

### Graph is reconstructable

Graph recovery authority is the ledger plus permitted governed objects and retained extraction outputs. A graph snapshot may reduce recovery time but is not the sole backup.

Rebuilding the same projection generation replays retained proposals and admission decisions. It must not rerun a stochastic extractor and silently create different historical relations. Deliberate re-extraction creates a new Extraction Run and new proposals.

## Canonical contract from schema v1

Canonical schema v1 must define stable IDs, versions and ordered events needed by both relational and graph consumers. It must not create a temporary graph-less event model.

The initial graph-aware contract includes at least:

- Source Definition and Version;
- Source Item, Revision and Representation;
- Discovery Signal and News Lead;
- Event Hypothesis and Version;
- Story Candidate and Version;
- Planned Agenda Item and Version;
- Entity Mention and Canonical Entity;
- Entity Resolution Proposal and Decision;
- Relation Proposal, Relation Assertion and Relation Admission Decision;
- Extraction Run;
- Evidence Handoff and downstream feedback references;
- Operational Finding and Coverage Gap;
- later Source Observation, Claim, Story, Story Version and publication identities; and
- ordered ledger-event and projection metadata.

Not every later domain must have complete implementation before discovery fixtures run, but IDs, event envelopes, trust states and extension boundaries must not require a planned v1-to-v2 semantic migration.

## Trust model

Graph-visible records use explicit trust scopes.

### `OBSERVED`

The Newsroom observed source text, metadata, a delivery or a deterministic structural record. `OBSERVED` means the item appeared in the attributed source or workflow; it does not mean the source claim is true.

### `PROPOSED`

A model, extractor, retrieval process or unverified editorial hypothesis proposed an entity identity, claim or relation. Confidence remains metadata and does not create authority.

### `ADMITTED`

A deterministic rule or authorised admission decision accepted the exact proposal for a declared purpose and scope. Admission does not make a disputed real-world assertion objectively true and does not bypass evidence or publication gates.

Retrieval may use different trust scopes for different purposes. Every context pack must identify the trust scope of each result. Publication validation may not rely on unlabelled `PROPOSED` relations.

## Graph model

### Deterministic structural relationships

Relationships whose meaning follows directly from canonical record structure may be projected as direct typed edges, for example:

- `HAS_VERSION`;
- `HAS_REVISION`;
- `HAS_REPRESENTATION`;
- `PRODUCED_SIGNAL`;
- `PROMOTED_TO_LEAD`;
- `CONTRIBUTES_TO_CANDIDATE`;
- `HAS_PASSAGE`;
- `DERIVED_FROM`; and
- `CONTAINS_PAYLOAD`.

Their source ledger event and version remain traceable.

### Editorially meaningful relationships

Relations such as the following must not be ordinary ungoverned edges:

- `SAME_EVENT_AS`;
- `DEVELOPMENT_OF`;
- `SAME_PROCESS_AS`;
- `CORRECTS`;
- `SUPERSEDES`;
- `SUPPORTS`;
- `DISPUTES`;
- `CONTRADICTS`;
- `ABOUT_EVENT`; and
- entity equivalence or merge.

They are represented by reified Relation Proposal and, where admitted, Relation Assertion records that identify:

- subject and object;
- predicate;
- trust state;
- exact supporting passages or workflow records;
- valid-time assertions and uncertainty;
- Extraction Run or deterministic rule;
- proposal version;
- admission or rejection decision; and
- invalidation, revocation or supersession history.

The system must not rely on every query remembering to filter a generic edge property such as `status = approved`.

## Entity resolution

Entity resolution is a first-class governed domain, not an ingestion side effect.

The contract distinguishes:

- Entity Mention;
- Canonical Entity;
- Alias;
- Entity Resolution Proposal;
- Entity Resolution Decision;
- Entity Merge Decision; and
- Entity Split or Reversal Decision.

Embedding similarity, identical names or Graphiti extraction may propose equivalence but cannot canonicalise automatically. Decisions preserve predecessor identities, evidence, reason, versions and reversal paths.

Multilingual aliases, especially English and Hong Kong Traditional Chinese names, must be testable independently from relation retrieval.

Dependent claims or relations cannot be admitted against an unresolved entity identity where that uncertainty could change their meaning.

## Temporal semantics

Graphiti or another framework's temporal fields do not replace Newsroom time semantics. The graph and retrieval layer preserve, where applicable:

- source-published time;
- source-revised time;
- Newsroom-observed time;
- source-asserted effective or validity time;
- authoritative ledger-recorded time;
- proposal time;
- admission time;
- invalidation or revocation time;
- first-publication time; and
- target-acknowledgement time.

Missing, approximate, date-only, provisional and conflicting times remain explicit.

Queries such as “what did the Newsroom know at this cutoff?” and “what source state was asserted as valid on this date?” require different temporal predicates and must not be answered by one generic timestamp.

## Extraction and admission

### Graphiti proposal workspace

The initial GraphRAG lane may use Graphiti for incremental temporal entity and relation extraction. Graphiti is an untrusted producer.

It must not write directly into the governed graph. If Graphiti requires a graph database during extraction, it uses a logically isolated, disposable proposal workspace or separate controlled instance.

### Persist before admission

Every extraction run records:

- exact permitted input identities and hashes;
- model, prompt, framework and code versions;
- raw structured extraction output where rights permit;
- entity and relation proposals;
- confidence and uncertainty;
- cost and timing; and
- failure or partial outcome.

A separate deterministic or authorised admission decision accepts, rejects, holds, merges, splits or supersedes a proposal. Rejected proposals remain traceable for evaluation.

### Project admitted state

The governed graph projector exposes deterministic structural records, `OBSERVED` records permitted for retrieval and exact `ADMITTED` assertions. Unadmitted proposals may be exposed only through an explicitly proposal-scoped research surface.

## Projection contract

### Ordered projection

Graph, vector and full-text projectors consume the canonical ordered ledger-event contract idempotently. The authoritative transaction records the domain change and one consumer-neutral ledger event. It does not synchronously dual-write the graph as a co-authority.

Each projector owns:

- checkpoint;
- retry state;
- dead-letter or gap state;
- projector version;
- ontology version;
- projection generation; and
- health and lag assessment.

A checkpoint cannot advance past an unhandled required event and still claim a contiguous projection.

### Query metadata

Every graph or hybrid retrieval response identifies at least:

- `projected_through_ledger_seq`;
- projector version;
- ontology version;
- projection generation;
- gap or dead-letter state;
- trust scope;
- query validity or cutoff time;
- serving time; and
- result provenance references.

A later projected sequence must not hide an earlier unresolved gap.

### Blue-green rebuild

Material ontology, projector or index changes build a new isolated generation. Validation compares counts, identities, hashes, relation invariants, trust states and required query cases before the active generation switches.

Rights expiry, privacy deletion and retention actions propagate to graph, vector and full-text derivatives. Rebuild must not resurrect prohibited source expression.

## Hybrid GraphRAG retrieval

The first GraphRAG implementation uses hybrid retrieval rather than graph-only traversal.

A bounded retrieval plan may:

1. use exact IDs, formal identifiers, aliases, dates and deterministic relationships;
2. search full-text indexes;
3. use vector similarity to seed cross-language or differently worded candidates;
4. traverse allow-listed relation types to a bounded depth and time window;
5. rerank and deduplicate candidate paths;
6. hydrate exact permitted passages and decision records from the ledger or object store; and
7. return a size-limited context pack with provenance and trust scope for every item.

Vector retrieval is a recall index, not an outdated or competing architecture. Graph proximity, semantic similarity and full-text ranking remain context signals rather than authority.

## Agent and tool boundary

Hermes or another agent receives named read-only tools rather than unrestricted `run_cypher` or write credentials.

Initial named tools should include:

- `find_related_event_candidates`;
- `get_event_or_process_timeline`;
- `find_source_revision_impact`;
- `find_shared_origin_dependencies`;
- `find_conflicting_relation_candidates`;
- `get_candidate_provenance`; and
- later `get_story_provenance` or `find_versions_using_claim` when evidence and publication domains exist.

Each tool fixes:

- accepted purpose;
- allowed node and relation types;
- trust scopes;
- maximum depth and fan-out;
- date window;
- result limit;
- timeout and cost budget;
- required projection freshness; and
- mandatory provenance fields.

Generated Cypher has no general write path. Even read-only free-form query generation requires separate evaluation and containment; it is not part of the initial production contract.

## Discovery integration

### First-class use in triage

GraphRAG participates in the initial implementation of advisory event retrieval and long-horizon context. It is not postponed until after a relational discovery system launches.

Primary discovery use cases are:

1. distinguishing same event state, development, correction and related-but-distinct cases;
2. preserving long-running policy, bill, court, incident and formal-process timelines;
3. identifying shared original-source or republishing dependencies;
4. finding earlier Source Revisions, Leads and Candidate Versions relevant to a new Lead; and
5. later assessing which admitted claims or Story Versions may be affected by a source revision.

### Authority remains deterministic

GraphRAG returns Retrieval Context and proposals. It does not:

- allocate Event Hypothesis identity;
- merge or split authoritative records;
- create a News Lead;
- decide that an item is a development;
- admit a Story Candidate;
- establish evidence; or
- publish.

Exact current-Candidate and identity collision checks remain authoritative relational operations.

### Discovery records in the graph

The first graph projection includes the accepted discovery identities and their deterministic structural lineage. Event Hypotheses and proposed editorial relationships remain explicitly unverified or proposed.

The graph contract must be in place before the first complete end-to-end live shadow qualification. Adapter-only transport smoke tests or offline fixtures may run earlier but cannot be presented as qualification of the full target architecture.

## Degraded graph behaviour

Graph unavailability must not become either total silent failure or a false `no match`.

- Source scheduling, collection, change detection, deterministic gates and durable Lead creation may continue when their accepted dependencies are healthy.
- Graph-dependent retrieval enters an explicit degraded or unavailable outcome.
- Candidate admission may proceed without graph only when an accepted exact relational path proves the required collision, relationship and history checks for that specific route.
- Where GraphRAG context is required and no equivalent approved path exists, the Lead enters Operational Hold or Watch rather than being forced into `new event`, reject or merge.
- Urgent work may use an accepted guarded exact fallback only under the Topic 6 and Topic 9 contracts, with mandatory later reconciliation.
- Graph outage does not weaken evidence, relation or publication requirements.

Graph independence is a resilience boundary, not permission to defer the graph contract.

## Initial proof-of-concept lane

### Neo4j Community plus Graphiti

The first compatibility-focused proof of concept uses:

- Neo4j Community as the governed property-graph, vector and full-text projection engine;
- Graphiti in an isolated proposal workspace for incremental temporal extraction; and
- Neo4j GraphRAG retrievers or a thin Newsroom retrieval adapter behind named tools.

This is an initial qualification baseline, not automatic production commitment. Exact licence, backup, security, single-instance, resource and deployment constraints require evaluation and operational approval.

### Conditional challenger

LadybugDB plus a thin Newsroom adapter is the conditional challenger only if the Neo4j proof of concept reveals a measured blocker in server footprint, licence, backup, deployment or intended Mac mini operation.

FalkorDB, Memgraph, TypeDB, Apache AGE and SurrealDB remain research alternatives rather than simultaneous implementation lanes. Kuzu is not selected for new work.

### Microsoft GraphRAG boundary

Microsoft GraphRAG may later be evaluated for corpus-wide themes, community summaries or global queries. Its batch community pipeline is not required for the first newsroom success cases and is not what this specification means by putting GraphRAG in the initial architecture.

## Initial success cases

The first shared corpus and ontology must test:

1. `same_event` and `development_of` precision across English, Hong Kong Traditional Chinese and mixed-language reporting;
2. one long-running policy or immigration guidance timeline with revisions and supersession;
3. one court, bill or formal-process timeline with similarly named but distinct records;
4. source-revision impact on downstream Candidates and, when available, claims and Story Versions;
5. shared press-release, wire and republishing dependency;
6. correction, contradiction and reversal;
7. false entity merges and split or reversal recovery; and
8. unrelated articles sharing names or keywords.

Generic chat with documents and broad community-summary generation are not first-round success criteria.

## Evaluation requirements

GraphRAG receives no production authority from a working demonstration. Evaluation under Topic 8 must measure:

- precision and recall for same state, development, correction, related-distinct, same-process, supports, contradicts and supersedes relations;
- entity-resolution precision, false merge and missed merge;
- provenance completeness to exact source or workflow records;
- temporal correctness before and after revisions or corrections;
- hybrid retrieval against exact/full-text-only, vector-only and graph-only ablations;
- candidate ranking quality without treating rank as authority;
- incremental ingest and extraction cost;
- model and embedding cost by permitted input class;
- graph projection lag and contiguous checkpoint correctness;
- behaviour with a projection gap or dead letter;
- rebuild without stochastic re-extraction;
- blue-green generation switch correctness;
- p50 and p95 query latency, memory, disk growth and backup or rebuild time on intended hardware;
- recovery after killed writes, interrupted projection and replaced indexes;
- rights-expiry and privacy-deletion purge followed by clean rebuild;
- graph-unavailable and stale-projection degraded behaviour;
- named-tool security, query budgets and resistance to generated-query abuse; and
- exact licence approval for the intended product use.

A successful graph answer without provenance, temporal correctness, reproducibility and trust separation is a failed qualification.

## Implementation timing

The revised implementation programme must include GraphRAG from its first architectural milestones:

### Foundation

- canonical identity, temporal, trust and ordered-event contract;
- relational ledger and governed object interface;
- graph ontology v1 and projection event mapping;
- projection checkpoint and generation contracts; and
- initial Neo4j development environment and fixtures.

### Early vertical slice

- deterministic structural projection of source and discovery records;
- Graphiti extraction proposal persistence;
- entity and relation admission decisions;
- hybrid full-text, vector and graph retrieval;
- named read-only tools; and
- GraphRAG replay and ablation tests.

### Before full live shadow

The graph projector, hybrid retrieval path, trust-labelled context, gap detection, rebuild proof and initial relationship evaluation must be operational in evaluation authority. A live shadow that omits these cannot qualify the final target architecture, although bounded adapter-only qualification may occur earlier.

## Requirements

### Architecture and authority

**GRAG-001 — GraphRAG from schema v1.** The canonical identity, temporal, trust and ordered-event contract MUST include graph-projection requirements from its first production-schema version and MUST NOT plan a graph-less semantic migration.

**GRAG-002 — Relational authority.** The relational editorial ledger MUST remain authoritative for Newsroom identities, versions, observations, proposals, admissions, outcomes and ordered history.

**GRAG-003 — Object authority.** Governed object storage MUST remain authoritative for exact retained permitted bytes and hashes, not for factual truth.

**GRAG-004 — Projection boundary.** Graph, vector and full-text stores MUST be rebuildable projections and MUST NOT become independent editorial, evidence or publication authority.

**GRAG-005 — No synchronous co-authority.** The system MUST NOT require a relational-and-graph dual write to commit one authoritative decision.

**GRAG-006 — Same initial programme.** Ontology, projection, Graphiti governance, hybrid retrieval and graph evaluation MUST be delivered in the initial implementation programme before complete live-shadow qualification.

### Trust, entities and relations

**GRAG-010 — Explicit trust scope.** Graph-visible records and retrieval results MUST distinguish `OBSERVED`, `PROPOSED` and `ADMITTED` or an exact equivalent mapping.

**GRAG-011 — Confidence is not admission.** Model or embedding confidence MUST NOT create admitted entity identity, relation, claim, Event Hypothesis or Candidate authority.

**GRAG-012 — Structural versus editorial relation.** Deterministic structural relationships and editorially meaningful relation assertions MUST remain distinct.

**GRAG-013 — Reified editorial relations.** Editorially meaningful relations MUST retain subject, object, predicate, provenance, temporal scope, proposal and admission history rather than rely on an ungoverned ordinary edge.

**GRAG-014 — First-class entity resolution.** Entity mentions, canonical entities, aliases, proposals, merge, split and reversal decisions MUST remain explicit and versioned.

**GRAG-015 — Dependent admission guard.** A relation or claim MUST NOT be admitted against materially unresolved entity identity where that uncertainty changes meaning.

**GRAG-016 — Trust-labelled context.** Every context item returned to a worker or agent MUST carry trust scope and provenance sufficient to prevent proposed relations being mistaken for governed facts.

### Extraction and projection

**GRAG-020 — Graphiti is proposal-only.** Graphiti or another extractor MAY create proposals but MUST NOT write authoritative editorial relations or governed graph state directly.

**GRAG-021 — Isolated extraction workspace.** Any framework-required extraction graph MUST be logically isolated from the governed projection and disposable without loss of authoritative history.

**GRAG-022 — Persist extraction provenance.** Extraction inputs, versions, structured outputs, proposals, costs and failures MUST be retained subject to rights before admission decisions.

**GRAG-023 — Separate admission.** Entity and relation proposals MUST receive explicit admission, rejection, hold, merge, split or supersession decisions before admitted projection.

**GRAG-024 — Ordered idempotent projection.** Graph and index projectors MUST consume canonical ledger events idempotently with exact checkpoints, versions and gap state.

**GRAG-025 — Checkpoint cannot skip.** A projector MUST NOT claim a contiguous watermark after skipping an unresolved required event.

**GRAG-026 — Rebuild without stochastic rewrite.** Rebuild under the same version MUST replay retained proposals and admission decisions rather than rerun extraction.

**GRAG-027 — Blue-green generation.** Material ontology or projector changes MUST support isolated generation, validation and controlled switch.

**GRAG-028 — Rights-safe rebuild.** Retention, rights and privacy deletion MUST propagate to graph and indexes and MUST prevent rebuild from resurrecting prohibited data.

### Temporal and retrieval behaviour

**GRAG-030 — Time dimensions remain distinct.** Source, observation, validity, recording, proposal, admission, invalidation and publication-related times MUST NOT be collapsed into one graph timestamp.

**GRAG-031 — Hybrid retrieval.** Initial GraphRAG MUST combine exact, full-text, vector and bounded graph retrieval rather than rely on one mode as universal truth.

**GRAG-032 — Hydrate authority.** Graph results SHOULD return identifiers and paths and MUST hydrate exact permitted source passages or decisions from the authoritative ledger or object store before factual use.

**GRAG-033 — Bounded named tools.** Agent access MUST use purpose-specific read-only tools with allow-listed types, depth, fan-out, date, result, timeout, trust and provenance controls.

**GRAG-034 — No general write Cypher.** Agents, models and source content MUST NOT receive graph write credentials or an unrestricted mutation path.

**GRAG-035 — Query projection metadata.** Every graph or hybrid response MUST identify watermark, projector, ontology, generation, gap, trust and serving metadata.

### Discovery integration and degraded operation

**GRAG-040 — Graph-assisted retrieval is context.** GraphRAG MAY generate event and relation candidates but MUST NOT allocate Event Hypothesis identity, merge records or admit Candidates directly.

**GRAG-041 — Exact collision remains authoritative.** Candidate and identity collision checks MUST use an authoritative deterministic path rather than graph similarity alone.

**GRAG-042 — Discovery graph from first slice.** Source, Revision, Signal, Lead, Hypothesis and Candidate lineage MUST be projectable in the initial vertical slice with unverified states explicit.

**GRAG-043 — No false no-match.** Graph outage, lag or gap MUST NOT be represented as no prior event, no relation or no development.

**GRAG-044 — Degraded decision rule.** Graph-dependent decisions MUST use an approved exact fallback or enter Watch or Operational Hold when equivalent context is unavailable.

**GRAG-045 — Collection isolation.** Healthy deterministic source collection and Lead creation MAY continue during graph outage when their own authority and storage remain available.

**GRAG-046 — Full-shadow gate.** The complete end-to-end target architecture MUST NOT receive live-shadow qualification without the governed graph projection and hybrid retrieval path included.

### Initial engine and evaluation

**GRAG-050 — Initial POC baseline.** Neo4j Community plus Graphiti is the first compatibility-focused proof-of-concept lane, not automatic production admission.

**GRAG-051 — Conditional challenger only.** LadybugDB or another engine MAY be tested only after a measured blocker or owner-approved comparison purpose; multiple engines are not implemented in parallel by default.

**GRAG-052 — No Kuzu new work.** New implementation MUST NOT select archived Kuzu as the target graph engine.

**GRAG-053 — Package neutrality.** GraphRAG architecture MUST NOT be equated with mandatory use of Microsoft GraphRAG community summarisation.

**GRAG-054 — First use cases.** Initial qualification MUST cover event or development precision, source-revision impact and long-running policy, case or process timelines.

**GRAG-055 — Hybrid ablation.** Evaluation MUST compare hybrid retrieval against exact or full-text-only, vector-only and graph-only modes.

**GRAG-056 — Provenance and temporal blocker.** Missing exact provenance, trust separation, temporal correctness or reproducible rebuild MUST block qualification regardless of answer quality.

**GRAG-057 — Operational and licence qualification.** Engine admission MUST include intended-hardware operation, backup or rebuild, resource use, security and product-use licence review.

**GRAG-058 — Acceptance is not execution.** Accepting this specification MUST NOT start Neo4j, Graphiti, embeddings, extraction, external requests, model calls, spending, shadow operation or production activation.

## Acceptance criteria

1. The first canonical identity and event contract supports both relational records and graph projection without a later semantic rewrite.
2. A Graphiti-extracted `development_of` relation is stored as a proposal and cannot become governed merely because confidence is high.
3. Rebuilding a projection does not rerun Graphiti and produce different historical relations silently.
4. A graph query identifies the exact projected ledger watermark, ontology version, generation, trust scope and gap state.
5. An unresolved projection gap prevents a query from claiming complete current context.
6. Source, observed, valid, recorded and admitted times remain distinguishable in a policy-revision timeline.
7. Two bilingual names do not merge solely because vector similarity is high.
8. A relation assertion retains exact supporting passages and admission history.
9. A graph outage cannot become `REL_NO_ADEQUATE_PRIOR_MATCH` automatically.
10. Exact Candidate collision checks remain available from authoritative records or Candidate admission is blocked.
11. Source checks and Lead creation may continue safely during graph outage without claiming graph-dependent completeness.
12. A complete live shadow includes graph projection, hybrid retrieval, gap handling and GraphRAG evaluation.
13. A full-text-only, vector-only or graph-only result cannot be called superior without the pre-registered ablation.
14. A graph answer without provenance or temporal correctness fails qualification.
15. Rights deletion followed by rebuild does not resurrect prohibited passages or embeddings.
16. Hermes receives named bounded tools and no general graph write credential.
17. Neo4j or Graphiti POC success does not automatically select the production engine.
18. Acceptance creates no runtime authority.

## Owner decisions required to complete the GraphRAG topic

The Draft recommends that the owner accept:

1. GraphRAG, vector and full-text projections as first-class parts of canonical schema v1 and the initial implementation programme, not a backlog or later semantic migration.
2. A relational editorial ledger and governed object store as authority, with graph and indexes as rebuildable projections rather than co-authorities.
3. The authority and projection boundary proposed in ADR 0001.
4. A single-host SQLite canonical ledger as proposed in ADR 0002, provided it is implemented together with the graph workstream rather than as a temporary graph-less phase.
5. One canonical identity, temporal, trust and ordered-event contract shared by discovery, future evidence, publication and graph consumers.
6. Explicit `OBSERVED`, `PROPOSED` and `ADMITTED` trust scopes or an exact equivalent mapping.
7. Direct projection only for deterministic structural relationships and reified proposal or assertion records for editorially meaningful relations.
8. First-class entity-resolution proposals, decisions, merge, split and reversal semantics.
9. Graphiti as an isolated proposal producer, with persisted provenance and separate admission before governed projection.
10. Idempotent ordered projectors, contiguous checkpoints, visible gaps, blue-green generations and rebuild without stochastic re-extraction.
11. Hybrid exact, full-text, vector and bounded graph retrieval, with authoritative hydration from the ledger or object store.
12. Named read-only Hermes or agent tools and no unrestricted graph write or general production Cypher authority.
13. GraphRAG as advisory context for event grouping and source-revision impact, while deterministic controllers retain Event Hypothesis, Candidate and evidence authority.
14. Explicit degraded behaviour: graph failure is not no-match; safe collection may continue, while graph-dependent decisions use an approved exact fallback or hold.
15. Neo4j Community plus Graphiti as the first POC baseline, with LadybugDB only as a conditional challenger and Microsoft GraphRAG community pipelines outside the first success criteria.
16. The initial use cases: same-event or development precision, source-revision impact and long-running policy, bill, case or incident timelines.
17. Pre-registered GraphRAG evaluation covering relation and entity quality, temporal correctness, provenance, hybrid ablation, cost, lag, rebuild, security, rights purge and outage behaviour.
18. A release gate requiring the governed graph and hybrid retrieval path before complete live-shadow qualification; adapter-only tests may occur earlier but do not qualify the full architecture.
19. Revision of the implementation plan so graph ontology, projector, Graphiti proposal or admission and hybrid retrieval are delivered in the first milestones beside the canonical ledger.
20. Acceptance of this specification authorises no engine installation, source access, extraction, embedding, model call, spending, shadow run, canary or production activation.
