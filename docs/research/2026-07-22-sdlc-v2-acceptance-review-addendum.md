# SDLC-V2 acceptance review addendum

- Role: Dated current-head review evidence
- Status: Completed
- Owner: fol2
- Canonical language: English
- Date: 2026-07-22
- Related issue: #98
- Related PR: #99
- Contract version: `sdlc-v2.2`

## Scope

This addendum records review findings raised after owner acceptance but before merge. It supplements `docs/research/2026-07-21-sdlc-v2-substantive-review.md`.

## Result

- Additional P1 findings: 0
- Additional P2 findings: 2
- Total P2 findings across both reviews: 8
- Remaining unresolved P1/P2 after correction: 0

## P2-7 — Merge gate lane identifier did not resolve to its lane contract

`.sdlc/gates.toml` used `lane = "merge-group"` for `gate.merge-exact`, while the configured lane table was `[lanes.merge_group]`.

A router or runner resolving the gate's lane identifier exactly could miss the merge-group exact-tree, evidence-reuse and timeout settings or fall back to generic defaults.

Correction:

- change the gate lane identifier to `merge_group`;
- require Phase 1 contract validation to prove every `gate.*.lane` resolves to exactly one `lanes.*` table.

## P2-8 — Projection policy changes could omit actual Neo4j evidence

`newsroom/projection/policy.py` was present only in the `R2_STATEFUL_CONTRACT` path set. It defines projection command and payload contracts consumed by the Neo4j authority composition, so changes can affect the service boundary.

Because the route schema forbids service evidence for R0–R2, the old classification could skip the actual-service lane.

Correction:

- add `newsroom/projection/policy.py` to the `R3_EXTERNAL_SERVICE_SECURITY` path set;
- retain it in R2 as well and classify by maximum triggered risk;
- require Phase 1 classifier tests proving this path selects R3 and service evidence.

## Final review state

The accepted source package now has no unresolved inline review thread and no known P1/P2. CI remains regression evidence only; the corrections are justified by contract semantics and will receive explicit executable tests in Phase 1.
