# News discovery implementation and migration plan

**Status:** Draft for owner review  
**Owner:** Product owner  
**Last updated:** 2026-07-16  
**Canonical language:** English  
**Implementation authority:** None. This plan proposes sequencing and concrete implementation boundaries. It authorises no code change, external request, model call, source activation, spending, shadow run, production canary or cutover until the applicable milestone and owner gate are separately approved.  
**Related review sequence:** [`2026-07-15-002-discovery-specification-review.md`](2026-07-15-002-discovery-specification-review.md)  
**Related architecture decision:** [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md) (`Proposed`; final owner decision pending)  
**Supersedes:** No existing implementation plan

## Purpose

Implement the Accepted Topic 1–11 discovery contracts without turning the current Brave, RSS, GDELT and Gemini pipeline into an unreviewable big-bang migration.

The plan delivers a separate, auditable discovery system through small vertical slices. It keeps the existing live pipeline isolated until the new system has fixture, replay, shadow, operational and canary evidence. It ends at a governed Evidence Intake handoff; it does not weaken downstream evidence or publication controls.

## Normative scope

The implementation must conform to every Accepted requirement in:

- [`discovery-coverage-contract.md`](../specs/editorial-automation/discovery-coverage-contract.md): `COV-001`–`COV-045`;
- [`discovery-workflow.md`](../specs/editorial-automation/discovery-workflow.md): `FLOW-001`–`FLOW-102`;
- [`discovery-record-semantics.md`](../specs/editorial-automation/discovery-record-semantics.md): `DREC-001`–`DREC-077`;
- [`discovery-source-roles-and-selection.md`](../specs/editorial-automation/discovery-source-roles-and-selection.md): `SRC-001`–`SRC-044`;
- [`discovery-change-and-planned-agenda.md`](../specs/editorial-automation/discovery-change-and-planned-agenda.md): `CHG-001`–`CHG-045` and `AGEN-001`–`AGEN-016`;
- [`discovery-triage-and-event-grouping.md`](../specs/editorial-automation/discovery-triage-and-event-grouping.md): `TRI-001`–`TRI-085`;
- [`discovery-search-and-coverage-audit.md`](../specs/editorial-automation/discovery-search-and-coverage-audit.md): `SRCH-001`–`SRCH-053` and `CAUD-001`–`CAUD-009`;
- [`discovery-shadow-evaluation.md`](../specs/editorial-automation/discovery-shadow-evaluation.md): `DEVAL-001`–`DEVAL-074`;
- [`discovery-reliability-and-operations.md`](../specs/editorial-automation/discovery-reliability-and-operations.md): `DOPS-001`–`DOPS-076`;
- [`discovery-prioritisation-and-outcomes.md`](../specs/editorial-automation/discovery-prioritisation-and-outcomes.md): `DOUT-001`–`DOUT-026` and `DPRI-001`–`DPRI-026`; and
- [`discovery-locality-scope-and-expansion.md`](../specs/editorial-automation/discovery-locality-scope-and-expansion.md): `LOC-001`–`LOC-064`.

The cross-cutting [`news-discovery.md`](../specs/editorial-automation/news-discovery.md) remains Draft until ADR 0004 is accepted or replaced. This plan cannot use that Draft to weaken or expand the focused Accepted specifications.

## Proposed implementation decisions

Topic 12 proposes the following concrete choices for owner acceptance:

1. Build discovery v2 beside the legacy pipeline rather than mutating the legacy link and event model in place.
2. Use a repository-owned, scheduler-neutral deterministic command surface. Cron, Hermes or another scheduler may invoke it later, but no agent framework is embedded in the semantic architecture.
3. Introduce a `DiscoveryStore` interface and a separate SQLite implementation for fixtures, replay and shadow. This is a scoped discovery implementation choice, not a decision for the whole product database architecture.
4. Keep the discovery store append-only for authoritative records, with rebuildable projections for current state.
5. Do not write v2 Signals, Leads, Event Hypotheses or Candidates into legacy `links` or `events` tables.
6. Do not import legacy events as canonical v2 event identity. Legacy rows may be read through a bounded Comparator adapter and referenced as untrusted historical context.
7. Implement generic transport and observation-model adapters before enabling named live sources.
8. Keep every real external source, search provider and model worker disabled until exact rights, Evaluation Plan, Operational Profile and budget gates pass.
9. End the first full vertical slice at an evaluation-scoped Evidence Intake test sink. Production Evidence Intake integration is a later explicit milestone and dependency.
10. Use the Accepted ordinal lanes and canonical outcomes at launch; do not reproduce legacy source-count ranking, category caps, finance caps or Hong Kong guaranteed slots.
11. Deliver implementation through multiple focused pull requests, each with requirement traceability, fixtures, migration and rollback evidence.
12. Keep the legacy live pipeline unchanged until an explicit canary and activation decision; there is no silent dual-write or automatic graduation.

## Target architecture

```text
Versioned policy and configuration
  - coverage mappings
  - Source Definition Versions
  - rights references
  - Operational Profiles
  - outcome/reason taxonomy
  - Evaluation Plans
            |
            v
Scheduler-neutral deterministic command surface
  - due-work calculation
  - preflight
  - no-work completion
            |
            v
Source / channel adapters
  - RSS / Atom
  - JSON API
  - complete current-state JSON/XML
  - maintained document / Content API
  - iCalendar / Planned Agenda
  - selector-based page change where approved
  - manual / reader / search channel input
            |
            v
Discovery Controller + append-only ledger
  Check Request -> Attempt -> Outcome
  Item -> Revision -> Representation -> Occurrence
  Signal -> Gate Decision -> Lead
            |
            v
Retrieval + Triage Work Item
  structured untrusted proposal
            |
            v
Deterministic relationship and Candidate admission
  Event Hypothesis Version
  Candidate Version
            |
            v
Evidence Handoff
  evaluation sink first
  governed Evidence Intake later
```

The system has no public publishing credential. Unchanged checks, due-work calculation, source access, parsing, baselining and deterministic gates do not require a model.

## Proposed repository layout

```text
newsroom/discovery/
  __init__.py
  ids.py                 # stable identities and idempotency keys
  records.py             # immutable semantic record dataclasses
  outcomes.py            # canonical outcomes, reasons and lanes
  policy.py              # versioned policy and mapping loader
  store.py               # DiscoveryStore protocol
  sqlite_store.py        # separate append-only shadow/evaluation store
  projections.py         # rebuildable current views
  registry.py            # Source Definition and portfolio registry
  profiles.py            # Operational Profile loader and validation
  scheduler.py           # due-work and Schedule Occurrence semantics
  controller.py          # deterministic transition authority
  changes.py             # observation-model and transition engine
  gates.py               # deterministic Signal gates
  retrieval.py           # exact and advisory retrieval context
  triage.py              # Work Item and worker boundary
  admission.py           # Hypothesis and Candidate admission
  handoff.py             # idempotent Evidence Intake boundary
  agenda.py              # Planned Agenda identities and windows
  search.py              # Search Purpose/Request records; providers disabled by default
  health.py              # health and coverage availability assessments
  reconcile.py           # leases, pending work and ambiguous effects
  evaluation.py          # fixture, replay and shadow evaluation records
  adapters/
    base.py
    rss_atom.py
    json_api.py
    current_state.py
    maintained_document.py
    icalendar.py
    page_change.py
    manual_channel.py

config/discovery/
  coverage.yaml
  outcome_taxonomy.yaml
  source_definitions/
  operational_profiles/
  rights_references/
  evaluation_plans/

scripts/
  discovery_tick.py
  discovery_reconcile.py
  discovery_status.py
  discovery_replay.py
  discovery_eval.py
  discovery_backup.py
  discovery_restore.py
```

Names may change during implementation, but the accepted semantics and one-to-one outcome mapping must remain visible.

## Storage boundary

### Separate database

The first implementation uses a separate path such as:

```text
data/newsroom/discovery_shadow.sqlite3
```

It must never default to `data/newsroom/news_pool.sqlite3`.

### Store abstraction

`DiscoveryStore` provides atomic or deterministically reconcilable operations for:

- immutable record insertion;
- identity and revision lookup;
- one-transition commit guards;
- queue or lease ownership;
- projection rebuild;
- exact Candidate collision checks;
- Handoff idempotency;
- health and coverage assessments;
- audit export; and
- backup, restore and reconciliation.

The SQLite implementation is permitted for fixtures, replay and shadow because the repository already operates SQLite and Python 3.12. It must use transactions, foreign-key enforcement, WAL where justified, explicit schema migrations, integrity checks and backup/restore tests. Production activation remains blocked until the exact store implementation passes Topic 8 and Topic 9 and is consistent with any later product-wide ledger ADR.

### No legacy identity import

Legacy `links.id`, `events.id`, event parentage, source-domain scores and merge winners are not v2 identities. A read-only legacy Comparator may expose them as attributed references. No automatic conversion may claim that a legacy cluster is a canonical Event Hypothesis.

## Migration modes

### Mode 0 — Documentation only

Current branch. No executable behaviour changes.

### Mode 1 — Offline contract implementation

Fixtures, in-memory or temporary SQLite stores and replay only. No external requests and no model calls.

### Mode 2 — Evaluation-scoped external checks

Exact source versions may make real external requests only under an owner-approved Evaluation Plan, rights decision, Operational Profile and budget. No public effect and no production state mutation.

### Mode 3 — Shadow triage and Candidate outcomes

Permitted live inputs may create evaluation-scoped Signals, Leads, Hypotheses and Candidates. Evidence Handoffs target an evaluation sink. Legacy remains live and isolated.

### Mode 4 — Scoped canary to governed Evidence Intake

Exact evaluated sources and components may hand off to a real Evidence Intake boundary for a bounded scope. No direct publication path is added. Legacy may remain a Comparator.

### Mode 5 — Production discovery activation

Requires a separate owner activation decision binding exact versions, source portfolio, Evaluation Plan result, Operational Admission, Evidence Intake readiness, canary result, rollback and accepted gaps.

### Mode 6 — Legacy retirement

Only after stable production evidence and an explicit retirement decision. Broad Brave/RSS/GDELT/Gemini cron paths are disabled or retained solely for a permitted Comparator role. Historical data remains read-only and traceable.

## Delivery milestones and pull-request boundaries

No milestone should combine unrelated concerns merely to reduce PR count. Each implementation PR must cite exact requirement IDs, include tests and state what remains blocked.

### Milestone 0 — Finalise the specification branch

**Scope**

- accept Topic 11;
- complete this Topic 12 plan;
- revise ADR 0004 into its final proposed architecture form;
- reconcile documentation maps and remove stale false-acceptance text;
- validate links, status metadata and requirement references;
- prepare one documentation-only PR.

**No code or runtime change.**

**Exit evidence**

- Topics 0–12 have explicit owner decisions or accepted deferrals;
- ADR 0004 has an explicit owner decision;
- all focused specs show correct status and implementation authority;
- `git diff --check`, Markdown-link validation and repository documentation checks pass.

### Milestone 1 — Semantic kernel and append-only store

**Principal requirements**

`FLOW-001`–`FLOW-005`, `DREC-001`–`DREC-077`, `DOUT-001`–`DOUT-026`, `DPRI-001`–`DPRI-026`, `DOPS-046`–`DOPS-055`.

**Deliverables**

- stable ID and version primitives;
- canonical outcomes, reason-basis classes and ordinal lanes;
- immutable record types for Check, Item, Revision, Representation, Signal, Lead, Work Item, Hypothesis, Candidate, Handoff, Finding, Gap, health and decisions;
- `DiscoveryStore` protocol;
- SQLite schema and migrations in a separate database;
- append-only decision writes and rebuildable projections;
- idempotency and one-transition commit guards;
- deterministic audit export and projection rebuild.

**Tests**

- identity and version invariants;
- duplicate delivery and retry idempotency;
- immutable outcome and supersession;
- Candidate collision and Handoff identity;
- transaction rollback and crash-boundary simulation;
- projection rebuild equals current projection;
- no dependency on legacy event identity.

**Rollback**

Delete only the isolated development database and disable the new CLI entry points. No legacy data is touched.

### Milestone 2 — Source registry, adapters and change semantics

**Principal requirements**

`SRC-001`–`SRC-044`, `CHG-001`–`CHG-045`, `AGEN-001`–`AGEN-016`, `FLOW-010`–`FLOW-037`, `DOPS-020`–`DOPS-037`.

**Deliverables**

- versioned registry and source-role mappings;
- adapter protocol and parser contracts;
- generic RSS/Atom, JSON API, complete-current-state, maintained-document and iCalendar adapters;
- conditional-request, strict TLS, redirect, response-size and parser-safety controls;
- source-specific identity, baseline and observation-model configuration;
- transition engine for new, revised, activation, escalation, de-escalation, clearance, withdrawal, reschedule and ambiguity;
- fixture corpus covering malformed, partial, rolling-list and parser-version cases.

**Important boundary**

Named candidate sources may appear as disabled Research or Held configuration, but no live source is enabled in this milestone.

**Tests**

- unchanged and repeated delivery;
- maintained-page revision without URL change;
- Representation-only parser change;
- rolling disappearance does not withdraw;
- partial snapshot cannot clear state;
- `404`, TLS and malformed content do not become no news;
- Agenda expectation and occurrence remain separate;
- first-run baseline does not emit history as current news.

### Milestone 3 — Deterministic tick, Signals, gates, Leads and health

**Principal requirements**

`FLOW-010`–`FLOW-045`, `FLOW-080`–`FLOW-102`, `COV-001`–`COV-045`, `DOPS-001`–`DOPS-045`, `DOUT-010`–`DOUT-026`.

**Deliverables**

- scheduler-neutral `discovery_tick.py`;
- due-work and Schedule Occurrence identities;
- preflight, rights/profile checks and no-work completion;
- Check Request, Attempt and Outcome commits;
- Signal admission, exact duplicate suppression and deterministic gates;
- News Lead creation and ordinal queue lanes;
- multidimensional health and Coverage Availability Assessment;
- scoped retry, circuit and quarantine state;
- status and diagnostic CLI.

**Tests**

- nothing due causes no source access and no model call;
- successful unchanged creates no Signal or Lead;
- parser failure is operational, not editorial;
- ambiguous relevance survives to a Lead;
- clear exclusion requires an exact accepted rule;
- Routine backlog cannot consume Urgent capacity in test profiles;
- stale source differs from healthy quiet source;
- Comparator cannot repair a blocked Anchor.

### Milestone 4 — Retrieval, triage, Event Hypotheses and Candidate admission

**Principal requirements**

`TRI-001`–`TRI-085`, `FLOW-045`–`FLOW-065`, `DREC-040`–`DREC-057`, `DOUT-013`–`DOUT-016`.

**Deliverables**

- exact and advisory retrieval interfaces;
- bounded Retrieval Context and exact Candidate collision check;
- immutable Triage Work Items and Execution Batches;
- worker protocol with structured schema and no write authority;
- deterministic proposal validator;
- same-state, development, correction, related-distinct, no-match and uncertain relationships;
- append-only Hypothesis create, associate, consolidate and split;
- Candidate admission and versioning;
- evaluation-scoped Evidence Intake sink and idempotent Handoff.

**Provider boundary**

Tests use deterministic fake workers first. A real model provider is a versioned adapter introduced only after its prompt, schema, privacy, cost and Evaluation Plan are approved.

**Tests**

- five Work Items may share one call without becoming one event;
- empty retrieval does not force a new event;
- context-only Leads cannot be mutated;
- false merge, snowball and fragmentation fixtures;
- development requires earlier and proposed new state;
- model timeout and invalid output create no transition;
- Candidate admission fails without exact collision checks;
- Handoff retry reuses one semantic identity.

### Milestone 5 — Planned Agenda and bounded search channels

**Principal requirements**

`AGEN-001`–`AGEN-016`, `SRCH-001`–`SRCH-053`, `CAUD-001`–`CAUD-009`, `FLOW-057`, `LOC-030`–`LOC-034`.

**Deliverables**

- Agenda import, versioning, windows, occurrence matching and missed-expectation Findings;
- Search Purpose, Request, Attempt, Outcome, Result Reference and Review Decision records;
- provider interface disabled by default;
- bounded manual/test provider for fixtures;
- privacy and query-amplification validation;
- Event-Scoped Local Watch records and expiry;
- prospective-versus-retrospective audit labelling.

**Restrictions**

Brave, GDELT, SearXNG and unofficial wrappers remain disabled until their exact rights and operational gates pass. No provider is selected merely because the interface exists.

### Milestone 6 — Evaluation, operations and recovery tooling

**Principal requirements**

`DEVAL-001`–`DEVAL-074`, `DOPS-001`–`DOPS-076`, `LOC-040`–`LOC-064`.

**Deliverables**

- versioned Evaluation Plan and Epoch manifests;
- fixture and replay runner;
- event-level review case and label workflow;
- stage and slice metrics;
- fault-injection harness;
- source contribution and ablation reports;
- lease, heartbeat and deterministic reconciler;
- queue/backpressure diagnostics;
- metrics and structured correlation logs;
- backup, restore, integrity and projection-rebuild commands;
- quarantine, canary, rollback and incident test fixtures.

**Tests**

- calibration results cannot qualify their own thresholds;
- changed Epochs cannot be pooled;
- no public-effect capability exists in shadow;
- failed Runs remain retained;
- false absence-based clearance is a zero-tolerance failure;
- restore reconciles baselines, active states, queues and Handoffs before resume;
- rollback does not re-emit history.

### Milestone 7 — First executable Evaluation Plan

This milestone is a separate owner decision, not an automatic consequence of implementing Milestones 1–6.

**Required inputs**

- exact source versions and rights records;
- exact disabled-to-enabled changes;
- exact Operational Profiles and budgets;
- selected worker/model version if used;
- prospective comparator method permitted by rights;
- thresholds, minimum exposure and reviewer policy;
- known Active gaps;
- stop conditions and incident handling.

**Recommended first scope**

Choose a small representative transport-and-semantics portfolio rather than trying to claim launch completeness. The first Plan should demonstrate at least:

- one maintained guidance revision path;
- one append-only official feed;
- one complete current-state warning path;
- one Planned Agenda path plus occurrence confirmation;
- one Hong Kong Traditional Chinese path;
- one established-media Comparator;
- no search provider unless rights permit the exact evaluation use.

The actual sources are selected in the Evaluation Plan, not by this implementation plan.

### Milestone 8 — Scoped Evidence Intake canary

**Preconditions**

- Topic 8 release evidence marks exact versions eligible;
- Topic 9 Operational Admission is complete;
- downstream Evidence Intake has its own accepted contract and idempotent interface;
- no public publishing credential is reachable;
- rollback and containment are tested.

**Canary**

A bounded set of Candidate Versions may be handed to governed Evidence Intake. Discovery outcomes remain separate from evidence decisions. Any publication remains controlled downstream.

### Milestone 9 — Production activation and legacy retirement

Production activation is a separate owner decision. It identifies exact portfolio, versions, Profiles, gaps, source health, search roles, capacity, alert ownership, evidence boundary, canary result and rollback.

The legacy path remains available as a read-only Comparator until retirement criteria pass. Retirement requires:

- no unresolved zero-tolerance issue;
- acceptable required slices and operational objectives;
- no hidden Active coverage dependency on the legacy path;
- confirmed job/scheduler disablement;
- retained historical records;
- rollback or reactivation policy; and
- updated current-system documentation.

Legacy ranking, category caps and guaranteed slots are not carried forward.

## Evidence Intake dependency

The discovery implementation can build and validate the Handoff protocol against an evaluation sink, but production canary cannot proceed until a governed Evidence Intake exists and can:

- acknowledge one exact Candidate Version idempotently;
- independently acquire permitted current source material;
- distinguish accepted, duplicate, stale, rights-blocked, insufficient-evidence and supplemental-discovery outcomes;
- preserve the original Candidate and Handoff history; and
- expose no direct publishing authority to discovery.

If that dependency is unavailable, discovery remains in shadow. The plan must not bridge directly from a Candidate into the existing story writer merely to demonstrate end-to-end throughput.

## Source enablement discipline

A source configuration moves through:

```text
Research / Held
→ fixture-qualified
→ rights-approved
→ shadow-shortlisted
→ Evaluation Plan enabled
→ evaluated
→ operationally qualified
→ canary admitted
→ separately activated
```

Repository configuration must fail closed. There is no built-in broad-feed fallback. A file may contain Research or Held candidate metadata without making the source executable.

## Testing strategy

Every implementation PR includes relevant layers from this matrix:

| Test class | Purpose |
|---|---|
| Unit | IDs, digests, outcomes, policy validation, reason mapping and pure transition rules |
| Contract fixture | Adapter shape, baseline, partial, failure and observation-model semantics |
| Store integration | Transactions, immutable writes, collision guards, migrations and projection rebuild |
| Workflow integration | Check through Lead, triage, Candidate and Handoff with fake dependencies |
| Replay regression | Historical and synthetic English, Traditional Chinese and mixed-language cases |
| Property and fuzz | Duplicate delivery, parser limits, unsafe URLs, malformed XML/JSON and idempotency |
| Fault injection | Timeout, partial snapshot, rate limit, store failure, worker failure and ambiguous Handoff |
| Shadow evaluation | Prospective event-level coverage, triage, source contribution, cost and operations |
| Backup/restore | Integrity, baseline, queue, active state and Handoff reconciliation |
| Security | SSRF, redirects, XML entities, decompression, injection, credentials and authority boundaries |

CI must not make unbounded external requests. Live contract tests are separately authorised, rate-limited and normally excluded from ordinary CI.

## Observability and acceptance evidence

Each milestone retains:

- exact code, schema, policy and configuration versions;
- requirement trace matrix;
- test and fixture results;
- migration and rollback result;
- known deviations and blockers;
- cost and external-request summary;
- security and rights assumptions; and
- owner decision where required.

A passing unit test cannot substitute for live coverage evidence, and a long shadow run cannot substitute for missing fixture or operational evidence.

## Pull-request strategy

The current branch should become one documentation-only PR after Topic 12 and ADR review are complete. Before opening it, the branch history should be consolidated into a small number of logical commits where repository tooling permits.

Implementation then uses separate branches and PRs, normally one milestone or coherent vertical slice per PR. A code PR must not include an unreviewed source activation, external spending or production switch as a side effect.

Recommended sequence:

1. semantic kernel and isolated store;
2. adapters and change fixtures;
3. deterministic tick, gates, Leads and health;
4. triage, Candidate and evaluation Handoff;
5. Agenda and bounded search records;
6. evaluation and operations tooling;
7. separately approved live Evaluation Plan;
8. scoped Evidence Intake canary;
9. production activation and legacy retirement.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Recreating the legacy mutable event model | Append-only v2 identities, no legacy event import and explicit consolidation/split decisions |
| Big-bang implementation | Milestone PRs with independent exit evidence and rollback |
| Hidden live requests during development | Offline-by-default adapters and explicit Evaluation Plan enablement |
| SQLite becoming accidental product-wide architecture | Store interface and scoped shadow decision; production store remains an admission gate |
| Model becoming policy authority | Structured proposal-only worker and deterministic validation |
| False no-news result | Check, failure, stale and health outcomes remain distinct |
| Coverage claims outrunning evidence | Event-level evaluation, Active blockers and locality-uncommitted launch |
| Search quietly becoming core | Providers disabled by default and Search Purpose budgets |
| Bridging discovery directly to publication | Evidence Intake test sink first and no publishing credential |
| Legacy dual-write causing inconsistent authority | Separate database and read-only Comparator integration |
| Long-lived two-system operation | Explicit canary, cutover and retirement gates with owner decision |

## Decisions required to accept Topic 12

The plan recommends that the owner accept:

1. the side-by-side discovery v2 architecture and rejection of in-place mutation of legacy `links` and `events` as the primary migration path;
2. a scheduler-neutral repository-owned deterministic command surface, with Hermes, cron or another scheduler treated as replaceable orchestration;
3. a `DiscoveryStore` abstraction with a separate SQLite implementation for offline, replay and shadow work, without deciding the product-wide database architecture;
4. append-only authoritative records and rebuildable projections;
5. no legacy event identity import and no silent v2-to-legacy dual-write;
6. generic adapter and observation-model implementation before named live-source enablement;
7. offline-by-default execution and separate owner approval for every real source, provider, model and budget;
8. an evaluation-scoped Evidence Intake sink before real downstream integration;
9. the proposed repository module and configuration boundaries, subject to naming changes that preserve semantics;
10. the nine milestone sequence from semantic kernel through legacy retirement;
11. one focused implementation PR per milestone or coherent vertical slice, rather than one full-system PR;
12. explicit Evaluation Plan, Operational Admission, canary, activation and retirement gates;
13. no carry-forward of source-count ranking, category or finance caps, Hong Kong guaranteed slots or filler quotas;
14. production canary remaining blocked until governed Evidence Intake exists;
15. the current branch becoming a documentation-only PR after ADR 0004 receives its final owner decision; and
16. Topic 12 itself authorising no code, source, query, model call, spending, run, canary, cutover or production activation.

## Open implementation choices after Topic 12

Acceptance of this plan deliberately leaves the following to the relevant milestone decision and evidence:

- exact SQLite schema and migration mechanics;
- exact scheduler or Hermes deployment;
- exact source versions and live Evaluation Plan;
- exact model provider, prompt and retrieval engine;
- exact Operational Profile values and release thresholds;
- exact search provider, if any;
- exact Evidence Intake transport;
- exact production hosting and observability services;
- any selected Locality Coverage Unit; and
- production activation date.
