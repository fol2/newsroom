# Increment 3E discovery-lineage projection and health design

**Issue:** #209  
**Parent:** #143  
**Programme:** #141  
**Owner-authorised base:** `main@65ba31c403c84b9fbe82243912fd57612c097735`  
**Runtime boundary:** repository fixtures and approved replay only

## Purpose

Increment 3E completes Increment 3 by projecting the accepted generic discovery lineage into the existing disposable Neo4j projection system and by exposing bounded, attributable health for source access, source contract, parser, Check execution, semantic lineage, projection and coverage availability.

SQLite authority records, immutable decisions, governed objects and the authority ledger remain canonical. Neo4j is a rebuildable structural read projection. A graph result, graph absence, graph count or graph reachability result cannot create or alter Source, Check, Signal, Gate, Lead, health, editorial, Candidate or publication authority.

The complete intended fixture path is:

```text
Source Definition
  -> Source Definition Version
  -> Source Item
  -> Source Revision
  -> Discovery Representation
  -> Discovery Occurrence / Check Outcome / Observable Transition
  -> Discovery Signal
  -> Gate Decision
  -> News Lead
  -> disposable structural Neo4j projection
```

## Authority composition

Increment 3E extends the retained projection authority rather than creating another checkpoint, generation or graph writer.

```text
SQLite authority ledger and domain records
  -> allow-listed discovery-lineage event adapter
  -> retained projection inbox / ordering / gap / dead-letter authority
  -> fixed discovery-lineage mutation plan
  -> inactive replacement generation in Neo4j
  -> server-computed expected/actual reconciliation
  -> SQLite-authoritative validation and atomic ACTIVE selection
  -> bounded authenticated lineage and health reads
```

Projector checkpoints, required gaps, retries, dead letters, generation contracts, validation results and active-generation selection remain SQLite-authoritative commands. A Neo4j property is never the sole record of projection progress or health.

## Projection family and version contracts

The initial family is a separate structural family rather than an extension of legacy links, events or clusters:

```text
family:             graph.discovery_lineage
definition version: discovery-lineage-family-v1
ontology ID:        newsroom.discovery-lineage
ontology version:   discovery-lineage-ontology-v1
mapping ID:         newsroom.discovery-lineage
mapping version:    discovery-lineage-mapping-v1
projector version:  discovery-lineage-projector-v1
```

A generation contract binds:

- projection family;
- exact ontology version;
- exact projector version;
- accepted authority event contract versions;
- fixed node labels, relationship types and property allow-lists;
- SQLite source watermark and contiguous ledger range;
- trust and security policy version;
- replacement-generation identity.

Wrong family, ontology, projector, source watermark, generation identity, endpoint or policy version fails closed. An old ACTIVE generation remains readable only while it satisfies the retained serving contract; a partially built replacement never becomes active.

## Structural ontology

Governed lifecycle IDs are graph keys. Human titles, locators, URLs, content digests, parser keys and mutable statuses are properties only.

Initial node-type allow-list:

```text
SOURCE_DEFINITION
SOURCE_DEFINITION_VERSION
SOURCE_ITEM
SOURCE_REVISION
SOURCE_REPRESENTATION
DISCOVERY_OCCURRENCE
CHECK_REQUEST
CHECK_ATTEMPT
CHECK_OUTCOME
OBSERVABLE_TRANSITION
SIGNAL
GATE_DECISION
LEAD
LEDGER_EVENT
```

Initial relationship allow-list:

```text
HAS_DEFINITION_VERSION
DEFINES_ITEM
REQUESTED_CHECK
ATTEMPTED_AS
PRODUCED_CHECK_OUTCOME
HAS_REVISION
HAS_REPRESENTATION
OBSERVED_AS
PRODUCED_OCCURRENCE
TRANSITION_OF_ITEM
CLASSIFIED_BY_TRANSITION
PRODUCED_SIGNAL
EMITTED_SIGNAL
DECIDED_BY_GATE
PROMOTED_TO_LEAD
OPENED_LEAD
PROJECTED_FROM_EVENT
```

Every relation is parameterised and derived from exact retained authority. Callers cannot choose labels, relationship types, properties, Cypher fragments or mutation order.

Each projected node and relation retains sufficient structural provenance to reconcile it without treating Neo4j as authority:

- governed ID;
- exact upstream governed IDs;
- authority event ID and ledger sequence;
- command and contract version;
- source digest or canonical payload digest where applicable;
- observed, produced, decided or opened time where applicable;
- trust class and security scope;
- projector and ontology versions;
- generation identity.

Sensitive content, raw fetched bodies, credentials and arbitrary canonical payload bytes are not projected.

## Ordered event handling

The discovery-lineage adapter consumes only accepted authority events required to reconstruct structural lineage. Each accepted event has one fixed mapping and one deterministic projection identity.

- Exact replay is idempotent.
- A lower or equal already-applied ledger sequence cannot mutate the generation again.
- A required future event with a missing predecessor creates a visible required gap and prevents contiguous watermark advancement.
- Unsupported required contract versions dead-letter and block validation.
- Optional events are optional only through a retained allow-list; they cannot be silently ignored because a projector does not understand them.
- A failed graph write leaves the SQLite checkpoint unadvanced.
- Restart resumes from SQLite authority and cannot infer progress from graph contents alone.

## Rebuild, reconciliation and activation

A replacement generation is rebuilt from retained SQLite authority, not copied from the prior graph generation.

Validation computes expected structural nodes and relations from SQLite and compares them with server-returned actual counts, identities, endpoint pairs, digests and contract metadata. Client-supplied counts are never trusted.

Activation requires all of the following:

- exact family, ontology and projector contracts;
- contiguous required watermark with no blocking gap or dead letter;
- expected/actual node and relationship equality;
- no unexpected label, relation or identity;
- exact trust and provenance metadata;
- query-valid and endpoint-valid generation;
- no retained tombstone or rights-removal conflict;
- authenticated Neo4j service proof for the exact generation.

Graph loss or corruption is repaired by constructing and validating another replacement generation. Authority records are never reconstructed from Neo4j.

## Rights removal and non-resurrection

Where accepted source authority records a rights revocation, deletion or tombstone that removes projection eligibility, the active lineage projection must cease serving the covered derivative lineage through a reviewed generation transition. A later rebuild cannot resurrect material excluded by current retained authority.

This design does not invent source deletion authority. It consumes only exact removal or tombstone semantics already accepted by the source and authority contracts.

## Health dimensions

Health is assessed per dimension and scope. A single aggregate colour cannot erase attribution.

Initial dimensions:

```text
SOURCE_ACCESS
SOURCE_CONTRACT
PARSER
CHECK_EXECUTION
OBSERVATION_FRESHNESS
SEMANTIC_LINEAGE
PROJECTION
COVERAGE_AVAILABILITY
```

Initial states:

```text
HEALTHY
DEGRADED
STALE
UNAVAILABLE
QUARANTINED
BLOCKED
UNKNOWN
```

Required semantics:

- `HEALTHY` requires positive qualifying evidence under the exact source observation model; absence of a recorded error is insufficient.
- A quiet source is not stale merely because no source change occurred.
- Last complete observation, last successful observation and last source change remain separate timestamps.
- Partial, truncated, malformed, blocked, unauthorised and transport-failed outcomes remain distinguishable.
- Projection lag, graph outage, required gap, dead letter, wrong contract, graph tamper and failed reconciliation affect projection health; they do not become source unchanged, source unavailable or editorial rejection.
- Semantic-lineage health derives from retained cross-record integrity, not graph reachability.
- `UNKNOWN` is used when the required positive evidence has not yet been established.

Health inputs and returned assessments are typed, bounded and explainable. Each assessment identifies the exact retained evidence, observation timestamps, policy version, state, reason and assessed time. Increment 3E computes this inspection seam from SQLite authority at read time; it does not introduce a second mutable health authority or claim durable assessment-history storage.

## Coverage availability

Coverage availability is derived from accepted Source Definition Version role, portfolio-function, coverage-responsibility, coverage-contribution and dependency mappings.

- Losing the sole qualifying Anchor or Active path produces blocked or degraded coverage, even if Comparator or radar sources remain reachable.
- Comparator count, source count, graph node count or search results cannot repair an unavailable required path.
- Alternative paths count only when the retained coverage contract marks them as qualifying substitutes.
- Coverage availability is not article volume, media volume, category balance or editorial priority.

## Bounded reads

Public projection and health reads are authenticated and policy-bounded. They accept typed governed identities, a fixed family, fixed query shapes and bounded limits.

Allowed read shapes include:

- lineage for one Source Item, Revision, Signal or Lead;
- current ACTIVE generation status and watermark;
- required gaps and dead-letter summaries;
- per-source and per-coverage-path health assessments;
- bounded node/relation provenance inspection for reconciliation support.

The API exposes no Neo4j driver, arbitrary Cypher, caller-selected label, relationship type, property name, unbounded traversal or cross-family discovery.

## Observation-model and transition coverage

The projector is deliberately event-contract generic: it maps the accepted Check Outcome and Observable Transition authority records without branching on source observation model or transition kind. Repository-owned Increment 3C fixtures remain the authority source for `APPEND_ONLY`, `MUTABLE_ITEM`, `COMPLETE_CURRENT_STATE`, `ROLLING_LIST`, `EXPLICIT_DELTA` and `PLANNED_AGENDA`. Increment 3E directly replays one meaningful transition from every accepted model—`FIRST_OBSERVED`, `REVISED`, `ACTIVATED`, `AMBIGUOUS_ABSENCE`, `ESCALATED` and `AGENDA_CREATED`—and proves that each retained transition reaches the same fixed governed node and `TRANSITION_OF_ITEM` / `CLASSIFIED_BY_TRANSITION` relations without caller-selected graph schema.

## Evidence plan

Repository-owned fixture evidence must cover:

- complete Source Definition → Revision → Representation → Signal → Lead projection;
- exact identities, endpoint pairs, digests, trust and time provenance;
- exact replay idempotency;
- restart and crash-prefix recovery;
- out-of-order required gaps and unsupported-contract dead letters;
- wrong family/ontology/projector/generation rejection;
- graph deletion followed by exact replacement-generation rebuild;
- relation deletion, endpoint mutation, count mismatch and property tamper rejection;
- stale generation and missing endpoint failure;
- source access, parser, Check, freshness, semantic, projection and coverage health attribution;
- unchanged versus no attempt, partial, parser failure, stale observation and outage;
- sole-Anchor loss without Comparator repair;
- typed read authorization, redaction and limit enforcement;
- authenticated actual-Neo4j execution with zero required skips, failures or errors;
- complete repository, Authority, Projection and signed SDLC exact-head gates.

## Explicit exclusions

Increment 3E creates no:

```text
named live source
source credential
source schedule or recurring collector
external network or browser request
model, Graphiti, embedding or search execution
Triage Work Item or Retrieval Context
Event Hypothesis, Candidate or Evidence Handoff
editorial materiality or rejection authority
publication, spending, production activation or public effect
legacy link/event/cluster identity import
```

## Stop and rollback

Stopping Increment 3E means stop issuing projector and health-assessment commands. Existing SQLite authority and accepted projection generations remain inspectable.

Before any new schema or contract opens a database, rollback is an ordinary source revert. After a forward migration or new projection contract has been used, apply a reviewed forward correction or restore a verified pre-change SQLite backup. Never delete checkpoints, gaps, dead letters, generation records, health evidence or authority events to make a generation appear healthy.

Neo4j rollback is replacement-generation selection or complete graph loss followed by rebuild; it is never a source of canonical recovery.

Increment 4 remains blocked until Increment 3E is merged, issue #209 and parent #143 are closed as completed, and a fresh owner-authorised Increment 4 base records the then-current `main` head.
