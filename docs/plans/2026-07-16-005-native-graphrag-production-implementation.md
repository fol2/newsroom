# Native GraphRAG production implementation plan

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. This plan organises future code work. It authorises no engine installation, source access, extraction, embeddings, model call, spending, shadow run, canary, cutover or production activation.  
**Related review sequence:** [`2026-07-15-002-discovery-specification-review.md`](2026-07-15-002-discovery-specification-review.md)  
**Accepted authority decisions:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md)  
**Proposed native-production decision:** [`../adr/0005-native-graphrag-production-deployment.md`](../adr/0005-native-graphrag-production-deployment.md)  
**Related discovery decision:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md)  
**Supersedes:** [`2026-07-16-004-integrated-discovery-graphrag-implementation.md`](2026-07-16-004-integrated-discovery-graphrag-implementation.md), whose `POC` framing still permitted an incorrect two-stage interpretation

## Purpose

Deliver one repository-native Newsroom system whose first production deployment includes governed GraphRAG.

The programme does not produce a graph-less discovery application, run GraphRAG as a separate proof of concept and then decide whether to merge it. The relational authority plane, graph-aware canonical contract, governed graph projection, vector and full-text indexes, extraction and admission path and hybrid retrieval are parts of one product from the beginning.

Code is still delivered in dependency order and small pull requests. Dependency order is not product staging. No intermediate production, canary or complete live-shadow architecture is permitted without GraphRAG.

## Normative basis

Implementation must conform to all applicable Accepted requirements in:

- [`discovery-coverage-contract.md`](../specs/editorial-automation/discovery-coverage-contract.md): `COV-001`–`COV-045`;
- [`discovery-workflow.md`](../specs/editorial-automation/discovery-workflow.md): `FLOW-001`–`FLOW-102`;
- [`discovery-record-semantics.md`](../specs/editorial-automation/discovery-record-semantics.md): `DREC-001`–`DREC-077`;
- [`discovery-source-roles-and-selection.md`](../specs/editorial-automation/discovery-source-roles-and-selection.md): `SRC-001`–`SRC-044`;
- [`discovery-change-and-planned-agenda.md`](../specs/editorial-automation/discovery-change-and-planned-agenda.md): `CHG-001`–`CHG-045`, `AGEN-001`–`AGEN-016`;
- [`discovery-triage-and-event-grouping.md`](../specs/editorial-automation/discovery-triage-and-event-grouping.md): `TRI-001`–`TRI-085`;
- [`discovery-search-and-coverage-audit.md`](../specs/editorial-automation/discovery-search-and-coverage-audit.md): `SRCH-001`–`SRCH-053`, `CAUD-001`–`CAUD-009`;
- [`discovery-shadow-evaluation.md`](../specs/editorial-automation/discovery-shadow-evaluation.md): `DEVAL-001`–`DEVAL-074`;
- [`discovery-reliability-and-operations.md`](../specs/editorial-automation/discovery-reliability-and-operations.md): `DOPS-001`–`DOPS-076`;
- [`discovery-prioritisation-and-outcomes.md`](../specs/editorial-automation/discovery-prioritisation-and-outcomes.md): `DOUT-001`–`DOUT-026`, `DPRI-001`–`DPRI-026`;
- [`discovery-locality-scope-and-expansion.md`](../specs/editorial-automation/discovery-locality-scope-and-expansion.md): `LOC-001`–`LOC-064`;
- [`governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md): `GRAG-001`–`GRAG-058`; and
- [`graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md): `GRPROD-001`–`GRPROD-032` after owner acceptance.

ADR 0001 and ADR 0002 govern authority and the SQLite ledger. The proposed ADR 0005 governs GraphRAG as a mandatory production subsystem. This plan cannot make the graph authoritative and cannot make it optional.

## Non-negotiable production invariant

The production system is one deployment contract containing:

```text
canonical command service
+ SQLite editorial ledger
+ governed content-addressed object store
+ graph/vector/full-text projectors
+ admitted graph engine
+ Graphiti proposal path
+ entity/relation admission
+ hybrid retrieval service and named tools
+ discovery collection and triage
+ evaluation, health, backup and recovery controls
```

A release missing the graph, indexes or hybrid retrieval is not a reduced production profile. It is non-conforming and cannot be activated.

Temporary graph outage is handled as degraded operation inside this architecture. It is not a graph-free deployment mode.

## Proposed implementation decisions

1. Build the target beside the legacy pipeline; do not mutate legacy `links` and `events` into canonical records.
2. Create canonical production schema v1 directly, including graph identities, trust states, temporal semantics and projection events.
3. Use the Accepted single-host SQLite ledger and governed object store as authority in every environment.
4. Make GraphRAG a repository-native production subsystem rather than a plugin, experiment or external notebook.
5. Use Neo4j Community plus Graphiti as the initial production-target implementation, subject to release gates but not optional adoption.
6. Replace an implementation that fails qualification before activation; do not remove GraphRAG.
7. Keep Graphiti isolated and proposal-only; persist every extraction result before admission.
8. Project deterministic structure and admitted relations through idempotent ordered projectors.
9. Combine exact, full-text, vector and bounded graph retrieval behind named read-only tools.
10. Keep exact identity, current Candidate collision and authoritative decisions in the ledger.
11. Use a scheduler-neutral repository-owned command surface; Hermes, cron or another scheduler is replaceable.
12. Build generic source adapters and fixtures before enabling named live sources.
13. Keep external sources, search providers, extractors, embeddings and generative models disabled until exact gates pass.
14. Make the first complete vertical slice graph-native, from ledger write through hybrid retrieval to Candidate admission.
15. Run complete live shadow against the production-target GraphRAG stack or an approved production-equivalent environment.
16. End the first product slice at an evaluation Evidence Intake sink; never bridge directly to the legacy writer.
17. Deliver focused pull requests with requirement traceability, integration tests and rollback.
18. Keep legacy runtime isolated until a separate canary and production activation decision.
19. Carry forward no source-count ranking, category or finance cap, Hong Kong guaranteed slot or filler quota.
20. Treat plan acceptance, implementation, release qualification, canary and production activation as separate authorities.

## Target production architecture

```text
Approved trigger or authenticated command
                    |
                    v
        Repository-owned command boundary
          - principal and authority
          - idempotency and expected version
          - rights and Operational Profile
                    |
                    v
  SQLite editorial ledger + governed object store
          - canonical IDs and versions
          - source/discovery history
          - proposals and admission decisions
          - immutable outcomes and audit
          - consumer-neutral ledger events
          - permitted retained objects and hashes
                    |
       +------------+-------------+----------------+
       |                          |                |
       v                          v                v
Discovery collection       Knowledge projectors   Operational views
  - source registry          - Neo4j graph          - health
  - adapters                 - vector index         - queues
  - change engine            - full-text index      - audit
  - Signal/Lead                    |
  - Agenda                         v
       |                 hybrid retrieval service
       |                  + named read-only tools
       |                          |
       +---------------+----------+
                       v
             bounded Triage Work Item
               + structured proposal
                       |
                       v
            deterministic relationship,
          Event Hypothesis and Candidate admission
                       |
                       v
          evaluation Evidence Intake sink
                       |
              governed Evidence Intake later
```

Graphiti follows a separate, controlled proposal path:

```text
permitted source or workflow input
                |
                v
isolated Graphiti extraction workspace
                |
                v
immutable extraction output and proposals
                |
                v
ledger proposal records
                |
       separate admission decision
                |
                v
governed projector -> graph/vector/full-text
```

The authoritative transaction never synchronously writes Neo4j as a co-authority.

## Native repository structure

Names may change, but the repository must contain equivalent first-class modules rather than an external experiment.

```text
newsroom/
  authority/
    ids.py
    time.py
    trust.py
    commands.py
    ledger.py
    objects.py
    events.py
    projections.py

  discovery/
    registry.py
    profiles.py
    scheduler.py
    adapters/
    changes.py
    controller.py
    gates.py
    agenda.py
    search.py
    health.py

  knowledge/
    ontology.py
    records.py
    entity_resolution.py
    relation_admission.py
    extraction/
      base.py
      graphiti.py
    projectors/
      base.py
      graph.py
      vector.py
      full_text.py
    stores/
      base.py
      neo4j.py
    retrieval/
      exact.py
      full_text.py
      vector.py
      graph.py
      hybrid.py
      tools.py
    generations.py
    rebuild.py
    purge.py
    health.py

  triage/
    retrieval_context.py
    work_items.py
    worker.py
    decisions.py
    hypotheses.py
    candidates.py
    handoff.py

config/
  authority/
  discovery/
  knowledge/
    ontology/
    projectors/
    extraction/
    retrieval_tools/
    operational_profiles/
    rights/
    evaluation/

deploy/
  development/
  shadow/
  production/

scripts/
  newsroom_command.py
  discovery_tick.py
  knowledge_project.py
  knowledge_rebuild.py
  knowledge_status.py
  knowledge_purge.py
  discovery_reconcile.py
  evaluation_run.py
```

The final deployment technology may be Compose, system services, containers or another approved mechanism. Whatever is selected, the production definition must include GraphRAG and be versioned in the repository.

## Environment contract

### Unit and pure-contract tests

May use deterministic fake graph, extractor and embedding implementations to test isolated logic. They cannot be used as production substitutions.

### Integration environment

Runs the canonical SQLite schema, governed objects and an actual Neo4j service with the production graph interfaces. It proves projection, query metadata, gap handling, rebuild and credential boundaries.

### Evaluation and shadow environment

Runs the production-target graph engine, projector, indexes, extraction/admission path and hybrid retrieval. Any difference from production topology or configuration is declared in the Evaluation Plan.

### Production environment

Requires admitted versions of every mandatory GraphRAG component. Startup, readiness and deployment validation fail closed when the required graph configuration is missing or incompatible.

## Production component contract

The production deployment binds:

- command-service version;
- SQLite migration and event-envelope version;
- governed-object layout and encryption version;
- ontology version;
- Neo4j or admitted replacement version;
- graph, vector and full-text projector versions;
- Graphiti and extraction-model version;
- entity and relation admission policy;
- embedding, chunking and normalisation versions;
- retrieval and named-tool versions;
- projector freshness, gap and degraded-operation Profiles;
- backup, rebuild and purge procedures;
- security roles and secrets;
- resource and licence decisions; and
- rollback or engine-replacement path.

A production manifest with no admitted value for any mandatory component is invalid.

## Workstreams

### A — Canonical authority and object plane

Owns IDs, trust, time, commands, SQLite transactions, immutable objects, ordered events, audit, projection registrations, backup and recovery authority.

### B — Native knowledge and GraphRAG plane

Owns ontology, Neo4j integration, graph/vector/full-text projectors, checkpoints, generations, Graphiti, entity and relation admission, hybrid retrieval, named tools, rebuild and purge.

### C — Discovery collection plane

Owns source registry, adapters, changes, Signals, Leads, Agenda, bounded search, locality watches and coverage health.

### D — Triage and Candidate plane

Owns Retrieval Context, Work Items, proposal validation, Event Hypotheses, Candidate collision, Candidate admission and Evidence Handoff.

### E — Evaluation and operations plane

Owns fixtures, replay, relation and retrieval ablation, source coverage, graph quality, performance, security, licensing, recovery, shadow, canary and release evidence.

A workstream may start after its shared contracts exist. None becomes an independently activatable graph-less product.

## Delivery increments and pull-request boundaries

The increments below are merge and verification boundaries. They are not product stages and none authorises production.

### Increment 0 — Documentation and decision closure

- accept or amend the native-production amendment and ADR 0005;
- accept or amend this plan;
- reconcile ADR 0004;
- mark earlier POC-framed plans superseded;
- validate statuses, links and requirement references; and
- prepare one documentation-only pull request.

### Increment 1 — Native integrated foundation

**Deliverables**

- canonical graph-aware schema v1;
- SQLite command writer and governed objects;
- trust and temporal types;
- ordered event envelope;
- ontology v1;
- graph/vector/full-text projector interfaces;
- Neo4j repository integration and deployment definitions;
- graph credential roles and client boundary;
- projector checkpoint, gap and generation records;
- production configuration validator requiring GraphRAG; and
- CI integration path using an actual Neo4j service.

**Evidence**

- fresh schema creation with no legacy or interim migration;
- command fencing, rollback and event integrity;
- Neo4j connectivity and least-privilege role tests;
- missing production GraphRAG config fails validation;
- graph internal IDs never become canonical IDs; and
- ledger authority survives graph deletion.

This increment already makes GraphRAG a native project component. It does not merely reserve future interfaces.

### Increment 2 — First graph-native vertical fixture slice

**Deliverables**

- one fixture Source Item and Revision;
- canonical ledger event;
- deterministic structural graph projection;
- full-text and vector fixture indexes;
- a governed synthetic or deterministic admitted relation;
- bounded hybrid retrieval and authoritative hydration;
- trust-labelled Retrieval Context; and
- deterministic triage and Candidate admission using that context.

**Evidence**

- source fixture -> ledger -> graph/indexes -> retrieval -> Candidate works with one canonical identity set;
- exact/full-text/vector/graph ablation is executable;
- graph gap never becomes no match;
- Candidate collision remains relational;
- projection rebuild produces the same result; and
- no graph-free variant passes the complete-slice test.

### Increment 3 — Source adapters, change semantics and live-shaped discovery lineage

- generic RSS/Atom, JSON, current-state, maintained-document and Agenda adapters;
- source-specific identities, baselines and observation models;
- strict transport and parser controls;
- Check, Revision, Signal, Gate and Lead records;
- graph projection of source and discovery lineage;
- source, graph and portfolio health; and
- offline fixture and approved capture corpus.

Named live sources remain disabled.

### Increment 4 — Native extraction, entity resolution and relation admission

- Graphiti adapter in an isolated workspace;
- Extraction Runs and immutable raw structured output where permitted;
- Entity Mention, Canonical Entity, Alias and resolution decisions;
- merge, split and reversal;
- Relation Proposal, Assertion and Admission Decision;
- admitted projection and proposal-scoped research surface; and
- bilingual English/Traditional-Chinese fixtures.

Deterministic fake extraction lands first in the same code path. A real Graphiti/model version requires separate rights, privacy, cost and Evaluation Plan approval, but the production implementation is part of the project rather than a separate experiment.

### Increment 5 — Production hybrid retrieval and named tools

- exact, full-text, vector and graph retrievers;
- dependency-aware reranking;
- source-origin deduplication;
- authoritative passage and decision hydration;
- query metadata, watermark and gap enforcement;
- named tools with purpose, depth, fan-out, date, trust, timeout and budget limits;
- stale and unavailable behaviour; and
- security and query-amplification tests.

### Increment 6 — Full triage, Event Hypotheses, Candidates and Handoff

- immutable Work Items and batches;
- decision versus context-only Leads;
- structured proposal-only worker;
- same state, development, correction, related-distinct, no-match and uncertain decisions;
- append-only Hypothesis create, associate, consolidate and split;
- exact Candidate collision and admission;
- Candidate and Handoff versioning; and
- evaluation Evidence Intake sink.

GraphRAG rank and confidence remain non-authoritative.

### Increment 7 — Agenda, bounded search and Event-Scoped Local Watch

- Agenda versions, windows, confirmation and missed findings;
- Search Purpose, Request, Attempt, Outcome and audit records;
- provider interface disabled by default;
- Event-Scoped Local Watch and expiry; and
- prospective versus retrospective labels.

### Increment 8 — Integrated evaluation, operations, recovery and security

- Evaluation Plans and frozen Epochs;
- event-level labels and stage metrics;
- source and GraphRAG ablation;
- queue, lease and reconciliation;
- graph and ledger backup/recovery;
- destructive graph/index rebuild;
- rights/privacy purge and rebuild;
- projection generation switch;
- licence and intended-hardware evidence;
- fault injection and degraded-operation tests; and
- production deployment readiness validation.

### Increment 9 — First executable production-equivalent shadow plan

Requires a separate owner-approved plan binding exact:

- sources and rights;
- SQLite and object versions;
- Neo4j, Graphiti, ontology, projector and index versions;
- model and embedding versions;
- retrieval tools and thresholds;
- Operational Profiles and budgets;
- reviewers and stop conditions;
- licence decision; and
- production-equivalence declaration.

The complete shadow runs GraphRAG. Adapter-only live checks may be approved earlier but cannot qualify the product.

### Increment 10 — Governed Evidence Intake canary

Only after discovery, GraphRAG, operational and rights gates pass. The canary uses the production-target graph stack and hands exact Candidate Versions to governed Evidence Intake. It adds no direct publication path.

### Increment 11 — Production activation and legacy retirement

Production activation is one explicit owner decision binding all mandatory graph and relational versions. There is no activation option that excludes GraphRAG.

Legacy Brave, RSS, GDELT, per-link Gemini clustering, destructive merge and quota paths remain isolated until retirement criteria pass.

## Native GraphRAG release gates

The mandatory subsystem must pass:

- ontology and canonical-ID integrity;
- entity-resolution quality, including bilingual false merges;
- event, development, correction and related-distinct quality;
- provenance completeness;
- temporal correctness;
- hybrid retrieval ablation;
- projection checkpoint and gap correctness;
- destructive rebuild without extraction replay drift;
- rights and privacy purge;
- query and credential security;
- backup and recovery;
- intended-hardware performance and capacity;
- licence and commercial-use review;
- deployment and upgrade behaviour; and
- graph outage and stale-projection handling.

A failed gate blocks activation or requires implementation replacement. It does not downgrade GraphRAG to a backlog.

## Engine substitution rule

The project owns interfaces and canonical semantics, but the first production target is Neo4j Community plus Graphiti.

An alternative engine may replace Neo4j before activation when evidence shows a blocker. Replacement must:

- implement the same ontology and projection contracts;
- preserve canonical IDs and ordered-event replay;
- pass the same quality and operational tests;
- preserve trust and provenance;
- rebuild from the same ledger and objects;
- keep named-tool behaviour compatible or explicitly versioned; and
- complete before production activation.

This is a component replacement inside one target architecture, not a second stage.

## Degraded operation after deployment

Temporary graph outage does not erase native production support.

- Collection may continue safely where independent requirements pass.
- Graph-dependent retrieval becomes unavailable, stale or gapped explicitly.
- Exact fallbacks are permitted only for evaluated routes.
- Other Leads wait or hold.
- Projectors recover from their checkpoint.
- Production health and incident records show the impairment.
- The graph service remains a mandatory component to restore.

## Legacy and migration boundary

- Legacy IDs and clusters are not canonical identities.
- No silent canonical-to-legacy dual write exists.
- Historical import requires a separate idempotent adapter and owner decision.
- The new graph never treats legacy mutable event state as authority.
- Cutover requires no later graph semantic migration because GraphRAG is native from schema v1.

## Testing strategy

Every implementation pull request includes the applicable layers:

| Test class | Required purpose |
|---|---|
| Unit | identity, trust, time, outcomes, ontology and pure transition rules |
| Ledger integration | commands, fences, transactions, migrations, objects and events |
| Native graph integration | Neo4j connectivity, roles, projection, query metadata and rebuild |
| Extraction and admission | Graphiti isolation, proposal persistence, resolution and relation decisions |
| Adapter contract | source shape, baseline, partial, failure and change semantics |
| Hybrid retrieval | exact, lexical, vector, graph and combined bilingual ablation |
| Workflow integration | source or fixture through graph context, Candidate and Handoff |
| Replay and property | duplicates, crash recovery, malformed input and deterministic history |
| Fault injection | graph gaps, projector failure, extractor failure, store failure and outage |
| Backup and purge | ledger/object recovery, graph rebuild and prohibited-data non-resurrection |
| Security | SSRF, parsing, credentials, Cypher boundaries, query budgets and prompt injection |
| Production-manifest validation | graph components cannot be omitted or replaced by fakes |
| Live evaluation | coverage, GraphRAG quality, cost, lag, operations and licence |

Ordinary CI makes no unbounded source or model calls. It does run deterministic Neo4j integration through the repository-approved test mechanism.

## Pull-request strategy

The current branch becomes one documentation-only pull request after the native-production amendment, ADR 0005, Topic 13 and ADR 0004 receive final decisions.

Implementation then uses focused pull requests. Recommended order:

1. native integrated foundation;
2. first graph-native vertical fixture slice;
3. source adapters and discovery lineage;
4. Graphiti, entity resolution and relation admission;
5. hybrid retrieval and named tools;
6. triage, Candidates and Handoff;
7. Agenda, search and local watch;
8. evaluation, operations, recovery and security;
9. approved production-equivalent shadow;
10. governed Evidence Intake canary; and
11. production activation and legacy retirement.

Several pull requests may proceed concurrently after shared contracts merge. None creates an intermediate graph-less product release.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `POC` becomes permanent side project | GraphRAG is mandatory in production manifests and complete vertical tests |
| Relational design later needs graph migration | Graph-aware canonical schema, trust and events from v1 |
| Graph becomes authority | Ledger proposal/admission and projector-only writes |
| Neo4j blocks deployment | Replace before activation under the same contract; no graph-less release |
| Graphiti creates false facts | Proposal isolation, admission, provenance and replay |
| Graph failure becomes false new event | Gap metadata, exact fallback or Watch/Hold |
| Native graph increases cost without value | Pre-registered quality, ablation and cost gates, while capability remains mandatory |
| Production config silently disables graph | Repository validation and deployment tests fail closed |
| Two systems coexist indefinitely | Explicit canary, activation and retirement decision |
| Legacy semantics leak into graph | No legacy identity import or authoritative projection from legacy clusters |

## Decisions required to accept the plan

The plan recommends that the owner accept:

1. GraphRAG as a native mandatory part of the first production deployment, with no POC or optional-adoption stage.
2. One canonical schema and event contract serving relational authority and GraphRAG from v1.
3. Side-by-side legacy replacement rather than in-place mutation.
4. SQLite ledger and governed objects as authority, without making graph optional.
5. Neo4j Community plus Graphiti as the initial production-target implementation.
6. Replacement before activation if that stack fails gates, with no graph-less fallback.
7. Repository-native GraphRAG modules, configuration, deployment, operations and tests.
8. A production profile that cannot omit or fake GraphRAG.
9. Graph contract, Neo4j integration and deployment plumbing in the first code increment.
10. A graph-native first complete vertical slice.
11. Persisted extraction proposals and separate admission before governed projection.
12. Ordered graph/vector/full-text projectors and hybrid named-tool retrieval.
13. Relational authority for exact identities and Candidate collision, with GraphRAG advisory.
14. Generic adapters and offline fixtures before named source enablement.
15. Production-equivalent complete shadow using the production-target graph stack.
16. Eleven dependency-ordered increments that are merge boundaries, not product stages.
17. Separate release qualification, GraphRAG admission, Evidence Intake canary, activation and retirement decisions.
18. No legacy identity import, silent dual write, source-count ranking, quotas or filler.
19. The current branch remaining documentation-only until the documentation pull request is approved.
20. Acceptance of this plan authorising no runtime action.

## Open implementation choices

Acceptance deliberately leaves evidence-dependent details to later approved work:

- exact SQLite tables and command-service process;
- object-store encryption and filesystem mechanism;
- exact ontology predicates and entity classes;
- Neo4j edition, packaging, process topology and backup mechanism;
- exact Graphiti, model, embedding, chunking and normalisation versions;
- vector and full-text index implementation;
- named-tool limits and freshness thresholds;
- source versions and first live Evaluation Plan;
- search provider, if any;
- Operational Profile values;
- Evidence Intake transport;
- hosting and observability services;
- selected Locality Coverage Units; and
- production activation date.