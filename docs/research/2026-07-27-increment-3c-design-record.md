# Increment 3C Check, baseline and observable-transition design record

**Status:** Implemented review design; final qualification pending
**Issue:** #207
**Parent:** #143
**Authorised base:** `main@707519cebcc18fd8010b9b1b608b361ab2f6de03`
**Runtime boundary:** Repository fixtures and approved replay only

## Purpose

Increment 3C adds deterministic authority between the merged fixture adapter proposal boundary and the later Discovery Signal boundary. It records logical Check work, physical Attempts, immutable Outcomes, baseline decisions, operational findings and source-observable transitions while reusing the existing Increment 3A Source Item, Revision, Representation and Occurrence authority.

The unit does not create a Discovery Signal, Gate Decision, News Lead, Event Hypothesis, Candidate, evidence record, schedule, credential, external request, model call, projection write or public effect.

## Authority composition

The implementation extends the existing single-writer SQLite authority rather than creating a second ledger. Schema version 11 adds retained Check and transition records around the existing v10 source lineage:

```text
approved trigger basis
    -> Check Request
        -> Check Attempt
            -> Adapter Observation Proposal
                -> Check Outcome
                    -> existing Source Item / Revision / Representation / Occurrence
                    -> Baseline Decision or later baseline head
                    -> Observable Transition
                    -> Operational Finding when integrity or execution is insufficient
```

Every committed record owns one authenticated and authorised command, one ledger event, one audit event and one immutable typed payload. Convenience heads are guarded, rebuildable and never the sole history.

## Stable identities and replay

- A Check Request semantic key binds the exact trigger identity and version, Source Definition Version, coverage obligation and contribution, rights decision, adapter/parser/normalizer contract, baseline/revision/transition policies and bounded request purpose. A retry reuses the Request.
- Each Check Attempt has a separate identity and ordinal under one Request. Attempts retain started, terminal or retained state without overwriting earlier Attempts.
- One Check Outcome belongs to one exact Attempt. A later recovery creates a later Attempt and Outcome. One exact Outcome cannot later be reinterpreted by changing its baseline control or item transition classification.
- Baseline Decision identity binds the exact Source Definition Version, Check Outcome, observation model, baseline policy, included and excluded item/revision manifest and reason. Reset/rebuild creates a later decision and preserves prior history. At most one Baseline Decision may consume one Check Outcome.
- Observable Transition identity binds exact prior/current Revision or the exact absence/explicit-delta evidence, transition policy and transition discriminator. Equivalent replay produces at most one semantic transition, and one Check Outcome may classify at most one transition per Source Item.
- Operational Finding identity is a stable operational case. Each contributing failure remains separately retained through the exact Attempt and Outcome; grouping does not erase occurrences.

Deterministic request factories may derive UUIDv4 identifiers from retained namespace material only where the identifier remains an opaque internal identity. Digest equality is used for semantic collision and idempotency, never as a lifecycle identity replacement.

## Check outcome boundary

The authoritative Outcome preserves adapter proposal distinctions without copying proposal authority:

- successful empty;
- successful unchanged;
- successful changed;
- successful partial;
- successful truncated;
- blocked preflight;
- redirected or rate-limited;
- unauthorised, not-found or gone;
- malformed or shape drift;
- transport failure; and
- quarantined or disabled recommendation.

The Outcome records exact receipt, Capture and Parser Result digests where present, exact candidate item-key and representation digests, timing, validator, incompleteness, quarantine recommendation and the source/version lineage consumed. It cannot record `no news`, editorial rejection, Signal, Lead or Candidate state.

## Existing source-lineage reuse

Increment 3C resolves valid proposal candidates into the v10 source authority:

1. source-scoped item identity is resolved under the exact current Source Definition Version and identity policy;
2. the approved permitted-state digest resolves the same Source Revision or creates a later Revision extending the exact retained head;
3. parser/normalizer output resolves or creates one Representation in the exact producer slot;
4. every observed or redelivered Revision records an Occurrence tied to the exact Check Outcome; and
5. transition authority consumes exact retained source records rather than raw adapter fields.

A parser or normalizer change over unchanged source state creates only a later Representation and Occurrence. It cannot allocate a new Revision or publisher transition.

## Baseline semantics

Baseline actions are explicit typed decisions:

- maintained document: establish initial state without `newly published` or `revised`;
- bounded backfill: include only the approved freshness window while retaining excluded identities in the decision manifest;
- complete current state: retain an explicit baseline, including a valid empty complete snapshot, and emit `ACTIVATED` for included first-observed items without asserting their real start time;
- Planned Agenda: retain future expectations only, preserving past or unknown entries as explicit exclusions; normal source observation still creates an Occurrence, but no Lead or Candidate;
- explicit delta: retain exact sequence/cursor basis; and
- reset/rebuild: preserve the predecessor baseline and block uncontrolled re-emission.

A baseline head may advance only to a decision for the same Source Definition and a strictly later authority event. Raw mutation, deletion or version rollback fails startup integrity.

## Observable transitions

The transition catalogue remains source-observable and non-editorial:

- `FIRST_OBSERVED`;
- `REVISED`;
- `REOBSERVED`;
- `ACTIVATED`;
- `ESCALATED`;
- `DEESCALATED`;
- `RESOLVED_OR_CLEARED`;
- `EXPIRED`;
- `CANCELLED`;
- `WITHDRAWN`;
- `REPLACED`;
- `REACTIVATED`;
- `AGENDA_CREATED`;
- `AGENDA_RESCHEDULED`;
- `AGENDA_CANCELLED`;
- `AGENDA_MISSED_EXPECTATION`;
- `AGENDA_LATE_OCCURRENCE`; and
- `AMBIGUOUS_ABSENCE`.

Transition policy input is deterministic and versioned. Change facets describe source-observable differences only and never materiality. First observation is not newly published. Source-asserted time remains separate from observation and authority-record time.

## Complete-snapshot and absence guard

Absence-based ending is permitted only when all exact guards are present in one typed decision:

- declared `COMPLETE_CURRENT_STATE` observation model;
- successful complete non-partial Outcome;
- exact prior active item and Revision identity;
- exact complete-scope and pagination/filter contract;
- required confirmation count or grace decision;
- no transport, parser, rights, policy, permission or version change explaining absence; and
- an allowed transition under the exact transition policy.

Append-only, rolling-list, partial, truncated, failed, malformed, redirected, unauthorised and blocked outcomes cannot clear, cancel, delete or withdraw by absence. Rolling or incomplete absence may create `AMBIGUOUS_ABSENCE`; independently valid present items from partial or truncated output may still advance their exact Revision and current-item transition while the degraded Outcome also creates an Operational Finding.

## Planned Agenda boundary

Agenda transition records are expectation-only. Creation, reschedule, cancellation, miss and late occurrence retain exact source Revision, asserted window, precision, time zone, confirmation paths and policy. Window opening or clock passage cannot create a Lead or Candidate. A miss means required paths did not observe the expected occurrence after accepted window/grace/confirmation checks; it does not prove non-occurrence, cancellation or delay.

## Operational Findings

Integrity, source-contract, rights, policy, identity, baseline, parser, shape, transport, confirmation and quarantine conditions create a typed Operational Finding case or occurrence. A Finding is not a successful unchanged Outcome, editorial rejection, Coverage Gap or evidence conclusion. Finding closure semantics are deferred; no current operation mutates or erases the stable case or its contributing Attempts and Outcomes.

## Read and command boundary

The public facade exposes typed writes and policy-bounded authenticated reads only. Raw SQLite, mutable heads, source locators, payload bytes and unredacted error/provider data do not escape. Command scopes are separate for Request, Attempt, Outcome, Baseline, Transition and Finding authority. Adapter proposal objects remain untrusted input and are revalidated against exact retained Source Definition Version and source policies before any commit.

## Migration and startup integrity

Schema v11 contains immutable tables, semantic uniqueness constraints, exact foreign keys, guarded heads and update/delete triggers. It enforces one Baseline Decision per Check Outcome and one transition classification per Check Outcome and Source Item. Startup validation rehydrates every Check, baseline, transition and Finding record from its canonical payload and authority event; validates chronology, exact source/version lineage and head reconstruction; and rejects raw-SQL tampering, missing predecessors, duplicate classifications or impossible absence-based endings.

## Implemented recovery and concurrency behavior

Proposal admission pre-authorizes its full write plan, then commits each existing authority record independently. Exact deterministic identifiers and semantic lookups permit recovery after an Outcome-only prefix, after source-lineage commitment, or after baseline commitment but before required activation transitions. A retry resumes at the first missing record rather than wrapping the workflow in an unreviewed transaction.

Competing workers share the single SQLite writer. The winner creates each record; a loser reloads the exact semantic winner and reports reuse rather than duplicate creation. A conflicting producer slot, historical-state reactivation without an explicit directive, changed baseline classification, or changed transition classification fails closed.

The operational runbook is `docs/operations/increment-3c-check-transition-authority.md`.

## Normative traceability

The review unit targets:

- `FLOW-010`–`FLOW-037`;
- `DREC-001`–`DREC-023`, `DREC-060`–`DREC-061`, `DREC-070`–`DREC-077`;
- `CHG-001`–`CHG-045`;
- `AGEN-001`–`AGEN-016`;
- `DOPS-001`–`DOPS-037` and applicable `DOUT-*`;
- ADR 0001, ADR 0002 and ADR 0004; and
- the merged Increment 3A/3B contracts.

## Explicit exclusions and deferred work

Deferred to Increment 3D: Discovery Signal admission, deterministic Gate Decisions, duplicate/exclusion/promotion authority, News Leads, urgency and Watch Conditions.

Deferred to Increment 3E: Neo4j discovery-lineage projection and source/parser/coverage health views.

Excluded: real source access, source credentials, schedules, browser collection, model or Graphiti execution, embeddings, search, spending, shadow or canary source execution, Evidence Intake, publication, production activation, legacy `links`/mutable `events`/clusters, and any public effect.

## Rollback

Before merge, rollback is branch deletion. After merge, rollback is a reviewed code revert or scoped disable of Check execution. The v11 migration is append-only and retained records are not deleted or downgraded. Rolling back executable code cannot reinterpret, erase or reconstruct Source Revisions or transitions from derivative projections.