# SDLC decision metadata-propagation correction

**Status:** Corrective review unit  
**Issue:** #212  
**Infrastructure parent:** #98  
**Discovered by:** Increment 3B / #206 / PR #211  
**Authorised base:** `main@86afbf878f6b138ae0c99386d42828b32f12b645`

## Incident

The signed SDLC decision collector evaluated Increment 3B head `477bdf2cde259790551c420141782d34c0fcb36f`. CI, Authority A2a, Authority A2b, Projection B1 and authenticated Neo4j passed. The SDLC route and core jobs also passed, and the core artifact retained 1,338 tests with zero failures, errors or required skips.

The decision job began approximately three seconds after the core job completed. Its one immediate GitHub run/jobs/artifact snapshot returned `EVIDENCE_MISMATCH:decision:lane-verification`. A later verification of the exact same run ID, run attempt, artifact ID and digest, evaluated commit, tree and producer/consumer contexts passed without changing evidence bytes. The failure was therefore a GitHub Actions metadata-propagation race, not invalid lane evidence.

A later diagnostic after a job rerun correctly failed an attempt-1 fetch with `GitHubTransportError:run_attempt`, because GitHub then reported a later current attempt. This is an expected anti-replay boundary and is not relaxed by the correction.

## Corrective design

`collect_decision_inputs` now performs one bounded operation for each required lane:

1. remove any failed local transport directory;
2. fetch the exact run-attempt and exact named artifact;
3. validate transport metadata and archive safety;
4. verify job telemetry, artifact receipt, route, gate evidence and exact commit/tree provenance;
5. accept only a fully verified `ShadowLaneRecord`; or
6. retry the same exact operation within a strict four-attempt, 0.75-second delay bound.

No vote, partial acceptance, weakened digest, alternate attempt, alternate artifact, alternate source or fallback evidence is permitted. Exhaustion retains the existing typed `EVIDENCE_MISMATCH`. A controlled `ShadowLaneError` code is appended to `lane-verification` only when it satisfies the existing safe-code grammar; arbitrary provider or secret text remains redacted.

## Evidence

The clean implementation was committed as:

```text
d9790543c11bfb5c94b0e581cc55321617f22378
fix(sdlc): retry exact lane verification after metadata propagation
```

Before that commit was pushed, the isolated materializer completed:

- Python compilation and `git diff --check`;
- `newsroom/tests/test_sdlc_workflow_orchestrator.py`;
- the complete repository test suite; and
- the clustering regression gate.

New deterministic cases prove:

- transient lane-verification recovery;
- transient GitHub transport-snapshot recovery;
- removal of failed local bundles before retry;
- no extra fetch after successful verification;
- exact retry-attempt and delay bounds;
- typed exhaustion with controlled subcode; and
- fallback redaction for unsafe error text.

The final connector-authored head must still pass CI, Authority A2a, Authority A2b, Projection B1, authenticated Neo4j and the signed SDLC route/core/service/decision workflow before merge.

## Authority and rollback

This correction changes no evidence schema, route schema, risk classification, gate command, accepted timeout, source authority, product state, credential scope, publication authority, production activation or public effect. The existing exact run-attempt equality and all cryptographic/provenance checks remain mandatory on every retry.

Rollback is a normal code revert. Any rollback restores one-shot collection and therefore restores the observed false-negative risk; it does not alter retained evidence or product authority.