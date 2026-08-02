# Increment 5 retrieval evaluation plan v1

This plan is preregistered by 5A and executed in 5E (#254). Thresholds are frozen before qualification. Calibration and qualification examples are disjoint.

- **Machine record:** `newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json`
- **Machine-record digest:** `sha256:6d52ea47056a8df4cd71213ae68c47471f7c2f546bd834053b27d747a0247c29`
- **Contract:** `sha256:c7dabaf97301f851c67a2d831f6ac87b34b38c78626ea7edf8f5725ff97f1c58`

The contract contains the exact ranking thresholds, slices and ablation summary. The machine record binds that summary byte-for-byte and adds the mandatory GraphRAG query families plus zero-tolerance temporal and rebuild gates. Its digest remains outside the contract it binds, avoiding a plan-digest/contract-digest cycle.

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

## Mandatory GraphRAG use-case families

Every qualification dataset and report must include all three query families below. A family that is absent, under-labelled or not separately reported is `NOT_EVALUATED`, never passed.

### Event and development precision

`EVENT_AND_DEVELOPMENT_PRECISION` must distinguish:

- same-event state;
- a development of an existing event; and
- a related-but-distinct event.

It must report precision and recall across `EN_GB`, `ZH_HANT_HK`, `MIXED_EN_GB_ZH_HANT_HK` and `DISTRACTOR_FALSE_MERGE`. Similar names, shared entities or lexical overlap cannot repair a false merge.

### Source-revision impact

`SOURCE_REVISION_IMPACT` must retrieve and preserve the exact provenance of:

- correction impact;
- supersession impact; and
- downstream Candidate impact.

It must report precision, recall and provenance completeness across `CORRECTION_AND_SUPERSESSION` and `TEMPORAL_CUTOFF`. A source-impact tool existing in code does not satisfy this family unless the frozen qualification set exercises and reports it.

### Long-running policy, case or process timeline

`LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE` must cover ordered developments, corrections, supersessions and as-of temporal cutoffs across `LONG_RUNNING_TIMELINE` and `TEMPORAL_CUTOFF`. It must report precision, recall and temporal correctness separately.

These families operationalize the three mandatory first-use cases in `GRAG-054`; a generic aggregate retrieval score cannot substitute for any family.

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

Calibration and qualification remain disjoint. Calendar duration alone is not sufficient exposure: a required slice or mandatory query family without enough pre-registered examples is `INCONCLUSIVE` or `NOT_EVALUATED`, never passed. The reviewed signed dataset is a bounded evaluation universe; no provider, index or retrieval branch is treated as complete ground truth.

Every reported rate retains its count, denominator, slice, query family, population-or-sample status, sampling method and uncertainty where applicable. Adapter/index behaviour, branch retrieval, fusion, hydration, security, latency, cost, purge and recovery remain separately attributable. An early-stopped run retains a failed or inconclusive report and cannot disappear from the evidence history.

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
| Temporal-correctness error | 0 |
| Rebuild-reproducibility mismatch | 0 |

Aggregate success cannot hide a required-slice or mandatory-query-family failure. A result is `COMPLETE` only when all mandatory branches and reconciliation work complete. Empty candidates from incomplete work count as false no-match.

### Zero-tolerance temporal correctness

`temporal_correctness_error_count` has a frozen maximum of zero. It counts any result that:

- leaks state recorded or valid only after the query cutoff;
- selects the wrong source Revision or valid-time version;
- collapses observation, validity, recording, proposal, admission or invalidation times;
- misorders a development, correction or supersession; or
- otherwise violates the frozen as-of authority labels.

The gate applies to every relevant query and specifically to `TEMPORAL_CUTOFF`. The 0.80 slice-recall floor cannot excuse one temporal-correctness error.

### Zero-tolerance reproducible rebuild

`rebuild_reproducibility_mismatch_count` has a frozen maximum of zero. After complete projection/index loss, a rebuild under the same exact contract, components, dataset, retained proposals/decisions and generation inputs must reproduce all eligible:

- authority identifiers and ordering;
- branch, fusion, exclusion and hydration receipts;
- provenance and trust labels;
- temporal fields; and
- final explicit outcomes.

Any difference is a blocking mismatch. `RIGHTS_PURGE_AND_REBUILD` must execute this experiment while also proving that prohibited or purged material does not resurrect. Merely completing a rebuild is not evidence of reproducibility.

## Safety and failure experiments

Qualification must include:

- generated/raw Cypher rejection;
- caller Lucene syntax rejection;
- arbitrary index, predicate, depth, fan-out and date-window rejection;
- write-credential and write-query rejection;
- stale/incomplete generation behaviour;
- branch timeout and unavailable-service behaviour;
- authoritative collision conflicts;
- rights withdrawal, derivative purge, rebuild, reproducibility and non-resurrection;
- rollback to an eligible prior generation; and
- source/dataset/component identity mismatch.

Every experiment must retain the exact contract, profile, component, dataset, generation and service identities used. Failed runs are evidence and are not silently discarded.

## Public artifact safety

Repository-visible datasets, manifests, reports, receipts and regression cases exclude secrets, credentials, prohibited source expressions, unrestricted query payloads, personal data, protected or rights-restricted text, and confidential review material. Protected material may be represented only through permitted hashes, protected references, bounded permitted extracts or independently reproducible fixtures.

The signed dataset manifest must assert repository safety and current rights clearance. A safety or rights omission blocks the run; it cannot be repaired by redacting the final report after prohibited material entered an index, log or retained context.

## Decision output

The 5E report retains the exact Plan, Epoch, contract, profile, component, dataset, generation, service and code identities; methods, samples and labels; counts, denominators, query-family and slice results; latency and zero-cost evidence; deviations, incidents and environment; and every failed or superseded run needed for reasonable reproduction.

It separates:

- contract conformance;
- retrieval/index/hydration qualification;
- embedding quality, explicitly unqualified;
- stage-specific quality, contribution, amplification and failure metrics;
- temporal-correctness and reproducible-rebuild zero-tolerance results;
- security and rights results;
- operational recovery, quarantine, capacity, runbook and rollback evidence;
- unresolved Active-path or insufficient-exposure blockers; and
- production activation, explicitly unauthorized.

A completed run ends with a retained owner decision or an explicit unresolved status. Any frozen gate, required-slice, mandatory-query-family, zero-tolerance, rights or Active-path failure blocks the affected qualification scope. Confirmed errors and material near misses create rights-permitted regression cases. Passing 5E still does not activate production; activation remains a separate owner-controlled decision outside Increment 5.
