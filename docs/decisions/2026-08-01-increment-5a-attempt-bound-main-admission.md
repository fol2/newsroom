# Increment 5A attempt-bound post-merge implementation admission

**Issue:** #250
**Pull request:** #255
**Owner-record effect:** `PRODUCTION_EQUIVALENT_QUALIFICATION_ONLY`
**Main-admission effect:** `IMPLEMENTATION_OF_ISSUES_251_254_ONLY`
**Approval schema:** `sha256:cc87d78551d3e2f2ae61c0bd5e247288c291feced7b63165d55e2e8b05dcc56e`
**Main-admission schema:** `sha256:4247835d3c200a1012dbc45ec1a7ee609acce44205e3868a1cb5d6e69d7d0d65`
**Owner-body digest:** `sha256:665e146d420088a1a88e4946741bae187cd950e6e0eb733e103f2fcfda1fe37b`

The canonical owner record now authorizes production-equivalent qualification
only. `DOWNSTREAM_IMPLEMENTATION` is an immutable non-effect of that record.

Implementation authority is created only by the separately pinned post-merge
main-qualification record. CI, Authority A2a, Authority A2b, Projection B1
and Projection B2/B3/C1 Neo4j each require one truthful `push` attempt on
`refs/heads/main`; SDLC Evidence Shadow requires one truthful
`workflow_dispatch` attempt. Every attempt retains immutable workflow
ID/name, run ID and attempt, repository ID, head commit/tree, workflow
SHA/ref, successful conclusion, exact API/HTML URLs and canonical timestamps.
All attempts must be distinct and bind the same declared merged-main
commit/tree.

The signed SDLC evidence is embedded as its exact canonical decision document.
The loader first validates it through
`scripts.sdlc.shadow_decision.validate_shadow_decision` under the
repository SDLC contract, then recomputes its document digest and requires
`result=PASS`,
`result_reason=PASS:decision`, no first failure, matching exact-main context and
event, the same SDLC run/attempt, zero failures/errors/required skips, matching
test/skip totals and only PASS gate decisions. The record summary cannot differ
from the embedded canonical artifact.

A failed, unrelated, pull-request, wrong-tree, reused-attempt, noncanonical,
summary-tampered or non-PASS record therefore cannot grant downstream
implementation authority.

No shadow, canary, production activation, publication, public effect,
live-source execution, external embedding API call, provider spending or
protected-content vector is authorized.
