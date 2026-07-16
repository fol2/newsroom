# Native GraphRAG production implementation plan

**Status:** Accepted  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Accepted by owner:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. Acceptance organises future code work. It authorises no engine installation, source access, extraction, embeddings, model call, spending, shadow run, canary, cutover or production activation.  
**Related review sequence:** [`2026-07-15-002-discovery-specification-review.md`](2026-07-15-002-discovery-specification-review.md)  
**Accepted architecture decisions:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md), [`../adr/0005-native-graphrag-production-deployment.md`](../adr/0005-native-graphrag-production-deployment.md)  
**Accepted native-production contract:** [`../specs/editorial-automation/graphrag-native-production-deployment.md`](../specs/editorial-automation/graphrag-native-production-deployment.md)  
**Related discovery ADR:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md) (`Proposed`)  
**Supersedes:** [`2026-07-16-004-integrated-discovery-graphrag-implementation.md`](2026-07-16-004-integrated-discovery-graphrag-implementation.md), whose POC framing preserved an incorrect two-stage interpretation

## Purpose

Deliver one repository-native Newsroom system whose first production deployment includes governed GraphRAG.

The programme does not build a graph-less discovery application, run GraphRAG as a separate proof of concept and then decide whether to merge it. The relational authority plane, graph-aware canonical contract, governed graph projection, vector and full-text indexes, extraction and admission path and hybrid retrieval are parts of one product from the beginning.

Code is delivered in dependency order and small pull requests. Dependency order is not product staging. No intermediate production, canary or complete live-shadow architecture may omit GraphRAG.

## Normative basis

Implementation must conform to the applicable Accepted discovery requirements (`COV`, `FLOW`, `DREC`, `SRC`, `CHG`, `AGEN`, `TRI`, `SRCH`, `CAUD`, `DEVAL`, `DOPS`, `DOUT`, `DPRI`, `LOC`, `GRAG` and `GRPROD`) and to ADR 0001, ADR 0002 and ADR 0005.

This plan cannot make the graph authoritative and cannot make it optional.

## Non-negotiable production invariant

The production system is one deployment contract containing:

```text
canonical command service
+ SQLite editorial ledger
+ governed content-addressed object store
+ graph, vector and full-text projectors
+ admitted graph engine
+ isolated extraction and proposal path
+ entity and relation admission
+ hybrid retrieval and named tools
+ discovery collection and triage
+ evaluation, health, backup and recovery controls
```

A release missing the graph, indexes or hybrid retrieval is non-conforming and cannot be activated.

Temporary graph outage is degraded operation inside this architecture. It is not a graph-free deployment mode.

## Accepted implementation decisions

1. Build beside the legacy pipeline; do not mutate legacy `links` and `events` into canonical records.
2. Create canonical production schema v1 directly, including graph identities, trust, time and projection events.
3. Use the Accepted single-host SQLite ledger and governed object store as authority in every environment.
4. Make GraphRAG a repository-native production subsystem rather than a plugin, experiment or external notebook.
5. Use Neo4j Community plus Graphiti as the initial production-target implementation.
6. Repair or replace a failing implementation before activation; never remove GraphRAG.
7. Keep Graphiti isolated and proposal-only; persist extraction output before admission.
8. Project deterministic structure and admitted relations through idempotent ordered projectors.
9. Combine exact, full-text, vector and bounded graph retrieval behind named read-only tools.
10. Keep exact identity and Candidate-collision authority in the relational ledger.
11. Use a scheduler-neutral repository-owned command surface.
12. Build generic adapters and fixtures before enabling named live sources.
13. Keep all real sources, providers, extractors, embeddings and generative models disabled until exact gates pass.
14. Make the first complete vertical slice graph-native from ledger write to Candidate admission.
15. Run complete live shadow against the production-target GraphRAG stack or an approved production-equivalent environment.
16. End the first product slice at an evaluation Evidence Intake sink rather than the legacy writer.
17. Deliver focused pull requests with requirement traceability, integration evidence and rollback.
18. Keep legacy runtime isolated until separate canary and activation decisions.
19. Carry forward no source-count ranking, category or finance cap, Hong Kong guaranteed slot or filler quota.
20. Keep plan acceptance, implementation, qualification, canary and production activation separate.

## Target architecture

```text
Approved trigger or authenticated command
                    |
                    v
        repository-owned command boundary
                    |
                    v
 SQLite editorial ledger + governed object store
   - canonical identities, versions and audit
   - proposals and admission decisions
   - consumer-neutral ordered events
   - retained permitted objects and hashes
                    |
      +-------------+--------------+
      |                            |
      v                            v
Discovery plane             Knowledge plane
- registry/adapters         - Neo4j graph
- change/Signal/Lead        - vector/full-text
- Agenda/search/watch       - projectors/gaps
      |                            |
      +-------------+--------------+
                    v
        named hybrid retrieval tools
                    |
                    v
           bounded Triage Work Item
                    |
                    v
   deterministic Hypothesis/Candidate admission
                    |
                    v
       evaluation Evidence Intake sink
                    |
          governed Evidence Intake later
```

Graphiti follows an isolated path:

```text
permitted input
→ Graphiti proposal workspace
→ immutable extraction output and proposals
→ ledger proposal records
→ separate admission decision
→ governed graph/vector/full-text projection
```

The authoritative transaction never synchronously writes Neo4j as a co-authority.

## Native repository boundary

The project contains equivalent first-class modules for:

- canonical authority, objects and ordered events;
- discovery registry, adapters, changes, Signals and Leads;
- graph ontology and entity or relation records;
- Graphiti and other extraction adapters;
- graph, vector and full-text projectors;
- Neo4j integration;
- hybrid retrieval and named tools;
- triage, Event Hypotheses, Candidates and Handoffs;
- health, gaps, reconciliation, rebuild and purge; and
- evaluation and production deployment configuration.

A representative layout is:

```text
newsroom/
  authority/
  discovery/
  knowledge/
    ontology.py
    entity_resolution.py
    relation_admission.py
    extraction/
    projectors/
    stores/
    retrieval/
    rebuild.py
    health.py
  triage/
config/
  authority/
  discovery/
  knowledge/
deploy/
  development/
  evaluation/
  production/
scripts/
  newsroom_command.py
  discovery_tick.py
  knowledge_project.py
  knowledge_rebuild.py
  knowledge_status.py
  evaluation_run.py
```

Names may change. The capabilities, ownership and boundaries may not be moved to an undocumented separate experiment.

## Environment contract

### Unit environment

May use deterministic fake graph, extractor and embedding implementations for isolated logic. Fakes are not production substitutions.

### Integration environment

Runs canonical SQLite, governed objects and an actual Neo4j service through production interfaces. It proves projection, query metadata, gap handling, rebuild and credential boundaries.

### Evaluation and shadow environment

Runs the production-target graph engine, projectors, indexes, extraction/admission path and hybrid retrieval. Every meaningful difference from production is declared in the Evaluation Plan.

### Production environment

Requires admitted versions of every mandatory GraphRAG component. Build, startup and readiness validation fail closed when required graph configuration is missing, incompatible, disabled or fake.

## Production component contract

Production activation binds exact versions of:

- command service, SQLite schema and ordered event envelope;
- governed object storage;
- ontology;
- graph, vector and full-text projectors;
- graph engine;
- extraction framework and model where used;
- entity and relation admission policy;
- embedding, chunking and normalisation;
- named tools and retrieval policy;
- freshness, gap and degraded-operation Profiles;
- backup, rebuild and purge procedures;
- security roles and secrets;
- resource and licence decisions; and
- rollback or engine-replacement path.

A production manifest with a missing mandatory component is invalid.

## Workstreams

### A — Authority and objects

Canonical IDs, trust, time, commands, SQLite transactions, objects, ordered events, audit, backup and recovery authority.

### B — Native knowledge and GraphRAG

Ontology, Neo4j, graph/vector/full-text projectors, Graphiti, entity/relation admission, hybrid retrieval, named tools, rebuild and purge.

### C — Discovery collection

Source registry, adapters, changes, Signals, Leads, Agenda, bounded search, locality watch and coverage health.

### D — Triage and Candidate

Retrieval Context, Work Items, proposal validation, Event Hypotheses, collision control, Candidate admission and Handoff.

### E — Evaluation and operations

Fixtures, replay, ablation, coverage, graph quality, performance, security, licensing, recovery, shadow, canary and release evidence.

Workstreams may overlap after shared contracts merge. None is an independently activatable graph-less product.

## Delivery increments

These are merge and verification boundaries, not product stages. None authorises production.

### Increment 0 — Documentation closure

Accept or amend the detailed production contract and this plan, decide ADR 0004, validate cross-references and prepare a documentation-only pull request.

### Increment 1 — Native integrated foundation

Deliver:

- canonical graph-aware schema v1;
- SQLite command writer and governed objects;
- trust and temporal types;
- ordered event envelope;
- ontology v1;
- graph/vector/full-text projector interfaces;
- Neo4j repository integration and deployment definitions;
- graph credentials and client boundary;
- checkpoint, gap and generation records;
- production configuration validator requiring GraphRAG; and
- CI integration against an actual Neo4j service.

Evidence includes fresh schema creation, command fencing, event integrity, Neo4j least privilege, graph-config failure tests and proof that graph deletion loses no authority.

### Increment 2 — First graph-native complete fixture slice

Exercise:

```text
fixture Source Revision
→ canonical ledger event
→ structural graph projection and indexes
→ governed fixture relation
→ hybrid retrieval and authoritative hydration
→ trust-labelled context
→ deterministic Candidate admission
```

The complete-slice test has no graph-free passing variant.

### Increment 3 — Source adapters and discovery lineage

Implement generic RSS/Atom, JSON, current-state, maintained-document and Agenda adapters; strict transport and parser controls; source identity, baseline and change semantics; Checks, Signals and Leads; graph projection of discovery lineage; and source/graph/coverage health.

Named live sources remain disabled.

### Increment 4 — Extraction, entity resolution and relation admission

Implement Graphiti integration, Extraction Runs, entity resolution, merge/split/reversal, Relation Proposals and Admission Decisions, admitted projection and bilingual fixtures.

Deterministic fake extraction is used first through the same interfaces. A real model version still needs separate rights, cost and Evaluation Plan approval.

### Increment 5 — Production hybrid retrieval and named tools

Implement exact, full-text, vector and bounded graph retrievers; dependency-aware deduplication; authoritative hydration; watermark and gap enforcement; named tools; query budgets; security; and ablation.

### Increment 6 — Full triage, Hypotheses, Candidates and Handoff

Implement Work Items, context-only Leads, structured proposals, relationship decisions, append-only Event Hypotheses, relational collision checks, Candidate admission/versioning and evaluation Handoff.

Graph rank remains advisory.

### Increment 7 — Agenda, bounded search and local watch

Implement Agenda lifecycle, bounded Search records, privacy validation, Event-Scoped Local Watch and prospective-versus-retrospective audit labels. Providers remain disabled until exact gates pass.

### Increment 8 — Evaluation, operations, recovery and security

Implement Evaluation Plans and Epochs, review workflows, source and retrieval ablation, queue and reconciliation, ledger/graph backup and restore, destructive rebuild, rights purge, generation switch, fault injection, licence and intended-hardware qualification and production readiness validation.

### Increment 9 — Production-equivalent integrated shadow

A separate owner-approved plan binds exact sources, SQLite/object versions, graph engine, ontology, projectors, Graphiti, embeddings, retrieval tools, Operational Profiles, reviewers, budgets, licence and production-equivalence statement.

Adapter-only live checks may occur earlier but cannot qualify the product.

### Increment 10 — Governed Evidence Intake canary

After discovery, GraphRAG, rights and operational gates pass, hand a bounded set of Candidate Versions to governed Evidence Intake using the production-target GraphRAG deployment. Add no direct publication path.

### Increment 11 — Production activation and legacy retirement

One explicit owner decision binds every mandatory relational and GraphRAG version. There is no activation option without GraphRAG.

Legacy Brave, RSS, GDELT, per-link Gemini, destructive merge and quota paths remain isolated until explicit retirement criteria pass.

## Native GraphRAG release gates

The mandatory subsystem must pass:

- canonical-ID and ontology integrity;
- bilingual entity resolution;
- same-event, development, correction and related-distinct quality;
- provenance and temporal correctness;
- hybrid retrieval ablation;
- checkpoint and gap correctness;
- destructive rebuild without stochastic historical rewrite;
- rights and privacy purge;
- query and credential security;
- backup and recovery;
- intended-hardware performance and capacity;
- product-use licence review;
- deployment and upgrade behaviour; and
- graph outage and stale-projection handling.

Failure blocks activation or requires implementation replacement. It does not make GraphRAG a backlog.

## Engine substitution

Neo4j Community plus Graphiti is the accepted initial production target.

An alternative may replace it before activation only when evidence shows a blocker. Replacement must preserve canonical IDs, event replay, trust, provenance, proposal/admission history, rebuild and named-tool behaviour and must pass the same gates.

That is component substitution inside one architecture, not a second product stage.

## Degraded operation after deployment

Temporary graph outage does not erase native support:

- safe collection may continue;
- graph-dependent work becomes explicitly unavailable, stale or gapped;
- exact fallbacks are limited to evaluated routes;
- other work waits or holds;
- projectors recover from checkpoints; and
- the graph remains a mandatory component to restore.

## Legacy boundary

- Legacy IDs and clusters are not canonical identities.
- There is no silent target-to-legacy dual write.
- Historical import requires a separate idempotent adapter and decision.
- Graph projection never treats legacy mutable event state as authority.
- Cutover requires no later GraphRAG semantic migration.

## Testing strategy

Every implementation pull request includes applicable tests:

| Test class | Purpose |
|---|---|
| Unit | identity, trust, time, outcomes, ontology and transitions |
| Ledger integration | commands, transactions, migrations, objects and events |
| Native graph integration | Neo4j roles, projection, query metadata and rebuild |
| Extraction/admission | proposal provenance, resolution and relation decisions |
| Adapter contract | source shape, baseline, partial, failure and change semantics |
| Hybrid retrieval | exact, lexical, vector, graph and combined bilingual ablation |
| Workflow integration | source or fixture through graph context, Candidate and Handoff |
| Fault/replay | duplicates, crashes, projector gaps, extractor and store failures |
| Backup/purge | coordinated recovery and prohibited-data non-resurrection |
| Security | SSRF, parsing, graph credentials, query budgets and injection |
| Manifest validation | production cannot omit or fake GraphRAG |
| Live evaluation | coverage, graph quality, cost, lag, operations and licence |

Ordinary CI makes no unbounded source or model calls. It does run an approved actual-Neo4j integration path.

## Pull-request strategy

The current branch becomes one documentation-only pull request after this plan and ADR 0004 receive final decisions.

Implementation uses focused pull requests matching the increments. Several may proceed concurrently after shared contracts merge. None creates an intermediate graph-less product release.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| POC becomes a permanent side project | GraphRAG is required in production manifests and complete-slice tests |
| Relational design later needs graph redesign | Graph-aware canonical schema and events from v1 |
| Graph becomes hidden authority | Ledger proposals/admissions and projector-only writes |
| Neo4j blocks production | Replace before activation under the same contract; no graph-less release |
| Graphiti creates false facts | Proposal isolation, admission, provenance and replay |
| Graph failure becomes false new event | Gap metadata, exact fallback or Watch/Hold |
| Production config disables graph | Build and readiness validation fail closed |
| GraphRAG cost exceeds value | Pre-registered quality, cost and capacity gates while the capability remains mandatory |
| Legacy creates two authorities | Side-by-side isolation and no silent dual write |

## Open implementation choices

Acceptance leaves evidence-dependent details to later decisions: exact SQLite tables and command process; object storage; ontology predicates; Neo4j edition, packaging and backup; Graphiti/model/embedding versions; vector and full-text implementation; named-tool limits; live sources; search provider; Operational Profiles; Evidence Intake transport; hosting and observability; locality selection; and activation date.

## Completion record

The product owner accepted this plan on 2026-07-16.

The accepted clarifications are:

1. Neo4j Community plus Graphiti is the initial production-target implementation, not a POC.
2. An implementation that fails release gates is repaired or replaced before activation; the product does not launch graph-less.
3. GraphRAG code, deployment, operations and tests are native to the principal repository.
4. A production profile cannot disable, omit or fake GraphRAG.
5. The first code increment includes graph deployment, ontology, projection and actual graph-service integration plumbing.
6. The first complete vertical slice traverses the ledger, governed GraphRAG retrieval and deterministic Candidate admission.
7. Complete live shadow uses the production-target graph stack or an explicitly approved production-equivalent environment.
8. The eleven increments are merge and verification boundaries rather than product stages.
9. Exact identity and Candidate-collision authority remains relational.
10. Graphiti output is persisted as proposals and separately admitted before governed projection.
11. Evaluation Plan, Operational Admission, Evidence Intake canary, production activation and retirement remain separate safety gates.
12. Acceptance authorises no runtime action.
