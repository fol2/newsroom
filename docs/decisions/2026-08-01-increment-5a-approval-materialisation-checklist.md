# Increment 5A owner-approval materialisation checklist

This checklist is executed only after the proposal/code head has permanent-gate evidence and a fresh substantive review with zero unresolved P1/P2 findings.

1. Post the exact single-line owner statement on issue #250 from repository owner `fol2`.
2. Read the immutable GitHub comment ID, URL, author, stored body and creation time.
3. Recompute the exact body digest and reject any edit, paraphrase, author, issue or digest mismatch.
4. Build canonical `increment5a_owner_approval_record_v1.json` from the reviewed proposal, schema and component identities plus the exact comment evidence.
5. Compute the record SHA-256 and pin that digest in `newsroom/increment5/approval.py` in the same commit that adds the record.
6. Run focused parsing, binding, missing/changed-record, production-profile, protected-content and fixture-substitution tests.
7. Run all permanent CI, Authority, Projection, authenticated Neo4j and signed SDLC workflows on that exact head.
8. Obtain a final substantive review with zero unresolved P1/P2 findings and resolve every thread.
9. Merge 5A, qualify exact `main`, close #250 and only then begin #251.

Materialisation authorises implementation and production-equivalent qualification only. It does not authorise shadow, canary, production activation, publication, public effect, live-source execution, external embedding API calls, provider spending or protected-content vectors.


## Post-merge downstream admission

The owner record alone permits production-equivalent qualification but does not
open #251. After PR #255 merges, qualify the exact merged `main` commit with all
six permanent workflows, build the canonical post-merge main-qualification
record from those immutable run identities and the signed decision, pin its
digest in source in the same reviewed commit, qualify that admission change,
merge it, requalify exact `main`, close #250, and only then begin #251.
