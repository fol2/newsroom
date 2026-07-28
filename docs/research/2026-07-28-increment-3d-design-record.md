# Increment 3D Signal, deterministic-gate and Lead design record

**Status:** Active implementation design checkpoint
**Issue:** #208
**Parent:** #143
**Programme:** #141
**Authorised base:** `main@074ba35b160de87762d57f438c9720f1b27d87b4`
**Runtime boundary:** Repository fixtures and approved replay only

## Purpose

Increment 3D adds the deterministic discovery-authority boundary between the merged Increment 3C source-observable transition authority and later editorial triage. It records immutable Discovery Signals, versioned deterministic Gate Decisions, one stable News Lead per promoted Signal, qualitative urgency context, inspectable Watch Conditions and append-only Lead Disposition Decisions.

The unit does not create a Triage Work Item, Retrieval Context, model proposal, Event Hypothesis, Candidate, Evidence Handoff, evidence record, schedule, credential, external request, graph projection, publication or public effect.

## Accepted semantic basis

The implementation targets the accepted contracts in:

- `FLOW-030`–`FLOW-045`, `FLOW-080`–`FLOW-086`, `FLOW-090`, `FLOW-092` and `FLOW-100`–`FLOW-101`;
- `DREC-030`–`DREC-037`, `DREC-070`–`DREC-077`;
- applicable `COV-*`, source-role and source-dependency requirements;
- `TRI-001`–`TRI-017` as the boundary before full triage;
- applicable `DOUT-*` and `DPRI-*` outcome, reason, next-action and ordinal-route distinctions;
- `DOPS-*` authority, replay, isolation and inspectability requirements; and
- ADR 0001, ADR 0002 and ADR 0004.

The accepted ordering is non-bypassable:

```text
Source Revision + Representation + Observable Transition
    -> Discovery Signal
        -> deterministic Gate Decision
            -> suppressed duplicate / suppressed non-change
            -> clear deterministic exclusion
            -> operational hold
            -> promotion
                -> one stable News Lead
                    -> qualitative urgency route
                    -> immutable current/future disposition history
```

## Authority composition

The implementation extends the existing single-writer SQLite authority and ledger. Schema version 12 will add Signal, gate and Lead records around the merged v11 Check and source lineage. It will not create a second database, mutable workflow store or alternative event authority.

Every committed record owns:

- one authenticated and authorised semantic command;
- one ledger event and audit event;
- one immutable canonical typed payload;
- exact upstream identities and governing versions; and
- normalized columns and guarded convenience heads that are rederived at startup.

The initial command family is:

```text
discovery.signal.admit
discovery.gate.decide
discovery.lead.open
discovery.watch_condition.record
discovery.lead.disposition.record
```

The intended command scopes are distinct:

```text
authority.discovery.signals.admit
authority.discovery.gates.decide
authority.discovery.leads.open
authority.discovery.watch.manage
authority.discovery.leads.disposition
```

Metadata and sensitive-lineage reads remain separately scoped and policy bounded.

## Stable Discovery Signal identity

The first implemented Signal input is deliberately narrower than the full channel-neutral specification. It requires exact retained Increment 3C source authority:

- Source Definition and exact Source Definition Version;
- Source Item;
- Source Revision;
- Discovery Representation;
- Check Outcome and Discovery Occurrence;
- Observable Transition; and
- a versioned Signal admission policy.

Equivalent approved reader, webhook, radar, manual or search channels remain deferred until their input identity, rights and replay contracts are separately accepted. They receive no temporary bypass through a generic string field.

A Signal semantic identity binds:

- the exact Source Revision;
- the exact Discovery Representation;
- the exact Observable Transition;
- a stable deterministic purpose;
- a stable transition/purpose discriminator;
- the exact Signal admission policy; and
- the exact source/version lineage consumed.

The internal Signal ID may be deterministically derived as an opaque RFC UUIDv4 from that retained semantic value. Digest equality proves idempotency and collision handling; it does not replace the lifecycle identity.

One Revision may create several Signals only when every Signal has a distinct approved deterministic purpose or discriminator. Model-created topic splitting, headline wording, category, publisher, similarity or media volume cannot allocate another Signal.

A later Source Revision, Representation, Transition or policy never mutates an existing Signal. A later parser Representation may produce a later Signal, but the gate must suppress an equivalent already-processed semantic transition rather than create another Lead.

Cross-source reports remain separate Source Items, Revisions, Signals and Leads. Cross-source similarity is not Signal identity and cannot collapse their lineage.

## Signal admission guard

Signal admission rederives the complete v11 lineage before commit:

1. the Check Outcome exists and is a successful observable outcome;
2. the exact Discovery Occurrence belongs to that Outcome;
3. the Occurrence, Revision and Representation belong to the same Source Item and source/version lineage;
4. the Observable Transition belongs to the same Outcome, Item, Revision and Representation;
5. the Signal discriminator is allowed by the versioned admission policy;
6. source rights and policy references are present and current for the decision being attempted; and
7. the exact semantic Signal has not already committed.

Blocked, failed, malformed, unauthorised or quarantined Outcomes cannot create a Signal. Partial or truncated Outcomes may create Signals only for independently valid observed items already admitted by Increment 3C, while preserving the Outcome incompleteness and related Operational Finding lineage.

First-run baseline-only source state, parser-only reprocessing, repeated Occurrence and Agenda expectation-only transitions cannot silently become editorial work. They may be represented by an exact candidate Signal only when the admission policy requires an inspectable gate decision; otherwise admission terminates without a Signal. Either route must be deterministic and versioned.

## Versioned Gate Decision

A Gate Decision is an immutable deterministic decision for one exact Signal. A first decision uses ordinal 1 with no predecessor. Re-evaluation requires the exact current predecessor, a later decision ordinal and current governing versions. The gate head is a guarded rebuildable view, never sole authority.

The canonical gate outcomes are the accepted one-to-one vocabulary:

```text
SIGNAL_SUPPRESSED_DUPLICATE
SIGNAL_SUPPRESSED_NON_CHANGE
SIGNAL_REJECTED_CLEAR_EXCLUSION
SIGNAL_PROMOTED_TO_LEAD
SIGNAL_OPERATIONAL_HOLD
```

A Gate Decision binds:

- exact Signal, source, revision, representation, occurrence and transition lineage;
- original and currently evaluated Source Definition Version;
- coverage obligation, responsibility and contribution;
- current rights decision and rights policy;
- Signal, gate, duplicate, newness, time-validity and exclusion policy references;
- canonical outcome and terminality;
- one primary structured reason and zero or more supporting reasons;
- reason taxonomy and outcome taxonomy versions;
- uncertainty and missing-context markers;
- exact duplicate or rule target where applicable;
- next action or closure semantics; and
- decision time and exact predecessor decision.

### Gate basis classes

The gate records distinct typed basis components rather than one boolean or score:

- identity and lineage integrity;
- exact or accepted rule-defined duplication;
- observable-newness classification;
- time and source-version validity;
- accepted scope or clear exclusion;
- current rights and policy validity; and
- operational executability.

Ambiguous relevance, likely materiality, cross-geography effect, event relationship, novelty, public impact or reader utility is not a deterministic exclusion. Such ambiguity promotes to a Lead when safe triage can proceed, or produces an explicit operational hold when required authority or context is unavailable.

A clear exclusion requires an accepted versioned rule that unambiguously applies to retained metadata. Keyword absence, one source, low media/domain count, low model confidence, low similarity, publisher tier, category balance, geography quota or spare writing capacity cannot independently support it.

### Duplicate and non-change treatment

Duplicate suppression preserves every Signal, source-specific lineage and Discovery Occurrence. The decision references the exact prior Signal or accepted duplicate rule and does not delete either record.

Cross-source reports are not collapsed at this gate merely because they likely concern one event. They remain separate Signals and Leads. Candidate-level duplication and event grouping are later authority.

Non-change suppression is reserved for exact source-observable states such as repeated delivery, parser-only output or expectation-only transition classes under the accepted gate policy. It is not an editorial judgement that a genuine source Revision is immaterial.

### Operational hold

Identity collision, corrupted Representation, missing lineage, prohibited rights, stale governing versions or unavailable mandatory deterministic context creates `SIGNAL_OPERATIONAL_HOLD`. It must record an inspectable owner, dependency, retry, review or expiry action. It is neither deterministic exclusion nor editorial rejection.

## News Lead authority

A News Lead is allocated only by a committed `SIGNAL_PROMOTED_TO_LEAD` Gate Decision. The default and v1 invariant is one Lead identity per promoted Signal.

The Lead binds:

- exact Signal and promoting Gate Decision;
- exact Source Item, Revision, Representation, Occurrence and Observable Transition lineage;
- accepted coverage basis;
- source roles, portfolio functions and declared dependencies from the exact source version;
- source-observable transition context and incompleteness warnings;
- qualitative urgency hint and its structured basis;
- outcome/reason taxonomy versions; and
- authoritative creation time.

A Lead does not absorb a later Revision or cross-source report. Those produce separate Signals and Leads that later triage may relate as follow-up, corroborating, superseding or event-related inputs.

Lead creation is idempotent and concurrent promotion converges on one exact Lead. A changed promoting decision, Signal or lineage conflicts rather than silently reusing the Lead ID.

## Qualitative urgency route

The active v1 Lead routes are:

```text
URGENT
TIME_SENSITIVE
PLANNED
ROUTINE
```

Urgency expresses harm from delay and is not materiality, evidence quality or publication prominence. It has no numeric score or quota authority.

The urgency basis records accepted coverage and deterministic source context, such as a safety/public-health indicator, hard action deadline, effective date, Planned window or routine state. Unknown or conflicting urgency remains explicit. Potential Urgent safety or public-health work cannot be silently demoted to Routine because of low confidence, one source, low media volume or backlog pressure.

Urgent isolation is represented as a route requirement only. Exact queue timing, batching, reserve capacity and fairness mechanisms remain deferred to later operational profiles and triage work implementation.

## Watch Condition and Lead Disposition seam

A Watch Condition is an immutable inspectable condition that may support a later `LEAD_WATCH_DEFER` disposition. It must identify at least one concrete resume or closure condition:

- a permitted future Source Transition;
- an expected source update or occurrence;
- a corroborating Lead identity or accepted relationship class;
- a deadline or review time;
- an expiry; or
- an authorised operator review condition.

An indefinite watch with no trigger, deadline, expiry or closure rule is invalid. Watch Conditions create no trigger, source access, model work or Candidate by themselves.

A Lead Disposition Decision is immutable, ordered under one Lead and references the exact predecessor disposition where present. The current disposition head is rebuilt from decisions.

The complete accepted vocabulary is retained as a versioned contract, but Increment 3D activates only the foundation states that require no full triage or Candidate authority:

```text
LEAD_QUEUED_FOR_TRIAGE
LEAD_OPERATIONAL_HOLD
LEAD_WATCH_DEFER
```

`LEAD_WATCH_DEFER` requires an exact Watch Condition. `LEAD_OPERATIONAL_HOLD` requires an inspectable operational next action and cannot masquerade as watch or editorial rejection. The initial queued disposition is created with the Lead and records the qualitative route.

The following accepted later outcomes remain reserved and cannot be committed by the v1 3D disposition command without future triage/Candidate authority:

```text
LEAD_EDITORIAL_REJECT
LEAD_ASSOCIATE_WITHOUT_CANDIDATE
LEAD_SUPPLEMENTAL_DISCOVERY
LEAD_ADMIT_NEW_CANDIDATE
LEAD_ADMIT_DEVELOPMENT_CANDIDATE
LEAD_ADMIT_CORRECTION_CANDIDATE
```

Declaring their vocabulary does not implement Increment 6 or create a bypass.

## Outcome, reason and next-action separation

Outcome, reason, next action and priority route are separate typed fields and separate semantics.

Every Gate or Lead Disposition Decision records:

- one canonical outcome;
- terminal, pending, retryable or occurrence-only semantics;
- one primary structured reason;
- optional supporting structured reasons;
- a reason-basis class;
- exact source observation, field, relationship, dependency or policy references;
- uncertainty and missing context;
- next action, Watch Condition, retry or closure; and
- exact taxonomy and policy versions.

Reason basis classes follow the accepted vocabulary:

```text
DETERMINISTIC_OBSERVATION
DETERMINISTIC_POLICY
SOURCE_ASSERTION
EDITORIAL_ASSESSMENT
OPERATIONAL_ASSESSMENT
HUMAN_ADJUDICATION
DOWNSTREAM_FEEDBACK
```

Increment 3D Gate Decisions may use deterministic observation, deterministic policy, source assertion and operational assessment only. Editorial, human and downstream basis classes are reserved for later authorised decisions.

Reason codes are namespaced, versioned and append-only. Free text may explain but cannot replace structured basis. A source assertion remains attributed and unverified.

## Schema v12

The planned checked migration adds immutable tables equivalent to:

```text
discovery_signals
gate_decisions
gate_decision_reasons
gate_decision_heads
news_leads
watch_conditions
lead_disposition_decisions
lead_disposition_reasons
lead_disposition_heads
```

Required database constraints include:

- one exact semantic Signal identity;
- one Gate Decision ordinal and predecessor chain per Signal;
- one current guarded Gate head per Signal;
- one News Lead per promoted Signal;
- one Lead references one exact promoting Gate Decision;
- one disposition ordinal and predecessor chain per Lead;
- one guarded disposition head per Lead;
- watch-required and hold-required outcome constraints;
- immutable update/delete triggers;
- exact foreign keys into v11 source, Check and transition records; and
- semantic uniqueness independent of mutable heads.

Canonical payload bytes remain authoritative. Normalized columns, reason indexes and heads must rehydrate to the exact canonical request and ledger event on every open.

## Replay, concurrency and recovery

The deterministic Signal-to-Lead controller pre-authorizes its complete intended command plan, then commits each independent authority record through the existing single SQLite writer.

A crash-safe retry resumes from the first missing record after any prefix:

```text
Signal only
Signal + Gate Decision
Signal + promoting Gate Decision + Lead
Signal + Gate Decision + Lead + initial disposition
```

The controller never invents an enclosing unreviewed transaction across separate domain commands. Deterministic identifiers and exact semantic lookups permit safe resumption.

Competing workers converge on the same Signal, Gate Decision, Lead and initial disposition. A loser reloads and verifies the exact semantic winner. A changed outcome, policy, duplicate target, urgency basis, reason or lineage conflicts rather than silently reusing authority.

A later gate re-evaluation never deletes an existing Lead. Promotion is retained history. A later operational restriction creates later Gate and/or Lead Disposition history according to the exact policy; current status is rebuilt and the original promoting decision remains reconstructable.

## Reads and current status

Authenticated bounded reads will expose:

- Signal by ID and source lineage;
- Gate Decision and history by Signal;
- Lead by ID or Signal;
- Watch Condition by ID;
- Lead Disposition and history; and
- a redacted current-status view derived from immutable heads.

A mutable status string is never sole authority. Sensitive source locators, payload bytes, protected metadata and unredacted operational details remain behind a distinct read scope.

## Required tests

The Increment 3D test plan includes:

1. exact Signal replay and several Signals from one Revision only under distinct deterministic discriminators;
2. parser-only/repeated delivery suppression without losing source Occurrences;
3. one promoted Signal creates one Lead and one initial queued disposition;
4. cross-source reports remain separate Signals and Leads;
5. accepted clear exclusion with exact rule and basis;
6. ambiguity promotion and inability to reject by keyword absence, volume, source count or confidence;
7. rights, identity, version and lineage failures produce operational hold/block;
8. Urgent hint preservation and no numeric/quota route authority;
9. stale-policy revalidation and immutable later Gate Decisions;
10. watch-condition finite/inspectable guard;
11. concurrent promotion and crash-prefix recovery;
12. canonical payload, normalized-column, reason-index and head tamper rejection;
13. startup reconstruction of Gate and Lead current views; and
14. no Candidate, Evidence, model, Graphiti, search, external I/O or publication import/call surface.

## Explicit exclusions and deferred work

Deferred to later full triage/Candidate increments:

- Triage Work Items and execution batches;
- Retrieval Context and event matching;
- model-assisted Triage Proposals;
- editorial reject and association decisions;
- supplemental discovery execution;
- Event Hypotheses;
- Candidate admission and Evidence Handoff; and
- exact queue timing, batching, fairness and numeric experiments.

Deferred to Increment 3E:

- Neo4j discovery-lineage projection;
- source/parser/projection/coverage health records and views; and
- actual-Neo4j complete Source Revision → Signal → Lead projection proof.

Excluded from Increment 3D:

- named live sources, credentials, schedules, network requests and browser collection;
- models, Graphiti, embeddings, search and spending;
- source shadow/canary and production-equivalent execution;
- Evidence Intake, drafting, publication and production activation;
- legacy link/event/cluster identity import or dual write; and
- any public effect.

## Rollback

Before merge, rollback is branch deletion. After merge, executable code may be reverted or Signal/Lead creation may be disabled through a reviewed forward control. Schema v12 is append-only: retained Signals, Gate Decisions, Leads, Watch Conditions and Dispositions are not deleted, downgraded or reconstructed from Neo4j, parser output, mutable status or legacy tables.
