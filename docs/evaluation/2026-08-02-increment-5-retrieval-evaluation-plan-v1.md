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

## Decision output

The 5E report separates:

- contract conformance;
- retrieval/index/hydration qualification;
- embedding quality, explicitly unqualified;
- security and rights results;
- operational recovery results; and
- production activation, explicitly unauthorized.

Any frozen gate failure blocks qualification. Passing 5E still does not activate production; activation remains a separate owner-controlled decision outside Increment 5.
