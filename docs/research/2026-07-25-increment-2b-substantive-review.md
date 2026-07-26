# Increment 2B substantive implementation review

- Role: Dated current-head review evidence
- Status: Completed for the corrected source tree; exact-head GitHub evidence still required
- Owner: Product owner
- Canonical language: English
- Date: 2026-07-25
- Updated: 2026-07-26
- Related issue: #156
- Parent epic: #142
- Related draft PR: #164
- Authorised base: `main@819883fb77eeabfb76d91aca531003d07932d5a7`
- Reviewed pre-correction head: `86a08bc7ea615681c9dcf420c3d0026bc1a3ac08`
- Corrected review boundary: the commit containing this record; record the exact SHA on PR #164 after push

## Scope

The review covers only owner-authorised Increment 2B:

- complete structural, admitted-relation, full-text and vector generation contracts;
- deterministic bilingual fixture evidence and deterministic vectors;
- checked SQLite schema version 7 and startup integrity;
- fixed private Neo4j adapter and actual-service workflow;
- ordered delivery, checkpoints, gaps and dead letters;
- expected/actual reconciliation, validation, qualification and promotion;
- rebuild, replacement generation, rights, deletion and tombstones;
- compatibility, operations, traceability, exclusions and rollback.

The review excludes Increment 2C, hybrid retrieval, Retrieval Context version 2, Graphiti, external models or embeddings, live sources, search, shadow, canary, production activation, publication, spending and public effect.

## Result

- P1 findings: 1
- P2 findings: 9
- Remaining unresolved P1/P2 after correction: 0

Review submissions, inline threads and actionable top-level comments must be rechecked against the exact final PR head before merge.

## Findings and corrections

### P1-1 — A source event could arrive during reconciliation and stale authority could still commit

The pre-correction complete boundary compared the requested checkpoint with the latest non-projection source watermark before Neo4j reconciliation. Validation and promotion did not repeat that comparison atomically inside their SQLite transactions. A new source event could therefore arrive during a slow graph reconciliation and the earlier generation could still receive validation or promotion authority.

Correction:

- compare the exact source watermark before validation, qualification and promotion;
- compare it again after Neo4j reconciliation or query evidence;
- pass the required source sequence into the SQLite validation and promotion stores;
- inside `BEGIN IMMEDIATE`, compare the latest non-projection ledger sequence immediately before returning replay or creating authority;
- reject a changed source watermark without creating validation or promotion authority; and
- add adversarial tests that inject a source command during reconciliation, promotion authorization and qualification evidence collection.

### P2-1 — Neo4j null semantics broke optional canonical-property equality

The pre-correction adapter serialized optional values such as `revision_id=None` and `valid_until=None`. Neo4j removes a property assigned `null`, so a subsequent exact read returned an absent key and the strict decoder reported an identity conflict.

Correction:

- omit only typed nullable properties from Neo4j writes;
- reconstruct their canonical value as `None` when absent;
- retain exact required-property and unknown-property rejection; and
- add unit and actual-service coverage for nullable round trips.

### P2-2 — SDLC service routing and legacy artifact contracts drifted

Increment 2B extended the permanent Neo4j workflow and service test set, but the accepted SDLC routing tests and legacy evidence artifact name still described the earlier B2/B3/C1 topology. Full CI and the SDLC decision failed even when the extended service tests executed.

Correction:

- update the exact service test allow-list in both SDLC contract tests;
- retain the extended complete evidence artifact; and
- upload the legacy B2/B3/C1 evidence alias for the accepted service lane.

### P2-3 — Three actual-service tests asserted the wrong authority surface

Three qualification cases failed for test-contract reasons rather than projection failures:

- one counted every generation relationship instead of the governed `DEVELOPMENT_OF` relationship;
- replacement recovery attempted to register an already retained family again; and
- lifecycle evidence read a checkpoint from the rebuild receipt rather than the authoritative family projection status.

Correction:

- count only the governed relation type;
- create replacement generations under the already retained family; and
- read the current checkpoint from the family projection status view.

The corrected cases retain the same fail-closed production assertions.

### P2-4 — The normalized full-text query contract was retained but not executed

`FullTextQualificationQuery` retained both original and normalized text, but the actual and memory adapters executed only the original query. This did not satisfy the required actual-service proof for exact and normalized full-text paths.

Correction:

- execute every full-text qualification as two separate query identities: the original ID and `<id>.normalized`;
- execute the retained normalized text even when it is byte-equal to the original language form;
- require the same exact first passage for both paths;
- retain both result sets in qualification evidence; and
- add unit, authority and actual-service assertions for both query identities.

### P2-5 — Required operations, traceability and rollback evidence was absent

The initial PR source checkpoint contained implementation and tests but no Increment 2B operations guide, dedicated traceability register, rollback contract or dated substantive-review record. Passing CI could not satisfy issue #156's completion gate without these records.

Correction:

- add `docs/operations/increment-2b-complete-projection.md`;
- add this substantive-review record;
- add exact Increment 2B traceability, exclusions and deferred-work constants;
- add documentation-contract tests; and
- update the documentation map.

### P2-6 — The authority boundary trusted adapter query evidence completeness

The adapter checked fixture query results, but the complete authority boundary accepted any typed `PASSED` qualification whose projection-state digest matched validation. A defective or substituted adapter could omit normalized full-text evidence, duplicate ranks or return an incomplete vector-query set without the boundary detecting the missing proof.

Correction:

- revalidate qualification identity and checkpoint against SQLite authority;
- require the exact raw and normalized full-text query-ID set;
- require contiguous ranks and the expected first passage for every full-text query;
- require the exact vector query-ID set and expected active prefix;
- require exact tombstone expectations and reject returned tombstoned passages; and
- add an adversarial adapter test that removes normalized evidence after an otherwise successful reconciliation.

### P2-7 — Startup integrity did not compare every normalized contract column

The pre-correction startup pass re-derived canonical bytes and checked selected identity columns, but several normalized SQLite columns were not compared with the retained typed contracts. Raw-SQL tampering could alter fields such as full-text source property, vector label, fixture revision, provider mode or complete-contract projector version while leaving canonical bytes unchanged.

Correction:

- compare every normalized full-text contract field and boolean;
- compare every normalized vector contract field, similarity, quantization, provider kind and fixture-only flag;
- compare fixture manifest identity and every fixture-document metadata column;
- compare every complete-contract, generation-binding and validation-binding column; and
- add trigger-preserving raw-SQL tamper/reopen tests proving store open fails for normalized contract, generation-binding and validation-binding changes.

### P2-8 — Deterministic core evidence exceeded the accepted lane budget

The exact PR head passed the ordinary full CI suite, but the SDLC deterministic core command exceeded the accepted 55-second lane deadline. The first hosted profile completed the full suite in 58.50 seconds. The overrun came from repeated deterministic setup rather than product or service failures: each route-classification test reparsed the complete repository dependency graph, watchdog tests waited near multi-second deadlines even after readiness was observable, and complete-projection tests repeatedly rebuilt identical SQLite and governed-object fixture authority.

Correction:

- cache the dependency graph only by an exact snapshot of every repository-owned Python source path and byte sequence;
- return isolated mapping copies and prove same-root byte changes invalidate the cache;
- shorten watchdog fixtures only after explicit process-readiness evidence while preserving shared-deadline, descendant-termination and unauthorized-background-process assertions;
- build one closed deterministic complete-fixture authority template per test process, then copy the SQLite database and governed-object CAS into each test's isolated `tmp_path`;
- retain independent startup integrity validation and per-test mutation after every clone; and
- keep the accepted 55-second deadline, complete deterministic suite and service-lane topology unchanged.

### P2-9 — Complete actual-service cases were not optional in the deterministic core manifest

The full deterministic core suite correctly skipped tests that require authenticated Neo4j, but the optional-test manifest still listed only the earlier Increment 1 service cases. All eight new complete Increment 2B actual-service cases therefore counted as required skips in the core JUnit summary even though the dedicated service lane executed them successfully.

Correction:

- add the exact eight complete-service testcase identities, including every parameterized drift case, to the core-only optional manifest;
- keep `test_complete_projection_2b_neo4j_service.py` mandatory in the service route;
- retain the service workflow proof that exactly eight complete cases execute without skip, failure or error; and
- add contract tests binding both the sorted 19-case core optional set and mandatory complete-service file selection.

The change does not suppress a product test or relax the actual-service gate. It distinguishes intentionally unavailable Neo4j cases in the deterministic lane from their required execution in the authenticated service lane.

## Local validation

The corrected implementation and substantive-review additions passed a bounded complete repository run:

```text
1,094 passed, 19 skipped, 0 failed
```

Hosted-runner profiling of the same full deterministic suite improved from 58.50 seconds before the correction to 52.62 seconds after exact-source dependency caching and readiness-observed watchdog fixtures, then to 50.77 seconds after closed-store complete-fixture cloning (`51.98` seconds wall time). The accepted 55-second lane, complete suite and service topology are unchanged; the exact final SDLC run remains the authoritative merge gate.

Additional local checks passed:

- targeted authority and normalized-query tests;
- `python -m compileall -q newsroom scripts`;
- `git diff --check`; and
- clustering evaluation with `--fail-on-regression`.

These results are local regression evidence. A local `uv lock --check` attempt was blocked by the configured internal package mirror returning HTTP 503 while fetching `pytest`; `pyproject.toml` and `uv.lock` are unchanged. The final exact GitHub head must rerun the complete lockfile and repository gates after this review record and traceability are committed.

## Residual merge gates

PR #164 must remain draft and unmerged until:

1. CI passes on the exact final head;
2. the authenticated actual-Neo4j workflow proves every required case without skip, failure or error;
3. SDLC route, core, service and decision jobs pass on that same head;
4. current-head review still has zero unresolved P1/P2 findings;
5. review submissions, requested changes, unresolved threads and actionable comments are zero; and
6. issue #156 records the exact final head and evidence.

Issue #157 remains blocked. This review authorises no Increment 2C implementation or runtime activation.
