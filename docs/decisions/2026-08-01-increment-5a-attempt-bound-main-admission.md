# Increment 5A attempt-bound post-merge implementation admission

**Issue:** #250
**Pull request:** #255
**Owner-record effect:** `PRODUCTION_EQUIVALENT_QUALIFICATION_ONLY`
**Main-admission effect:** `IMPLEMENTATION_OF_ISSUES_251_254_ONLY`
**Approval schema:** `sha256:cc87d78551d3e2f2ae61c0bd5e247288c291feced7b63165d55e2e8b05dcc56e`
**Main-admission schema:** `sha256:4247835d3c200a1012dbc45ec1a7ee609acce44205e3868a1cb5d6e69d7d0d65`
**Owner-body digest:** `sha256:665e146d420088a1a88e4946741bae187cd950e6e0eb733e103f2fcfda1fe37b`
**Proposal fixture schema:** `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`
**Effective fixture schema:** `sha256:1f8491f3cef73c6a6b189f99d7130628122651e13053c18ccbe1289b5bb1ad22`

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

The source-pinned loader does not dispatch transport methods in its caller's
Python process. It launches the permanent verifier with the exact CPython
executable in isolated mode (`-I`), a fixed script path and a minimal
environment. The parent captures the process boundary and verifier-source
digest at import, rechecks that digest before execution, rejects all
noncanonical output and validates the returned authentication identity.
Caller monkeypatches, `PYTHONPATH`, user-site packages and substituted public
transport methods therefore cannot mint authority in the loading process.

Inside that fresh process, the verifier parses the exact source-pinned record,
performs authenticated GitHub REST reads for the exact Git commit and all six
attempt endpoints, and fails closed on missing credentials, nonexistent runs,
failed or unrelated attempts, changed workflow paths, repository mismatch,
timestamp mismatch or a wrong commit tree.

The verifier also fetches the uniquely named
`newsroom-sdlc-decision-<run>-<attempt>-<sha>` artifact belonging to the
authenticated SDLC attempt. GitHub artifact metadata, repository/run identity,
reported archive digest, downloaded ZIP bytes, safe extraction and transport
receipt are all checked. The artifact inventory must contain exactly
`decision.json`, `decision-input/context.json` and
`decision-input/collection.json`. The exact canonical `decision.json` bytes
must equal the decision document embedded in the main-admission record.
Context and collection bytes must be canonical and must bind the same complete
repository, event, run, commit and tree identity. An internally canonical but
locally fabricated PASS document therefore cannot satisfy admission.

The signed SDLC evidence is additionally validated through
`scripts.sdlc.shadow_decision.validate_shadow_decision` under the repository
SDLC contract. The loader recomputes the document digest and requires
`result=PASS`, `result_reason=PASS:decision`, no first failure, matching
exact-main context and event, the same SDLC run/attempt, zero
failures/errors/required skips, matching test/skip totals, exact
source-integrity evidence and only PASS gate decisions. The record summary
cannot differ from the authenticated artifact.

A failed, unrelated, pull-request, wrong-tree, reused-attempt, noncanonical,
summary-tampered, locally fabricated or non-PASS record therefore cannot grant
downstream implementation authority.

No shadow, canary, production activation, publication, public effect,
live-source execution, external embedding API call, provider spending or
protected-content vector is authorized.
