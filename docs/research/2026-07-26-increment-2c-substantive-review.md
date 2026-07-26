# Increment 2C substantive implementation review

- Role: Dated current-head review evidence
- Status: Completed for the corrected local source tree; exact-head GitHub evidence still required
- Owner: Product owner
- Canonical language: English
- Date: 2026-07-26
- Related issue: #157
- Parent epic: #142
- Authorised base: `main@cc9053e80a0198af33ed862df118dbdac625f58f`
- Corrected review boundary: the commit containing this record; record the exact remote SHA after checked materialisation

## Scope

The review covers only Increment 2C: the fixed named tool, four bounded retrieval branches, deterministic fusion, authoritative hydration, SQLite-retained Retrieval Context v2, explicit failure outcomes, actual-Neo4j evidence, operations, traceability and rollback.

It excludes Increment 2D Candidate admission, Graphiti, external models or embeddings, live sources/search, generalized retrieval, shadow, canary, production activation, publication, spending and public effect.

## Result

- P1 findings: 2
- P2 findings: 19
- Remaining unresolved P1/P2 after correction: 0

Review submissions, requested changes, inline threads and actionable PR comments must be rechecked against the exact final remote head before merge.

## Findings and corrections

### P1-1 — Retrieval initially opened a second SQLite authority writer

The first authority composition attempted to keep a governed-object writer open beside a retrieval writer over the same SQLite database. That violated the repository single-writer authority lock and could not provide one atomic projection/hydration/context boundary.

Correction:

- one `_HybridRetrievalAuthorityStore` now owns retrieval, governed-object hydration and access-decision writes;
- object access decisions and Retrieval Context linkage are committed through the same authority writer;
- no lock bypass, parallel writer or shadow authority was introduced; and
- focused success, replay, rights, lifecycle and tamper tests exercise the single-writer composition.

### P1-2 — Authentication could expire while Neo4j work was in flight

The initial boundary authenticated and authorised before replay lookup or graph access, but a slow branch, hydration sequence or persistence wait could outlive the authentication context. A result or classified graph failure could then be retained after the credential-derived authority had expired.

Correction:

- recheck authentication currency and the exact allowed authorization before constructing the final context;
- repeat the same security-provenance check inside the SQLite write transaction before complete or failure authority is retained;
- recheck current security before any idempotent replay is returned;
- refuse to persist a classified Neo4j failure after authentication expiry; and
- add adversarial tests that expire authentication during successful branch execution and during graph failure, proving no attempt or context is created.

### P2-1 — The exact branch lacked explicit prior-revision authority

The initial typed fixture contract identified the prior Candidate and hypothesis but did not retain the exact prior source-revision identity needed by the exact branch.

Correction:

- add and validate `prior_revision_id` against the repository-owned fixture;
- bind the exact query to that revision under the generation-derived document label;
- require `GOVERNED_REVISION` evidence and the exact prior revision at the authority boundary; and
- reject unknown passage, revision or dependency-root rows.

### P2-2 — Public composition exposed replaceable policy and retrieval contracts

The public opener accepted optional policy and fixture-contract objects. A caller with composition access could indirectly alter server-owned limits even though the request itself exposed no limit or query surface.

Correction:

- the public opener now always fixes `HYBRID_FIXTURE_POLICY_V1` and `INTEGRATED_FIXTURE_V2_RETRIEVAL`;
- injection remains available only on the private test composition seam; and
- the public-surface contract test rejects policy, retrieval-contract, limit, generation, label, predicate, driver and Cypher parameters.

### P2-3 — Date-window and projection-freshness contracts were implicit

The initial checkpoint retained query-valid and serving times but did not encode the accepted date window or a maximum age for the projection validation. An old but watermark-current generation could therefore continue serving indefinitely.

Correction:

- fix a 31-day date window and one-hour validation freshness limit in the policy digest;
- bind root observation times and the exact fixture query-valid time;
- retain validation time, date-window start and freshness deadline in every context;
- reject non-contract query-valid times before graph lookup;
- enforce freshness before reads, before context authority commit and on replay; and
- add temporal-exclusion and expired-replay tests.

### P2-4 — Neo4j reads initially had no transaction timeout

The adapter measured total elapsed time and rejected an over-budget result after completion, but a hung Neo4j transaction was not itself bounded by the five-second contract.

Correction:

- wrap every branch callback with a Neo4j managed-transaction `unit_of_work` timeout;
- attach fixed non-sensitive tool/branch metadata;
- preserve the post-execution monotonic check as defence in depth; and
- add unit evidence that all four branches receive a server-owned timeout.

### P2-5 — Permanent actual-service and SDLC evidence did not include 2C

The implementation had unit and authority tests but no permanent authenticated Neo4j proof or SDLC service classification for the named retrieval path.

Correction:

- add three required actual-service cases for complete four-branch/hydration/replay success, missing full-text index, and missing admitted relation;
- set a dedicated retrieval-service-required flag in both permanent workflows and the fixed SDLC service environment;
- prove exact test identities execute without skip, failure or error;
- retain previous actual-service artifact aliases; and
- classify the exact three cases optional only in the no-service deterministic core lane.

### P2-6 — Each branch could consume a fresh five-second timeout

The first managed-transaction correction assigned the full five-second timeout to every sequential branch. Four slow branches could therefore consume close to twenty seconds before the post-execution total-time check rejected the result. That did not enforce the accepted five-second tool budget at the execution boundary.

Correction:

- derive one monotonic deadline for the complete named-tool call;
- calculate each branch transaction timeout from the remaining shared budget;
- refuse to start a later branch when no budget remains;
- reject a branch immediately if it returns after the shared deadline; and
- add deterministic tests proving timeout values decrease and later branches never start after exhaustion.

### P2-7 — Branch score domains were not independently bound

The adapter rejected non-finite and negative scores, but typed evidence did not bind the exact branch-specific domains. A substituted adapter could return an exact or direct graph score below one, or a vector score above one, while still constructing typed records for the authority layer.

Correction:

- require exact-identity scores to equal one;
- require the fixture's direct admitted-relation score to equal one and adapter graph scores to match path depth;
- require vector scores to remain within `[0, 1]` and full-text scores to be finite and non-negative;
- recheck the fixture score contract at the SQLite authority boundary; and
- add adapter, model and substituted-adapter adversarial tests.

### P2-8 — Hydrated lifecycle metadata recorded admission state as blob state

The initial context builder populated `lifecycle_state` from the object admission state. Admission authority and blob lifecycle authority are separate retained contracts, even when both happen to be `ACTIVE` in the fixture. The context could therefore mislabel its current lifecycle provenance and startup validation repeated the same category error.

Correction:

- populate hydration `lifecycle_state` from the exact access-decision `blob_state`;
- continue to require the distinct admission state to be `ACTIVE`;
- compare the retained lifecycle value with both the current blob lifecycle during context commit and the immutable access-decision cutoff during startup validation; and
- add evidence that every hydrated passage lifecycle equals its retained governed-object blob state.

### P2-9 — Actual-service evidence covered full-text loss but not vector-index loss

The first permanent service package proved complete retrieval, full-text-index loss and admitted-relation loss. The vector branch is equally mandatory, but deleting its generation index had no dedicated Increment 2C retrieval outcome proof.

Correction:

- add a fourth authenticated Neo4j case that deletes the generation vector index;
- require the named tool to return explicit `UNAVAILABLE` with no context rather than `no prior match`;
- include the exact test identity in the permanent workflow proof and the SDLC core-only optional manifest; and
- update the workflow contracts so omission or skip of the vector-loss case fails closed.

### P2-10 — The retrieval adapter imported Neo4j outside the single driver seam

The first transaction-timeout implementation imported `unit_of_work` directly inside `_retrieval_adapter.py`. Although that module is private, the retained projection boundary deliberately permits the official Neo4j package to be imported by only one driver-isolation module. The complete repository boundary test correctly rejected the second import location.

Correction:

- expose a private `_neo4j_unit_of_work_factory` from the existing `_adapter.py` driver seam;
- obtain the managed-transaction decorator through that seam without exposing it publicly;
- retain dependency injection for unit tests; and
- rerun the repository import-boundary tests proving `_adapter.py` remains the sole production importer of the official Neo4j package.

### P2-11 — Fixture dependency roots could overlap or change identity

The first typed fixture validated coverage of active passages but did not require the exact contract ID/version, canonical process identity, root inventory, unique passage ownership or unique dependency ownership. Duplicate keys in the derived lookup maps could silently select the last root and make fusion or hydration depend on tuple order rather than checked authority.

Correction:

- require the exact retrieval contract identity, version, canonical process and query-valid time;
- require the exact four fixture roots and exactly one non-excluded prior-Candidate root;
- reject passage or dependency identifiers that occur under more than one root;
- retain exact active-passage coverage and temporal eligibility; and
- add dataclass-substitution tests for process, passage and dependency ambiguity.

### P2-12 — Authority-clock rollback could make retained evidence appear current

Projection freshness and authentication are time-bound. The initial checks rejected future serving time and expiry but did not explicitly reject a clock value earlier than query-valid, validation or retained serving time. A rolled-back authority clock could therefore replay old evidence as apparently current.

Correction:

- reject serving time earlier than query-valid time or projection validation;
- reject commit/replay time earlier than the retained serving, query-valid or validation time;
- classify rollback as explicit stale source authority rather than `no prior match`; and
- add a restart/replay test proving clock rollback causes `STALE` without a graph lookup.

### P2-13 — Bounded subprocess evidence raced interpreter readiness

The complete repository shard exposed nondeterministic SDLC evidence failures. The process-group watchdog fixtures launched additional Python interpreters under short deadlines, and the JSON timeout fixture allowed only half a second for interpreter startup before expecting emitted output. Under runner load, a child could be terminated before writing PID, readiness or output evidence even though the production timeout and process-group behaviour had not regressed.

Correction:

- use the POSIX-only watchdog boundary to create descendants with `os.fork()` instead of launching a second Python interpreter;
- use fixed `/bin/true` and `/bin/sh` commands for the shared-deadline probe;
- run remaining Python fixtures with isolated, no-site, unbuffered startup;
- write explicit child-readiness and child-PID evidence before either process enters its long wait;
- retain the same shared deadline, timeout result, process-group termination, child SIGTERM, output truncation and unauthorized-background-process assertions; and
- repeat the corrected cases under their complete repository shard without failure.

### P2-14 — A typed adapter could omit the mandatory fixture neighbourhood

The authority boundary required all four branch identities and the prior Candidate, but it did not require branch evidence to cover every checked fixture dependency root. A substituted typed adapter could omit the self-query or distractor neighbourhood and still construct a superficially complete context, weakening the negative evidence required by issue #157.

Correction:

- require the union of dependency roots observed across all four executions to equal the exact checked four-root fixture inventory;
- keep self-query, jurisdiction and formal-ID distractors as explicit exclusions rather than optional search results;
- expand the deterministic memory adapter to retain all mandatory roots with branch provenance; and
- add an authority test proving omitted neighbourhood evidence becomes `INCOMPLETE` and creates no context.

### P2-15 — Typed branch timing evidence could exceed the shared deadline

The actual adapter enforced one monotonic five-second deadline, but the typed branch and context records accepted four individually bounded elapsed values whose sum exceeded the tool budget. A substituted adapter could therefore retain timing provenance inconsistent with the execution contract.

Correction:

- require the sum of all four branch elapsed values to remain within the fixed policy timeout at the fixture authority boundary;
- repeat the same fixed five-second invariant in `RetrievalContextV2`; and
- add contract tests proving both the fixture validator and typed context reject over-budget timing evidence.

### P2-16 — Retrieval serving trusted constructor-time driver compatibility only

The private retrieval adapter pinned the Python driver version when constructed, but it did not re-identify the live Neo4j server before executing the named read. A reused, redirected or upgraded endpoint could therefore execute the fixed queries under compatibility assumptions retained for a different qualified target.

Correction:

- execute one authenticated, fixed and parameter-free component-identification read before the four retrieval branches;
- place that compatibility read inside the same monotonic five-second deadline and managed-transaction timeout boundary;
- require exactly Neo4j `2026.06.0` Community before any branch query executes;
- classify missing, malformed or non-qualified live-server evidence as explicit `UNAVAILABLE` with no Retrieval Context; and
- add adapter and authority tests proving branch queries never start and no context is created against a non-qualified service.

### P2-17 — Canonical score syntax confused significant digits with decimal places

The typed score serializer correctly used Python's `.17g` form to preserve an exact finite binary64 round trip, but its validation regex allowed at most seventeen digits after the decimal point. A valid Neo4j `2026.06` full-text score of `0.03687901422381401` serializes canonically as `0.036879014223814011`: seventeen significant digits require eighteen fractional digits at that magnitude. The adapter therefore classified successful full-text reads as a retrieval-contract mismatch before the vector branch could execute.

Correction:

- retain `.17g` as the single deterministic binary64 serializer;
- allow the complete fixed-notation shape it can emit, up to twenty fractional digits for exponent `-4`;
- keep exact parse-and-reserialize equality as the canonical-text boundary, so padded or alternate spellings remain rejected;
- add a regression using the exact live Neo4j score and a negative alternate-spelling case; and
- rerun authenticated success and missing-vector-index cases so the former reaches complete authority and the latter reaches its intended explicit unavailability boundary.

### P2-18 — Retrieval re-derived a graph key without the fixture binding

The live admitted relation carried the authoritative `newsroom-governed-relation-key-v1` identity, which includes the immutable fixture binding ID. The retrieval fixture validator and memory adapter independently re-derived an older endpoint-only digest. Unit evidence passed because both duplicated the same incomplete formula, while authenticated Neo4j correctly returned the admitted assertion key and the nominal context failed closed.

Correction:

- add one shared typed `governed_relation_key` primitive in the relation contract layer;
- include the exact repository-owned `integrated_fixture_v2` binding identity in the retrieval contract and its digest;
- make relation admission, retrieval validation and memory evidence call the same primitive;
- reject a retrieval contract rebound to any other fixture binding;
- retain an exact regression for the live admitted relation key; and
- remove temporary reason-code and branch-recording diagnostics; and
- rerun the nominal and missing-relation actual-Neo4j cases so only the deliberate relation deletion produces contract incompleteness.

### P2-19 — Deterministic core evidence exhausted the accepted shared lane margin

The exact P2-18 source passed full CI and all authenticated Neo4j cases, and the SDLC route, core and service commands themselves passed. The signed decision nevertheless failed closed because source integrity plus the complete deterministic test command consumed the shared `55`-second core lane budget. Hosted profiling showed the complete `1,170`-test deterministic suite at `54.94` seconds, then `54.25` seconds after bytecode precompilation. Repeated full-tree AST parsing and deliberately long timeout fixtures left insufficient evidence margin under normal runner variance.

Correction:

- retain the accepted `55`-second shared lane budget and the complete deterministic suite;
- precompile the exact checked-out repository source after locked sync and exact Python validation but before the lane clock starts;
- keep the in-lane source-integrity compilation authoritative and independent of bootstrap bytecode;
- parse production imports once per exact immutable path-and-byte snapshot, so any source change invalidates the test-only cache;
- shorten watchdog and subprocess fixture waits only after explicit readiness/output evidence while preserving shared-deadline, process-group termination, child `SIGTERM`, output truncation and unauthorized-background-process assertions; and
- bind the bootstrap precompile command and exact-source cache invalidation into repository tests.

The correction changes no product runtime, accepted gate, optional-test classification or evidence topology.

## Validation performed

The corrected focused retrieval, service-contract and SDLC selection passed locally:

```text
155 passed, 4 intentional no-service skips, 0 failed
```

The P2-17 binary64 score correction then passed the exact affected retrieval, authority, traceability and SDLC selection:

```text
116 passed, 4 intentional no-service skips, 0 failed
```

The P2-18 shared governed-relation key correction passed the exact affected relation, complete-projection, retrieval, authority, migration and traceability selection:

```text
122 passed, 4 intentional no-service skips, 0 failed
```

The P2-19 deterministic-evidence correction passed the exact affected boundary, watchdog, subprocess and workflow-contract selection:

```text
46 passed, 0 skipped, 0 failed
```

The complete repository passed in eight deterministic file-list shards:

```text
shard 1: 198 passed,  0 skipped
shard 2: 149 passed,  4 skipped
shard 3: 143 passed,  0 skipped
shard 4: 116 passed,  0 skipped
shard 5: 106 passed,  0 skipped
shard 6: 235 passed, 14 skipped
shard 7: 130 passed,  1 skipped
shard 8:  95 passed,  4 skipped
----------------------------------
total:   1,172 passed, 23 skipped, 0 failed
```

Additional checks passed at the review boundary:

- `python -m compileall -q newsroom scripts`;
- `git diff --check`;
- the projection import-boundary regression; and
- clustering evaluation with `--fail-on-regression`.

The four retrieval service tests intentionally skip without `NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED=1`; the exact remote authenticated-service run remains mandatory. Earlier unsharded local pytest processes were stopped by the execution wrapper without an observed failure; the post-P2-18 run reached 60 percent. The complete result above therefore comes from deterministic file-list shards. Hosted profiling of the exact P2-18 tree measured `54.94` seconds for the complete deterministic suite and `54.25` seconds after bootstrap bytecode precompilation, confirming that product correctness was green while shared-lane evidence margin was insufficient. `uv lock --check` passed, while a local `uv sync --dev --locked` attempt was blocked by the configured internal package mirror returning HTTP 503; `pyproject.toml` and `uv.lock` are unchanged. The exact corrected remote head must provide the authoritative locked-sync, actual-Neo4j and signed SDLC evidence.

## Residual merge gates

The focused Increment 2C pull request linked to issue #157 must remain unmerged until:

1. the complete corrected tree is checked-materialised to the authorised branch;
2. full CI and lockfile sync pass on that exact head;
3. all four 2C actual-Neo4j cases execute without skip, failure or error;
4. SDLC route, core, service and signed decision pass on the same head;
5. current-head review still reports zero unresolved P1/P2 findings;
6. requested changes, unresolved review threads and actionable comments are zero; and
7. issue #157 records the exact head, tree, workflow runs, evidence and deferred work.

Issue #158 remains blocked. This review authorises no Increment 2D or runtime activation.
