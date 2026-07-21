# High-performance evidence SDLC

- Role: Normative target specification
- Status: Proposed — owner review required before implementation replaces existing gates
- Owner: fol2
- Canonical language: English
- Date: 2026-07-21
- Specification ID: `SDLC-V2`
- Related issue: #98
- Related active product work: #96 / PR #97

## 1. Decision summary

Newsroom will replace increment-by-increment CI accumulation with a single evidence-oriented SDLC.

Every machine gate is a bounded decision function over an exact change, environment and evidence contract. A gate must either produce a reproducible decision inside its budget or fail closed with a typed reason. It must not grow its timeout whenever the repository grows.

The normal pull-request path will have one always-reporting router and two possible parallel evidence lanes:

1. a core lane for deterministic repository checks and tests;
2. a service lane only when the exact change can affect Neo4j, authority persistence, migrations, credentials, workflow service setup or qualifying GraphRAG behaviour.

The current repository remains small enough that the full deterministic test suite is cheaper and safer than selective regression. Full deterministic tests therefore remain the blocking default until measured p95 execution exceeds the threshold defined below. Test-impact analysis will first run in shadow mode and may become blocking only after repository-specific evidence demonstrates that it preserves defect detection.

Deep mutation, fuzz, compatibility, flake, performance and recovery work will run as independent scientific shards outside the interactive path. Each shard still has a sub-60-second execution budget; the programme may contain many parallel shards without turning one gate into an unbounded monolith.

## 2. Goals

`SDLC-V2` must:

- preserve or improve regression, authority, security and production-profile confidence;
- give developers a correct blocking decision in less than 60 seconds of gate execution;
- target less than 60 seconds p95 from push to decision once runner queue and prewarming are measured and controlled;
- prevent obsolete commits from consuming runner capacity;
- eliminate repeated checkout, Python setup, uv installation, dependency sync and overlapping test execution;
- make gate cost, selection, cache use and evidence visible;
- keep changes small, reviewable, reversible and independently mergeable;
- use risk and dependency evidence rather than historical increment names to select checks;
- detect when optimisation has reduced defect-detection power;
- evolve through measured experiments rather than permanent accumulation.

## 3. Non-goals

This specification does not:

- weaken SQLite or governed-object authority;
- make Neo4j authoritative;
- permit graph-free qualifying production, evaluation or complete-live-shadow paths;
- authorise Graphiti, model, embedding, live-source, publication, shadow, canary or production execution;
- claim that GitHub-hosted runner queue latency is controllable before it is measured;
- require Bazel, Pants or another heavyweight build system while the repository does not need one;
- use machine learning test selection as an unmeasured blocking dependency;
- treat CI success as code-review approval;
- require human review to complete in 60 seconds. Human review latency is measured separately.

## 4. Terms

### 4.1 Gate

A gate is one typed machine decision with:

- exact inputs;
- exact risk scope;
- explicit evidence requirements;
- p50 and p95 targets;
- a hard execution timeout;
- one typed result.

A workflow containing several parallel gates is not itself one gate.

### 4.2 Lane

A lane is an execution environment shared by one or more closely related gates. A lane performs checkout and environment bootstrap once.

### 4.3 Execution latency

Time from the first repository-owned gate command to its decision. Runner provisioning and queueing are excluded and reported separately.

### 4.4 Feedback latency

Time from receiving the GitHub event to the required decision being visible.

### 4.5 Evidence identity

The content-addressed identity of a gate result:

```text
sha256(
  repository_tree_sha,
  base_tree_sha,
  gate_contract_version,
  risk_classifier_version,
  lockfile_digest,
  toolchain_digest,
  service_compatibility_digest,
  selected_test_manifest_digest,
  gate_inputs
)
```

### 4.6 Risk tier

A deterministic classification of the changed files and semantic surfaces that controls evidence escalation. Risk does not mean business priority.

## 5. Non-negotiable safety properties

1. A timeout is not success.
2. A skipped required test is not success.
3. A diagnostic rerun cannot overwrite the first required result.
4. Cache contents are never treated as authority without exact key and provenance validation.
5. A required workflow must always report a terminal result. Required checks must not rely on GitHub path filtering that can leave skipped checks pending.
6. Unknown files, unknown dependency edges or classifier errors escalate risk rather than reduce it.
7. Workflow, dependency, migration, authority, credential, cryptographic, deletion, production-profile and release changes cannot use the lowest risk tier.
8. Test-impact selection cannot become blocking until its false-negative controls have completed the shadow acceptance period.
9. Critical authority, security, deletion/non-resurrection and migration tests cannot be quarantined without explicit owner approval.
10. Exact merge-group evidence is required before merge once merge queue is enabled.
11. No gate may silently increase its timeout. A budget breach creates a typed optimisation defect.
12. A service fake or no-op can never satisfy an actual-service gate.
13. Evidence from a different tree, lock, toolchain or service compatibility target cannot be replayed as current evidence.
14. Product work must remain recoverable from pushed commits; meaningful implementation cannot exist only in an ephemeral environment.

## 6. Budget contract

All durations below are wall-clock execution durations after runner allocation.

| Gate | p50 target | p95 target | hard timeout | Blocking |
|---|---:|---:|---:|---|
| `route` | 1 s | 2 s | 5 s | yes |
| `source-integrity` | 3 s | 8 s | 15 s | yes |
| `core-deterministic` | 15 s | 35 s | 55 s | yes |
| `service-neo4j` | 25 s | 50 s | 55 s | risk-triggered |
| `merge-exact` | 20 s | 50 s | 55 s | yes after merge queue adoption |
| each `science-*` shard | 20 s | 50 s | 55 s | no for PR; policy-dependent for release |
| `evidence-finalize` | 1 s | 3 s | 5 s | yes |

Global targets:

- warm bootstrap p95: 10 seconds;
- cold bootstrap p95 during migration: 30 seconds;
- PR decision p50: 30 seconds from event receipt;
- PR decision p95 target: 60 seconds from event receipt;
- runner queue p95 target: 5 seconds;
- obsolete-head cancellation: less than 5 seconds after a newer head is observed.

The hosted-runner feedback target is an objective until measured. Compliance cannot be claimed from execution time alone. If hosted-runner queue plus bootstrap cannot meet the feedback target for ten working days, the implementation plan must evaluate a prewarmed ephemeral runner.

Every repository-owned gate command runs under an operating-system timeout no greater than 55 seconds. GitHub job timeout is one minute where supported. The five-second difference is reserved for evidence finalisation and clean termination.

A hard timeout produces:

```text
BUDGET_EXCEEDED:<gate_id>:<phase>
```

The change remains blocked. The response is to remove duplication, cache reproducible work, split the gate, improve the test, or move deep evidence to a bounded science shard. Increasing the budget requires an owner-approved specification amendment.

## 7. Risk model

### 7.1 `R0_DOCUMENTATION`

Typical changes:

- prose under `docs/`;
- comments with no generated or executable effect;
- issue templates or non-executable metadata.

Required evidence:

- source integrity;
- document metadata and link checks;
- workflow/spec consistency checks when SDLC documents change.

Any executable code, lockfile, workflow, schema, fixture or generated baseline change prevents `R0`.

### 7.2 `R1_LOCAL_CODE`

Typical changes:

- isolated pure functions;
- deterministic scripts with no persistence, credentials, external service or production-profile effect;
- tests only.

Required evidence:

- source integrity;
- full deterministic suite while it fits the budget;
- architecture/import sentinels;
- clustering gate when clustering code, dataset or baseline can be affected.

### 7.3 `R2_STATEFUL_CONTRACT`

Triggers include:

- `newsroom/authority/**`;
- SQLite access or transaction code;
- object admission, rights, hydration or deletion code;
- schemas, migrations, event types, idempotency or canonicalisation;
- public contract or policy changes;
- tests claiming authority or recovery evidence.

Required evidence adds:

- authority fault and tamper sentinels;
- migration and reopen tests;
- exact replay/idempotency tests;
- transaction rollback tests;
- full deterministic suite.

### 7.4 `R3_EXTERNAL_SERVICE_SECURITY`

Triggers include:

- Neo4j adapter, schema, qualification or service integration;
- authentication, credentials, secrets or permissions;
- dependency or lockfile changes;
- workflow or runner-image changes;
- network exposure;
- production/evaluation/complete-shadow configuration;
- graph rebuild, deletion/non-resurrection or service compatibility.

Required evidence adds the parallel actual-service lane and relevant security/configuration sentinels.

### 7.5 `R4_RELEASE_OPERATIONAL`

Triggers include:

- release, deployment or production activation configuration;
- target credentials;
- backup/restore or operational admission;
- canary, shadow or public-effect controls;
- irreversible migrations.

`R4` requires explicit owner authority and release evidence. It is not authorised by this specification.

### 7.6 Escalation rules

Risk is the maximum triggered tier. The router fails closed on:

- an unclassified path;
- an import/dependency graph cycle it cannot interpret;
- a missing base SHA;
- a changed classifier or gate contract;
- generated files without a declared generator;
- a changed test manifest without corresponding source provenance.

The router emits the exact reasons for its classification.

## 8. Evidence lanes

### 8.1 `G0` edit loop

Purpose: immediate developer feedback.

Target: p95 5 seconds.

Runs against changed files only:

- syntax/compile for changed Python modules;
- formatter/linter when adopted;
- import-boundary checks;
- nearest deterministic unit tests;
- generated-file consistency.

`G0` is advisory but should be the default editor/save command.

### 8.2 `G1` local commit gate

Purpose: prevent obviously invalid commits.

Target: p95 15 seconds.

Runs:

- lock consistency when dependency inputs changed;
- deterministic change classification;
- full small suite while under the threshold;
- relevant migration/schema checks;
- no untracked generated output.

Local hooks must remain bypassable for emergencies; server evidence remains authoritative.

### 8.3 `G2` pull-request core lane

Purpose: one correct, fast blocking decision for repository code.

Implementation shape:

1. always start;
2. cancel obsolete heads with a PR-specific concurrency group;
3. checkout exact head and sufficient base history;
4. install pinned Python and pinned uv once;
5. restore a lock/toolchain-keyed cache;
6. run `route`;
7. run source integrity and deterministic tests in the same environment;
8. emit one compact evidence bundle;
9. report one stable required decision name.

The core lane must not preserve historical increment workflows as separate required checks. Requirement IDs live in the test/evidence manifest, not in workflow count.

### 8.4 `G3` pull-request service lane

Purpose: real Neo4j evidence only when risk requires it.

Runs in parallel with `G2`, not after it.

Requirements:

- exact image and driver target;
- runtime-generated masked credentials;
- loopback-only network exposure;
- dedicated projector identity;
- authenticated readiness;
- exact service compatibility;
- relevant actual-service tests only;
- deterministic teardown;
- service evidence manifest.

The service lane does not rerun all pure authority/unit tests already proved by `G2`. Shared cross-boundary tests are selected once and attributed explicitly.

### 8.5 `G4` merge-group exact lane

Purpose: prove the exact prospective merge tree, including interactions with other queued changes.

Once merge queue is adopted, the router workflow also triggers on `merge_group`.

The merge lane:

- evaluates the merge-group tree, not the earlier PR head;
- reuses only evidence whose identity exactly matches unaffected actions;
- reruns the full deterministic suite while it fits the budget;
- runs the service lane when the combined change triggers `R3`;
- emits the only merge-required decision.

### 8.6 `G5` main post-merge certification

Purpose: catch repository-level interactions without delaying every edit.

Runs bounded shards such as:

- full deterministic suite from a clean environment;
- package/wheel smoke tests;
- migration matrix;
- actual-service rebuild/recovery;
- dependency and workflow integrity;
- clustering evaluation.

A critical main failure creates a revert/fix-forward incident and may pause merges. It never rewrites the earlier PR result.

### 8.7 `G6` scientific verification

Purpose: measure whether the fast path remains trustworthy.

Independent shards include:

- mutation testing by bounded target slice;
- deterministic fault injection;
- property-based and fuzz campaigns with fixed seeds plus rotated seeds;
- flake detection by repeated isolated execution;
- performance and memory budgets;
- test-impact shadow comparison;
- compatibility matrix slices;
- dependency/security scans.

Every shard stays below 60 seconds. Larger experiments consist of many content-addressed shards and may run nightly or on demand.

### 8.8 `G7` release/operational evidence

Not authorised in this increment. Future release gates must consume exact evidence from the same contract rather than invent a separate pipeline.

## 9. Required router design

The repository will have one required workflow that always reports. It must not use `paths` or `paths-ignore` to skip the required decision, because GitHub can leave a required skipped workflow pending.

The router computes:

- base and head tree SHAs;
- changed paths and change types;
- risk tier and reasons;
- required lanes;
- deterministic test manifest;
- service-test manifest;
- always-run sentinels;
- clustering requirement;
- evidence identity inputs.

The classifier is repository-owned, versioned and unit-tested. Third-party path-filter actions are unnecessary.

Suggested output schema:

```json
{
  "schema": "newsroom.sdlc.route.v1",
  "base_sha": "...",
  "head_sha": "...",
  "risk_tier": "R3_EXTERNAL_SERVICE_SECURITY",
  "reasons": ["neo4j_adapter_changed"],
  "core_tests": ["newsroom/tests/test_projection_b3_rebuild.py"],
  "service_tests": ["newsroom/tests/test_projection_b3_neo4j_service.py"],
  "sentinels": ["architecture", "authority_replay", "secret_boundary"],
  "clustering": false,
  "contract_version": "sdlc-v2.1"
}
```

## 10. Test strategy

### 10.1 Full-suite-first rule

The complete deterministic suite remains blocking when all are true:

- p95 test execution is at most 35 seconds;
- p95 warm bootstrap is at most 10 seconds;
- the gate remains below its 55-second execution limit;
- flake rate is below 0.1%;
- no test requires an unauthorised external effect.

This repository currently satisfies the test-execution part by a wide margin. Selective regression is therefore not yet justified as a blocking optimisation.

### 10.2 Test size contract

- `micro`: individual test target p95 below 100 ms;
- `small`: hermetic test or file p95 below 1 second;
- `service`: real local disposable service, individual test p95 below 5 seconds;
- `science`: bounded experiment shard below 55 seconds.

A test above its size budget must be split, redesigned, moved to an appropriate lane or granted a documented temporary exception.

### 10.3 Always-run sentinels

Regardless of impact selection, the core lane always runs compact sentinels for:

- authority authentication-before-lookup;
- command/event idempotency and rollback;
- migration open/reopen integrity;
- graph-writer import boundary;
- credential redaction/default-admin rejection;
- required-gap checkpoint blocking;
- deletion/non-resurrection once implemented;
- production/evaluation/complete-shadow graph requirement once implemented;
- workflow and gate-contract integrity.

The sentinel set has a target execution time below five seconds.

### 10.4 Test-impact analysis

Impact analysis has three phases:

1. `observe`: calculate selections but run the full suite;
2. `shadow`: run selected tests as the nominal path and compare with a full-suite holdback;
3. `blocking`: permit selected tests to replace the full suite only when acceptance criteria are met.

Inputs may include:

- static Python import graph;
- declared package and contract dependencies;
- source-to-test naming rules;
- coverage-derived source/test edges generated from trusted main;
- historical failure correlation;
- migration/schema/authority escalation rules.

Machine learning may rank tests but cannot remove deterministic mandatory edges or sentinels.

Blocking activation criteria:

- at least 30 calendar days of shadow evidence;
- at least 500 representative changes, or all available changes if fewer with owner review;
- zero known full-suite failures missed by selected tests;
- at least 99.5% mutation-kill recall relative to the full suite on sampled targets;
- deterministic 5% sentinel sample from otherwise unselected tests, seeded by head SHA;
- nightly complete suite;
- rollback to full-suite mode available by one contract change.

Impact selection automatically disables when:

- selection miss is observed;
- dependency graph coverage falls below 99%;
- classifier or coverage map is stale;
- an unclassified path changes;
- mutation recall falls below the threshold;
- the full suite again fits comfortably and selection complexity is not paying for itself.

### 10.5 Flake policy

A failing required test remains failed.

A diagnostic rerun may classify the failure but cannot turn the required result green. Evidence records both attempts.

Quarantine requires:

- an issue;
- an owner;
- a reason and failure fingerprint;
- an expiry not greater than seven days;
- continued execution in `science-flake`;
- no critical authority/security/migration/deletion test unless the owner explicitly approves.

Target flake rate: below 0.1% of test executions. Any gate with more than 0.5% flake rate over seven days is non-conformant.

## 11. Environment, cache and execution architecture

### 11.1 Immediate target

- Python version pinned by repository policy;
- uv version pinned exactly;
- official `astral-sh/setup-uv` action pinned by commit SHA;
- uv cache enabled and keyed by OS, architecture, Python, uv and `uv.lock` digest;
- no repeated `pip install --upgrade pip` or `pip install uv` in each historical workflow;
- one `uv sync --locked` per lane;
- `concurrency.cancel-in-progress: true` for obsolete PR heads;
- minimal token permissions;
- one compact evidence artifact, uploaded on failure and retained longer for merged/release evidence.

### 11.2 Toolchain image

If warm-cache bootstrap p95 exceeds ten seconds for ten working days, build a small digest-pinned toolchain image keyed by the lockfile and toolchain contract. Image synthesis happens when dependency inputs change; interactive gates consume the already-built immutable image.

### 11.3 Prewarmed ephemeral runner

If feedback p95 remains above 60 seconds because hosted-runner queue/provisioning exceeds the target, evaluate an ephemeral prewarmed runner with:

- one job per VM/container;
- clean workspace and secrets per job;
- toolchain image already present;
- bounded autoscaling;
- no persistent untrusted workspace;
- measured queue p95 below five seconds;
- documented cost and security controls.

### 11.4 Build-system graduation

Do not introduce Bazel/Pants solely to appear sophisticated.

Evaluate a hermetic build graph and remote action cache only when at least one is true:

- full deterministic gate cannot stay below 55 seconds after simpler optimisations;
- repository contains multiple independently versioned packages;
- generated artifacts or multi-language targets make dependency inference unreliable;
- remote cache hit-rate modelling predicts material lead-time reduction;
- local/CI environment drift becomes a recurring defect source.

Any adoption must prove a lower p95 and no reduction in reproducibility during a shadow period.

## 12. Evidence model

Each gate emits one JSON record and, where relevant, JUnit XML.

Mandatory fields:

```text
schema_version
gate_id
gate_contract_version
repository
base_sha
head_sha
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
selected_tests
sentinel_tests
random_sample_seed
random_sample_tests
test_count
failure_count
error_count
skip_count
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

Successful evidence is reusable only for an exact matching evidence identity and only where the current gate contract permits reuse. PR-origin caches are not trusted as privileged evidence.

## 13. Review and change-flow policy

Automation speed cannot compensate for oversized changes.

Default change target:

- one independently useful concept;
- no more than 400 net executable lines;
- no more than 12 changed files;
- related tests in the same change;
- no unrelated refactor mixed with behavioural change;
- branch lifetime target below one working day;
- draft PR opened after the first coherent pushed checkpoint.

These are review triggers, not blind rejection thresholds. Larger changes require a decomposition note explaining why a smaller sequence would be less safe.

The repository should use trunk-based, short-lived branches, feature flags or branch-by-abstraction where incomplete behaviour must be merged safely. Long-running branches and increment-named permanent CI workflows are not the target architecture.

## 14. Scientific control loop

### 14.1 Hypotheses

Each SDLC optimisation states a falsifiable hypothesis, for example:

```text
H1: Consolidating five cold workflows into one core lane and one conditional
service lane reduces PR decision p95 by at least 50% without increasing missed
regressions.
```

### 14.2 Primary performance measures

- event-to-decision p50/p95/p99;
- queue p50/p95;
- bootstrap p50/p95;
- gate execution p50/p95;
- compute minutes per merged change;
- cache hit rate;
- obsolete-run cancellation savings;
- review wait and review duration;
- commit-to-merge lead time.

### 14.3 Primary quality measures

- selection miss rate;
- mutation-kill recall relative to full suite;
- escaped defect rate;
- change fail rate;
- deployment rework rate;
- failed deployment recovery time;
- flake rate;
- revert/fix-forward frequency;
- authority/security incident count;
- false-positive gate rate.

### 14.4 Experimental method

- establish a baseline before replacing workflows;
- shadow new routing against the old full evidence for at least 30 changes;
- use paired exact-head comparisons where possible;
- retain a deterministic full-suite holdback sample;
- report confidence intervals, not only averages;
- separate queue, bootstrap and execution latency;
- document cache warm/cold state;
- stop or roll back an experiment if a quality guardrail regresses;
- review the model monthly and after every escaped defect.

### 14.5 Gate SLO error budget

A lane is non-conformant when any applies over a rolling seven-day window:

- p95 execution exceeds 55 seconds;
- more than 1% of executions hit `BUDGET_EXCEEDED`;
- flake rate exceeds 0.5%;
- evidence mismatch exceeds 0.1%;
- a known regression was missed by routing or selection.

A non-conformant gate cannot accept additional scope until its bottleneck is fixed or split.

## 15. Security and supply-chain rules

- GitHub Actions use minimal permissions.
- Third-party actions are commit-SHA pinned and reviewed.
- Dependency or lockfile changes trigger `R3`.
- Cache keys include the exact lock and toolchain identity.
- Privileged/default-branch caches are writeable only from trusted events.
- Secrets never enter cache paths, artifacts, exceptions or evidence JSON.
- Workflow changes run workflow-integrity sentinels and cannot self-approve release authority.
- Actual-service credentials are random, masked, disposable and loopback-bound.
- Scheduled dependency and workflow scans remain separate bounded science shards.

## 16. Failure, merge and rollback

### 16.1 Pull request

Any blocking gate failure blocks merge and emits a targeted reproducer.

### 16.2 Obsolete head

A newer PR head cancels the old run. Cancellation is neither pass nor fail and old evidence cannot satisfy the new head.

### 16.3 Merge group

The exact merge-group tree must pass. A changed merge-group SHA invalidates its earlier evidence.

### 16.4 Main failure

A critical main certification failure:

1. creates a typed incident;
2. identifies the first bad merge where possible;
3. opens or recommends the smallest revert/fix-forward;
4. may pause the merge queue;
5. does not mutate historical evidence.

### 16.5 SDLC rollback

Migration keeps the old workflows available but non-required during shadow. If the new decision workflow misses a known regression or becomes unavailable, restore the old required checks and full-suite mode by one reviewed configuration change.

## 17. Adoption sequence

`SDLC-V2` becomes Accepted only after owner review.

Implementation then proceeds in reversible phases:

1. telemetry and machine-readable budgets;
2. one router and core decision workflow in shadow;
3. cached pinned uv bootstrap;
4. conditional parallel Neo4j service lane;
5. old workflows become non-required, then are removed after paired evidence;
6. merge-group exact evidence;
7. test-impact analysis in observe and shadow modes;
8. scientific nightly shards;
9. optional prewarmed runner if measured feedback requires it.

B3 product work may resume after the specification is accepted and the minimum Phase 1/2 SDLC controls are available, unless the owner explicitly authorises an earlier transition.

## 18. Acceptance criteria

The owner may mark this specification Accepted when:

- the risk model covers every current repository surface;
- budgets, SLOs and timeout behaviour are explicit;
- current baseline evidence is attached;
- regression-selection false-negative controls are explicit;
- service/fake boundaries are preserved;
- migration and rollback are credible;
- required-check behaviour cannot deadlock on skipped workflows;
- security/cache boundaries are explicit;
- the implementation plan is reversible;
- remaining owner decisions are acknowledged.

## 19. Owner decisions requested

1. Accept the default PR size trigger of 400 net executable lines / 12 files, or choose different review triggers.
2. Accept a 30-day/500-change shadow requirement before selective regression may block.
3. Confirm whether a prewarmed ephemeral runner may be evaluated if hosted-runner p95 cannot meet 60 seconds.
4. Confirm whether critical main-certification failure should automatically pause merges or only create an incident.
5. Confirm evidence retention targets for PR, main and release records.

Until these decisions are made, the specification remains Proposed and current product state remains preserved on pushed branches.