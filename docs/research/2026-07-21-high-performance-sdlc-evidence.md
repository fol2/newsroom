# High-performance SDLC evidence study

- Role: Dated research and current-state evidence
- Status: Completed
- Owner: fol2
- Canonical language: English
- Date: 2026-07-21
- Related specification: `docs/specs/sdlc/high-performance-evidence-sdlc.md`
- Related issue: #98

## Research question

How should Newsroom preserve strong regression, authority, security and actual-service evidence while keeping every machine gate below one minute and avoiding an ever-growing CI critical path?

## Current repository evidence

The baseline is B3 exact head:

```text
74df38790fd17ba9163a6fbcd25a58a5a88d5395
```

It passed:

```text
Authority A2a          29874638866
Authority A2b          29874638887
Projection B1          29874638839
Projection B2/B3       29874638830
Full CI + clustering   29874638841
```

### Current workflow topology

Five workflows run on both every `push` and every `pull_request`:

| Workflow | File | Repeated bootstrap | Test scope |
|---|---|---|---|
| CI | `.github/workflows/ci.yml` | checkout, setup-python, pip upgrade, pip install uv, lock, sync | complete pytest plus clustering |
| Authority A2a | `.github/workflows/authority-a2a.yml` | same | A2a tests |
| Authority A2b | `.github/workflows/authority-a2b.yml` | same | focused A2b, earlier authority regression, fault matrix |
| Projection B1 | `.github/workflows/projection-b1.yml` | same | B1 tests |
| Projection B2/B3 Neo4j | `.github/workflows/projection-b2-neo4j.yml` | same plus service startup | B1, B2 and B3 tests against actual service |

The workflows preserve historical increment names rather than representing the current dependency/risk graph. The same checkout, Python setup, uv installation, dependency sync and tests are repeated.

### Exact JUnit measurements

The following figures were parsed from the successful exact-head artifacts. `suite time` is the JUnit suite duration and includes pytest collection/setup/reporting according to the generated report.

| Evidence | Tests | Suite time | Longest test | p95 test |
|---|---:|---:|---:|---:|
| A2a | 29 | 1.134 s | 0.147 s | 0.043 s |
| A2b focused | 86 | 6.988 s | 0.675 s | 0.171 s |
| A2b prior-authority regression | 79 | 1.572 s | 0.277 s | 0.039 s |
| A2b fault matrix | 31 | 2.127 s | 0.175 s | 0.115 s |
| Projection B1 | 35 | 1.809 s | 0.084 s | 0.082 s |
| Projection B2/B3 actual-service selection | 94 | 7.401 s | 2.258 s | 0.346 s |

Artifact provenance:

```text
A2a artifact                 8512497562
A2b focused artifact         8512499396
A2b regression artifact      8512500313
A2b fault artifact           8512501422
Projection B1 artifact       8512497737
Projection B2/B3 artifact    8512509061
```

### Diagnosis

The test code is not currently too slow. Even the largest measured selection is about seven seconds. The dominant structural waste is:

- five cold runner allocations;
- repeated action downloads;
- repeated checkout;
- repeated Python setup;
- repeated `pip install --upgrade pip`;
- repeated `pip install uv`;
- repeated `uv lock --check`;
- repeated `uv sync --dev --locked`;
- overlapping test scopes;
- multiple artifact uploads;
- obsolete heads continuing unless manually superseded.

The immediate optimisation should therefore consolidate evidence and cache/bootstrap once. Introducing probabilistic test selection before fixing duplicated orchestration would increase complexity without addressing the primary bottleneck.

## Primary-source findings

### GitHub Actions concurrency

GitHub documents workflow/job concurrency and `cancel-in-progress: true`, which can cancel obsolete work in the same concurrency group. This directly supports one PR-head-specific group rather than allowing old commits to consume capacity.

Source:

- <https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency>
- <https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency>

### Required checks and path filtering

GitHub documents that a workflow skipped by branch/path filtering can remain `Pending`; a pull request requiring that check can then be blocked. Therefore the required decision must always start and route internally. Conditional jobs may be skipped, but the stable final decision must report.

Source:

- <https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushpull_requestpull_request_targetpathspaths-ignore>

### Dependency caching

GitHub's dependency-cache model uses exact keys followed by controlled prefix fallback, with branch-scoped restrictions and explicit cache-poisoning considerations. Caches can reduce repeated environment work, but credentials must never be stored in cache paths and privileged cache writes must remain on trusted events.

Source:

- <https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching>

### uv integration

Astral recommends the official `astral-sh/setup-uv` action, exact version pinning, cache persistence and using GitHub's cached Python setup. This removes repeated pip upgrades and uv installation. Astral also documents cache pruning and non-ephemeral runner considerations.

Source:

- <https://docs.astral.sh/uv/guides/integration/github/>
- <https://docs.astral.sh/uv/guides/integration/pre-commit/>

### Small changes

Google's engineering practices argue that small changes are reviewed faster and more thoroughly, are less likely to introduce bugs, are easier to merge and roll back, and reduce wasted work. This supports treating change size and branch lifetime as SDLC controls, not trying to compensate for large PRs with more CI.

Source:

- <https://google.github.io/eng-practices/review/developer/small-cls.html>

### Software-delivery measures

DORA now describes five software-delivery metrics grouped as throughput and instability:

- change lead time;
- deployment frequency;
- failed deployment recovery time;
- change fail rate;
- deployment rework rate.

DORA also recommends small batches and an iterative improvement loop. Newsroom should measure gate latency as a leading indicator while retaining escaped-defect and rework measures as quality outcomes.

Source:

- <https://dora.dev/guides/dora-metrics/>
- <https://dora.dev/insights/dora-metrics-history/>
- <https://dora.dev/capabilities/continuous-delivery/>

### Regression-test selection

Microsoft Research reports a lightweight data-driven test-selection model evaluated across 22 large repositories. It reported 15–30% compute savings while identifying more than approximately 99% of buggy pull requests. This demonstrates that selection can be useful at scale, but it also demonstrates that it is not perfect. Newsroom must validate its own selector through shadow full-suite comparisons, mutation recall and deterministic sentinels before selection can block.

Source:

- <https://www.microsoft.com/en-us/research/publication/data-driven-test-selection-at-scale/>

### Test duration evidence

pytest exposes per-test and slowest-test durations and records JUnit durations. These are sufficient for the first telemetry phase without a new test framework.

Source:

- <https://docs.pytest.org/en/stable/how-to/output.html>
- <https://docs.pytest.org/en/stable/reference/reference.html>

### Remote caching and execution

Bazel documents content-addressed action caches and remote execution for reproducible declared actions. These are valuable patterns: explicit inputs, action hashes, content-addressed outputs and shared reproducible results. The current repository does not yet justify Bazel's adoption cost. The evidence identity in `SDLC-V2` adopts the useful pattern without prematurely replacing the Python toolchain.

Source:

- <https://bazel.build/remote/caching>
- <https://bazel.build/versions/8.1.0/remote/rbe>

## Options considered

### A. Keep one workflow per increment

Rejected.

Benefits:

- historical traceability is visually obvious;
- each increment can own a check name.

Costs:

- duplicated bootstrap and overlapping tests;
- workflow count grows with project history;
- requirement names become infrastructure topology;
- obsolete workflows become difficult to remove;
- every new boundary increases PR feedback cost.

Traceability belongs in test/evidence manifests and requirement IDs, not in permanent cold runner count.

### B. Run one full monolithic workflow on every change

Partially accepted for the core deterministic suite, rejected for unconditional service work.

The current complete deterministic suite is cheap enough to run every time in one environment. Actual Neo4j setup should still be conditional on deterministic risk classification, because docs-only or unrelated pure-code changes do not need a service container.

### C. Use GitHub path-filtered required workflows

Rejected.

GitHub warns that path-skipped workflows can remain pending when required. A single always-reporting router avoids merge deadlocks and provides explicit skip evidence.

### D. Adopt selective regression immediately

Rejected for the blocking path.

The measured test suites are too fast to justify new false-negative risk. Impact analysis should be implemented only in observe/shadow mode until full-suite execution approaches the budget.

### E. Adopt Bazel/Pants immediately

Rejected.

The repository is a single Python project with a fast suite. A heavyweight build graph would add migration, maintenance and developer-learning cost before remote caching is needed. `SDLC-V2` defines graduation criteria so this decision can change when evidence changes.

### F. Use a cached single core lane plus conditional service lane

Selected.

This addresses the measured bottleneck directly while preserving actual-service credibility.

### G. Rerun flaky failures to green

Rejected.

A rerun can diagnose non-determinism but must not erase the first failure. Otherwise CI reliability appears better while evidence quality worsens.

### H. Raise timeouts as the suite grows

Rejected.

The one-minute limit is an architecture constraint. Work must be cached, split, selected safely or moved to bounded science shards.

## Feasibility assessment

The current evidence strongly supports a sub-60-second gate architecture:

- core test selections are single-digit seconds;
- individual actual-service tests stay below roughly 2.3 seconds;
- the actual-service selection totals about 7.4 seconds;
- the dependency set is small and mostly pure Python;
- the present waste is repeated setup rather than irreducible computation.

The unknown is GitHub-hosted runner queue/provisioning p95. The implementation must measure it separately. If hosted runners cannot meet the end-to-end feedback target, a prewarmed ephemeral runner is a measured infrastructure decision rather than a speculative first step.

## Scientific quality-control model

Optimisation is accepted only when both speed and defect-detection guardrails hold.

Performance outcomes:

- event-to-decision latency;
- queue, bootstrap and execution latency;
- compute minutes per merged change;
- cache hit rate;
- obsolete-run cancellation savings.

Quality outcomes:

- full-suite/selector disagreement;
- mutation-kill recall;
- escaped defects;
- change fail and deployment rework rates;
- flake and false-positive rates;
- authority/security/deletion incidents.

Every optimisation begins with a baseline, runs in shadow where feasible, and has a one-change rollback.

## Conclusion

A faster Newsroom SDLC does not require less testing today. It requires fewer duplicated environments, one risk-aware decision topology, evidence reuse with exact provenance, obsolete-head cancellation, compact changes, and deep verification outside the interactive critical path.

The recommended sequence is:

1. budgets and telemetry as code;
2. one always-reporting router;
3. one cached core lane;
4. one conditional parallel Neo4j lane;
5. paired shadow evidence before deleting historical workflows;
6. merge-group exact evidence;
7. test-impact analysis only after the full suite approaches the budget;
8. bounded scientific shards and continuous calibration.