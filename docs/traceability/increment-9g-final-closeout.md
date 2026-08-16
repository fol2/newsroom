# Increment 9G exact-main integrated shadow closeout

- **Issue:** [#498](https://github.com/fol2/newsroom/issues/498)
- **Signing prerequisite:** [#521](https://github.com/fol2/newsroom/issues/521)
- **Module:** `newsroom.increment9.closeout`
- **Builder/verifier:** `scripts/sdlc/increment9g_closeout_receipt.py`

## Outcome preserved

Increment 9 completed its evidence process with the explicit shadow disposition
`BLOCKED_ACTIVE_COVERAGE`:

- 9B3 stopped before first I/O because twenty material runtime gates remained;
- the Run/Attempt/checkpoint inventory is empty and reconciled;
- 9C2 retained all eight comparator and eighteen fault phases as not run under
  the higher-precedence stop;
- 9D2 retained every metric, slice, ablation, reviewer, zero-tolerance and
  operational result as `NOT_EVALUATED`; and
- source/provider/model/embedding/reviewer usage, spend, public effects and
  production mutations are zero.

Closeout completion does not turn this result into a technical PASS. Increment
10 eligibility, Evidence Intake, publication, canary, production mutation and
production activation remain false.

## Exact closed world

The builder requires live-retained CLOSED evidence for #488–#497, #500 and the
narrow signing prerequisite #521. It refuses an open/missing dependency. #498
itself remains open during the final signed run and closes only after the bundle
verifies.

At one exact clean main SHA/tree, the builder independently reconstructs:

1. the owner-approved plan and digest;
2. the final 9B3 blocked campaign bundle from closed dependency gates;
3. the final 9C2 complete not-run phase inventory;
4. the final 9D2 `BLOCKED_ACTIVE_COVERAGE` decision;
5. the #490 actual Neo4j 5.26.2 readiness/restart receipt;
6. the reconciled Run inventory;
7. the complete review/metric report;
8. the accepted 18-shard topology and unchanged 75/90 and 300/330 limits;
9. the exact-main Tier-M SDLC decision with both core and actual-service lanes;
   and
10. the final closeout receipt and signed-subject manifest.

The historical #490 evidence is fixed to run `31923002243`, head
`390237b9183f5ee77da363669de3ddef964d0c32`, Community Neo4j 5.26.2,
`increment9` / `increment9_shadow`, actual restart/re-authentication and zero
residual nodes, indexes or secrets.

## Required signed subjects

The final GitHub Actions OIDC/Sigstore attestation contains at minimum:

- exact SDLC decision;
- `increment9-shadow-plan.json`;
- `increment9-deployment-receipt.json`;
- `increment9-run-inventory.json`;
- `increment9-review-metric-report.json`;
- `increment9-shadow-decision.json`; and
- `increment9g-final-closeout.json`.

The campaign, fault, issue-inventory and subject-manifest files are retained and
attested as additional subjects. File digests, canonical identities, exact
SHA/tree and cross-subject bindings are reconstructed before signing and again
from the downloaded bundle.

## Topology and gates

The closeout refuses any topology other than:

- 18 core shards;
- two persistent work-stealing workers per shard;
- testcase warning/hard 75/90 seconds;
- shard/critical-path warning/hard 300/330 seconds; and
- zero required failures, errors or skips.

The final manual Tier-M run must report all complete deterministic outcomes,
source integrity and the actual Neo4j service lane on exact `main`. P1,
material-P2 and unresolved review-thread counts must all remain zero.

## Commands

```bash
python -m scripts.sdlc.increment9g_closeout_receipt build \
  --repo-root . \
  --issue-directory /protected/increment9/issues \
  --sdlc-decision /protected/increment9/decision.json \
  --deployment-readiness /protected/increment9/increment9-neo4j-readiness.json \
  --deployment-restart /protected/increment9/increment9-neo4j-restart.json \
  --observed-at 2026-08-16T00:00:00.000000Z \
  --output-directory /protected/increment9/subjects

python -m scripts.sdlc.increment9g_closeout_receipt verify \
  --repo-root . \
  --subject-directory /protected/increment9/subjects \
  --sdlc-decision /protected/increment9/decision.json
```

## Final downstream record

The closeout status is `INCREMENT9_EVIDENCE_PROCESS_CLOSED`, while its shadow
outcome stays `BLOCKED_ACTIVE_COVERAGE`. Parent #149 may close with that explicit
result. Parent #150 remains blocked: no suitable canary scope, no accepted
Evidence Intake authority and no separate Increment 10 owner plan exist.
