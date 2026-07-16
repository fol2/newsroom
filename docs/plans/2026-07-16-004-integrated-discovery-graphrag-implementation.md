# Integrated discovery and GraphRAG implementation plan

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. This plan proposes implementation sequencing and concrete boundaries. Acceptance would organise later code work but would not authorise a source, graph engine, extractor, embedding, model call, external request, spending, shadow run, canary, cutover or production activation.  
**Related review sequence:** [`2026-07-15-002-discovery-specification-review.md`](2026-07-15-002-discovery-specification-review.md)  
**Accepted authority ADRs:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md)  
**Related discovery ADR:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md) (`Proposed`; final review follows this plan)  
**Supersedes:** [`2026-07-16-003-discovery-implementation-and-migration.md`](2026-07-16-003-discovery-implementation-and-migration.md)

## Purpose

Implement the Accepted discovery and governed GraphRAG contracts as one target architecture without turning the current Brave, RSS, GDELT and Gemini pipeline into either:

- an in-place accumulation of incompatible semantics; or
- a graph-less interim product that must later be redesigned around a knowledge graph.

The programme builds one canonical identity, temporal, trust and ordered-event contract from schema v1. A SQLite editorial ledger and governed object store provide authority. Neo4j, vector and full-text structures provide rebuildable knowledge and retrieval projections. Discovery, GraphRAG and later evidence or publication consumers share the same contract.

Code is delivered in dependency order and small pull requests. The graph workstream begins with the canonical foundation and must be included before complete end-to-end live-shadow qualification.

## Normative basis

Implementation must conform to every applicable Accepted requirement in:

- [`discovery-coverage-contract.md`](../specs/editorial-automation/discovery-coverage-contract.md): `COV-001`–`COV-045`;
- [`discovery-workflow.md`](../specs/editorial-automation/discovery-workflow.md): `FLOW-001`–`FLOW-102`;
- [`discovery-record-semantics.md`](../specs/editorial-automation/discovery-record-semantics.md): `DREC-001`–`DREC-077`;
- [`discovery-source-roles-and-selection.md`](../specs/editorial-automation/discovery-source-roles-and-selection.md): `SRC-001`–`SRC-044`;
- [`discovery-change-and-planned-agenda.md`](../specs/editorial-automation/discovery-change-and-planned-agenda.md): `CHG-001`–`CHG-045` and `AGEN-001`–`AGEN-016`;
- [`discovery-triage-and-event-grouping.md`](../specs/editorial-automation/discovery-triage-and-event-grouping.md): `TRI-001`–`TRI-085`;
- [`discovery-search-and-coverage-audit.md`](../specs/editorial-automation/discovery-search-and-coverage-audit.md): `SRCH-001`–`SRCH-053` and `CAUD-001`–`CAUD-009`;
- [`discovery-shadow-evaluation.md`](../specs/editorial-automation/discovery-shadow-evaluation.md): `DEVAL-001`–`DEVAL-074`;
- [`discovery-reliability-and-operations.md`](../specs/editorial-automation/discovery-reliability-and-operations.md): `DOPS-001`–`DOPS-076`;
- [`discovery-prioritisation-and-outcomes.md`](../specs/editorial-automation/discovery-prioritisation-and-outcomes.md): `DOUT-001`–`DOUT-026` and `DPRI-001`–`DPRI-026`;
- [`discovery-locality-scope-and-expansion.md`](../specs/editorial-automation/discovery-locality-scope-and-expansion.md): `LOC-001`–`LOC-064`; and
- [`governed-graphrag-and-knowledge-projection.md`](../specs/editorial-automation/governed-graphrag-and-knowledge-projection.md): `GRAG-001`–`GRAG-058`.

ADR 0001 and ADR 0002 govern authority, projection and the canonical SQLite ledger. This plan may organise those decisions but cannot weaken them.

## Proposed implementation decisions

The owner is asked to accept the following implementation choices.

1. Build the new system beside the legacy pipeline. Do not mutate legacy `links` and `events` into the canonical model.
2. Create canonical production schema v1 directly. Do not create a discovery-only semantic schema followed by a graph-aware migration.
3. Use one canonical SQLite ledger and governed content-addressed object-store contract for authoritative records. Test, replay, shadow and later production use separate physical environments created from the same migrations and event contract.
4. Define graph ontology, trust states, projection event mappings and projection metadata in the first canonical-contract milestone.
5. Use Neo4j Community plus Graphiti as the first compatibility-focused GraphRAG proof-of-concept lane, not as automatic production admission.
6. Keep Graphiti in an isolated proposal workspace. Persist extraction outputs and proposals in the ledger before separate admission and governed projection.
7. Build exact, full-text, vector and bounded graph retrieval as one hybrid retrieval layer behind named read-only tools.
8. Keep exact identity and Candidate-collision checks authoritative in the relational ledger. GraphRAG remains advisory context.
9. Use a repository-owned scheduler-neutral deterministic command surface. Hermes, cron or another scheduler may invoke it without defining semantic authority.
10. Implement generic adapters, observation models and fixtures before enabling named live sources.
11. Keep all real sources, providers, extractors, embeddings and model workers disabled until exact rights, Evaluation Plan, Operational Profile and budget gates pass.
12. End the first complete vertical slice at an evaluation-scoped Evidence Intake sink. Do not connect discovery directly to the existing writer.
13. Require the governed graph, hybrid retrieval, projection-gap behaviour and GraphRAG evaluation before complete end-to-end live-shadow qualification.
14. Deliver code through focused milestone or thin vertical-slice pull requests with requirement traceability, tests, rollback and explicit non-authority.
15. Keep the legacy live system isolated until a separate canary and production-activation decision. There is no silent dual write or automatic graduation.
16. Carry forward no source-count ranking, category or finance cap, Hong Kong guaranteed slot or filler quota.

## Target architecture

```text
Authenticated commands and approved triggers
                |
                v
Canonical command boundary
  - caller and authority
  - idempotency and expected version
  - rights and Operational Profile
                |
                v
SQLite editorial ledger + governed object store
  - canonical identities and versions
  - source and discovery history
  - trust-scoped proposals and admissions
  - immutable decisions and audit
  - consumer-neutral ordered ledger events
  - exact retained permitted bytes and hashes
                |
       +--------+---------+----------------+
       |                  |                |
       v                  v                v
Discovery workflow   Knowledge projectors  Operational projections
  - adapters           - Neo4j graph         - health
  - change engine      - vector index        - queues
  - Signals/Leads      - full-text index     - audit views
  - Agenda                   |
       |                      v
       |             named hybrid retrieval tools
       |                      |
       +----------+-----------+
                  v
        bounded Triage Work Items
          - retrieval context
          - structured proposal
                  |
                  v
      deterministic relationship and
             Candidate admission
                  |
                  v
       evaluation Evidence Intake sink
                  |
          governed Evidence Intake later
```

Graphiti follows a separate path:

```text
permitted source or workflow input
        |
        v
isolated Graphiti proposal workspace
        |
        v
immutable entity and relation proposals
        |
        v
ledger proposal records and admission decisions
        |
        v
governed projector -> Neo4j / vector / full-text
```

The graph is never synchronously written as a co-authority inside the authoritative command transaction.

## Canonical schema-v1 boundary

The first schema version must establish stable catalogues and extension points before consumers are built.

### Identity and version spine

At minimum:

- Source Definition and Version;
- Source Item, Revision and Representation;
- Check Request, Attempt and Outcome;
- Discovery Occurrence, Signal and Lead;
- Gate and Lead Disposition Decisions;
- Triage Work Item and Proposal;
- Event Hypothesis and Version;
- Story Candidate and Version;
- Evidence Handoff and acknowledgement or feedback references;
- Planned Agenda Item and Version;
- Operational Finding and Coverage Gap;
- Entity Mention, Alias and Canonical Entity;
- Entity Resolution Proposal, Decision, Merge, Split and Reversal;
- Extraction Run;
- Relation Proposal, Relation Assertion and Relation Admission Decision;
- governed object identity and manifest;
- ledger event, projector, checkpoint, gap, dead letter and projection generation; and
- reserved stable extension namespaces for later Source Observation, Claim, Evidence Package, Story, Story Version and publication identities.

Later domains do not need complete behaviour before discovery fixtures run. Their identity and event boundaries must not require planned reinterpretation of existing records.

### Ordered event envelope

Every authoritative change emits a versioned consumer-neutral event with at least:

- monotonic ledger sequence;
- event identity and type;
- schema version;
- aggregate type, identity and version;
- authoritative recorded time;
- correlation and causation identities;
- producer version;
- payload digest or immutable object reference;
- trust scope;
- rights, security and retention routing metadata; and
- projection-relevant compatibility metadata.

Protected content stays outside the routing envelope and is loaded only by an authorised consumer.

### Trust and time

Schema v1 preserves:

- `OBSERVED`, `PROPOSED` and `ADMITTED` or exact equivalent trust states;
- source-published and source-revised time;
- Newsroom-observed and collected time;
- source-asserted effective or validity time;
- ledger-recorded, proposal, admission and invalidation time; and
- later publication and target-acknowledgement clocks.

## Physical environments

Development, fixture, replay, shadow and production are separate authority scopes and physical roots. They use the same migrations and canonical record semantics for implemented domains.

A possible local shape is:

```text
data/newsroom/v2/<environment>/
  ledger.sqlite3
  objects/
  exports/
  backups/
```

Exact paths remain configuration. The implementation must never default to legacy `data/newsroom/news_pool.sqlite3`.

The initial Neo4j or Graphiti development instances are environment-scoped. No development or extraction workspace shares production credentials or authority.

## Repository boundaries

Names may change, but responsibilities remain separate.

```text
newsroom/core/
  ids.py                  # stable identity and version primitives
  events.py               # canonical event envelope
  trust.py                # OBSERVED / PROPOSED / ADMITTED
  time.py                 # explicit temporal fields
  outcomes.py             # canonical outcomes, reasons and lanes

newsroom/ledger/
  commands.py             # authenticated/fenced command contracts
  records.py              # immutable authoritative records
  store.py                # ledger repository protocols
  sqlite.py               # SQLite implementation
  migrations/
  objects.py              # content-addressed governed objects
  projections.py          # rebuildable relational current views
  backup.py
  reconcile.py

newsroom/knowledge/
  ontology.py             # ontology and relation catalogue
  event_mapping.py        # ledger-event to projection mapping
  proposals.py            # entity/relation proposal contracts
  admissions.py           # deterministic/authorised admission
  graphiti_workspace.py   # isolated extraction adapter
  projector.py            # governed graph projector
  graph_store.py          # projection interface
  neo4j_store.py          # initial POC implementation
  indexes.py              # full-text/vector projection interface
  retrieval.py            # hybrid retrieval coordinator
  tools.py                # bounded named read-only tools
  generations.py          # blue-green rebuild and switch

newsroom/discovery/
  registry.py
  profiles.py
  scheduler.py
  adapters/
  changes.py
  controller.py
  gates.py
  agenda.py
  search.py
  triage.py
  admission.py
  handoff.py
  health.py
  evaluation.py

config/newsroom_v2/
  coverage/
  sources/
  rights/
  operational_profiles/
  ontology/
  retrieval_tools/
  evaluation_plans/

scripts/
  newsroom_v2_command.py
  discovery_tick.py
  knowledge_project.py
  knowledge_rebuild.py
  knowledge_status.py
  discovery_reconcile.py
  discovery_replay.py
  discovery_eval.py
  newsroom_v2_backup.py
  newsroom_v2_restore.py
```

The plan rejects one monolithic store or service object that mixes command authority, source access, graph projection, model execution and publication credentials.

## Workstreams

After the canonical contract is accepted, workstreams may proceed concurrently where dependencies allow. They are engineering workstreams, not separate production stages.

### Workstream A — Canonical authority and recovery plane

Owns:

- canonical identity, version, trust and temporal contracts;
- SQLite command writer and ledger repositories;
- governed object storage;
- ordered events;
- migrations;
- immutable decisions;
- backup, restore and reconciliation; and
- authority, security and idempotency tests.

### Workstream B — Discovery collection and workflow plane

Owns:

- source registry and Operational Profiles;
- scheduler-neutral due work;
- adapters and observation models;
- Source Revisions and state transitions;
- Signals, gates and Leads;
- Planned Agenda;
- bounded search records;
- locality watches; and
- discovery health and coverage assessments.

### Workstream C — Governed knowledge and GraphRAG plane

Owns:

- ontology v1;
- entity and relation proposal or admission records;
- Graphiti proposal workspace;
- graph, vector and full-text projectors;
- checkpoint, gap and generation handling;
- Neo4j POC;
- hybrid retrieval; and
- named read-only tools.

### Workstream D — Triage and Candidate plane

Owns:

- exact and advisory retrieval context;
- bounded Work Items and batches;
- worker boundary and proposal schema;
- relationship decisions;
- append-only Event Hypotheses;
- Candidate collision and admission;
- Candidate versioning; and
- evaluation Evidence Handoff.

### Workstream E — Evaluation and operations plane

Owns:

- fixtures, replay and fault injection;
- Evaluation Plans and frozen Epochs;
- event-level review and labels;
- source and retrieval ablation;
- Operational Profiles and alerts;
- capacity, backup and recovery evidence;
- GraphRAG quality, lag, cost and licence evidence; and
- canary and rollback qualification.

## Delivery milestones and pull-request boundaries

### Milestone 0 — Documentation and decision closure

**Scope**

- accept Topic 12 GraphRAG specification and ADRs 0001–0002;
- review this Topic 13 plan;
- revise and decide ADR 0004;
- correct stale references in the large integrated architecture plan;
- validate links, statuses and requirement ranges; and
- prepare one documentation-only pull request.

**Exit evidence**

- all Topic 0–13 decisions are explicit;
- the first implementation Draft is visibly superseded;
- ADR 0004 has an owner decision;
- no runtime or production code is in the documentation pull request; and
- documentation checks pass.

### Milestone 1 — Canonical contract, SQLite authority and graph-aware schema

**Principal requirements**

`DREC-001`–`DREC-077`, `DOUT-001`–`DOUT-026`, `DPRI-001`–`DPRI-026`, `DOPS-046`–`DOPS-055`, `GRAG-001`–`GRAG-016`.

**Deliverables**

- stable IDs and immutable version primitives;
- explicit trust and time types;
- canonical outcome and reason mapping;
- ordered ledger-event envelope;
- command interface and expected-version fencing;
- canonical SQLite schema v1 and migrations;
- governed object-store interface;
- graph ontology v1 and ledger-to-projection event catalogue;
- projection, checkpoint, gap and generation record contracts;
- append-only authoritative writes and rebuildable relational projections; and
- reserved extension boundaries for later evidence and publication domains.

**Tests**

- identity and version invariants;
- immutable outcome and supersession;
- stale-command fencing and idempotency;
- transaction rollback and crash boundaries;
- content-addressed object install and orphan handling;
- event sequence and payload integrity;
- trust-state separation;
- graph-aware schema contract without graph engine availability; and
- fresh database creation without legacy or intermediate schema migration.

**No external sources, graph server, extractor or model.**

### Milestone 2 — Governed structural graph projection foundation

**Principal requirements**

`GRAG-004`–`GRAG-006`, `GRAG-012`–`GRAG-016`, `GRAG-024`–`GRAG-028`, `GRAG-030`, `GRAG-035`, `DOPS-050`–`DOPS-055`.

**Deliverables**

- graph-store and index interfaces;
- Neo4j Community development environment;
- deterministic structural projector for canonical records;
- projector-owned checkpoint, retry, gap and dead-letter state;
- projection generation and blue-green switch primitives;
- projection query metadata;
- destructive graph-drop and rebuild command; and
- graph health and lag diagnostics.

**Tests**

- deterministic structural lineage projects identically after rebuild;
- checkpoint cannot pass a required failed event;
- duplicate event delivery creates no duplicate graph structure;
- gap state appears in retrieval metadata;
- a later sequence cannot hide an earlier gap;
- blue-green generation validates before switch;
- deleting Neo4j loses no authoritative history; and
- graph unavailability leaves SQLite authority intact.

**No Graphiti extraction and no live sources.**

### Milestone 3 — Source registry, adapters, change semantics and discovery projection

**Principal requirements**

`SRC-001`–`SRC-044`, `CHG-001`–`CHG-045`, `AGEN-001`–`AGEN-016`, `FLOW-010`–`FLOW-044`, `DOPS-020`–`DOPS-045`, `GRAG-042`–`GRAG-045`.

**Deliverables**

- source registry and disabled Research or Held configurations;
- generic RSS/Atom, JSON API, complete-current-state, maintained-document and iCalendar adapters;
- strict transport, parser and payload safeguards;
- source-specific identity, revision, baseline and observation-model configuration;
- Source Item, Revision, Representation and Occurrence records;
- deterministic transition engine;
- Check, Signal, Gate and Lead records;
- deterministic projection of source and discovery lineage into the graph; and
- source, graph and portfolio health views.

**Tests**

- successful unchanged creates no Signal, Lead or model work;
- maintained-page revision without URL change;
- parser-only Representation change;
- rolling disappearance does not withdraw;
- partial snapshot cannot clear state;
- `404`, TLS and malformed content do not become no news;
- baseline does not emit history as current news;
- Agenda expectation and occurrence remain separate;
- source and discovery graph lineage survives destructive rebuild; and
- graph outage does not stop safe collection or become no prior match.

Named source definitions remain disabled. Fixtures and approved offline captures only.

### Milestone 4 — Entity resolution, Graphiti proposals and admitted relations

**Principal requirements**

`GRAG-010`–`GRAG-028`, `GRAG-050`–`GRAG-057`, applicable `TRI-020`–`TRI-060`.

**Deliverables**

- Entity Mention, Canonical Entity and Alias records;
- entity-resolution proposal, decision, merge, split and reversal;
- isolated Graphiti workspace adapter;
- Extraction Run and immutable structured-output persistence;
- Relation Proposal, Assertion and Admission Decision;
- governed projector for admitted entities and relations;
- proposal-scoped research surface separated from admitted retrieval; and
- bilingual ontology and alias fixtures.

**Tests**

- confidence never admits identity or relation;
- bilingual names do not merge solely through similarity;
- dependent relation admission blocks on material identity ambiguity;
- Graphiti cannot write governed graph state;
- rejected proposals remain replayable;
- rebuild replays retained extraction output rather than rerunning Graphiti;
- relation assertion retains exact provenance and temporal fields;
- merge, split and reversal preserve predecessor identity; and
- rights deletion prevents proposal and projection resurrection.

Use deterministic fake extractors first. A real Graphiti/model run requires a separately approved evaluation and rights scope.

### Milestone 5 — Hybrid GraphRAG retrieval and named tools

**Principal requirements**

`GRAG-031`–`GRAG-046`, `TRI-001`–`TRI-045`, `FLOW-045`–`FLOW-054`.

**Deliverables**

- exact, full-text, vector and bounded graph retrievers;
- dependency-aware reranking and deduplication;
- authoritative passage and decision hydration;
- trust-labelled Retrieval Context;
- projection watermark and gap validation;
- named read-only tools;
- query budgets and allow-listed graph traversal;
- GraphRAG degraded and exact-fallback routes; and
- hybrid, exact/full-text-only, vector-only and graph-only ablation harness.

**Tests**

- same-event and development cases across English and Traditional Chinese;
- long-running policy and formal-process timelines;
- shared-origin dependency detection;
- unrelated items sharing names remain distinct;
- graph gap never becomes no match;
- stale projection blocks freshness-sensitive tools;
- named tools enforce depth, fan-out, date, result and trust limits;
- no tool has graph write authority;
- hydrated context references exact ledger or object records; and
- ablation reports retain pre-registered cases and versions.

### Milestone 6 — Triage, Event Hypotheses, Candidates and evaluation Handoff

**Principal requirements**

`TRI-001`–`TRI-085`, `FLOW-045`–`FLOW-075`, `DREC-040`–`DREC-057`, `DOUT-013`–`DOUT-016`, `GRAG-040`–`GRAG-046`.

**Deliverables**

- exact and advisory retrieval interfaces;
- immutable Triage Work Items and Execution Batches;
- decision versus context-only Lead handling;
- structured proposal-only worker boundary;
- deterministic proposal validation;
- same state, development, correction, related-distinct, no-match and uncertain relation decisions;
- append-only Event Hypothesis create, associate, consolidate and split;
- exact relational Candidate collision check;
- Candidate admission and versioning;
- graph projection of unverified Hypotheses and deterministic Candidate lineage; and
- evaluation-scoped Evidence Intake sink with idempotent Handoff.

**Tests**

- several Work Items may share one call without becoming one event;
- empty or unavailable graph retrieval does not force a new event;
- context-only Leads cannot be mutated;
- false merge, snowball and fragmentation fixtures;
- development requires earlier and proposed new state;
- model timeout and invalid output create no transition;
- Candidate admission fails without exact collision checks;
- Handoff retry reuses one semantic identity;
- GraphRAG rank never commits a relationship; and
- Candidate and Handoff reconstruct from canonical records after graph rebuild.

A real triage model remains disabled until prompt, schema, privacy, cost and Evaluation Plan approval.

### Milestone 7 — Agenda, bounded search and Event-Scoped Local Watch

**Principal requirements**

`AGEN-001`–`AGEN-016`, `SRCH-001`–`SRCH-053`, `CAUD-001`–`CAUD-009`, `LOC-030`–`LOC-034`, `FLOW-057`.

**Deliverables**

- Agenda import, versions, windows and occurrence matching;
- missed-expectation Findings;
- Search Purpose, Request, Attempt, Outcome, Result Reference and Review Decision;
- provider interface disabled by default;
- privacy and query-amplification validation;
- Event-Scoped Local Watch, expiry and closure; and
- prospective versus retrospective audit labels.

Brave, GDELT, SearXNG and unofficial wrappers remain disabled until exact rights and Operational Profiles pass.

### Milestone 8 — Evaluation, operations, recovery and security tooling

**Principal requirements**

`DEVAL-001`–`DEVAL-074`, `DOPS-001`–`DOPS-076`, `GRAG-050`–`GRAG-058`, `LOC-040`–`LOC-064`.

**Deliverables**

- Evaluation Plan and frozen Epoch manifests;
- fixture, replay and event-level review workflow;
- contemporaneous and later-outcome labels;
- stage and slice metrics;
- source, retrieval and graph ablation reports;
- fault-injection harness;
- queue, lease, heartbeat and reconciliation tools;
- backup, restore, deletion-aware recovery and projection rebuild;
- quarantine, canary and rollback fixtures;
- GraphRAG cost, lag, licence and intended-hardware qualification reports; and
- security tests for SSRF, parser abuse, Graphiti input, query amplification and credential isolation.

**Tests**

- calibration cannot qualify its own thresholds;
- changed Epochs cannot be pooled;
- shadow has no public-effect capability;
- failed Runs remain retained;
- false absence-based clearance is zero tolerance;
- graph answer without provenance or temporal correctness fails;
- projection gap is visible and blocks complete context;
- restore reconciles ledger, objects, active states, queues, Handoffs and projection checkpoints;
- graph rebuild does not rerun stochastic extraction;
- rights purge survives rebuild; and
- rollback does not re-emit historical Signals or relations.

### Milestone 9 — First executable integrated Evaluation Plan

This is a separate owner decision.

**Required inputs**

- exact source versions and rights records;
- exact SQLite schema, command, object and backup versions;
- exact Neo4j, ontology, projector, Graphiti, embedding and retrieval versions;
- exact Operational Profiles and budgets;
- selected model or deterministic worker versions;
- prospective Comparator method permitted by rights;
- thresholds, minimum exposure and reviewer policy;
- known Active gaps;
- stop conditions and incident handling; and
- licence and intended-hardware scope.

**Recommended first scope**

Use a small representative portfolio and shared graph corpus that includes:

- one maintained guidance-revision path;
- one append-only official feed;
- one complete current-state warning path;
- one Planned Agenda path and occurrence confirmation;
- one Hong Kong Traditional Chinese path;
- one established-media Comparator;
- same-event and development cases;
- one policy or immigration timeline;
- one court, bill or formal-process timeline;
- shared-origin and contradictory reporting;
- entity false-merge cases; and
- no search provider unless rights permit the exact evaluation use.

The Plan must evaluate the integrated ledger, projection and retrieval system. Adapter-only live checks may be separately approved earlier, but cannot qualify the complete target architecture.

### Milestone 10 — Governed Evidence Intake canary

**Preconditions**

- Topic 8 release evidence marks exact versions eligible;
- Topic 9 Operational Admission is complete;
- GraphRAG and projection gates pass;
- governed Evidence Intake has an accepted idempotent interface;
- no publishing credential is reachable;
- rollback and containment are tested; and
- all Active coverage blockers for the canary scope are explicit.

A bounded set of Candidate Versions may be handed to governed Evidence Intake. Discovery and GraphRAG remain context and proposal layers; Evidence Intake independently acquires and governs source material.

### Milestone 11 — Production activation and legacy retirement

Production activation is a separate owner decision binding:

- exact canonical schema and command versions;
- source portfolio and rights;
- Evaluation Plan and results;
- Operational Admission;
- Neo4j, ontology, projector, retrieval and graph-degraded policy;
- Evidence Intake readiness;
- capacity, alerts and ownership;
- backup and restore;
- canary result;
- accepted gaps; and
- rollback.

Legacy Brave, RSS, GDELT, Gemini clustering, mutable merge and quota paths remain isolated until retirement criteria pass. Legacy records may be read as attributed Comparator context but do not become canonical identity or truth.

Retirement requires:

- no unresolved zero-tolerance defect;
- acceptable required geography, language, urgency, transition and GraphRAG slices;
- no hidden Active coverage dependency on the legacy path;
- confirmed job disablement;
- retained historical records;
- rollback or bounded reactivation policy; and
- updated current-system documentation.

## Evidence Intake dependency

The initial programme may validate Handoff against an evaluation sink. Production canary cannot proceed until governed Evidence Intake can:

- acknowledge one exact Candidate Version idempotently;
- independently acquire current permitted source material;
- create Source Observations and governed evidence records;
- distinguish accepted, duplicate, stale, rights-blocked, insufficient-evidence and supplemental-discovery outcomes;
- preserve Candidate and Handoff history; and
- expose no public publishing authority to discovery or GraphRAG.

The plan must not bridge Candidate output directly into the legacy writer to demonstrate throughput.

## Source, model and graph enablement discipline

### Source path

```text
Research or Held
→ fixture-qualified
→ rights-approved
→ shadow-shortlisted
→ Evaluation Plan enabled
→ evaluated
→ operationally qualified
→ canary admitted
→ separately activated
```

### Model or extractor path

```text
interface and fake implementation
→ prompt/schema fixture qualification
→ rights/privacy/cost approval
→ Evaluation Plan enabled
→ proposal-quality evaluation
→ operational qualification
→ separately admitted version
```

### Graph engine and projector path

```text
ontology and interface
→ local Neo4j POC
→ deterministic structural rebuild proof
→ Graphiti proposal/admission proof
→ hybrid retrieval and ablation
→ licence/security/backup/resource qualification
→ integrated shadow eligibility
→ separately admitted version
```

A configuration file may contain disabled Research metadata without making the component executable.

## Migration and legacy boundary

- Legacy `links.id`, `events.id`, parentage, merge winners and scores are not canonical v2 identities.
- There is no automatic conversion from a legacy cluster to an Event Hypothesis.
- There is no silent v2-to-legacy dual write.
- Historical import, if later desired, requires a one-time idempotent adapter, provenance and owner decision.
- The legacy pipeline remains operationally separate until explicit cutover.
- Graph projection rebuild never reads legacy mutable event state as authority.
- A cutover does not require a later graph semantic migration because graph contracts exist from schema v1.

## Testing strategy

Every implementation pull request includes relevant layers from this matrix.

| Test class | Purpose |
|---|---|
| Unit | IDs, trust, time, outcomes, reasons, pure transition and ontology rules |
| Ledger integration | transactions, commands, fences, immutable writes, migrations, objects and projections |
| Graph projection | event mapping, checkpoints, gaps, idempotency, generations and rebuild |
| Extraction and admission | proposal provenance, entity resolution, relation admission, merge, split and rejection |
| Adapter contract | source shape, baseline, partial, failure and observation-model semantics |
| Workflow integration | Check through Lead, GraphRAG context, Candidate and Handoff with fake dependencies |
| Hybrid retrieval | exact, lexical, vector, graph and combined ablation with bilingual cases |
| Replay regression | historical and synthetic English, Traditional Chinese and mixed-language cases |
| Property and fuzz | duplicate delivery, malformed inputs, unsafe URLs, XML, JSON, graph and idempotency |
| Fault injection | timeout, partial snapshot, store failure, projector gap, extractor failure and ambiguous Handoff |
| Backup and restore | ledger, objects, active states, proposals, checkpoints, rights purge and rebuild |
| Security | SSRF, redirects, XML entities, decompression, injection, graph credentials and query budgets |
| Live evaluation | prospective coverage, GraphRAG quality, source contribution, cost, operations and licence |

Ordinary CI makes no unbounded external source or model calls. Live contract and evaluation runs require separate authority and budgets.

## Pull-request strategy

The current branch becomes one documentation-only pull request after Topic 13 and ADR 0004 are decided.

Implementation then uses separate branches and focused pull requests. A recommended dependency order is:

1. canonical contract, SQLite ledger and governed objects;
2. graph projection foundation and ontology;
3. source adapters, change semantics and discovery lineage;
4. entity resolution, Graphiti proposals and relation admission;
5. hybrid retrieval and named tools;
6. triage, Event Hypotheses, Candidates and evaluation Handoff;
7. Agenda, bounded search and local watch;
8. evaluation, operations, recovery and security;
9. separately approved live Evaluation Plan;
10. governed Evidence Intake canary; and
11. production activation and legacy retirement.

Several pull requests may be developed in parallel after their shared contract is merged. No pull request may activate an unreviewed source, model, graph engine, spending or production path as a side effect.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Relational model later needs graph redesign | Canonical graph-aware identity, trust, temporal and event contract from schema v1 |
| Graph becomes hidden authority | Proposal/admission boundary, relational authority and rebuildable projection |
| Relational and graph dual-write divergence | Consumer-neutral ledger events and projector-owned checkpoints |
| Graphiti rewrites historical truth on rebuild | Persist extraction output and replay admission decisions without re-extraction |
| False entity or event merge | First-class resolution decisions, bilingual fixtures, split and reversal |
| Big-bang implementation | Dependency-ordered milestone pull requests and offline-first proof |
| Graph server or licence blocks production | Neo4j POC qualification and conditional challenger after measured blocker |
| Graph outage becomes false new event | Explicit gap metadata, exact fallback or Watch/Operational Hold |
| Search quietly becomes core | Search Purpose controls and disabled providers |
| Legacy dual write creates two authorities | Separate canonical ledger and read-only Comparator integration |
| SQLite becomes unexamined bottleneck | Evidence-based operating envelope and explicit migration triggers |
| GraphRAG increases cost without value | Pre-registered hybrid ablation, event-level quality and cost metrics |
| Discovery bypasses evidence | Evaluation Handoff sink first and governed Evidence Intake gate |
| Two systems coexist indefinitely | Explicit canary, activation and retirement decisions |

## Decisions required to accept Topic 13

The plan recommends that the owner accept:

1. one integrated target architecture from canonical schema v1, with no discovery-only semantic phase;
2. side-by-side replacement of the legacy pipeline rather than in-place mutation;
3. the Accepted SQLite ledger and governed object store as authority, with separate physical environments using the same canonical schema;
4. graph ontology, event mappings and projection metadata in the first implementation milestone;
5. Neo4j Community plus Graphiti as the initial POC lane, without automatic production admission;
6. Graphiti proposal isolation, persisted provenance and separate admission before governed projection;
7. idempotent graph, vector and full-text projectors consuming consumer-neutral ordered events;
8. hybrid exact, full-text, vector and bounded graph retrieval behind named read-only tools;
9. exact relational identity and Candidate collision authority, with GraphRAG advisory only;
10. a scheduler-neutral repository-owned deterministic command surface;
11. generic adapters and fixtures before named live source enablement;
12. offline-by-default execution and separate approval for every source, provider, extractor, embedding, model and budget;
13. an evaluation Evidence Intake sink before real downstream integration;
14. complete live-shadow qualification blocked until the governed graph and hybrid retrieval path pass their gates;
15. the eleven-milestone sequence from canonical foundation through legacy retirement;
16. focused milestone or vertical-slice pull requests rather than a full-system implementation pull request;
17. no legacy identity import, silent dual write, source-count ranking, quotas or filler targets;
18. separate Evaluation Plan, Operational Admission, GraphRAG admission, Evidence Intake canary, production activation and retirement decisions;
19. the current branch remaining documentation-only and becoming a documentation pull request only after ADR 0004 receives its final owner decision; and
20. Topic 13 acceptance itself authorising no code, engine installation, source, query, extraction, embedding, model call, spending, run, canary, cutover or production activation.

## Open implementation choices after Topic 13

Acceptance deliberately leaves the following to later milestone evidence and owner decisions:

- exact SQLite tables, migrations and repository APIs;
- exact command-service process and filesystem permissions;
- exact object-store layout and encryption mechanism;
- exact ontology predicates, entity classes and cardinalities;
- exact Neo4j deployment, licence and backup method;
- exact Graphiti, model, embedding, chunking and normalisation versions;
- exact full-text and vector index implementation;
- exact named-tool parameters, graph depth and freshness thresholds;
- exact source versions and first live Evaluation Plan;
- exact search provider, if any;
- exact Operational Profile numbers and release thresholds;
- exact Evidence Intake transport;
- exact hosting and observability services;
- any selected Locality Coverage Unit; and
- production activation date.