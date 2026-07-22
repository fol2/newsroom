# High-performance evidence SDLC

- Role: Normative target specification
- Status: Proposed — owner review required before implementation replaces existing gates
- Owner: fol2
- Canonical language: English
- Date: 2026-07-21
- Specification ID: `SDLC-V2`
- Contract version: `sdlc-v2.2`
- Related issue: #98
- Related active product work: #96 / PR #97

## 1. Decision

Newsroom will replace increment-by-increment CI accumulation with an evidence-oriented SDLC.

A machine gate is a bounded decision over an exact change, environment and evidence contract. It either produces a reproducible typed decision inside its budget or fails closed. Its timeout does not grow whenever repository scope grows.

The normal pull-request path has one always-reporting decision workflow with two possible parallel lanes:

1. a core lane for routing, source integrity and deterministic repository tests;
2. a Neo4j service lane when the exact change affects the graph adapter, projection-authority integration, graph migrations, service compatibility, credentials, workflow service setup or qualifying GraphRAG behaviour.

The measured exact-head test selections are currently small: the recorded JUnit suites range from 1.134 to 7.401 seconds. The exact full-repository pytest p95 has not yet been recorded. Full deterministic tests remain the blocking default until measurement proves that their p95 no longer fits the core-lane budget. Test-impact analysis begins in observe mode and cannot replace full evidence until repository-specific shadow controls demonstrate that it preserves defect detection.

Deep mutation, fuzz, compatibility, flake, performance and recovery work runs as independent scientific shards outside the interactive path. Each shard has its own sub-60-second budget; a large experiment is many content-addressed shards, not one unbounded job.

## 2. Goals

`SDLC-V2` must:

- preserve or improve regression, authority, security, deletion and production-profile confidence;
- give developers a correct blocking machine decision within a 55-second repository-owned execution envelope;
- target less than 60 seconds p95 from GitHub event to decision once queue and provisioning are measured and controlled;
- prevent obsolete commits from consuming runner capacity;
- remove repeated checkout, Python setup, uv installation, dependency sync and overlapping tests;
- make gate cost, selection, cache use and evidence visible;
- keep changes small, reviewable, reversible and independently mergeable;
- route by current risk and dependency evidence rather than historical increment names;
- detect when optimisation reduces defect-detection power;
- improve through measured experiments rather than permanent accumulation.

## 3. Non-goals

This specification does not:

- weaken SQLite or governed-object authority;
- make Neo4j authoritative;
- permit graph-free qualifying production, evaluation or complete-live-shadow paths;
- authorise Graphiti, model, embedding, live-source, publication, shadow, canary or production execution;
- claim that GitHub-hosted queue latency is controllable before it is measured;
- require Bazel, Pants or another heavyweight build system while the repository does not need one;
- use machine-learning test selection as an unmeasured blocking dependency;
- treat CI success as code-review approval;
- require human review to complete in 60 seconds. Review latency is measured separately.

## 4. Terms and clocks

### 4.1 Gate

One typed machine decision with exact inputs, risk scope, evidence requirements, p50/p95 targets, a hard timeout and one result.

### 4.2 Lane

One execution environment shared by related gates. A lane performs checkout and environment bootstrap once.

### 4.3 Queue latency

Time from GitHub event receipt until a runner begins the job.

### 4.4 Bootstrap latency

Time from runner start until the repository-owned gate environment is ready.

### 4.5 Gate execution latency

Time spent by one repository-owned gate command. It excludes queue and runner provisioning.

### 4.6 Lane execution latency

Time from the first repository-owned command in a lane until all blocking commands in that lane finish. Internal gate budgets share this deadline; they cannot each consume their individual maximum sequentially.

### 4.7 Finalisation latency

Time to validate evidence, publish the stable decision and cleanly terminate after lane execution.

### 4.8 Feedback latency

Time from GitHub event receipt until the required decision is visible.

### 4.9 Evidence identity

Evidence identity is the SHA-256 digest of UTF-8 RFC 8785-style canonical JSON for this object:

```json
{
  "repository_tree_sha": "...",
  "base_tree_sha": "...",
  "gate_contract_version": "...",
  "risk_classifier_version": "...",
  "lockfile_digest": "sha256:...",
  "toolchain_digest": "sha256:...",
  "service_compatibility_digest": null,
  "selected_test_manifest_digest": "sha256:...",
  "gate_inputs_digest": "sha256:..."
}
```

Implementations must use one repository-owned canonicaliser and test it with fixed vectors. Delimiter-free string concatenation is forbidden.

### 4.10 Risk tier

A deterministic classification of changed paths and semantic surfaces that controls evidence escalation. Risk tier is not business priority.

## 5. Non-negotiable safety properties

1. A timeout is not success.
2. A skipped required test is not success.
3. A diagnostic rerun cannot overwrite the first required result.
4. Cache content is never authority without exact key and provenance validation.
5. The required workflow always reports a terminal result; it does not rely on path filtering that can leave skipped checks pending.
6. Unknown paths, unknown dependency edges and classifier errors escalate risk.
7. Workflow, dependency, projection migration, authority, credential, cryptographic, deletion, production-profile and release changes cannot use the lowest tier.
8. Test-impact selection cannot block until its false-negative controls complete the shadow acceptance period.
9. Critical authority, security, deletion/non-resurrection and migration tests cannot be quarantined without explicit owner approval.
10. Exact merge-group evidence is required once merge queue is enabled.
11. No gate silently increases its timeout. A budget breach is a typed optimisation defect.
12. A fake, no-op or in-memory service cannot satisfy an actual-service gate.
13. Evidence from another tree, lock, classifier, toolchain or compatibility target cannot satisfy the current decision.
14. Meaningful work is committed and pushed; an ephemeral environment is not a source of truth.
15. A faster path must preserve a one-change rollback to conservative full evidence.

## 6. Budget contract

All gate and lane durations below start after runner allocation.

| Gate | p50 | p95 | hard command timeout | Lane |
|---|---:|---:|---:|---|
| `route` | 1 s | 2 s | 5 s | core |
| `source-integrity` | 3 s | 8 s | 15 s | core |
| `core-deterministic` | 15 s | 35 s | 55 s | core |
| `service-neo4j` | 25 s | 50 s | 55 s | service |
| `merge-exact` | 20 s | 50 s | 55 s | merge group |
| each `science-*` shard | 20 s | 50 s | 55 s | science |
| `evidence-finalize` | 1 s | 3 s | 5 s | decision |

Aggregate execution rules:

- core-lane repository-owned execution hard deadline: 55 seconds;
- service-lane repository-owned execution hard deadline: 55 seconds;
- merge-lane repository-owned execution hard deadline: 55 seconds;
- finalisation hard deadline: 5 seconds;
- an internal command's timeout is capped by the lane's remaining deadline;
- a GitHub job may use a one-minute timeout where supported, but the repository-owned lane watchdog is authoritative and reserves finalisation time.

Global objectives:

- warm bootstrap p95: 10 seconds;
- cold bootstrap p95 during migration: 30 seconds;
- PR feedback p50: 30 seconds;
- PR feedback p95: 60 seconds;
- runner queue p95: 5 seconds;
- obsolete-head cancellation: 5 seconds after a newer head is observed.

The hosted-runner feedback SLO is an objective until queue and provisioning are measured. Compliance cannot be claimed from test time alone. If hosted-runner queue plus bootstrap prevents compliance for ten working days, the migration plan evaluates a prewarmed ephemeral runner.

A timeout produces:

```text
BUDGET_EXCEEDED:<gate_id>:<phase>
```

The change remains blocked. The response is to remove duplication, improve caching, split the gate, improve the test, or move deep evidence to bounded science shards. Raising a budget requires an owner-approved specification amendment.

## 7. Risk model

Risk is the maximum tier triggered by paths, imports, contracts and semantic ownership.

### 7.1 `R0_DOCUMENTATION`

Typical scope:

- prose under `docs/`;
- comments with no executable/generated effect;
- non-executable metadata.

Required evidence:

- source integrity;
- document metadata and link checks;
- spec/workflow consistency when SDLC documents change.

Executable code, workflow, lockfile, schema, fixture, machine contract or generated baseline prevents `R0`.

### 7.2 `R1_LOCAL_CODE`

Typical scope:

- isolated pure functions;
- deterministic scripts with no persistence, credential, service or qualifying-profile effect;
- ordinary tests.

Required evidence:

- source integrity;
- full deterministic suite while measured p95 fits;
- architecture/import sentinels;
- clustering gate when clustering sources, dataset or baseline can change.

### 7.3 `R2_STATEFUL_CONTRACT`

Triggers include:

- general `newsroom/authority/**` persistence and transactions;
- SQLite, object admission, rights, hydration or deletion code;
- schemas, migrations, event types, idempotency or canonicalisation;
- public contracts and policies;
- tests claiming authority or recovery evidence.

Required evidence adds:

- authority fault/tamper sentinels;
- migration and reopen tests;
- exact replay/idempotency tests;
- transaction rollback tests;
- full deterministic suite.

### 7.4 `R3_EXTERNAL_SERVICE_SECURITY`

Triggers include:

- Neo4j adapter, schema, qualification or compatibility;
- projection-authority integration, including projector delivery, rebuild, validation, promotion or projection migrations;
- authentication, credentials, secrets or permissions;
- dependency or lockfile changes;
- workflow, action, runner-image, cache or network changes;
- production/evaluation/complete-shadow configuration;
- graph deletion/non-resurrection or service recovery.

Required evidence adds the parallel actual-service lane and relevant security/configuration sentinels.

General authority changes stay `R2` unless dependency analysis reaches the projection-authority integration. The classifier has explicit `R3` paths for current integration modules and tests; unknown edges escalate rather than assuming isolation.

### 7.5 `R4_RELEASE_OPERATIONAL`

Triggers include:

- release, deployment or production activation configuration;
- target credentials;
- backup/restore or operational admission;
- canary, shadow or public-effect controls;
- irreversible migrations.

`R4` requires explicit owner authority and release evidence. It is not authorised here.

### 7.6 Fail-closed escalation

The router fails closed on:

- an unclassified path;
- an import/dependency cycle it cannot interpret;
- missing base/head commit or tree identity;
- a changed classifier, gate contract or test manifest without provenance;
- generated files without a declared generator;
- stale coverage/dependency maps;
- route/schema mismatch.

It emits exact reasons for the selected tier.

## 8. Evidence lanes

### 8.1 `G0` edit loop

Purpose: immediate advisory feedback, p95 target 5 seconds.

Runs changed-module compile, adopted formatting/linting, import-boundary checks, nearest deterministic unit tests and generated-file consistency.

### 8.2 `G1` local commit gate

Purpose: prevent obviously invalid commits, p95 target 15 seconds.

Runs deterministic classification, relevant lock/schema/migration checks, the small hermetic suite that fits and a clean-tree/generated-output check. Local hooks remain bypassable; server evidence remains authoritative.

### 8.3 `G2` pull-request core lane

Purpose: one fast blocking repository decision.

Shape:

1. always start;
2. cancel obsolete heads with a PR-specific concurrency group;
3. checkout exact head and sufficient base history;
4. install pinned Python and pinned uv once;
5. restore an exact lock/toolchain-keyed cache;
6. run `route`;
7. run source integrity and deterministic tests in the same environment under one lane deadline;
8. emit one compact evidence bundle;
9. report one stable required decision name.

Historical increment names do not remain separate required workflows. Requirement IDs live in test/evidence manifests.

### 8.4 `G3` pull-request Neo4j lane

Purpose: actual Neo4j evidence only when risk requires it. It runs in parallel with `G2`.

Requirements:

- exact image and driver;
- runtime-generated masked credentials;
- loopback-only exposure;
- dedicated projector identity;
- authenticated readiness;
- exact compatibility;
- relevant actual-service tests only;
- deterministic teardown;
- service evidence manifest.

It does not rerun pure tests already proved by `G2`. Shared cross-boundary tests are selected once and attributed explicitly.

### 8.5 `G4` merge-group exact lane

Once merge queue is adopted, the required workflow also triggers on `merge_group`.

It:

- evaluates the prospective merge tree, not the earlier PR head;
- reuses only exact matching action evidence;
- reruns full deterministic evidence while it fits;
- runs service evidence when the combined change is `R3` or higher;
- emits the only merge-required decision.

### 8.6 `G5` main certification

Purpose: catch repository interactions without delaying every edit.

It runs bounded shards for clean full deterministic evidence, package smoke, migration matrices, actual-service recovery, dependency/workflow integrity and clustering. If a full category exceeds 55 seconds, it is partitioned into deterministic content-addressed shards; no shard exceeds the budget.

A critical failure creates a revert/fix-forward incident and follows the owner-selected merge-pause policy. It never rewrites PR evidence.

### 8.7 `G6` scientific verification

Independent sub-55-second shards include:

- mutation testing by target slice;
- deterministic fault injection;
- property/fuzz campaigns with fixed and rotating recorded seeds;
- isolated repeat runs for flake detection;
- performance and memory budgets;
- test-impact shadow comparison;
- compatibility matrix slices;
- dependency/security scans.

### 8.8 `G7` release/operational evidence

Not authorised in this increment. Future release gates consume the same exact evidence model rather than inventing another pipeline.

## 9. Required router

The repository has one required workflow that always starts and always reports a terminal decision. It does not use `paths` or `paths-ignore` to skip the required workflow. Conditional lanes may skip only when the route evidence says they are not required; the final decision validates that condition.

The router computes:

- base/head commit and tree SHAs;
- changed paths/types;
- risk tier and reasons;
- required lanes;
- deterministic and service test manifests;
- always-run sentinels;
- clustering requirement;
- evidence-identity inputs.

It is repository-owned, versioned and unit-tested.

Canonical output shape:

```json
{
  "schema_version": "newsroom.sdlc.route.v1",
  "contract_version": "sdlc-v2.2",
  "base_sha": "0000000000000000000000000000000000000000",
  "head_sha": "1111111111111111111111111111111111111111",
  "base_tree_sha": "2222222222222222222222222222222222222222",
  "head_tree_sha": "3333333333333333333333333333333333333333",
  "risk_tier": "R3_EXTERNAL_SERVICE_SECURITY",
  "reasons": ["projection_authority_integration_changed"],
  "core_required": true,
  "service_required": true,
  "clustering_required": false,
  "owner_authority_required": false,
  "core_tests": ["newsroom/tests/test_projection_b3_rebuild.py"],
  "service_tests": ["newsroom/tests/test_projection_b3_neo4j_service.py"],
  "sentinels": ["authority_replay", "secret_boundary"],
  "selected_test_manifest_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

`.sdlc/route.schema.json` is authoritative for serialization.

## 10. Test strategy

### 10.1 Full-suite-first

The complete deterministic suite remains blocking while all are true:

- measured p95 test execution is at most 35 seconds;
- measured warm bootstrap p95 is at most 10 seconds;
- lane execution remains below 55 seconds;
- flake rate is below 0.1%;
- no test requires an unauthorised external effect.

Current component selections are well below the test threshold, but the exact full-suite p95 must be added during telemetry Phase 1 before conformance is claimed. Selective regression is not justified as a blocking optimisation before that measurement and shadow evidence.

### 10.2 Test sizes

- `micro`: individual p95 below 100 ms;
- `small`: hermetic test/file p95 below 1 second;
- `service`: disposable actual-service individual p95 below 5 seconds;
- `science`: shard below 55 seconds.

A target above its size budget is split, redesigned, moved to the correct lane or granted a documented temporary exception.

### 10.3 Always-run sentinels

The core lane always runs compact sentinels for:

- authentication before lookup;
- command/event idempotency and rollback;
- migration open/reopen integrity;
- graph-writer import boundaries;
- credential redaction/default-admin rejection;
- required-gap checkpoint blocking;
- deletion/non-resurrection once implemented;
- qualifying-profile graph requirements once implemented;
- workflow/gate-contract integrity.

Sentinel p95 target: 5 seconds.

### 10.4 Test-impact analysis

Modes:

1. `observe`: calculate selections and run full suite;
2. `shadow`: selected suite is measured and compared with a full-suite holdback;
3. `blocking`: selected suite may replace full evidence only after acceptance.

Inputs may include static imports, declared contract ownership, source/test naming, trusted-main coverage edges, historical failure correlation and mandatory migration/authority escalation.

Machine learning may rank tests but cannot remove deterministic edges or sentinels.

Blocking acceptance:

- at least 30 calendar days;
- at least 500 representative changes, or all available changes with owner review;
- zero known full-suite failures missed;
- at least 99.5% mutation-kill recall relative to full suite on sampled targets;
- deterministic 5% holdback sample from otherwise unselected tests, seeded by head SHA;
- nightly full suite;
- one-contract rollback to full-suite mode.

Selection automatically disables on a miss, dependency coverage below 99%, stale maps, unclassified paths, mutation recall below threshold, or when its complexity no longer pays for itself.

### 10.5 Flake policy

A failing required test remains failed. A diagnostic rerun may classify the failure but cannot turn the required result green.

Quarantine requires an issue, owner, fingerprint, reason, expiry no greater than seven days and continued `science-flake` execution. Critical authority/security/migration/deletion tests require owner approval.

Target flake rate: below 0.1%. A gate above 0.5% over seven days is non-conformant.

## 11. Environment, cache and runner architecture

### 11.1 Immediate target

- repository-pinned Python;
- exact uv version;
- official `astral-sh/setup-uv` pinned by commit SHA;
- uv cache keyed by OS, architecture, Python, uv, lock and toolchain contract;
- no repeated pip upgrade/uv install in historical workflows;
- one `uv sync --locked` per lane;
- `concurrency.cancel-in-progress: true` for obsolete PR heads;
- minimal token permissions;
- one compact evidence artifact per lane.

### 11.2 Toolchain image

If warm-cache bootstrap p95 exceeds ten seconds for ten working days, evaluate a digest-pinned toolchain image produced only when dependency/toolchain inputs change.

### 11.3 Prewarmed ephemeral runner

If execution conforms but feedback p95 remains above 60 seconds because queue/provisioning exceeds target, evaluate an ephemeral prewarmed runner with one job per VM/container, clean secrets/workspace, bounded autoscaling, no persistent untrusted workspace, measured queue p95 below five seconds and documented cost/security controls.

### 11.4 Build-system graduation

Do not adopt Bazel/Pants for appearance. Evaluate a hermetic action graph/remote cache only when simpler optimisation cannot keep the deterministic lane below 55 seconds, the repository becomes multi-package/multi-language, generated dependency inference is unreliable, remote-cache modelling predicts material improvement, or environment drift becomes recurring.

Any adoption must prove lower p95 and no reproducibility loss in shadow.

## 12. Evidence model

Each gate emits one JSON record and, when relevant, JUnit XML. `.sdlc/evidence.schema.json` is authoritative.

Mandatory fields include:

```text
schema_version
gate_id
gate_contract_version
risk_classifier_version
repository
base_sha
head_sha
base_tree_sha
tree_sha
risk_tier
risk_reasons
runner_kind
queue_ms
bootstrap_ms
execution_ms
finalize_ms
cache_key
cache_hit
python_version
uv_version
lockfile_digest
toolchain_digest
service_compatibility_digest
selected_test_manifest_digest
gate_inputs_digest
selected_tests
sentinel_tests
random_sample_seed
random_sample_tests
test_count
failure_count
error_count
skip_count
required_skip_count
first_failure_fingerprint
result
result_reason
created_at
```

Allowed results:

```text
PASS
FAIL
BUDGET_EXCEEDED
CLASSIFIER_ERROR
ENVIRONMENT_ERROR
EVIDENCE_MISMATCH
UNAUTHORISED_EFFECT
```

`PASS` requires `failure_count == 0`, `error_count == 0` and `required_skip_count == 0`.

Successful evidence is reusable only for an exact evidence identity and where the current contract permits reuse. PR-origin caches cannot write privileged/default-branch cache namespaces.

## 13. Review and change flow

Automation speed cannot compensate for oversized changes.

Default review triggers:

- one independently useful concept;
- 400 net executable lines;
- 12 changed files;
- related tests in the same change;
- no unrelated refactor mixed with behaviour;
- branch-lifetime target below one working day;
- Draft PR after the first coherent pushed checkpoint.

These are triggers, not blind rejection. A larger change needs a decomposition note explaining why a smaller sequence is less safe.

Use trunk-based short-lived branches and branch-by-abstraction or disabled feature seams for incomplete behaviour. Long-running branches and increment-named permanent CI workflows are not the target.

## 14. Scientific control loop

Each optimisation states a falsifiable hypothesis, for example:

```text
H1: one cached core lane plus one conditional service lane reduces PR decision
p95 by at least 50% without increasing missed regressions.
```

Performance measures:

- event-to-decision p50/p95/p99;
- queue, bootstrap, execution and finalisation p50/p95;
- compute minutes per merged change;
- cache hit rate;
- obsolete-run savings;
- review wait/duration;
- commit-to-merge lead time.

Quality measures:

- selection miss rate;
- mutation-kill recall;
- escaped defects;
- change fail and deployment rework rates;
- failed-deployment recovery time;
- flake and false-positive rates;
- revert/fix-forward frequency;
- authority/security incident count.

Method:

- establish baseline before replacement;
- shadow new routing against old evidence for at least 30 changes;
- use paired exact-head comparisons;
- retain deterministic full-suite holdbacks;
- report confidence intervals, not only averages;
- separate queue/bootstrap/execution;
- record warm/cold cache state;
- stop/rollback on quality regression;
- review monthly and after every escaped defect.

A lane is non-conformant over seven days when p95 execution exceeds 55 seconds, more than 1% hit `BUDGET_EXCEEDED`, flake exceeds 0.5%, evidence mismatch exceeds 0.1%, or routing/selection misses a known regression. It accepts no additional scope until fixed or split.

## 15. Security and supply chain

- minimal GitHub token permissions;
- third-party actions pinned by reviewed commit SHA;
- dependency/lock changes trigger `R3`;
- cache keys include exact lock/toolchain identity;
- privileged cache writes only from trusted events;
- no secrets in caches, artifacts, exceptions or evidence;
- workflow changes cannot self-approve release authority;
- actual-service credentials are random, masked, disposable and loopback-bound;
- dependency/workflow scans are bounded science shards.

## 16. Failure, merge and rollback

- Any blocking failure blocks merge and emits a targeted reproducer.
- A newer PR head cancels the old run; old evidence cannot satisfy the new head.
- A changed merge-group SHA invalidates prior merge-group evidence.
- A critical main failure creates a typed incident, locates the first bad merge where possible, and opens/recommends the smallest revert or fix-forward. Merge pausing follows the owner decision.
- Historical evidence is immutable.
- During migration, old workflows remain available in shadow. A miss or new-workflow outage restores old required checks/full-suite mode by one reviewed change.

## 17. Adoption sequence

`SDLC-V2` becomes Accepted only after owner review.

Reversible phases:

1. telemetry and machine-readable budgets;
2. one router/core decision workflow in shadow;
3. cached pinned uv bootstrap;
4. conditional parallel Neo4j lane;
5. old workflows become non-required, then are removed after paired evidence;
6. merge-group exact evidence;
7. test-impact observe/shadow;
8. bounded scientific shards;
9. optional prewarmed runner if measured feedback requires it.

B3 product work may resume after acceptance and minimum Phase 1/2 controls, unless the owner explicitly authorises another transition.

## 18. Acceptance criteria

The owner may accept this specification when:

- the risk model covers every current surface;
- budgets, aggregate lane deadlines and timeout behaviour are explicit;
- baseline evidence and limitations are attached;
- route and evidence schemas match the normative examples;
- false-negative controls are explicit;
- actual-service/fake boundaries are preserved;
- required-check skip behaviour cannot deadlock merges;
- cache/security boundaries are explicit;
- migration and rollback are credible;
- remaining owner decisions are acknowledged.

## 19. Owner decisions requested

1. Accept the 400 net executable lines / 12 files review triggers, or choose alternatives.
2. Accept the 30-day/500-change shadow requirement before selective regression may block.
3. Permit evaluation of a prewarmed ephemeral runner if hosted-runner feedback p95 cannot meet 60 seconds.
4. Choose whether a critical main-certification failure automatically pauses merges or creates an incident without an automatic pause.
5. Choose evidence retention for PR, main and release records.

Until these decisions are made, the specification remains Proposed and current product state remains preserved on pushed branches.
