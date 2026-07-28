# Parallel authenticated-service evidence within the retained hard budget

**Date:** 2026-07-28
**Issue:** #215
**Discovered by:** Increment 3C PR #214
**Authority boundary:** repository-owned SDLC evidence only

## Problem

Two exact-tree signed SDLC runs completed the authenticated Neo4j service job but failed the final decision because the serial pytest command exhausted the retained 55-second hard gate:

- run `30344872737`: `54,434 ms`;
- run `30352484083`: `54,433 ms`.

The independent authenticated Neo4j workflow on the same source tree executed all 32 required service cases with zero failure, error or skip. The defect was therefore the evidence harness wall-clock topology, not product correctness. Increasing the timeout, removing tests, accepting an incomplete JUnit report or retrying until a favourable runner would weaken the accepted SDLC contract and was rejected.

## Correction

The service lane continues to derive its complete test-file inventory from every repository `test_*_neo4j_service.py` file. It now:

1. validates the exact sorted inventory and rejects missing, extra, duplicate or symlinked files;
2. divides the complete inventory into two deterministic shards using repository file size as a stable balancing input;
3. launches both shards concurrently with separate pytest temp roots, logs and JUnit reports;
4. disables ambient third-party pytest plugin autoload, assertion rewriting overhead and cache writes for the evidence subprocesses while retaining Python assertions and normal failure output;
5. prints each shard log in deterministic order;
6. merges both reports into one private JUnit document; and
7. re-summarises the merged report and rejects missing reports, malformed XML, duplicate test identities, incomplete coverage or any summary drift.

No Neo4j test, source file, service configuration, credential boundary, artifact contract, hard timeout or decision rule is removed or relaxed.

## Concurrency safety

Each service test uses a separate local pytest temporary root and independently retained SQLite/object authority. Neo4j projection data and derived index names are generation-scoped. The accepted actual-service run remains the authoritative proof that concurrent execution preserves the required isolation and exact test inventory.

## Validation

Before remote actual-service qualification, the correction passed:

- 39 focused workflow-lane tests;
- 310 repository SDLC tests, with one local environment-only `uv --no-sync` test excluded because the extracted review workspace had no synced lock environment;
- the complete repository core topology: 1,395 passed and 32 intentional actual-service skips; and
- the clustering regression gate with no baseline regression.

Merge remains blocked until the exact reviewed head executes all 32 authenticated service cases once, produces a complete merged JUnit report, passes the signed service gate with material margin below 55 seconds and passes every permanent repository workflow.

## Rollback

Before merge, delete the branch. After merge, revert the harness commit. Do not alter the accepted hard timeout or service-test inventory as a rollback mechanism.
