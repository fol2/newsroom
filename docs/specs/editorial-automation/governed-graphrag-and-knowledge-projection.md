# Governed GraphRAG and knowledge-projection specification

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Accepted by owner:** 2026-07-16  
**Canonical language:** English  
**Related review sequence:** [`../../plans/2026-07-15-002-discovery-specification-review.md`](../../plans/2026-07-15-002-discovery-specification-review.md)  
**Accepted discovery contracts:** [`discovery-coverage-contract.md`](discovery-coverage-contract.md), [`discovery-workflow.md`](discovery-workflow.md), [`discovery-record-semantics.md`](discovery-record-semantics.md), [`discovery-source-roles-and-selection.md`](discovery-source-roles-and-selection.md), [`discovery-change-and-planned-agenda.md`](discovery-change-and-planned-agenda.md), [`discovery-triage-and-event-grouping.md`](discovery-triage-and-event-grouping.md), [`discovery-search-and-coverage-audit.md`](discovery-search-and-coverage-audit.md), [`discovery-shadow-evaluation.md`](discovery-shadow-evaluation.md), [`discovery-reliability-and-operations.md`](discovery-reliability-and-operations.md), [`discovery-prioritisation-and-outcomes.md`](discovery-prioritisation-and-outcomes.md), [`discovery-locality-scope-and-expansion.md`](discovery-locality-scope-and-expansion.md)  
**Accepted architecture decisions:** [`../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md), [`../../adr/0004-source-registry-first-change-driven-discovery.md`](../../adr/0004-source-registry-first-change-driven-discovery.md), [`../../adr/0005-native-graphrag-production-deployment.md`](../../adr/0005-native-graphrag-production-deployment.md)  
**Accepted production contract:** [`graphrag-native-production-deployment.md`](graphrag-native-production-deployment.md)  
**Related research:** [`../../research/2026-07-15-local-agentic-graph-rag-database-options.md`](../../research/2026-07-15-local-agentic-graph-rag-database-options.md), [`../../research/2026-07-15-database-architecture.md`](../../research/2026-07-15-database-architecture.md)  
**Implementation authority:** None. Acceptance defines the GraphRAG architecture and initial qualification boundary. It authorises no graph-engine installation, source access, extraction, embedding, model call, spending, shadow run, canary or production activation.  
**Supersedes:** The rejected assumption that GraphRAG could be deferred until after a separate discovery-only implementation, and the superseded experiment-only framing for the initial Neo4j Community plus Graphiti target.

## Purpose

Define GraphRAG as a first-class part of the Newsroom's initial target architecture while preserving deterministic, temporal and reconstructable authority.

The architecture prevents two opposite failures:

1. building a relational discovery system whose identities, event model and retrieval contracts must later be redesigned for a graph; and
2. making an LLM-extracted graph the authoritative record for source history, editorial decisions, evidence or publication.

The target is:

> One canonical identity, temporal, trust and ordered-event contract from schema v1; a relational editorial ledger and governed object store as authority; and graph, vector and full-text retrieval projections delivered in the same initial programme.

GraphRAG is neither a backlog item nor the system of record.

## Scope

This specification defines:

- the authority boundary between relational records, retained objects and retrieval projections;
- graph-aware canonical schema requirements from v1;
- explicit trust states;
- deterministic structural graph data versus editorial relation assertions;
- entity resolution, extraction and relation-admission governance;
- temporal and provenance fields;
- ordered projection, checkpoints, gaps, generations and rebuild;
- hybrid exact, full-text, vector and graph retrieval;
- named read-only agent tools;
- GraphRAG use in discovery triage and event grouping;
- degraded behaviour when projection data is stale or unavailable;
- the initial production-target engine and framework qualification lane; and
- the release-evidence gate before complete live-shadow qualification.

It does not set the final physical schema, exact engine or framework release, commercial licence approval, model or embedding provider, extraction prompt, numeric retrieval thresholds, graph depth, latency objective, resource envelope or production activation.

## Corrected implementation direction

The rejected direction was:

```text
Discovery-only identities and retrieval
        ↓ later migration
Graph-aware identities, ontology and retrieval
```

The accepted direction is:

```text
Canonical identity, temporal, trust and ordered-event contract
        ├── relational authority and governed objects
        ├── graph projection
        ├── vector and full-text indexes
        └── bounded hybrid retrieval tools
```

Code may be delivered in dependency order. The ontology, projection mapping, proposal and admission model, hybrid retrieval contract and GraphRAG acceptance proof nevertheless belong to the initial programme and must exist before the complete end-to-end live shadow can qualify the target architecture.

## Terminology

### Graph database

A storage and query engine for nodes, relationships and properties.

### Knowledge graph

The governed domain model and projected data concerning sources, revisions, entities, events, claims, stories and relationships. It is not identical to its database engine.

### GraphRAG

Retrieval and context construction that combine graph structure with exact, lexical and vector retrieval. This term does not mandate the Microsoft GraphRAG community-summary pipeline.

### Agentic retrieval

A controller or agent selecting among bounded named retrieval tools. The agent is not the database and receives no unrestricted write or query authority.

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
  - retained permitted bytes and hashes
                    |
          +---------+----------+
          |                    |
          v                    v
Graphiti proposal       deterministic projectors
workspace                         |
  - entity proposals              v
  - relation proposals     governed graph
          |                + full-text/vector indexes
          v                         |
relational proposal                v
and admission records     named read-only retrieval tools
          |                         |
          +-------------------------+
                                    |
                                    v
                         bounded triage or research context
```

The relational ledger records the Newsroom's authoritative system history. Governed object storage is authoritative for exact retained permitted bytes and hashes, not for whether a source claim is true. Graph, vector and full-text structures remain projections.

There is no synchronous relational-and-graph co-authority write. The authoritative transaction records domain changes, proposals or decisions and emits consumer-neutral ordered events. Projectors consume those events idempotently.

## Canonical contract from schema v1

Canonical schema v1 must define stable identities, versions, time fields, trust states and ordered events needed by both relational and graph consumers.

The graph-aware contract includes at least:

- Source Definition and Version;
- Source Item, Revision and Representation;
- Discovery Signal and News Lead;
- Event Hypothesis and Version;
- Story Candidate and Version;
- Planned Agenda Item and Version;
- Entity Mention, Alias and Canonical Entity;
- Entity Resolution Proposal and Decision;
- Entity Merge, Split and Reversal Decisions;
- Extraction Run;
- Relation Proposal, Relation Assertion and Relation Admission Decision;
- Evidence Handoff and downstream feedback references;
- Operational Finding and Coverage Gap;
- later Source Observation, Claim, Story, Story Version and publication identities; and
- ordered ledger-event and projection metadata.

Not every later product domain must have complete implementation before discovery fixtures run. The identity catalogue, event envelope, trust semantics and extension boundaries must nevertheless avoid a planned graph-less-to-graph-aware semantic migration.

## Trust model

Graph-visible records use explicit trust scopes.

### `OBSERVED`

The Newsroom observed source text, metadata, a delivery or a deterministic workflow record. `OBSERVED` means the attributed source or workflow contained the record; it does not mean the source claim is true.

### `PROPOSED`

A model, extractor, retrieval process or unverified editorial hypothesis proposed an entity identity, claim or relation. Confidence remains metadata and creates no authority.

### `ADMITTED`

A deterministic rule or authorised decision accepted the exact proposal for a declared purpose and scope. Admission does not make a disputed real-world assertion objectively true and does not bypass evidence or publication gates.

Every context item returned to a worker or agent identifies its trust scope. Publication validation may not rely on unlabelled `PROPOSED` relationships.

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

Every projected structure remains traceable to exact ledger events and versions.

### Editorially meaningful relationships

Relations such as the following must not be ungoverned ordinary edges:

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

They use reified proposal and assertion records that retain:

- subject and object;
- predicate;
- trust state;
- exact supporting passages or workflow records;
- valid-time assertions and uncertainty;
- Extraction Run or deterministic rule;
- proposal version;
- admission, rejection or hold decision; and
- invalidation, revocation, correction or supersession history.

Safety must not depend on every graph query remembering to filter a generic `status = approved` property.

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

English, Hong Kong Traditional Chinese and mixed-language aliases must be evaluated independently from relation retrieval. A dependent relation or claim cannot be admitted against materially unresolved entity identity where that uncertainty changes meaning.

## Temporal semantics

Framework timestamps do not replace Newsroom time semantics. The ledger and projections preserve, where applicable:

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

“What did the Newsroom know at this cutoff?” and “what state did a source assert as valid on this date?” are different temporal queries and cannot be answered by one generic timestamp.

## Extraction and admission

### Proposal workspace

The initial lane may use Graphiti for incremental temporal entity and relation extraction. Graphiti is an untrusted producer.

It must not write directly into the governed graph. If the framework requires a graph database during extraction, it uses a logically isolated, disposable proposal workspace or controlled separate instance.

### Persist before admission

Every extraction run records, subject to rights:

- exact input identities and hashes;
- model, prompt, framework and code versions;
- raw structured extraction output;
- entity and relation proposals;
- confidence and uncertainty;
- cost and timing; and
- failure or partial outcome.

A separate deterministic or authorised admission decision accepts, rejects, holds, merges, splits or supersedes each proposal. Rejected and held proposals remain traceable for evaluation.

### Governed projection

The governed projector exposes deterministic structural records, permitted `OBSERVED` records and exact `ADMITTED` assertions. Unadmitted proposals may appear only on an explicitly proposal-scoped research surface.

## Projection contract

Graph, vector and full-text projectors consume canonical ordered ledger events idempotently.

Each projector owns:

- a contiguous checkpoint;
- retry state;
- dead-letter or gap state;
- projector version;
- ontology version;
- projection generation; and
- health and lag assessment.

A checkpoint cannot advance past an unresolved required event and still claim a contiguous projection.

Every graph or hybrid retrieval response identifies:

- `projected_through_ledger_seq`;
- projector version;
- ontology version;
- projection generation;
- gap or dead-letter state;
- trust scope;
- query validity or cutoff time;
- serving time; and
- provenance references.

A later projected sequence does not conceal an earlier unresolved gap.

Material ontology, projector, embedding, chunking or index changes use an isolated generation. Validation compares identities, counts, hashes, trust states, relationship invariants and required query cases before the active generation switches.

Rebuild under the same contract replays retained extraction outputs and admission decisions. It does not rerun stochastic extraction. Rights expiry, privacy deletion and retention decisions propagate to graph, vector and full-text derivatives and prevent rebuild from resurrecting prohibited material.

## Hybrid GraphRAG retrieval

The initial implementation combines:

1. exact identifiers, formal process IDs, aliases, dates and deterministic relationships;
2. full-text retrieval;
3. vector retrieval for cross-language or differently worded candidates;
4. bounded traversal of allow-listed relation types within a time window;
5. reranking and dependency-aware deduplication;
6. hydration of exact permitted passages and decision records from the ledger or object store; and
7. a size-limited context pack with provenance and trust scope for every item.

Vector retrieval is a recall index rather than an outdated or competing architecture. Graph proximity, semantic similarity and full-text ranking remain context signals, not authority.

## Agent and tool boundary

Hermes or another agent receives named read-only tools rather than unrestricted `run_cypher` or any graph write credential.

Initial tools include:

- `find_related_event_candidates`;
- `get_event_or_process_timeline`;
- `find_source_revision_impact`;
- `find_shared_origin_dependencies`;
- `find_conflicting_relation_candidates`;
- `get_candidate_provenance`; and
- later `get_story_provenance` or `find_versions_using_claim` when those domains exist.

Each tool fixes:

- accepted purpose;
- allowed node and relationship types;
- trust scopes;
- maximum depth and fan-out;
- date window;
- result limit;
- timeout and cost budget;
- required projection freshness; and
- mandatory provenance fields.

Generated Cypher has no general write path. Free-form read-query generation, if ever considered, requires separate evaluation and containment and is not part of the initial production contract.

## Discovery integration

GraphRAG participates in the initial implementation of advisory event retrieval and long-horizon context. It is not postponed until after a relational discovery system launches.

Initial discovery uses include:

- distinguishing same event state, development, correction and related-but-distinct cases;
- preserving policy, bill, court, incident and formal-process timelines;
- identifying shared original-source and republishing dependencies;
- finding earlier Source Revisions, Leads and Candidate Versions relevant to a new Lead; and
- later identifying claims or Story Versions potentially affected by a source revision.

GraphRAG returns Retrieval Context and proposals. It does not allocate Event Hypothesis identity, merge or split authoritative records, create a Lead, decide a development, admit a Candidate, establish evidence or publish.

Exact current-Candidate and identity collision checks remain authoritative relational operations.

The first graph projection includes discovery identities and deterministic lineage. Event Hypotheses and editorial relations remain explicitly unverified or proposed until admitted.

## Degraded graph behaviour

Graph unavailability, lag or gap is never represented as `no prior match`.

- Healthy source scheduling, collection, change detection, deterministic gates and durable Lead creation may continue when their own dependencies are healthy.
- Graph-dependent retrieval creates an explicit degraded or unavailable outcome.
- Candidate admission may proceed without graph only when an accepted exact relational path proves the required collision, relationship and history checks for that route.
- Where GraphRAG context is required and no equivalent approved path exists, the Lead enters Watch or Operational Hold rather than being forced into new-event, reject or merge.
- Urgent work may use an accepted guarded exact fallback under the triage and operations contracts, followed by mandatory reconciliation.
- Graph outage never weakens evidence, relation or publication requirements.

Graph independence is a resilience boundary, not permission to defer the graph contract.

## Initial production-target implementation

### Neo4j Community plus Graphiti

The initial repository-native production-target implementation uses:

- Neo4j Community as the governed property-graph, vector and full-text projection engine;
- Graphiti in an isolated proposal workspace for incremental temporal extraction; and
- Neo4j GraphRAG retrievers or a thin Newsroom adapter behind named tools.

This is the mandatory initial implementation and qualification baseline. Evaluation and Operational Admission decide whether the exact releases and configuration are ready, not whether GraphRAG exists. Licence, backup, security, single-instance, resource and deployment constraints require separate evidence and approval.

### Conditional challenger

LadybugDB plus a thin Newsroom adapter is considered only if Neo4j exposes a measured blocker in server footprint, licence, backup, deployment or intended Mac mini operation. Multiple graph engines are not implemented in parallel by default.

FalkorDB, Memgraph, TypeDB, Apache AGE and SurrealDB remain research alternatives. Kuzu is not selected for new work.

### Microsoft GraphRAG boundary

Microsoft GraphRAG may later be evaluated for corpus-wide themes or community summaries. Its batch community pipeline is not required for the initial newsroom success cases and is not what this specification means by putting GraphRAG in the initial architecture.

## Initial success cases

The first shared corpus and ontology test:

1. same-event and development precision across English, Hong Kong Traditional Chinese and mixed-language reporting;
2. one long-running policy or immigration-guidance timeline with revisions and supersession;
3. one court, bill or formal-process timeline containing similarly named but distinct records;
4. source-revision impact on downstream Candidates and, when available, claims and Story Versions;
5. shared press-release, wire and republishing dependencies;
6. correction, contradiction and reversal;
7. false entity merges and split or reversal recovery; and
8. unrelated articles sharing names or keywords.

Generic document chat and broad community-summary generation are not first-round success criteria.

## Evaluation and release gate

Topic 8 evaluation must measure:

- relation precision and recall for same state, development, correction, related-distinct, same-process, supports, contradicts and supersedes;
- entity-resolution precision, false merge and missed merge;
- provenance completeness to exact source or workflow records;
- temporal correctness before and after revisions or corrections;
- hybrid retrieval against exact or full-text-only, vector-only and graph-only ablations;
- candidate-ranking quality without treating rank as authority;
- incremental ingest, extraction and embedding cost;
- projection lag and contiguous checkpoint correctness;
- behaviour with a gap or dead letter;
- rebuild without stochastic re-extraction;
- blue-green generation switch correctness;
- p50 and p95 query latency, memory, disk growth and backup or rebuild time on intended hardware;
- recovery after interrupted writes, projection and index replacement;
- rights-expiry and privacy-deletion purge followed by clean rebuild;
- graph-unavailable and stale-projection degraded behaviour;
- named-tool security, budgets and generated-query abuse resistance; and
- licence approval for the intended product use.

A graph answer without exact provenance, temporal correctness, trust separation and reproducible rebuild is a failed qualification regardless of apparent answer quality.

The graph ontology, projector, hybrid retrieval, trust-labelled context, gap detection, rebuild proof and initial relationship evaluation must be operational in evaluation authority before complete end-to-end live-shadow qualification. Adapter-only transport tests may run earlier but do not qualify the full target architecture.

## Requirements

### Architecture and authority

**GRAG-001 — GraphRAG from schema v1.** The canonical identity, temporal, trust and ordered-event contract MUST include graph-projection requirements from its first production-schema version and MUST NOT plan a graph-less semantic migration.

**GRAG-002 — Relational authority.** The relational editorial ledger MUST remain authoritative for Newsroom identities, versions, observations, proposals, admissions, outcomes and ordered history.

**GRAG-003 — Object authority.** Governed object storage MUST remain authoritative for exact retained permitted bytes and hashes, not factual truth.

**GRAG-004 — Projection boundary.** Graph, vector and full-text stores MUST be rebuildable projections and MUST NOT become independent editorial, evidence or publication authority.

**GRAG-005 — No synchronous co-authority.** One authoritative decision MUST NOT depend on a synchronous relational-and-graph dual write.

**GRAG-006 — Same initial programme.** Ontology, projection, extraction governance, hybrid retrieval and graph evaluation MUST be delivered in the initial implementation programme before complete live-shadow qualification.

### Trust, entities and relations

**GRAG-010 — Explicit trust scope.** Graph-visible records and retrieval results MUST distinguish `OBSERVED`, `PROPOSED` and `ADMITTED` or an exact equivalent mapping.

**GRAG-011 — Confidence is not admission.** Model or embedding confidence MUST NOT create admitted entity identity, relation, claim, Event Hypothesis or Candidate authority.

**GRAG-012 — Structural versus editorial relation.** Deterministic structural relationships and editorially meaningful relation assertions MUST remain distinct.

**GRAG-013 — Reified editorial relations.** Editorial relations MUST retain subject, object, predicate, provenance, temporal scope, proposal and admission history.

**GRAG-014 — First-class entity resolution.** Entity mentions, canonical entities, aliases, proposals, merge, split and reversal decisions MUST remain explicit and versioned.

**GRAG-015 — Dependent admission guard.** A relation or claim MUST NOT be admitted against materially unresolved entity identity when that uncertainty changes meaning.

**GRAG-016 — Trust-labelled context.** Every context item returned to a worker or agent MUST carry trust scope and provenance.

### Extraction and projection

**GRAG-020 — Extractor is proposal-only.** Graphiti or another extractor MAY create proposals but MUST NOT write authoritative editorial relations or governed graph state directly.

**GRAG-021 — Isolated extraction workspace.** Any framework-required extraction graph MUST be logically isolated from the governed projection and disposable without loss of authoritative history.

**GRAG-022 — Persist extraction provenance.** Extraction inputs, versions, structured outputs, proposals, costs and failures MUST be retained subject to rights before admission.

**GRAG-023 — Separate admission.** Entity and relation proposals MUST receive explicit admission, rejection, hold, merge, split or supersession decisions before admitted projection.

**GRAG-024 — Ordered idempotent projection.** Graph and index projectors MUST consume canonical ledger events idempotently with exact checkpoints, versions and gap state.

**GRAG-025 — Checkpoint cannot skip.** A projector MUST NOT claim a contiguous watermark after skipping an unresolved required event.

**GRAG-026 — Rebuild without stochastic rewrite.** Rebuild under the same version MUST replay retained proposals and admission decisions rather than rerun extraction.

**GRAG-027 — Blue-green generation.** Material ontology or projector changes MUST support isolated generation, validation and controlled switch.

**GRAG-028 — Rights-safe rebuild.** Retention, rights and privacy deletion MUST propagate to graph and indexes and prevent resurrection of prohibited data.

### Temporal and retrieval behaviour

**GRAG-030 — Time dimensions remain distinct.** Source, observation, validity, recording, proposal, admission, invalidation and publication-related times MUST NOT be collapsed into one graph timestamp.

**GRAG-031 — Hybrid retrieval.** Initial GraphRAG MUST combine exact, full-text, vector and bounded graph retrieval.

**GRAG-032 — Hydrate authority.** Graph results SHOULD return identifiers and paths and MUST hydrate exact permitted passages or decisions from the ledger or object store before factual use.

**GRAG-033 — Bounded named tools.** Agent access MUST use purpose-specific read-only tools with allow-listed type, depth, fan-out, date, result, timeout, trust and provenance controls.

**GRAG-034 — No general write Cypher.** Agents, models and source content MUST NOT receive graph write credentials or an unrestricted mutation path.

**GRAG-035 — Query projection metadata.** Every graph or hybrid response MUST identify watermark, projector, ontology, generation, gap, trust and serving metadata.

### Discovery integration and degraded operation

**GRAG-040 — Graph-assisted retrieval is context.** GraphRAG MAY generate event and relation candidates but MUST NOT allocate Event Hypothesis identity, merge records or admit Candidates directly.

**GRAG-041 — Exact collision remains authoritative.** Candidate and identity collision checks MUST use an authoritative deterministic path rather than graph similarity alone.

**GRAG-042 — Discovery graph from first slice.** Source, Revision, Signal, Lead, Hypothesis and Candidate lineage MUST be projectable in the initial vertical slice with unverified states explicit.

**GRAG-043 — No false no-match.** Graph outage, lag or gap MUST NOT be represented as no prior event, no relation or no development.

**GRAG-044 — Degraded decision rule.** Graph-dependent decisions MUST use an approved exact fallback or enter Watch or Operational Hold when equivalent context is unavailable.

**GRAG-045 — Collection isolation.** Healthy deterministic source collection and Lead creation MAY continue during graph outage when their own authority and storage remain available.

**GRAG-046 — Full-shadow gate.** The complete target architecture MUST NOT receive end-to-end live-shadow qualification without governed graph projection and hybrid retrieval included.

### Initial engine and evaluation

**GRAG-050 — Initial production target.** Neo4j Community plus Graphiti is the initial repository-native production-target implementation, subject to exact release qualification; qualification decides readiness of the exact implementation, not whether the subsystem exists.

**GRAG-051 — Conditional challenger only.** Another engine MAY be tested only after a measured blocker or owner-approved comparison purpose; multiple engines are not implemented in parallel by default.

**GRAG-052 — No Kuzu new work.** New implementation MUST NOT select archived Kuzu as the target graph engine.

**GRAG-053 — Package neutrality.** GraphRAG architecture MUST NOT be equated with mandatory use of Microsoft GraphRAG community summarisation.

**GRAG-054 — First use cases.** Initial qualification MUST cover event or development precision, source-revision impact and long-running policy, case or process timelines.

**GRAG-055 — Hybrid ablation.** Evaluation MUST compare hybrid retrieval against exact or full-text-only, vector-only and graph-only modes.

**GRAG-056 — Provenance and temporal blocker.** Missing exact provenance, trust separation, temporal correctness or reproducible rebuild MUST block qualification regardless of answer quality.

**GRAG-057 — Operational and licence qualification.** Engine admission MUST include intended-hardware operation, backup or rebuild, resource use, security and product-use licence review.

**GRAG-058 — Acceptance is not execution.** Accepting this specification MUST NOT start a graph engine, extractor, embeddings, source access, model call, spending, shadow operation or production activation.

## Acceptance criteria

1. Canonical schema v1 supports relational records and graph projection without a later semantic rewrite.
2. A high-confidence extracted `development_of` remains a proposal until admitted.
3. Projection rebuild does not rerun Graphiti and silently produce different historical relations.
4. Every retrieval response identifies watermark, ontology, generation, trust and gap state.
5. An unresolved projection gap prevents a claim of complete current context.
6. Source, observed, valid, recorded and admitted times remain distinguishable.
7. Bilingual names do not merge solely because vector similarity is high.
8. An editorial relation retains supporting records and admission history.
9. Graph outage cannot become `REL_NO_ADEQUATE_PRIOR_MATCH` automatically.
10. Exact Candidate collision remains relational or admission is blocked.
11. Safe collection may continue during graph outage without claiming graph-dependent completeness.
12. Complete live shadow includes graph projection, hybrid retrieval, gap handling and GraphRAG evaluation.
13. No retrieval mode is called superior without pre-registered ablation.
14. A graph answer without provenance or temporal correctness fails qualification.
15. Rights deletion followed by rebuild does not resurrect prohibited passages or embeddings.
16. Hermes receives named bounded tools and no general graph write credential.
17. Qualification failure blocks activation or requires repair or replacement; it never authorises graph-less production.
18. Acceptance creates no runtime authority.

## Completion record

The product owner accepted this specification on 2026-07-16 with these decisions:

- GraphRAG, vector and full-text projections are first-class parts of canonical schema v1 and the initial implementation programme;
- the relational ledger and governed object store remain authority, while graph and indexes are rebuildable projections;
- ADR 0001 and ADR 0002 are accepted together with this specification;
- one canonical identity, temporal, trust and ordered-event contract is shared by discovery and later evidence, publication and graph consumers;
- `OBSERVED`, `PROPOSED` and `ADMITTED` trust scopes are accepted;
- deterministic structural edges remain distinct from reified editorial relation proposals and assertions;
- entity resolution, merge, split and reversal are governed first-class records;
- Graphiti is proposal-only, isolated from the governed graph and followed by separate admission;
- projectors are ordered and idempotent, expose contiguous checkpoints and gaps, support blue-green generations and rebuild without stochastic re-extraction;
- retrieval is hybrid and hydrates exact authority from the ledger or object store;
- agents use named read-only tools and receive no unrestricted graph write or production Cypher authority;
- GraphRAG supplies advisory event, timeline and source-revision context while deterministic controllers retain Hypothesis, Candidate and evidence authority;
- graph failure is not no-match, safe collection may continue and graph-dependent work falls back only through approved exact paths or enters Watch or Operational Hold;
- Neo4j Community plus Graphiti is the initial production-target implementation, with another engine only after a measured blocker or separate owner-approved comparison purpose;
- initial success cases are event or development precision, source-revision impact and long-running policy, bill, case or incident timelines;
- GraphRAG evaluation includes entity and relation quality, temporal correctness, provenance, hybrid ablation, cost, lag, rebuild, security, rights purge and outage behaviour;
- complete live-shadow qualification requires the governed graph and hybrid retrieval path; and
- acceptance authorises no execution.
