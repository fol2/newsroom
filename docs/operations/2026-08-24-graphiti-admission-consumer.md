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
  resolution or relation admission command and returns its retained decision;
- `GovernedGraphitiProjector` delivers ADMIT-only effects to the existing
  admitted projector and applies rights tombstones; and
- `GraphitiRightsAuthority` rechecks current rights before decision, before
  projection and during derivative reconciliation.

Graphiti receives none of these capabilities.

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
- admitted projection count and contiguous projection watermark; and
- zero provider/model calls for the admission service.

Malformed or tampered terminal receipts are retained as explicit integrity holds
and never become claimable. Ordinary authority or projection failure increments
bounded retry state and then dead-letters without entering the source-ingest or
corpus-extraction execution path.

## Non-effects

This service does not call an extraction provider, read the Graphiti private
graph as authority, change source scheduling, write CONT, form a Hypothesis or
Candidate, publish, dispatch publicly or activate production.
