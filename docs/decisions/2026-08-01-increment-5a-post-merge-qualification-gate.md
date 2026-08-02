# Increment 5A post-merge exact-main qualification gate

**Issue:** #250  
**Pull request:** #255  
**Owner-record effect:** `PRODUCTION_EQUIVALENT_QUALIFICATION_ONLY`  
**Main-admission effect:** `IMPLEMENTATION_OF_ISSUES_251_254_ONLY`  
**Main-admission schema:** `sha256:4247835d3c200a1012dbc45ec1a7ee609acce44205e3868a1cb5d6e69d7d0d65`  
**Admission-source manifest:** `sha256:70ab68bef6a9654d59164b70340a4c33bcab56d965b27789159fb49155ef87c8`  
**Admission-source bundle:** `sha256:9a8282231c2665f1e8f5467e7bbd9e16896b6e82704a8be9a17b66949cf11333`

Owner approval and downstream implementation admission are deliberately
separate.

The canonical owner-approval record permits production-equivalent
qualification of the exact retrieval contract. It does not permit #251 or any
later Increment 5 implementation to begin.
`production_qualification_authorized` reflects the owner record, while
`production_authorized`, `component_authorized(...)`, downstream contract
identity and `require_profile(PRODUCTION)` additionally require a separately
authenticated post-merge exact-main record.

## Canonical anchor sequence

The reviewed executable authority closure is immutable. Future record digests
are stored only in
`newsroom/increment5/data/increment5a_admission_anchors_v1.json`.

Before owner materialisation, both record digests are `null`. The owner
materialisation commit adds the canonical owner record and updates only
`approval_record_digest`. After PR #255 merges and exact main qualifies, the
post-merge admission commit adds the canonical main-qualification record and
updates only `main_qualification_record_digest`. Both reviewed source identities
and the owner-record digest remain unchanged.

A source-code edit to rebaseline the parent gate, child, parser, transport or
source manifest is not a valid substitute for updating the canonical data
anchor.

## Required exact-main evidence

The post-merge record can be created only after PR #255 is merged and the exact
merged `main` commit/tree has passed all six permanent workflows. It binds:

- the exact merged-main commit and tree;
- the exact owner-record digest and immutable proposal identities;
- the exact reviewed admission-source manifest and bundle;
- distinct successful CI, Authority A2a, Authority A2b, Projection B1 and
  authenticated Projection B2/B3/C1 Neo4j `push` attempts on exact main;
- one distinct successful SDLC Evidence Shadow `workflow_dispatch` attempt on
  the same exact main commit/tree;
- the complete authenticated SDLC decision artifact and collection, revalidated
  through the canonical repository contract; and
- one canonical UTC qualification time.

Before returning authority, the actual parent gate verifies its own reviewed Git
blob and the full executable source closure. The isolated child independently
verifies that closure, authenticates the Git commit and all six run attempts
against GitHub, downloads the uniquely named signed-decision artifact, validates
the exact three-file inventory and requires the complete collection to rederive
the embedded `PASS` decision.

The admitted decision must have zero failures, zero errors and zero required
skips. Missing credentials/evidence, failed or unrelated attempts, wrong
repository/ref/tree, reused runs, a partial collection, fabricated canonical
PASS, noncanonical time/JSON, wrong owner approval, source-identity mismatch or
anchor/record digest mismatch fails closed.

Issue #250 remains open until the post-merge record is separately reviewed,
admitted, merged and exact `main` is requalified. Only then may #251 begin.

This gate authorises no shadow, canary, production activation, publication,
public effect, live-source execution, external embedding API call, provider
spending or protected-content vector.
