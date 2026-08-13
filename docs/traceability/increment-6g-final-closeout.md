# Increment 6G final closeout traceability

- **Issue:** #368
- **Parent:** #146
- **Gate:** Tier M
- **Entry main:** `c52574afcc9725b7ee14edcc8f4aa608a2593ecc`
- **Entry tree:** `91754aeb76f05fac41b38ad8ef90715b7fe11ba4`
- **Inventory source:** `newsroom/increment6/closeout.py`
- **Inventory digest:** `sha256:cb051e71025a2387aa6bdc4e4fca0bc76b414aabaeb2d192b2aa1dd48c81e011`

## Closed boundary

The machine inventory reconciles 58 exact permanent pytest node identities. It
binds the complete Increment 6 fixture path from retained Source Revision,
Signal and Lead authority through Work Item, Retrieval Context, Proposal,
Disposition, Hypothesis, Relationship, Lineage, Candidate Admission,
evaluation-only Handoff, Feedback and mandatory Reconciliation Disposition.

The inventory is evidence only when the signed SDLC receipt finds every exact
node once in the retained core or authenticated-service JUnit reports and each
selected node passed without a skip. The receipt rejects any failure or error
in either complete lane, including a failure outside the selected inventory.

## Migration and authority boundary

The closeout adds no migration, table, product writer or product authority. The
retained migration inventory proves the literal v1-v25 history, every supported
exact predecessor upgrade, multihop backup identities, exclusive rollback and
restore/re-upgrade. The actual-service target binds that same current history,
schema version and schema fingerprint to the evaluated source head and tree.
Those Increment 6 identities are dedicated frozen constants: permanent future
service runs validate the exact v1-v25 prefix and permit a later authorised
migration suffix rather than freezing the repository's current schema at v25.

The selected authority cases retain the real public paths:

- Work Item claim ownership, stale recovery, urgent/degraded visibility and
  starvation protection;
- Proposal route/disposition matrices, inspectable holds and no-authority
  boundaries;
- Hypothesis create/append, relationship uncertainty/correction and retained
  receipt replay;
- consolidation, split and reversal lineage without predecessor rewrite;
- current collision recheck and equivalent/distinct Candidate admission;
- concurrent claim/admission and evaluation Handoff loss, delay, ambiguity and
  retry;
- mandatory Feedback obligations and reconciliation dispositions which remain
  visible until a governed terminal state; and
- Watch Condition and supplemental-discovery re-entry through a new governed
  Work Item.

Rights withdrawal, exact tombstone removal, tamper, unavailable, degraded and
no-false-success outcomes are retained as explicit fail-closed evidence.

The inherited v17 Handoff record does not immutably prove its original
registration-time `max_attempts`; #428 owns that later hardening and blocks
production-equivalent Handoff use. Increment 6 does not use that unanchored
scalar as authority. The selected feedback-authority case retains the exact
v25 Handoff acceptance snapshot in the same transaction as accepted feedback,
then changes only the underlying `max_attempts` value and proves that no new
feedback, reconciliation disposition or ledger effect is created. Exact replay
continues to return the retained snapshot. This known limitation therefore
cannot authorise an Increment 6 effect and is not hidden by the closeout.

## Actual service and retained receipt

`newsroom/tests/test_increment6g_neo4j_service.py` runs only with the permanent
authenticated Neo4j service lane. It verifies the pinned image, server,
edition, driver, database and projector identity through authenticated
transport, then records the exact source, migration and inventory identities as
JUnit properties. Wrong projector credentials and actual tombstone removal are
separate selected actual-service cases.

`scripts/sdlc/increment6g_closeout_receipt.py` replays the immutable core and
service transport bundles, validates the PASS decision, checks all 58 selected
outcomes, rejects any lane failure/error, and binds the raw JUnit, lane receipt,
envelope, transport, replay, selected-test manifest and service identities to
one exact source head and tree. It checks the tracked checkout before consuming
evidence and again before emission.

The final receipt is included with the decision evidence. Only a successful
service-required manual run on `refs/heads/main` advances to `signed-closeout`.
That isolated job independently checks its schema, exact-main identity, lane
set, inventory, decision binding and content hash, then attests the decision,
the retained Increment 5E2 receipt and the Increment 6G receipt together.

## Non-effects

Closeout performs no evidence acquisition, live provider/model call, product
runtime egress, product authority mutation, publication, production activation,
shadow or canary action. Disposable authenticated Neo4j is CI infrastructure;
it does not change the product non-effect boundary. Increment 7 remains outside
this work.
