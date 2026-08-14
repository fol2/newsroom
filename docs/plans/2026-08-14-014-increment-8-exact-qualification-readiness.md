# Increment 8 exact qualification readiness

**Issue:** #462 / 8R
**Parent:** #148 / Increment 8
**Gate:** Tier S
**Accepted implementation base:** `main@2805bd44b234879c3a4b4ee6cab5f700708f7d3a`
**Accepted tree:** `522ca79b85e9c879623bbb4d58bbd433e9d6c826`
**Checked authority schema:** v29 / `event_scoped_local_watch_authority_v29`
**Checked schema fingerprint:** `sha256:68194825ecc7c429b283204dbc1332a43481e04ca2681fcbf75886a984ea6f55`
**Corrective implementation base:** `main@1c03102dde3a666cf72ee97197bbf339e42f5b4e`
**Corrective tree:** `6ea8893cb1f5a0a33d6bf94abced81c9cea9a59c`
**Corrective checked schema:** v32 / `sha256:3439b82ec6d212116e54765d50cace4d7f147b6ecc3e6ff84146b523c6fd5676`

## Decision

Increment 7 is complete on the exact accepted base.  Increment 8 may implement
only the frozen deterministic fixture/replay and disposable actual-service
qualification programme recorded by
`newsroom/increment8/increment8_readiness_v2.json`.  The corrective v2 record
retains the exact reviewed v1 bytes and their
`sha256:52ad9f2d6022e95d738fe24913db2f379a91f6c945319db613b1b50cdea07d4c`
identity rather than rewriting that earlier decision.

The corrective record is a planning authority, not qualification evidence. It
sets Increment 8 completion, legacy-v1 result acceptance, qualification-result
acceptance and Operational Admission authority to false while #463, #464,
#465, #466, #467, #428 and #468 remain corrective blockers. Consequently the
retained v1 implementation may be used as a correction base, but none of its
existing PASS-shaped objects is accepted as qualification or admission proof.
The release builder and persistence authority, Qualification Packet builder
and Operational Admission builder consume these gates and fail closed; a
caller-constructed typed record does not bypass the persistence or admission
boundary. The Increment 8 closeout builder also consumes the completion and
Operational Admission gates: while either is false it emits only a
content-addressed `BLOCKED` corrective receipt, with no selected-case or final
closeout claim. The signed exact-main job therefore cannot attest Increment 8
completion during the corrective chain.

The record assigns each of the 110 Increment 8 requirements exactly once to
8A–8F.  It also makes #428 an explicit predecessor of 8F so an observed current
Handoff value can never be represented as its original registration value.

## Pre-registered Evaluation Plan

The first qualification Epoch uses 120 prospectively selected event-level
Cases and at least 12 Cases per required slice.  The original numerical lower
bound of eight completed slices remains unchanged, but it does not waive any
member of the following exact nine-slice manifest: every named slice must meet
the 12-Case minimum and release threshold.

| Required slice | Deterministic membership rule |
|---|---|
| `GEOGRAPHY_GLOBAL` | `case_metadata.geography EQ GLOBAL` |
| `GEOGRAPHY_HONG_KONG` | `case_metadata.geography EQ HONG_KONG` |
| `GEOGRAPHY_UNITED_KINGDOM` | `case_metadata.geography EQ UNITED_KINGDOM` |
| `LANGUAGE_EN_GB` | `case_metadata.language EQ EN_GB` |
| `LANGUAGE_MIXED_EN_GB_ZH_HANT_HK` | `case_metadata.language EQ MIXED_EN_GB_ZH_HANT_HK` |
| `LANGUAGE_ZH_HANT_HK` | `case_metadata.language EQ ZH_HANT_HK` |
| `SOURCE_MULTI_DOMAIN_CORROBORATED` | `source_evidence.distinct_domain_count GTE 2` |
| `TRANSITION_FAILURE_HEAVY` | `fixture.injected_failure_count GTE 2` |
| `URGENCY_URGENT` | `case_metadata.urgency EQ URGENT` |

The three required Case strata are also exact and each retains the accepted
12-Case minimum:

| Required stratum | Deterministic membership rule |
|---|---|
| `NEGATIVE` | `expected.candidate_outcome EQ NO_CANDIDATE` |
| `UNCHANGED` | `expected.transition_outcome EQ UNCHANGED` |
| `FAILURE_HEAVY` | `fixture.injected_failure_count GTE 2` |

Slice and stratum membership is evaluated only from the frozen Case input
manifest before any result exists.  Counts use distinct Case digests per slice
or stratum; a Case may satisfy more than one named membership rule, but it may
not be counted twice within one slice or stratum.  Invented identities,
post-result membership changes and post-result policy changes are forbidden.
Calendar duration alone is never sufficient.

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

Reservations are not migrations.  The machine-readable policy now explicitly
sets `additive_migrations_only=true`,
`history_preservation_required=true` and `policy_versions=[30,31,32]`.
Therefore v30–v32 remain additive and history-preserving, are serialised through
the central registry, and require exact predecessor backup, upgrade, integrity,
replay and restore evidence.  A destructive migration or rewritten migration
history fails the readiness loader even if the altered document is otherwise
canonical.

## Non-effects

This decision starts no live source or provider, model, embedding, permanent
locality, credential, egress, spend, publication, production-equivalent shadow,
canary or production activation.  Operational Admission remains a later 8F
decision and is not activation.
