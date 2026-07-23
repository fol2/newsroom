# SDLC v2 migration plan

- Role: Implementation and migration plan
- Status: Proposed — blocked on owner acceptance of `SDLC-V2`
- Owner: fol2
- Canonical language: English
- Date: 2026-07-21
- Related issue: #98
- Related specification: `docs/specs/sdlc/high-performance-evidence-sdlc.md`
- Active product work held at: issue #96 / PR #97

## 1. Outcome

Replace five independently bootstrapped, overlapping GitHub Actions workflows with a measured evidence pipeline that has:

- one always-reporting route/decision workflow;
- one cached core lane;
- one conditional parallel Neo4j service lane;
- exact merge-group evidence;
- content-addressed evidence manifests;
- bounded non-interactive scientific shards;
- no machine gate with an execution budget above 60 seconds.

The migration is reversible at every phase. Existing gates remain available in shadow until the replacement has paired evidence.

## 2. Starting state

Main:

```text
12d0c397e0c1f84eb878010b8e00a52a19069860
```

Active B3 branch/head when this plan was written:

```text
agent/increment-1b3-rebuild-promotion
74df38790fd17ba9163a6fbcd25a58a5a88d5395
```

Current required workflow families:

```text
CI
Authority A2a
Authority A2b
Projection B1
Projection B2/B3 Neo4j
```

All current workflows independently install the environment. Several run overlapping tests.

## 3. Workstream rules

1. Specification and SDLC implementation use a separate branch/PR from B3 product code.
2. B3 remains Draft and pushed; no uncommitted product implementation is carried across environments.
3. Every SDLC phase has an exact rollback commit.
4. Old workflows are not deleted until paired shadow evidence demonstrates the replacement.
5. No phase increases product authority or executes production effects.
6. A new workflow is not made required until it always reports on all relevant PR events.
7. Gate budgets are enforced by code, not prose alone.

## 4. Phase 0 — Baseline and contract

### Deliverables

- accepted `SDLC-V2` specification;
- dated evidence study;
- `.sdlc/gates.toml` machine contract;
- evidence JSON schema;
- exact baseline test-duration dataset;
- owner decisions recorded on issue #98.

### Verification

- TOML parses;
- durations and risk rules are internally consistent;
- every current repository path is classified or escalates to unknown/high risk;
- documentation review has no unresolved owner-level ambiguity.

### Rollback

Revert documentation and contract files. Existing workflows remain unchanged.

## 5. Phase 1 — Telemetry and budgets as code

### Deliverables

Repository-owned scripts:

```text
scripts/sdlc/classify_change.py
scripts/sdlc/run_gate.py
scripts/sdlc/emit_evidence.py
scripts/sdlc/validate_contract.py
```

Tests:

```text
newsroom/tests/test_sdlc_contract.py
newsroom/tests/test_sdlc_classifier.py
newsroom/tests/test_sdlc_evidence.py
newsroom/tests/test_sdlc_budget.py
```

The scripts must use only the standard library unless an accepted dependency is added explicitly.

### Behaviour

- classify an exact base/head diff;
- emit risk tier and reasons;
- select core/service/sentinel manifests;
- measure queue, bootstrap, execution and finalisation separately where available;
- run a command under a 55-second OS timeout;
- emit typed `BUDGET_EXCEEDED` rather than hanging;
- write deterministic evidence JSON;
- fail on unknown paths, malformed configuration or evidence mismatch.

### Interactive budget

The classifier plus contract validation must run in less than two seconds p95 on current repository size.

### Verification

- unit tests for every risk trigger;
- metamorphic tests: adding an unknown file never lowers risk;
- deterministic output for the same base/head/contract;
- secrets never appear in evidence or errors;
- a simulated timeout terminates child processes and returns the correct typed result.

### Rollback

Remove scripts/tests. No workflow has changed yet.

## 6. Phase 2 — Shadow decision workflow

### Deliverable

```text
.github/workflows/evidence.yml
```

Initially non-required and named clearly as shadow.

### Trigger

```yaml
on:
  pull_request:
  merge_group:
  workflow_dispatch:
```

A later main trigger is added after PR evidence is stable.

### Concurrency

PR heads use a stable PR-number group with `cancel-in-progress: true`. Merge groups use their own exact SHA group.

### Environment

- `actions/checkout` pinned to reviewed commit SHA;
- `actions/setup-python` pinned to reviewed commit SHA;
- official `astral-sh/setup-uv` pinned to reviewed commit SHA and exact uv version;
- uv cache enabled;
- one sync per lane;
- minimal permissions.

### Jobs

1. `route`
2. `core`
3. optional `neo4j`
4. `decision`

The stable `decision` job always runs and reports terminal status even when the Neo4j lane is not required.

### Core lane

During shadow, run:

- contract validation;
- compile/source integrity;
- full deterministic pytest suite;
- clustering gate when selected;
- compact JUnit/evidence output.

### Neo4j lane

Run only when the route result requires `R3` service evidence. During shadow, compare with the existing Projection B2/B3 workflow.

### Shadow comparison

For at least 30 representative PR heads:

- compare pass/fail result;
- compare test count;
- compare actual-service execution count;
- compare first failure fingerprint;
- compare execution/feedback latency;
- compare missing/skipped tests;
- record old/new compute minutes.

### Acceptance

- zero decision disagreement caused by missing evidence;
- zero unauthorised skip;
- p95 core execution below 55 seconds;
- p95 service execution below 55 seconds;
- stable decision always reports;
- obsolete runs cancel correctly;
- cache poisoning controls pass review.

### Rollback

Disable/delete the shadow workflow. Existing workflows remain required.

## 7. Phase 3 — Consolidate required evidence

### Changes

- make `evidence / decision` the stable required check;
- old workflows remain triggered but non-required for a short burn-in;
- remove duplicate artifact uploads from old workflows where safe;
- publish one compact evidence bundle per lane;
- retain exact-head references in PR summaries.

### Burn-in

Minimum:

- 20 merged changes;
- seven calendar days;
- zero missed regressions;
- no required-check pending deadlock;
- no budget violation above the specification error budget.

### Acceptance

- replacement decision matches old gates for all paired changes;
- PR decision p95 improves materially;
- compute minutes per merged change decrease;
- no quality guardrail regresses.

### Rollback

Restore old required checks by branch/ruleset configuration. New workflow remains available for diagnosis.

## 8. Phase 4 — Remove historical workflow duplication

Delete or convert to reusable/manual evidence:

```text
.github/workflows/authority-a2a.yml
.github/workflows/authority-a2b.yml
.github/workflows/projection-b1.yml
```

Replace `.github/workflows/ci.yml` and `.github/workflows/projection-b2-neo4j.yml` responsibilities with the consolidated evidence workflow.

Requirement traceability moves to:

- test metadata;
- route/evidence manifests;
- specification requirement IDs;
- PR evidence summary.

Historical workflow names are retained in Git history and documentation, not active runner topology.

### Acceptance

- one core bootstrap per PR head;
- at most one conditional service bootstrap;
- no duplicate full-suite execution on the same head;
- all former required properties mapped to current tests/sentinels;
- source-only workflow diff reviewed for permissions, cache and secret boundaries.

### Rollback

Revert workflow consolidation commit and restore required checks.

## 9. Phase 5 — Merge-group exact evidence

### Deliverables

- merge queue/ruleset configuration;
- `merge_group` trigger in the stable workflow;
- exact merge-group evidence identity;
- combined-change risk routing;
- evidence invalidation when merge-group SHA changes.

### Acceptance

- a PR cannot merge using evidence from its earlier head when the merge-group tree differs;
- combined changes trigger the maximum risk tier;
- service lane runs when either or the interaction requires it;
- exact merge decision remains within budget.

### Rollback

Disable merge queue and restore expected-head protected manual squash merge while keeping PR evidence.

## 10. Phase 6 — Test-impact analysis in observe mode

### Initial implementation

Build a conservative dependency map from:

- Python imports;
- declared package/contract ownership;
- source/test naming;
- trusted-main coverage edges;
- mandatory escalation rules.

The selector outputs a test manifest but the blocking core still runs the full suite.

### Data collected

- selected versus full test count;
- selected versus full duration;
- full failures not present in selection;
- mutation-kill recall;
- unknown dependency edges;
- random sentinel sample results.

### No blocking use

Observe mode cannot reduce required evidence.

### Rollback

Delete selector outputs. Core suite remains unchanged.

## 11. Phase 7 — Test-impact shadow mode

The nominal selected suite runs first; the full suite runs as a non-blocking paired holdback on trusted infrastructure.

Requirements before blocking activation:

- 30 calendar days;
- at least 500 representative changes where available;
- zero known failure misses;
- at least 99.5% mutation-kill recall;
- dependency graph coverage at least 99%;
- deterministic five-percent sample from unselected tests;
- nightly full suite;
- one-change rollback.

If the full deterministic suite p95 remains below 35 seconds, the owner may decide that selection complexity is not justified and keep full-suite mode indefinitely.

## 12. Phase 8 — Bounded scientific shards

Add independent workflows or dynamically generated shards, each under 55 seconds:

- `science-mutation-authority-*`;
- `science-mutation-projection-*`;
- `science-property-*`;
- `science-fuzz-*`;
- `science-flake-*`;
- `science-performance-*`;
- `science-compatibility-*`;
- `science-dependency-*`.

Rules:

- deterministic shard identity;
- fixed and rotating seeds recorded;
- no single unbounded job;
- failures create issues or release blockers according to policy;
- PR interactive lane remains unaffected unless a risk rule promotes a specific shard.

## 13. Phase 9 — Runner architecture decision

Collect at least ten working days of:

- GitHub queue p50/p95/p99;
- provisioning time;
- cache restore time;
- gate execution time.

If execution meets budget but event-to-decision p95 exceeds 60 seconds because queue/provisioning exceeds target, prepare a separate owner decision for an ephemeral prewarmed runner.

The decision must include:

- cost per month and per merged change;
- threat model;
- isolation and cleanup;
- autoscaling bounds;
- availability fallback;
- measured expected improvement;
- rollback to hosted runners.

No self-hosted runner is introduced speculatively.

## 14. Phase 10 — Resume product SDLC

After minimum accepted phases are merged:

1. restack B3 PR #97 if main advanced;
2. split remaining B3 work into small independently reviewable PRs where architecture allows;
3. route each change through `SDLC-V2` risk/evidence lanes;
4. keep meaningful implementation pushed at coherent checkpoints;
5. complete deletion/tombstone non-resurrection, validation reconciliation, qualifying configuration integration and final B3 evidence;
6. close #96 and #81 only after B3 is genuinely complete;
7. keep #82 blocked until #81 closes.

## 15. Metrics dashboard

The migration must expose, at minimum:

```text
PR event-to-decision p50/p95/p99
queue p50/p95
bootstrap p50/p95
core execution p50/p95
service execution p50/p95
compute minutes per merged change
cache hit rate
obsolete-run cancellation count/minutes
flake rate
false-positive rate
selection miss count
mutation recall
commit-to-merge lead time
review wait time
change fail rate
deployment rework rate
```

Until deployment exists, production metrics remain `not_applicable`, not zero.

## 16. Review checkpoints

Each phase needs:

- exact issue scope;
- small PR or explicit decomposition reason;
- current-head source-only review;
- permissions/secret/cache review for workflow changes;
- exact-head evidence;
- rollback instructions;
- updated measured baseline.

CI green remains regression evidence, not approval.

## 17. Owner decisions

Blocked decisions are tracked on issue #98:

- PR size review triggers;
- test-impact shadow duration/sample requirement;
- authority to evaluate prewarmed ephemeral runners;
- merge-pause behaviour after main certification failure;
- evidence retention by event type.

No later phase silently chooses these values.