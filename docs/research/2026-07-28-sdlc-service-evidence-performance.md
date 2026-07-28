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

Each service test uses a separate local pytest temporary root and independently retained SQLite/object authority. Neo4j projection data and derived index names are generation-scoped. The actual-service materializer is the first proof that concurrent execution preserves the required isolation and exact test inventory; the permanent signed workflow remains the merge authority.

## Validation

The reviewed correction passed:

- 39 focused workflow-lane tests;
- 310 repository SDLC tests, with one local environment-only `uv --no-sync` test excluded only in the extracted review workspace that had no synced lock environment;
- the complete repository core topology: 1,395 passed and 32 intentional actual-service skips;
- the clustering regression gate with no baseline regression; and
- one-use actual-service run `30354566271`, which executed all 32 authenticated Neo4j cases exactly once with zero failure, error or skip and satisfied the explicit sub-45-second material-margin gate.

The one-use finalizer reapplied the same content-addressed patch, reran the locked complete regression evidence, removed every payload, manifest, verifier and generated report, and committed only the three reviewed product files.

Merge remains blocked until the normal human-authored qualification head passes all permanent workflows, including the signed `service-neo4j` decision under the unchanged 55-second hard timeout.

## Rollback

Before merge, delete the branch. After merge, revert the harness commit. Do not alter the accepted hard timeout or service-test inventory as a rollback mechanism.
