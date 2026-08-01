# Increment 5 retrieval Evaluation Plan v1

**Status:** Pre-registered proposal — owner approval required before qualification  
**Plan ID:** `increment5-retrieval-evaluation-plan-v1`  
**Plan version:** `increment5-retrieval-evaluation-v1`  
**Bound decision payload:** `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`  
**Bound contract bundle:** `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`  
**Issue boundaries:** #250 defines; #254 executes  
**Runtime authority:** none

## Purpose

This Plan freezes the methods, slices, thresholds and blockers used to qualify the exact Increment 5 retrieval implementation. It prevents threshold selection after outcomes are known and prevents repository fixture replay from being described as production-vector evidence.

The Plan itself starts no model, index, Neo4j service, source access, shadow run, canary, spend or production effect. Issue #254 may execute it only after the exact 5A owner decision is recorded and #251–#253 are merged in dependency order.

## Epoch and Run rules

Every Run binds the decision payload, component identity digests, source commit, Neo4j image, Python and driver versions, embedding package wheel hash, model revision and artifact digest, index-generation identities, dataset manifest, rights manifest, query set, thresholds, resource profile, seed where applicable, and start/end times.

Calibration and qualification are disjoint. Calibration can inform a later plan amendment but cannot qualify the thresholds it selected. Any material change to a component, model artifact, chunker, normaliser, query, fusion, deduplication, hydration, degraded policy, dataset, threshold, rights scope, topology or resource profile creates a new Epoch. Epochs cannot be pooled to manufacture a pass.

Early-stopped, failed, incomplete and superseded Runs remain retained with an explicit result. A required slice with insufficient exposure is `INCONCLUSIVE`, never silently pooled into aggregate success.

## Dataset authority and rights

Qualification uses a signed, immutable, event-level dataset manifest. Allowed material is:

- governed synthetic qualification text with known labels and no prohibited expression;
- public governed source text only where a signed rights-cleared manifest permits local indexing, local self-hosted embedding, retention and review for the Run; and
- protected references, hashes or permitted extracts when exact expression cannot enter the repository.

Repository fixture replay is a regression and contract check only. It may not qualify the real model/vector lane. Rights-restricted source text, personal data, secrets and credentials are excluded from the vector qualification corpus. Tombstoned/revoked negative cases must prove purge from all derivatives and non-resurrection after rebuild.

Final release labels require authorised human review. Launch blockers, zero-tolerance cases, potentially urgent material errors and the pre-registered ordinary sample require independent second review or adjudication. Reviewer disagreement remains visible.

## Compared modes

Each eligible Case is evaluated against the same temporal cutoff, authority watermark and candidate universe under:

1. exact only;
2. full-text only;
3. vector only;
4. admitted graph only; and
5. complete hybrid retrieval.

Ablations must retain branch receipts, omissions and explicit outcomes. A missing/unavailable branch cannot be reclassified as a successful zero-result mode. No graph-free hybrid substitute is accepted.

## Required slices

- `EN_GB`
- `ZH_HANT_HK`
- `MIXED_EN_GB_ZH_HANT_HK`
- `TEMPORAL_CUTOFF`
- `CORRECTION_AND_SUPERSESSION`
- `SHARED_ORIGIN_DEPENDENCY`
- `DISTRACTOR_FALSE_MERGE`
- `LONG_RUNNING_TIMELINE`
- `RIGHTS_PURGE_AND_REBUILD`

Each Case records relation/route class, exact expected dependency roots, permitted no-match state, temporal cutoff, trust expectations, required provenance and whether a failure is zero-tolerance.

## Frozen thresholds

Rates are represented in parts per million to avoid floating-point ambiguity in the canonical decision record.

| Metric | Threshold |
|---|---:|
| Exact identifier precision@1 | 100.00% |
| Aggregate recall@12 | 90.00% minimum |
| Required-slice recall@12 | 80.00% minimum |
| Aggregate MRR@12 | 75.00% minimum |
| Provenance completeness | 100.00% |
| Trust-label completeness | 100.00% |
| p95 end-to-end retrieval latency | ≤ 5000 ms under the exact qualification profile |
| False no-match count | 0 |
| Rights-purge residual count | 0 |
| Scope escape count | 0 |
| Successful graph/index write attempts through a read tool | 0 |

Metrics retain numerator, denominator, sample/population status, uncertainty, versions and Run identity. Aggregate success cannot override a required-slice failure or any zero-tolerance failure.

## Correctness and security cases

The suite must include exact/formal identifiers, same-state repetitions, developments, corrections, supersessions, related-but-distinct incidents, no-adequate-prior-match, mixed-language aliases, shared-origin copies, long-running processes and adverse distractors. It must test temporal leakage, stale/gapped generations, branch timeout, missing indexes, graph loss, incomplete hydration, rights denial, collision-check failure, malformed adapter rows, score/tie determinism and deterministic replay.

Security qualification includes attempted raw Cypher, label/property injection, unrestricted index access, write requests, generated query text, over-depth/fan-out/date/result/byte/timeout bounds, untrusted-content instruction injection, cross-tenant/scope identifiers, stale credentials, and attempts to treat projection text or rank as authority. All read tools use least privilege and return exact serving metadata.

## Actual-service and recovery evidence

Issue #254 runs the exact authenticated Neo4j Community image and driver bound by the decision, with real full-text and vector indexes generated from the signed dataset. Required evidence includes:

- all four branches and hybrid fusion on the exact service;
- complete watermark, generation, ontology/projector, trust, gap/dead-letter and branch receipts;
- index/graph loss producing explicit unavailable/incomplete outcomes rather than no-match;
- isolated replacement generation rebuild from retained authority;
- rights purge followed by destructive rebuild with zero resurrection;
- deterministic replay and stable ranking/tie-breaks;
- backup/rebuild, intended-hardware resource and latency evidence; and
- failed and superseded Run retention.

A fixture-only vector or fake graph cannot satisfy this section.

## Release outcome

The report outcome is one of `PASSED_EXACT_SCOPE`, `FAILED`, `INCONCLUSIVE`, `BLOCKED_RIGHTS`, `BLOCKED_OPERATIONAL_PROFILE`, or `BLOCKED_OWNER_DECISION`. Passing only creates evidence for later Operational Admission; it does not start shadow, canary or production. A material failure requires remediation and a fresh qualifying Run in a new or repaired Epoch.
