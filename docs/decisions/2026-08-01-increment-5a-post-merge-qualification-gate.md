# Increment 5A post-merge exact-main qualification gate

**Issue:** #250
**Pull request:** #255
**Pre-approval reviewed head:** `8d70d83180906c548ab494b1359b1eefdb471174`

Owner approval and downstream implementation admission are deliberately separate.

The canonical owner approval record permits production-equivalent qualification
of the exact retrieval contract. It does not by itself permit #251 or any later
Increment 5 implementation to begin. `production_qualification_authorized`
therefore reflects the owner record, while `production_authorized`,
`component_authorized(...)`, and `require_profile(PRODUCTION)` additionally
require a second source-pinned post-merge record.

That later record can be created only after PR #255 is merged and the exact
merged `main` commit has passed all six permanent workflows. It binds:

- the exact merged main commit and tree;
- the exact owner-approval record digest;
- the immutable proposal and hardened qualification-profile schema;
- distinct successful CI, Authority A2a, Authority A2b, Projection B1 and
  authenticated Projection B2/B3/C1 Neo4j `push` attempts on exact main;
- one distinct successful SDLC Evidence Shadow `workflow_dispatch` attempt
  on the same exact main commit and tree;
- the complete signed SDLC decision validated through the canonical
  repository parser, with zero-failure, zero-error and zero-required-skip
  totals; and
- one canonical UTC qualification time.

Before that record is admitted, its digest is `None`, its path must be absent,
and every downstream implementation gate fails closed. A stray unpinned record,
missing pinned record, digest mismatch, wrong approval, wrong proposal,
incomplete workflow inventory, reused workflow run, noncanonical timestamp or
noncanonical JSON is rejected.

The owner approval comment may therefore be materialised and used to qualify the
5A contract without making an unmerged branch a source of 5B authority. Issue
#250 remains open until the post-merge record is separately reviewed, admitted,
merged and exact `main` is requalified. Only then may #251 begin.

This gate authorizes no shadow, canary, production activation, publication,
public effect, live-source execution, external embedding API call, provider
spending or protected-content vector.
