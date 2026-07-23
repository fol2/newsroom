# SDLC-V2 substantive specification review

- Role: Dated review evidence
- Status: Completed
- Owner: fol2
- Canonical language: English
- Date: 2026-07-21
- Related issue: #98
- Related PR: #99
- Reviewed pre-correction head: `e573896d0e6ac2dd3cc883e55a52caa9ec8a24c7`
- Reviewed specification version: `sdlc-v2.1`
- Corrected specification version: `sdlc-v2.2`

## Scope

The review tested whether the Proposed SDLC is internally coherent and whether its fast path can preserve the repository's authority, actual-service and regression guarantees.

Review dimensions:

- gate and lane time semantics;
- current measurement claims;
- risk routing and projection-authority/service coupling;
- required-check skip behaviour;
- route/schema consistency;
- evidence identity and replay safety;
- pass/fail machine invariants;
- cache and secret boundaries;
- selective-regression false-negative controls;
- merge-group exactness;
- migration and rollback;
- risk of recreating a fat pipeline under new names.

## Result

- P1 findings: 0
- P2 findings: 6
- Remaining unresolved P1/P2 after corrections: 0
- Owner-policy decisions still required: 5

The absence of unresolved P1/P2 means the Proposed contract is coherent enough for owner review. It does not mean the owner has accepted it or that workflow replacement is authorised.

## Findings and corrections

### P2-1 — Full-suite performance claim exceeded evidence

Initial wording said the repository was small enough that the complete deterministic suite was already cheaper than selective regression. The exact baseline contained JUnit for six focused/actual-service selections, but the existing full-CI workflow did not emit JUnit, so exact full-suite p95 was not measured.

Correction:

- state only the measured 1.134–7.401 second component-selection range;
- retain full-suite-first as the conservative default;
- require telemetry Phase 1 to record exact full-suite p95 before claiming budget conformance;
- keep selective regression non-blocking until both performance need and quality evidence exist.

### P2-2 — Route example and JSON schema disagreed

The initial prose example used `schema` and `clustering`, omitted required booleans, tree SHAs and the selected-manifest digest, while `.sdlc/route.schema.json` used different fields.

Correction:

- make the prose example exactly match the schema;
- add `base_tree_sha` and `head_tree_sha`;
- make `core_required` always true;
- enforce `service_required == false` for `R0`–`R2` and true for `R3`–`R4`;
- require owner authority for `R4`.

### P2-3 — Evidence identity serialization was ambiguous

The initial digest expression looked like tuple/string concatenation and did not define canonical bytes. That can produce cross-implementation mismatch or ambiguous identities.

Correction:

- define one repository-owned canonical JSON object;
- hash UTF-8 RFC 8785-style canonical JSON bytes;
- include exact base/head tree, gate contract, classifier, lock, toolchain, service, selected-manifest and gate-input digests;
- require fixed canonicalisation test vectors;
- forbid delimiter-free concatenation.

### P2-4 — Evidence schema could not enforce required-test success

The prose said skipped required tests cannot pass, but the schema only had total `skip_count` and did not require all identity fields. A nominal `PASS` could not be rejected mechanically when a required test skipped.

Correction:

- add mandatory `required_skip_count`;
- add mandatory classifier version, base tree, gate-input digest, cache/service/sample/fingerprint fields, using null/empty values where not applicable;
- make schema validation reject `PASS` unless failures, errors and required skips are all zero;
- validate the schema with a positive example and a negative required-skip example.

### P2-5 — Projection-authority service escalation was inconsistent

The prose implied all authority persistence/migration changes required Neo4j, while the machine contract routed general authority as `R2` with no service. Either extreme is wrong: all authority changes would waste service capacity, while no projection-authority escalation could miss cross-boundary regressions.

Correction:

- keep general authority/persistence at `R2`;
- route current projection-authority integration modules, projection migrations and B1/B2/B3 projection tests to `R3`;
- allow import/contract dependency analysis to escalate other authority changes;
- fail closed on unknown dependency edges.

### P2-6 — Internal gate maxima could exceed the lane budget

The initial table gave individual command limits but did not explicitly prevent sequential commands in one lane from each consuming their maximum, which could violate the one-minute objective.

Correction:

- define a 55-second aggregate repository-owned execution deadline per interactive lane;
- cap every internal command by the lane's remaining time;
- reserve a separate five-second finalisation deadline;
- distinguish queue, bootstrap, gate, lane, finalisation and feedback clocks;
- require typed `BUDGET_EXCEEDED` on aggregate deadline breach.

## Machine validation performed

The following were validated from clean local scratch material before publication:

- `.sdlc/gates.toml` parses with Python `tomllib`;
- all gate hard command timeouts are below 60 seconds;
- aggregate interactive lane execution is 55 seconds;
- evidence and route files parse as JSON;
- route schema accepts a valid `R3` exact-tree route;
- evidence schema accepts a valid `PASS` record;
- evidence schema rejects `PASS` with `required_skip_count = 1`;
- exact baseline JUnit was reparsed from GitHub artifacts;
- p95 baseline values use nearest-rank over testcase durations;
- baseline artifact digests are retained.

Validated local content SHA-256 after corrections:

```text
.sdlc/gates.toml
c21c0c8fdd7d78724071fdcf79867f1c2c4223be7ab879df50551c0ac50e2693

.sdlc/evidence.schema.json
b796adc74dc1b1f46381dc6f0f4b5a720d3b6bd72ee0a8ec8ff4b5de8865d094

.sdlc/route.schema.json
dc399985ff754a6d00947bcf535467a99e1cc911007f2261c1a5d8277212a2fd

corrected specification source
4979d7347c59160367b98930486b963706280eb2e90d0d5c4b9bb031ce56ffc4
```

These are content checks, not Git object SHAs.

## Remaining owner decisions

1. Review trigger: accept 400 net executable lines / 12 changed files, or choose alternatives.
2. Selector safety: accept 30 calendar days / 500 representative changes before blocking use.
3. Runner: permit evaluation of an ephemeral prewarmed runner if measured hosted-runner feedback p95 cannot meet 60 seconds.
4. Main failure: automatically pause merges, or create an incident without automatic pause.
5. Evidence retention: choose PR, main and release retention periods.

## Recommendation

Accept the architecture with these defaults unless repository economics or owner risk appetite require tighter values:

```text
review trigger:       400 executable lines / 12 files
selector shadow:      30 days and 500 representative changes
prewarmed evaluation: permitted only after measured hosted-runner failure
main critical failure: automatic merge pause, owner may resume
retention:            PR 30 days, main 180 days, release 7 years
```

The long release retention is only a proposed record policy. No release workflow or production authority is created here.

## Boundary

No current workflow was replaced by this review. B3 product code remains preserved on Draft PR #97. Issue #96, Graphiti, models, embeddings, live sources, publication, shadow execution, canary, production activation, spending and public effects remain untouched.