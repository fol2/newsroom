# Graphiti proposal admission consumer

**Issue:** [#758](https://github.com/fol2/newsroom/issues/758)

**Profile:** provider-free EVALUATION admission and projection atom

**Authority boundary:** SQLite ledger, entity-resolution authority,
editorial-relation authority and the Increment 4 admitted projector remain the
governed systems of record.

## Public seam

`GraphitiAdmissionConsumer` reads complete or partial terminal receipts already
retained in the private Control Plane store. It validates the receipt digest,
source authority records, proposal count, typed proposal bytes, evidence ranges,
relation endpoints and temporal fields before creating claimable work.

The consumer injects three reduced capabilities:

- `GovernedGraphitiAdmissionAuthority` maps the request to the existing entity
  resolution (`decide_entity_resolution`) or relation admission
  (`decide_relation_admission`) command and returns its retained decision;
- `GovernedGraphitiProjector` delivers ADMIT-only effects to the existing
  `graph.increment4.admitted` projector, applies rights tombstones and returns
  generation-scoped reconciliation receipts; and
- `GraphitiRightsAuthority` rechecks current rights before decision, before
  projection and during derivative reconciliation.

Graphiti receives none of these capabilities.

The queue retains the exact private relation endpoint receipt for byte-for-byte
audit, under `private_graph_receipt`. Deserialisation deliberately omits that
field from `GraphitiAdmissionRequest`: governed entity/relation commands receive
the proposed endpoint names and must return the matching effective Entity
Resolution Decision identities. The Graphiti extraction generation remains
source lineage only; a separately configured UUIDv4 Increment 4 generation is
required for projection receipts and reconciliation.
Before retaining a relation ADMIT, the consumer calls
`relation_endpoint_resolutions_current()` so the authority adapter must re-read
both effective Entity Resolution Decisions; syntactically valid UUIDs alone do
not admit or project a relation.

## Durable states

Each proposal has one stable key derived from its terminal receipt, local
identity and proposal digest. The queue retains `READY`, leased `CLAIMED`,
`DECIDED`, `TERMINAL`, `PROJECTED`, `DEAD_LETTER` or `REVOKED` state. Authority,
projection and tombstone calls use stable idempotency keys, so a restart after an
external commit replays rather than duplicates the effect. Admission decisions,
projection receipts and tombstone receipts are immutable SQLite rows.

`REJECT` and `HOLD` terminate without a projector call. `ADMIT` becomes terminal
for the contiguous projection watermark only after a governed projection receipt
exists, or after a current-rights veto proves that no projection may be made.

## Telemetry and recovery

The admission snapshot and Graphiti coverage surface expose:

- proposal denominator and admission backlog;
- admitted, rejected, held, dead-letter and revoked counts;
- integrity-held terminal receipts and oldest unresolved lag;
- admitted projection count and contiguous projection watermark;
- active projection gap count and exact generation reconciliation status; and
- zero provider/model calls for the admission service.

The watermark is an authority ledger watermark, never a local queue position.
It advances only across a contiguous prefix whose terminal decisions and ADMIT
projection receipts are retained. Reconciliation compares the active,
non-tombstoned effect identities in SQLite with the exact admitted projector
family and rejects gaps, extras, family drift or generation drift.

Malformed or tampered terminal receipts are retained as explicit integrity holds
and never become claimable. Ordinary authority or projection failure increments
bounded retry state and then dead-letters without entering the source-ingest or
corpus-extraction execution path.

## Processing plan

The private Control Plane caller performs one bounded admission atom after
terminal receipt retention: call `enqueue_complete_receipts()`, then
`drain(worker_id=..., limit=100)`. A later invocation reclaims expired leases and
continues `DECIDED` projection work with the same idempotency identities. The
same operational cycle calls `reconcile_rights(limit=100)` and, once the bounded
backlog is terminal, `reconcile_projection(generation_id=...)`. Integrity holds,
dead letters, non-zero projection gaps or a false reconciliation status page the
operator; they never trigger extraction or source intake retries. This plan does
not itself authorise or install a schedule.

## Non-effects

This service does not call an extraction provider, read the Graphiti private
graph as authority, change source scheduling, write CONT, form a Hypothesis or
Candidate, publish, dispatch publicly or activate production.
