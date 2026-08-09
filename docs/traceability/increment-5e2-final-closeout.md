# Increment 5E2 final closeout traceability

- **Issue:** #333
- **Corrective blocker:** #351
- **Parent:** #254
- **Programme:** #145
- **Gate:** Tier M
- **Inventory source:** `newsroom/increment5/final_closeout.py`
- **Inventory digest:** `sha256:7cdb2c769c4f312f0e2f670fd3c4084025d7cbe247788993d5b50841b0a5be95`

## Closed boundary

5E2 closes only the nine retrieval-specific requirements retained by the
accepted Increment 5 amendment:

`GRAG-050`, `GRAG-051`, `GRAG-054`, `GRAG-055`, `GRAG-056`, `GRPROD-001`,
`GRPROD-010`, `GRPROD-015` and `GRPROD-023`.

The machine inventory reconciles 64 exact pytest node identities across six
mandatory categories: query containment, rights purge, graph/index recovery,
failure/no-false-success, replay/retained-context integrity and qualification
identity. Every category has deterministic repository evidence and authenticated
actual-Neo4j evidence. The union of their requirement references is exactly the
nine-row set above.

The inventory is not evidence merely because a test name is listed. The 5E2
receipt validator reads the retained JUnit reports, requires every selected
node identity to occur exactly once and to pass without a skip, and records the
canonical selected-case values and outcome. Parameterised cases retain their
full pytest suffix, so each frozen variant is independently identified.

## Corrective qualification boundary

The final evaluator now:

- blocks a rights residual, scope escape or successful write reported by any
  executed system while retaining HYBRID-only quality thresholds;
- rederives every case label, fixture, query-set, source-inventory and dataset
  manifest identity from current content before Epoch construction, fixture
  execution or evaluation;
- rejects caller content that retains stale stored identities;
- admits only the exact reviewed target and corpus-policy identity;
- rederives and compares the complete Epoch, including source/provider,
  adapter/parser, threshold, policy and independently supplied code-tree
  identities, before evaluation; and
- retains the exact Epoch and report identities in the actual-service JUnit
  evidence.

Focused adversarial regressions cover each post-merge PR #350 P1. The four
comparative systems are all exercised for cross-system safety/rights blocking,
and each previously omitted derived Epoch field is changed independently.

## Security, rights and recovery reconciliation

The inventory binds permanent implementation tests rather than duplicating
their product paths:

- strict request decoding, fixed tool routing, scope containment, principal
  separation, wrong-credential rejection and absence of raw query/write
  surfaces;
- authority revocation/deletion, physical governed-byte non-resurrection,
  exact full-text/vector removal identities, current Neo4j derivative removal
  and tombstone non-resurrection;
- secure deletion of retained Retrieval Context bytes in required rollback
  journal mode, with WAL mode rejected before any success receipt; a
  content-addressed purge receipt binds every exactly matched passage,
  admission, blob and text identity without tombstoning an unselected sibling.
  The same transaction retains a canonical, digest-checked and content-free
  per-context inventory of every sibling derivative before it deletes the raw
  context. Purge events are append-only by purge identity: an unselected
  sibling remains usable until its own rights withdrawal, after which a later
  restart can locate it, retain a second exact tombstone and block replay or
  rehydration under a new request identity. Each version-two receipt separates
  whether that event deleted retained raw bytes from the required postcondition
  that those bytes are absent. An empty legacy prototype table migrates
  transactionally; a legacy table containing receipts fails closed because it
  cannot reconstruct the lost sibling inventory;
- generation-scoped rebuild from retained authority, checkpoint enforcement,
  graph-loss restart and isolated replacement; and
- missing graph/full-text/vector, stale watermark, required gap and dead-letter
  outcomes that cannot become a successful no-match.

The Retrieval Context journal's purge is an exact identity-driven operation. It
does not claim a scheduler or a complete operational rights-event subscriber;
those operational controls remain outside Increment 5.

## Retained receipts

The authenticated 5E2 target/report case is a first-class
`*_neo4j_service.py` test selected by both the permanent Neo4j workflow and the
signed SDLC service lane. It is an intentional optional skip only in the core
lane and must execute without a skip in either actual-service lane.

Its JUnit properties bind:

- exact source HEAD and Git tree;
- Neo4j image, server version, edition, Python driver, database and projector
  username, plus the service-compatibility digest;
- exact Epoch canonical JSON and digest;
- exact qualification-report canonical JSON and digest;
- exact 64-case closeout inventory digest and count; and
- the fixed non-effect inventory.

`scripts/sdlc/increment5e2_closeout_receipt.py` emits two content-addressed
receipts:

1. the permanent Neo4j workflow receipt validates all selected actual-service
   node results and the semantic identities above against the checked-out
   source; and
2. the signed SDLC final receipt replays the immutable core and service
   transport bundles, validates the PASS decision and both lane receipts,
   checks all 64 selected node results, and binds their raw JUnit digests,
   selected-test manifest, envelope, transport and replay identities to one
   exact source HEAD and tree.

The final GitHub completion record must add the merged `main` commit and tree,
permanent workflow run identities, signed SDLC decision and 5E2 receipt
identities, substantive-review counts and unresolved-thread count. A
branch-local or pre-merge receipt does not close #333, #254, #145 or #351.
An exact-main manual SDLC run must supply an explicit, resolvable non-head
`base_sha`; the workflow and event decoder reject a blank manual base rather
than routing an empty R0 comparison that omits service evidence.

Only that successful service-required manual run on `refs/heads/main` advances
to the isolated `signed-closeout` job. The job downloads the run-, attempt- and
HEAD-scoped final decision artifact, independently checks the PASS decision,
final receipt schema, source HEAD, source tree, lane set, inventory count,
decision binding and content-addressed self-hash using the Python standard
library, then requests a GitHub artifact attestation for the exact decision and
receipt files. Its attestation bundle is retained as a separate run-scoped
artifact. Pull-request and merge-queue runs remain
evidence-only: they neither receive OIDC or attestation write permissions nor
execute this signing job.

## Non-effects and later ownership

This closeout performs no live-source, provider, model or embedding call; no
live-source or production-product credential use; no product-runtime network
egress or spend; no live authority, Candidate or Hypothesis mutation; no
publication; and no shadow, canary or production activation. Its authenticated
credentials are generated for disposable loopback Neo4j only, are masked, and
are removed before evidence finalisation. CI dependency and image retrieval is
workflow infrastructure, not a product-runtime non-effect claim.

Cross-request Hypothesis/Candidate/collision/Handoff effects remain Increment
6/#146. Prospective human evaluation, complete operations, backup/restore,
capacity, licence and Operational Admission remain Increment 8/#148.
