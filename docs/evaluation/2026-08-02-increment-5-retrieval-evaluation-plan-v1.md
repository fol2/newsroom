# Increment 5 retrieval evaluation plan v1

This plan is preregistered by 5A and executed in 5E (#254). Thresholds are frozen before qualification. Calibration and qualification examples are disjoint.

- **Machine record:** `newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json`
- **Machine-record digest:** `sha256:79bd07c69a69933d3a8fc1c218d638101d3c10e4a15cb482a8ee724ee973127b`
- **Contract:** `sha256:c7dabaf97301f851c67a2d831f6ac87b34b38c78626ea7edf8f5725ff97f1c58`

The contract contains the exact ranking thresholds, slices and ablation inventory. The machine record binds that summary byte-for-byte and adds the mandatory GraphRAG query families, the decision-bearing system, exposure floors, and zero-tolerance temporal and rebuild gates. Its digest remains outside the contract it binds, avoiding a plan-digest/contract-digest cycle.

## Claim boundary

Qualification may establish that the reviewed hybrid exact/full-text/fixed-point-vector/admitted-graph implementation works against an actual Neo4j service, hydrates authority correctly, degrades explicitly, preserves rights and satisfies the frozen budgets.

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

## Decision-bearing system

`HYBRID` is the sole qualification target. Every contract threshold, mandatory-query-family criterion, required-slice gate, temporal-correctness gate and rebuild-reproducibility gate is calculated for and applied to the hybrid result independently.

The four non-hybrid systems are mandatory comparative ablations:

- `EXACT_ONLY`;
- `FULL_TEXT_ONLY`;
- `VECTOR_ONLY`; and
- `ADMITTED_GRAPH_ONLY`.

Their quality results are diagnostic and must be reported separately. They are not decision-bearing, cannot replace the hybrid target, cannot be pooled across systems, and cannot rescue a hybrid failure. A strong exact-only, vector-only or graph-only result therefore cannot manufacture a qualification pass when hybrid retrieval misses a frozen criterion.

A safety or rights violation in any executed system still blocks the affected qualification scope. Comparative status does not excuse a successful write, scope escape, rights-purge residual, prohibited material, or another safety breach.

## Mandatory GraphRAG use-case families

Every qualification dataset and report must include all three query families below for the `HYBRID` qualification target. A family that is absent, under-labelled or not separately reported is `NOT_EVALUATED`, never passed.

### Event and development precision

`EVENT_AND_DEVELOPMENT_PRECISION` must distinguish:

- same-event state;
- a development of an existing event; and
- a related-but-distinct event.

It must report hybrid precision and recall across `EN_GB`, `ZH_HANT_HK`, `MIXED_EN_GB_ZH_HANT_HK` and `DISTRACTOR_FALSE_MERGE`. Similar names, shared entities or lexical overlap cannot repair a false merge.

### Source-revision impact

`SOURCE_REVISION_IMPACT` must retrieve and preserve the exact provenance of:

- correction impact;
- supersession impact; and
- downstream Candidate impact.

It must report hybrid precision, recall and provenance completeness across `CORRECTION_AND_SUPERSESSION` and `TEMPORAL_CUTOFF`. A source-impact tool existing in code does not satisfy this family unless the frozen qualification set exercises and reports it.

### Long-running policy, case or process timeline

`LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE` must cover ordered developments, corrections, supersessions and as-of temporal cutoffs across `LONG_RUNNING_TIMELINE` and `TEMPORAL_CUTOFF`. It must report hybrid precision, recall and temporal correctness separately.

These families operationalize the three mandatory first-use cases in `GRAG-054`; a generic aggregate retrieval score or a non-hybrid ablation cannot substitute for any family.

## Per-family blocking acceptance criteria

Every mandatory family is a separate blocking decision surface for `HYBRID`. Aggregate recall, aggregate MRR, a comparative ablation or another family's result cannot rescue a hybrid family that misses one of its frozen criteria. A family below its exposure floor is `NOT_EVALUATED`; a sufficiently exposed family that misses any criterion is `FAIL` for the affected qualification scope.

| Mandatory query family | Precision | Recall | Required-slice recall | Additional blocker |
|---|---:|---:|---:|---|
| `EVENT_AND_DEVELOPMENT_PRECISION` | at least 0.90 | at least 0.80 | at least 0.80 in each required family slice | `DISTRACTOR_FALSE_MERGE` precision must be 1.00 |
| `SOURCE_REVISION_IMPACT` | at least 0.80 | at least 0.80 | at least 0.80 in each required family slice | provenance completeness must be 1.00 |
| `LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE` | at least 0.80 | at least 0.80 | at least 0.80 in each required family slice | temporal-correctness error count must be 0 |

The common 0.80 floor matches the already accepted required-slice recall floor while preventing cross-family averaging. Event/development precision is higher because false association is asymmetrically harmful, and the adversarial false-merge slice is zero-tolerance for false positives. Source-revision impact requires complete provenance because a result without exact revision lineage cannot support impact reasoning. Timeline qualification inherits the global zero-tolerance temporal blocker.

All rates retain exact numerators and denominators. Uncertainty is reported, but no confidence interval, reviewer judgment, comparative branch or aggregate score may lower these frozen point-estimate gates after outcomes are visible.

## Frozen exposure minima

Exposure sufficiency is decided before any qualification outcome exists. The signed qualification partition must contain at least **100 unique pre-registered cases**. Each `case_id` counts once in exactly one mandatory query family; cross-family reuse is prohibited. A case may satisfy multiple independently labelled slices, but duplicate, invalid, withdrawn, calibration or post-freeze cases do not count.

The exact family floors are:

| Mandatory query family | Minimum unique cases | Minimum per required case type |
|---|---:|---:|
| `EVENT_AND_DEVELOPMENT_PRECISION` | 30 | 10 |
| `SOURCE_REVISION_IMPACT` | 30 | 10 |
| `LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE` | 40 | 10 |

Every one of the nine required slices must have at least **20 independently relevant qualification cases**, and every mandatory family/required-slice intersection must contain at least **10 relevant cases**. This is an evidence floor, not permission to generalize beyond the bounded reviewed dataset: counts, denominators and uncertainty remain mandatory in the report. A family, case type, slice or total partition below its frozen floor is `NOT_EVALUATED`, never `PASS` or a reviewer-selected sufficiency judgment.

The family floors sum exactly to the 100-case unique-partition floor. The 20-case global slice floor gives the overall 0.80 required-slice threshold an explicit denominator of at least 20, while the 10-case family/slice floor makes each per-family slice gate measurable rather than inferred from another family. Calibration cases never repair a qualification exposure shortfall.

## Systems compared

Run the hybrid target and all four comparative ablations on the same qualification partition and generation:

1. hybrid — the sole decision-bearing qualification target;
2. exact only — comparative;
3. full-text only — comparative;
4. vector only — comparative; and
5. admitted graph only — comparative.

The vector branch uses only deterministic fixed-point fixture vectors. Record branch receipts, exclusions, ranks and final fused order. Do not compare raw branch scores.

The report must retain one separate result block for each system. Cross-system quality pooling is prohibited. Comparative quality results explain branch contribution and failure modes; they neither pass nor fail the hybrid target. Any safety or rights violation from an executed system remains blocking.

## Evaluation evidence semantics

The exact contract, component identities, dataset partitions, queries, labels, thresholds, decision target and policies are frozen for one qualification Epoch. A material change starts another Epoch. Results from different Epochs are reported separately and cannot be pooled to manufacture a pass.

Calibration and qualification remain disjoint. Calendar duration alone is not sufficient exposure. The exact machine-plan floors—100 unique qualification cases, family minima of 30/30/40, at least 10 cases per required case type, at least 20 relevant cases per required slice and at least 10 relevant cases per mandatory family/required-slice intersection—must all be met before the affected result can be evaluated. Any shortfall is `NOT_EVALUATED`, never passed. The reviewed signed dataset is a bounded evaluation universe; no provider, index or retrieval branch is treated as complete ground truth.

Every reported rate retains its count, denominator, system, slice, query family, population-or-sample status, sampling method and uncertainty where applicable. Adapter/index behaviour, branch retrieval, fusion, hydration, security, latency, cost, purge and recovery remain separately attributable. An early-stopped run retains a failed or inconclusive report and cannot disappear from the evidence history.

## Frozen gates

The table below is evaluated against `HYBRID`, the sole qualification target.

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

Aggregate hybrid success cannot hide a required-slice or mandatory-query-family failure. Each sufficiently exposed mandatory family must independently satisfy its own frozen precision, recall, family-slice and additional blocking criteria. A result is `COMPLETE` only when all mandatory branches and reconciliation work complete. Empty candidates from incomplete work count as false no-match.

No comparative quality result can rescue, replace or be pooled with the hybrid result. Independently, any safety or rights violation in any executed system blocks the affected qualification scope.

### Zero-tolerance temporal correctness

`temporal_correctness_error_count` has a frozen maximum of zero for the hybrid target. It counts any result that:

- leaks state recorded or valid only after the query cutoff;
- selects the wrong source Revision or valid-time version;
- collapses observation, validity, recording, proposal, admission or invalidation times;
- misorders a development, correction or supersession; or
- otherwise violates the frozen as-of authority labels.

The gate applies to every relevant hybrid query and specifically to `TEMPORAL_CUTOFF`. The 0.80 slice-recall floor cannot excuse one temporal-correctness error.

### Zero-tolerance reproducible rebuild

`rebuild_reproducibility_mismatch_count` has a frozen maximum of zero for the hybrid target. After complete projection/index loss, a rebuild under the same exact contract, components, dataset, retained proposals/decisions and generation inputs must reproduce all eligible:

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

Every experiment must retain the exact system, contract, profile, component, dataset, generation and service identities used. Failed runs are evidence and are not silently discarded. A safety or rights violation in any executed system blocks the affected scope even when that system is otherwise a comparative ablation.

## Public artifact safety

Repository-visible datasets, manifests, reports, receipts and regression cases exclude secrets, credentials, prohibited source expressions, unrestricted query payloads, personal data, protected or rights-restricted text, and confidential review material. Protected material may be represented only through permitted hashes, protected references, bounded permitted extracts or independently reproducible fixtures.

The signed dataset manifest must assert repository safety and current rights clearance. A safety or rights omission blocks the run; it cannot be repaired by redacting the final report after prohibited material entered an index, log or retained context.

## Decision output

The 5E report retains the exact Plan, Epoch, contract, profile, component, dataset, generation, service and code identities; methods, samples and labels; unique case IDs, family/case-type/slice exposure counts, pass denominators, query-family and slice results; latency and zero-cost evidence; deviations, incidents and environment; and every failed or superseded run needed for reasonable reproduction.

It identifies `HYBRID` as the sole decision-bearing result and reports each comparative ablation separately. It separates:

- contract conformance;
- hybrid retrieval/index/hydration qualification;
- comparative exact/full-text/vector/graph ablation results, explicitly non-decision-bearing;
- embedding quality, explicitly unqualified;
- stage-specific quality, contribution, amplification and failure metrics;
- temporal-correctness and reproducible-rebuild zero-tolerance results;
- security and rights results across every executed system;
- operational recovery, quarantine, capacity, runbook and rollback evidence;
- unresolved Active-path or insufficient-exposure blockers; and
- production activation, explicitly unauthorized.

A completed run ends with a retained owner decision or an explicit unresolved status. Any hybrid frozen gate, required-slice, mandatory-query-family or zero-tolerance failure blocks the affected qualification scope. Any rights or safety failure in any executed system also blocks. Confirmed errors and material near misses create rights-permitted regression cases. Passing 5E still does not activate production; activation remains a separate owner-controlled decision outside Increment 5.
