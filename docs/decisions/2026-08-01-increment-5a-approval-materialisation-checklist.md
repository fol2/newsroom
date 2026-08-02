# Increment 5A owner-approval materialisation checklist

This checklist is executed only after the exact proposal/code head has passed all
permanent gates and a fresh substantive review has recorded zero unresolved
P1/P2 findings.

## Preconditions

- PR #255 remains draft until the owner record has been materialised, qualified
  and reviewed.
- The immutable proposal remains `PENDING_OWNER_REVIEW`.
- `newsroom/increment5/data/increment5a_admission_anchors_v1.json` contains the
  reviewed admission-source manifest `sha256:70ab68bef6a9654d59164b70340a4c33bcab56d965b27789159fb49155ef87c8` and source-bundle
  identity `sha256:9a8282231c2665f1e8f5467e7bbd9e16896b6e82704a8be9a17b66949cf11333`.
- Both `approval_record_digest` and `main_qualification_record_digest` remain
  `null`.
- No owner record or post-merge main-qualification record is present.
- #251 remains blocked.

## Owner-record materialisation

1. Post the exact single-line owner statement from repository owner `fol2` on
   issue #250.
2. Read the immutable GitHub comment ID, URL, owner identity, author
   association, stored body, creation time and update time.
3. Require the exact prescribed body byte-for-byte, body digest
   `sha256:8e00ded4cec0a95a59b3507b5fb28eba8033f96c2dccb531d4075bdcbe976f87`, owner login and immutable user ID, issue #250, and an
   unedited comment whose `updated_at` equals `created_at`.
4. Build canonical
   `newsroom/increment5/data/increment5a_owner_approval_record_v1.json` from the
   immutable proposal, exact schemas and component identities, canonical comment
   time, and exact GitHub comment evidence.
5. Compute the canonical record SHA-256. In the same commit that adds the
   record, write that digest to `approval_record_digest` in
   `newsroom/increment5/data/increment5a_admission_anchors_v1.json`. Leave
   `main_qualification_record_digest` as `null` and leave the reviewed
   `source_manifest_digest` and `source_bundle_identity` unchanged.
6. Do not edit `approval.py`, `_approval_v1.py`, `github_attempts.py`,
   `_github_attempts_v1.py`, `main_qualification.py`,
   `_main_qualification_v2.py`, the isolated child, transport or another member
   of the reviewed executable source closure merely to admit the record.
7. Run focused anchor, source-manifest, owner-record, proposal-binding,
   production-profile, fixture-substitution, protected-content and
   missing/changed-record regressions.
8. Run CI, Authority A2a, Authority A2b, Projection B1, authenticated Projection
   B2/B3/C1 Neo4j and signed SDLC on that exact materialisation head.
9. Obtain another substantive review with zero unresolved P1/P2 findings and
   resolve every review thread.
10. Only then merge PR #255.

Owner materialisation authorises production-equivalent qualification only. It
does not authorise downstream implementation, shadow, canary, production
activation, publication, public effect, live-source execution, external
embedding API calls, provider spending or protected-content vectors.

## Post-merge downstream admission

The owner record alone does not open #251.

1. After PR #255 merges, qualify the exact merged `main` commit and tree with all
   six permanent workflows. The five normal workflows must be truthful
   successful `push` attempts; SDLC Evidence Shadow must be a truthful
   successful `workflow_dispatch` attempt on the same exact main commit/tree.
2. Authenticate the exact Git commit, all six run attempts and the uniquely
   named signed-decision artifact. Require the complete canonical collection to
   rederive the retained `PASS` decision with zero failures, errors and required
   skips.
3. Build canonical
   `newsroom/increment5/data/increment5a_main_qualification_record_v2.json`.
4. Compute its canonical SHA-256. In the same commit that adds the record, write
   that digest to `main_qualification_record_digest` in the existing canonical
   admission-anchor file. Preserve the owner-record digest and both reviewed
   source identities exactly.
5. Qualify and substantively review the admission change, merge it, then
   requalify exact `main`.
6. Close #250 and begin #251 only after the authenticated post-merge record is
   admitted on exact main.

The post-merge data-anchor update must not rewrite or rebaseline the immutable
executable source closure.
