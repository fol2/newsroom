# Increment 8 exact qualification readiness

**Issue:** #462 / 8R
**Parent:** #148 / Increment 8
**Gate:** Tier S
**Accepted implementation base:** `main@2805bd44b234879c3a4b4ee6cab5f700708f7d3a`
**Accepted tree:** `522ca79b85e9c879623bbb4d58bbd433e9d6c826`
**Checked authority schema:** v29 / `event_scoped_local_watch_authority_v29`
**Checked schema fingerprint:** `sha256:68194825ecc7c429b283204dbc1332a43481e04ca2681fcbf75886a984ea6f55`

## Decision

Increment 7 is complete on the exact accepted base.  Increment 8 may implement
only the frozen deterministic fixture/replay and disposable actual-service
qualification programme recorded by
`newsroom/increment8/increment8_readiness_v1.json`.

The record assigns each of the 110 Increment 8 requirements exactly once to
8A–8F.  It also makes #428 an explicit predecessor of 8F so an observed current
Handoff value can never be represented as its original registration value.

## Pre-registered Evaluation Plan

The first qualification Epoch uses 120 prospectively selected event-level
Cases and at least 12 Cases per required slice.  It includes at least eight
required slices, 12 negative Cases, 12 unchanged Cases and 12 failure-heavy
Cases.  Calendar duration alone is never sufficient.

Ordinary Cases receive independent second review at a frozen 20% rate.  Every
blocker, zero-tolerance failure and Urgent Case receives independent second
review.  Release permits no unresolved disagreement.

The frozen principal thresholds are:

| Measure | Threshold |
|---|---:|
| bounded event coverage | at least 90% |
| route-decision agreement | at least 90% |
| grouping precision / recall | at least 95% / 90% |
| Candidate precision / recall | at least 95% / 90% |
| required-slice score | at least 85% |
| reviewer agreement | at least 85% |
| false merge / snowball absorption | at most 1% / 1% |
| fragmentation | at most 2% |
| duplicate / unnecessary Candidate | at most 1% / 1% |
| Case latency p50 / p95 / maximum | 250 ms / 1,000 ms / 3,000 ms |

Public effect, authority cross-contamination, rights breach, credential
exposure, prohibited egress, provenance failure, temporal rewrite, silent queue
loss and unreconciled ambiguous effect all have a zero-count threshold.

## Frozen Operational Profile

The v1 Profile applies only to named fixture source, provider, parser, worker,
queue, Handoff and retrieval scopes.  Its principal values are:

- 300-second interval, 30-second permitted jitter, 900-second freshness
  objective and 1,200-second alert objective;
- 30-second request timeout, 60-second lease, 20-second renewal and 300-second
  maximum lease;
- four host workers, 1,000 queued items and a 200-item Urgent reserve;
- three attempts within 120 seconds, 2–30 second bounded backoff, 10% jitter,
  circuit opening after five failures and quarantine after three integrity
  failures;
- 24-hour backup RPO, one-hour restore RTO and 15-minute reconciliation RTO;
- target floor of four CPU cores, 8 GiB memory and 10 GiB free disk;
- 50% peak queue headroom and 20% Urgent capacity reserve; and
- zero live credentials, zero egress destinations and zero external spend.

Every live source, provider or materially different component needs a new exact
Profile and owner decision.  Calibration may start a later Plan or Epoch; it
cannot qualify the values it selected.

## Allocation and migration reservations

| Issue | Atom | Owner | Tier | Reserved migration |
|---|---|---|---|---|
| #462 | 8R | `newsroom.increment8.readiness` | S | none |
| #463 | 8A | `newsroom.increment8.evaluation` | S | v30 |
| #464 | 8B | `newsroom.increment8.metrics` | L | none |
| #465 | 8C | `newsroom.increment8.operations` | S | v31 |
| #466 | 8D | `newsroom.increment8.observability` | S | none |
| #467 | 8E | `newsroom.increment8.recovery` | S | v32 |
| #468 | 8F | `newsroom.increment8.admission` | M | none |

Reservations are not migrations.  v30–v32 remain additive, serialised through
the central registry and require exact predecessor backup, upgrade, integrity,
replay and restore evidence.

## Non-effects

This decision starts no live source or provider, model, embedding, permanent
locality, credential, egress, spend, publication, production-equivalent shadow,
canary or production activation.  Operational Admission remains a later 8F
decision and is not activation.
