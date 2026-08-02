# Increment 5 retrieval evaluation plan v1

This plan is preregistered by 5A and executed in 5E (#254). Thresholds are frozen before qualification. Calibration and qualification examples are disjoint.

## Claim boundary

Qualification may establish that the reviewed exact/full-text/fixed-point-vector/admitted-graph implementation works against an actual Neo4j service, hydrates authority correctly, degrades explicitly, preserves rights and satisfies the frozen budgets.

It cannot establish embedding quality because no embedding model is selected. It cannot authorize live sources, protected-content vectors, provider spending, shadow/canary traffic or production activation.

## Dataset protocol

5E must bind a signed dataset manifest containing dataset identity, digest, source classes, rights clearance, repository-safety assertion, generation identity and calibration/qualification partition digests.

The required slices are:

- `EN_GB`;
- `ZH_HANT_HK`;
- `MIXED_EN_GB_ZH_HANT_HK`;
- `LONG_RUNNING_TIMELINE`;
- `CORRECTION_AND_SUPERSESSION`;
- `SHARED_ORIGIN_DEPENDENCY`;
- `DISTRACTOR_FALSE_MERGE`;
- `TEMPORAL_CUTOFF`; and
- `RIGHTS_PURGE_AND_REBUILD`.

Each query has a frozen authority-labelled relevance set, expected dependency roots, trust labels, admissible predicates and required provenance. Calibration may tune implementation details allowed by the contract but cannot change qualification examples or pass thresholds.

## Systems compared

Run these ablations on the same qualification set and generation:

1. exact only;
2. full-text only;
3. vector only;
4. admitted graph only; and
5. hybrid.

The vector branch uses only deterministic fixed-point fixture vectors. Record branch receipts, exclusions, ranks and final fused order. Do not compare raw branch scores.

## Evaluation evidence semantics

The exact contract, component identities, dataset partitions, queries, labels, thresholds and policies are frozen for one qualification Epoch. A material change starts another Epoch. Results from different Epochs are reported separately and cannot be pooled to manufacture a pass.

Calibration and qualification remain disjoint. Calendar duration alone is not sufficient exposure: a required slice without enough pre-registered examples is `INCONCLUSIVE` or `NOT_EVALUATED`, never passed. The reviewed signed dataset is a bounded evaluation universe; no provider, index or retrieval branch is treated as complete ground truth.

Every reported rate retains its count, denominator, slice, population-or-sample status, sampling method and uncertainty where applicable. Adapter/index behaviour, branch retrieval, fusion, hydration, security, latency, cost, purge and recovery remain separately attributable. An early-stopped run retains a failed or inconclusive report and cannot disappear from the evidence history.

## Frozen gates

| Gate | Required result |
|---|---:|
| Aggregate recall@12 | at least 0.90 |
| Required-slice recall@12 | at least 0.80 for every slice |
| Aggregate MRR@12 | at least 0.75 |
| Exact-identifier precision@1 | 1.00 |
| Provenance completeness | 1.00 |
| Trust-label completeness | 1.00 |
| p95 end-to-end latency | at most 5,000 ms |
| False no-match | 0 |
| Scope escape | 0 |
| Successful write attempt | 0 |
| Rights-purge residual | 0 |

Aggregate success cannot hide a required-slice failure. A result is `COMPLETE` only when all mandatory branches and reconciliation work complete. Empty candidates from incomplete work count as false no-match.

## Safety and failure experiments

Qualification must include:

- generated/raw Cypher rejection;
- caller Lucene syntax rejection;
- arbitrary index, predicate, depth, fan-out and date-window rejection;
- write-credential and write-query rejection;
- stale/incomplete generation behaviour;
- branch timeout and unavailable-service behaviour;
- authoritative collision conflicts;
- rights withdrawal, derivative purge, rebuild and non-resurrection;
- rollback to an eligible prior generation; and
- source/dataset/component identity mismatch.

Every experiment must retain the exact contract, profile, component, dataset, generation and service identities used. Failed runs are evidence and are not silently discarded.

## Public artifact safety

Repository-visible datasets, manifests, reports, receipts and regression cases exclude secrets, credentials, prohibited source expressions, unrestricted query payloads, personal data, protected or rights-restricted text, and confidential review material. Protected material may be represented only through permitted hashes, protected references, bounded permitted extracts or independently reproducible fixtures.

The signed dataset manifest must assert repository safety and current rights clearance. A safety or rights omission blocks the run; it cannot be repaired by redacting the final report after prohibited material entered an index, log or retained context.

## Decision output

The 5E report retains the exact Plan, Epoch, contract, profile, component, dataset, generation, service and code identities; methods, samples and labels; counts, denominators and slice results; latency and zero-cost evidence; deviations, incidents and environment; and every failed or superseded run needed for reasonable reproduction.

It separates:

- contract conformance;
- retrieval/index/hydration qualification;
- embedding quality, explicitly unqualified;
- stage-specific quality, contribution, amplification and failure metrics;
- security and rights results;
- operational recovery, quarantine, capacity, runbook and rollback evidence;
- unresolved Active-path or insufficient-exposure blockers; and
- production activation, explicitly unauthorized.

A completed run ends with a retained owner decision or an explicit unresolved status. Any frozen gate, required-slice, zero-tolerance, rights or Active-path failure blocks the affected qualification scope. Confirmed errors and material near misses create rights-permitted regression cases. Passing 5E still does not activate production; activation remains a separate owner-controlled decision outside Increment 5.
