# Increment 5A zero-call and zero-spend schema hardening

**Issue:** #250  
**Pull request:** #255  
**Effective production-qualification schema:** `sha256:3e2ac38b2c17d11b8ea29afe58bd0cdf6924146969600cad2b89fc82ec8607b9`  
**Admission-source manifest:** `sha256:70ab68bef6a9654d59164b70340a4c33bcab56d965b27789159fb49155ef87c8`  
**Admission-source bundle:** `sha256:9a8282231c2665f1e8f5467e7bbd9e16896b6e82704a8be9a17b66949cf11333`  
**Exact owner-body digest:** `sha256:8e00ded4cec0a95a59b3507b5fb28eba8033f96c2dccb531d4075bdcbe976f87`

The effective production-qualification v2 JSON Schema makes both external-call
and provider-spend boundaries independently enforceable by every
standards-compliant schema consumer:

- `budgets.max_external_calls_per_request` is exactly `{"const":0}`;
- `budgets.max_gross_cost_microunits_per_request` is exactly `{"const":0}`;
- `rights.protected_content_allowed` is exactly `{"const":false}`.

The canonical schema artifact and source-defined schema are byte- and
digest-bound. Standalone `Draft202012Validator` regressions accept the exact
zero/false manifest and reject external calls, spend or protected-content
enablement. The Python profile validator independently enforces the same
proposal-bound values.

The historical proposal schemas remain immutable proposal evidence only. All
unqualified production and fixture-replay schema exports resolve to hardened
v2. Owner approval does not rewrite the proposal or either historical digest.

The exact owner statement additionally binds the reviewed admission-source
manifest and bundle. Future owner/main record materialisation updates only the
canonical data anchor and record files; it cannot rebaseline the executable
schema, parent gate or isolated child.

No owner approval record or post-merge admission is created by this hardening.
No model or vector is loaded, no external request is made, no provider
credential or spend is used, and no live-source, shadow, canary, publication or
production activation occurs.
