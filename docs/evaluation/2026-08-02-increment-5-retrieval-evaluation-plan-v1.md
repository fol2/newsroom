# Increment 5 retrieval evaluation plan v1

- **Status:** reviewed machine-plan binding for Increment 5A
- **Execution owner:** 5E / #254
- **Contract:** `newsroom/increment5/data/increment5a_retrieval_contract_v1.json`
- **Contract digest:** `sha256:c7dabaf97301f851c67a2d831f6ac87b34b38c78626ea7edf8f5725ff97f1c58`
- **Machine plan:** `newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json`
- **Machine-plan digest:** `sha256:250a5b21d524cae57789d4a2d66ce6a98c55d5855d5f7373c15e5bfe3e2b2e23`

The machine JSON is the authoritative preregistration. This document explains it without adding thresholds, exceptions or authority.

## Decision scope

`HYBRID` is the only qualification-bearing system. `EXACT_ONLY`, `FULL_TEXT_ONLY`, `VECTOR_ONLY` and `ADMITTED_GRAPH_ONLY` are mandatory comparative ablations.

Every contract threshold, mandatory-family criterion, required-slice criterion, temporal gate and rebuild gate applies independently to `HYBRID`. Comparative quality is reported separately, is not decision-bearing, cannot be pooled and cannot rescue a failed hybrid target. A safety or rights violation in any executed system remains blocking.

## Evaluation evidence semantics

Every retained metric identifies its count, denominator, unit, system role, query family, slice, generation, exact component identities and sampling status. Raw branch scores are never compared.

Ground truth is the owner-frozen corpus of authoritative identities, revisions, dependency roots, valid-time labels, rights decisions, expected Candidate dispositions and relevance judgements. No graph, index, provider or retrieval branch is ground truth.

Performance outcomes, change-evaluation outcomes, operational evidence and exploratory recommendations remain separate. A missing, invalid, withdrawn, under-exposed, rights-blocked or failed run is retained as such and cannot be pooled into a pass.

## Mandatory GraphRAG query families

A missing or under-exposed family is `NOT_EVALUATED`.

1. **Event and development precision** — same-event state, development of an existing event and related-but-distinct event; precision ≥ 0.90, recall ≥ 0.80, every required family/slice recall ≥ 0.80 and distractor false-merge precision = 1.00.
2. **Source-revision impact** — correction, supersession and downstream-Candidate impact; precision and recall ≥ 0.80, every required family/slice recall ≥ 0.80 and provenance completeness = 1.00.
3. **Long-running policy, case or process timeline** — ordered development, correction, supersession and temporal cutoff; precision and recall ≥ 0.80, every required family/slice recall ≥ 0.80 and temporal-correctness errors = 0.

Each sufficiently exposed family is an independent blocking surface. Aggregate MRR, aggregate recall, another family, a comparative branch or reviewer judgement cannot rescue it.

## DEVAL-046 triage-error protocol

The hybrid target must preregister and report all six classes separately. Each class retains eligible-opportunity count, error count or counts, rate in parts per million, exact case labels and definition. Cross-class rate pooling is prohibited. Each class requires at least 10 relevant preregistered qualification cases; a shortfall is `NOT_EVALUATED`.

| Class | Eligible opportunity | Error metrics | Frozen decision treatment |
|---|---|---|---|
| `FALSE_MERGE` | authority roots or events labelled related-but-distinct | `false_merge_count`, `false_merge_opportunity_count`, `false_merge_rate_ppm` | automatic blocker through perfect distractor false-merge precision |
| `FRAGMENTATION` | one authority-labelled event or development expected to remain one result root or disposition | `fragmentation_count`, `fragmentation_opportunity_count`, `fragmentation_rate_ppm` | mandatory separate report; no invented post-hoc threshold |
| `SNOWBALL_ABSORPTION` | related-but-distinct or shared-origin cases where a broad root must not absorb another event | `snowball_absorption_count`, `snowball_absorption_opportunity_count`, `snowball_absorption_rate_ppm` | mandatory separate report; no invented post-hoc threshold |
| `FALSE_OR_MISSED_DEVELOPMENT` | labelled developments, corrections and supersessions | `false_development_count`, `missed_development_count`, `development_opportunity_count`, `false_or_missed_development_rate_ppm` | automatic blocker through frozen event/development precision and recall |
| `DUPLICATE_CANDIDATE_CREATION` | one expected downstream Candidate disposition for one authoritative dependency root and material development | `duplicate_candidate_creation_count`, `single_candidate_opportunity_count`, `duplicate_candidate_creation_rate_ppm` | mandatory separate report; no invented post-hoc threshold |
| `UNNECESSARY_CANDIDATE_CREATION` | frozen labels require no new Candidate | `unnecessary_candidate_creation_count`, `no_candidate_expected_opportunity_count`, `unnecessary_candidate_creation_rate_ppm` | mandatory separate report; no invented post-hoc threshold |

Candidate-related evaluation uses read-only expected dispositions. It creates, mutates, admits or publishes no Candidate.

## Exposure minima

The frozen qualification partition contains at least:

- 100 unique qualification cases;
- 30/30/40 cases across the three mandatory families;
- 10 cases per required case type;
- 20 relevant cases per global required slice;
- 10 cases per mandatory family / required-slice intersection; and
- 10 relevant cases per triage-error class.

Each case counts once in exactly one mandatory family. It may carry multiple independently frozen slice and error-opportunity labels. Cross-family reuse and calibration counting are prohibited. Duplicate, invalid, withdrawn and post-freeze cases do not count.

Any total, family, case-type, slice, family/slice or triage-error-class shortfall makes the affected surface `NOT_EVALUATED`. Sufficiency cannot be chosen after outcomes are visible.

## Frozen gates

The contract gates apply to `HYBRID`: MRR@12 ≥ 0.75; recall@12 ≥ 0.90; exact-identifier precision@1 = 1.00; every required-slice recall@12 ≥ 0.80; provenance completeness = 1.00; trust-label completeness = 1.00; false no-match, scope escape, successful write and rights-purge residual counts = 0; p95 latency ≤ 5,000 ms.

Two additional gates are zero-tolerance:

- `temporal_correctness_error_count = 0`; and
- `rebuild_reproducibility_mismatch_count = 0` after authoritative loss and `RIGHTS_PURGE_AND_REBUILD` under the same exact inputs.

A completed rebuild that changes eligible identities, ordering, branch/fusion/exclusion/hydration receipts, provenance, trust labels, temporal fields or outcomes fails.

## Safety experiments

Retain exact contract, system role, generation, injected fault, expected outcome, observed outcome and evidence for missing branches, stale generations, incomplete hydration or collision checks, dependency-root duplicates, arbitrary query attempts, writes, credentials, egress, protected content, rights withdrawal, purge, authoritative loss, isolated rebuild, deterministic replay, restart and actual-Neo4j recovery.

A silent empty result, graph-free substitute, successful write or residual derivative is blocking.

## Public artifact safety

Public evidence contains only schemas, structural fixtures, counts, denominators, rates, timings, digests, bounded diagnostics and non-sensitive decision material. It excludes secrets, credentials, personal data, confidential material, prohibited source expressions, protected payloads and rights-restricted text. A redaction failure blocks publication of the artifact.

## Decision output

Results remain separate by system role, mandatory family, required slice, triage-error class, generation and component identity. Each completed Run retains its thresholds, exposure status, safety and rights blockers, at least one reconcilable incident timeline, comparative results and an owner decision or explicit unresolved state.

Allowed owner outcomes are `ACCEPTED`, `REPEAT_QUALIFICATION`, `REPLACEMENT_REQUIRED`, `RESOLVED_NO_CHANGE`, `REJECTED` and `UNRESOLVED`. A fixture-only vector result qualifies index semantics only; it does not establish embedding relevance or production vector authority.
