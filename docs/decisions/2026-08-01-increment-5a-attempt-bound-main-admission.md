# Increment 5A attempt-bound post-merge implementation admission

**Issue:** #250  
**Pull request:** #255  
**Owner-record effect:** `PRODUCTION_EQUIVALENT_QUALIFICATION_ONLY`  
**Main-admission effect:** `IMPLEMENTATION_OF_ISSUES_251_254_ONLY`  
**Approval schema:** `sha256:cc87d78551d3e2f2ae61c0bd5e247288c291feced7b63165d55e2e8b05dcc56e`  
**Main-admission schema:** `sha256:4247835d3c200a1012dbc45ec1a7ee609acce44205e3868a1cb5d6e69d7d0d65`  
**Admission-source manifest:** `sha256:70ab68bef6a9654d59164b70340a4c33bcab56d965b27789159fb49155ef87c8`  
**Admission-source bundle:** `sha256:9a8282231c2665f1e8f5467e7bbd9e16896b6e82704a8be9a17b66949cf11333`  
**Owner-body digest:** `sha256:8e00ded4cec0a95a59b3507b5fb28eba8033f96c2dccb531d4075bdcbe976f87`  
**Proposal fixture schema:** `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`  
**Effective fixture schema:** `sha256:1f8491f3cef73c6a6b189f99d7130628122651e13053c18ccbe1289b5bb1ad22`

The canonical owner record authorises production-equivalent qualification only.
`DOWNSTREAM_IMPLEMENTATION` is an immutable non-effect of that record.
Implementation authority is created only by a separately authenticated,
digest-anchored post-merge main-qualification record.

## Immutable executable closure and mutable records

The reviewed executable authority boundary is fixed by
`scripts/sdlc/increment5_admission_source_v1.json`. Its inventory includes the
actual parent authority gate, immutable gate core, owner and main-record parser
cores and wrappers, isolated child bootstrap and implementation, GitHub
transport, canonical SDLC collection/decision validators, repository SDLC
contract and every authority-bearing dependency.

The source manifest digest and bundle identity are stored in canonical
`newsroom/increment5/data/increment5a_admission_anchors_v1.json` and are also
part of the exact owner statement. The future owner-record and main-record
digests are separate mutable data fields in that same anchor. Materialising a
record updates only the canonical anchor and record files; it does not modify or
rebaseline the reviewed executable closure.

The anchor parser requires an exact non-symlink repository path, strict UTF-8
JSON, duplicate-name rejection, exact keys, canonical bytes and canonical
digests. A main-record digest cannot exist without an owner-record digest.

## Exact workflow attempts

CI, Authority A2a, Authority A2b, Projection B1 and Projection B2/B3/C1 Neo4j
each require one truthful successful `push` attempt on `refs/heads/main`. SDLC
Evidence Shadow requires one truthful successful `workflow_dispatch` attempt.
Every attempt retains immutable workflow ID/name/path, run ID/attempt/number,
repository and immutable repository ID, head commit/tree, workflow SHA/ref,
successful conclusion, exact API/HTML URLs and canonical timestamps. All six
attempts are distinct and bind the same declared merged-main commit/tree.

## Parent and isolated-child authentication

Before a record can be admitted, the actual parent gate validates the
anchor-bound manifest digest, canonical manifest bytes, source-bundle identity,
its own reviewed Git blob and every listed dependency. It then launches the
stdlib-only bootstrap with the exact CPython executable in isolated mode
(`-I`), a fixed manifest path/digest and a minimal environment.

The child independently revalidates the same manifest and every reviewed Git
blob before installing synthetic package paths or importing repository code.
Only then does it parse the exact source-pinned record and perform authenticated
GitHub REST reads for the Git commit and all six run-attempt endpoints.
Replacing the parent gate, child, transport, parser, contract or another listed
dependency fails before a certificate can grant authority.

Missing credentials, nonexistent runs, failed or unrelated attempts, changed
workflow paths, repository mismatch, wrong event/ref, timestamp mismatch, a
wrong commit tree or a reused attempt all fail closed.

## Signed SDLC artifact and complete collection

The verifier fetches the uniquely named
`newsroom-sdlc-decision-<run>-<attempt>-<sha>` artifact belonging to the
authenticated SDLC attempt. GitHub artifact metadata, repository/run identity,
reported archive digest, downloaded ZIP bytes, safe extraction and transport
receipt are checked.

The artifact inventory must contain exactly `decision.json`,
`decision-input/context.json` and `decision-input/collection.json`. Every file
must be canonical JSON. The complete collection is validated through
`workflow_orchestrator.validate_collection`, including `collection_identity`,
context/event, core/service lane records, receipts, routes, replay identities
and evidence identities. `aggregate_shadow_decision` is rerun from those exact
lanes and the derived decision must equal the authenticated `decision.json`
exactly.

The exact decision bytes must equal the decision embedded in the main-admission
record. The canonical SDLC validator additionally requires `PASS`,
`PASS:decision`, no first failure, exact-main context/event, the matching SDLC
run/attempt, zero failures/errors/required skips, matching test/skip totals,
exact source-integrity evidence and only PASS gate decisions.

A partial collection, locally fabricated canonical PASS, failed or unrelated
attempt, wrong tree, noncanonical record, summary tampering, anchor mismatch or
source-bundle substitution cannot grant downstream implementation authority.

No shadow, canary, production activation, publication, public effect,
live-source execution, external embedding API call, provider spending or
protected-content vector is authorised.
