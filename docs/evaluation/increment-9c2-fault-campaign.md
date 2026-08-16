# Increment 9C2 comparator and fault campaign outcome

- **Issue:** [#495](https://github.com/fol2/newsroom/issues/495)
- **Status:** deterministic higher-precedence stop sealer implemented
- **Dependencies:** #490, #491, #492, #493 and #494
- **Executable:** `scripts/increment9_fault_campaign.py`

## Boundary

9C2 may execute only phases admitted by the immutable #494 contract and only
after a qualifying 9B3 baseline. The current 9B3 evidence is an explicit
`BLOCKED_BEFORE_FIRST_IO` outcome. Under the frozen stop order,
`RIGHTS_OR_CREDENTIAL` precedes manifest, exposure and ordinary failure. No
comparator or fault phase may therefore start.

The executable verifies the strict-canonical 9B3 bundle and a current exact-main
dependency snapshot. It accepts only a blocked, non-decision-bearing 9B3 bundle
whose source/provider/model/embedding/spend/public/production counts are all
zero. Any non-blocked baseline is rejected and must use a separate live phase
runner; it is never simulated by this sealer.

## Complete phase inventory

The output retains every pre-registered phase, rather than omitting work that
did not run:

- eight comparator arms: frozen read-only news-pool export, RTHK, BBC, Exact,
  Full Text, Vector, Admitted Graph and Hybrid RRF;
- all eighteen approved fault kinds from `SOURCE_FAILURE` through
  `KILL_AND_RESTORE`.

Every one of the 26 entries is
`NOT_RUN_DUE_HIGHER_PRECEDENCE_STOP`, is non-decision-bearing, and points to the
original 9B3 stop. The fault entries retain their expected observation,
mandatory containment and recovery action even though no injection occurred.
This satisfies the #495 rule that a phase is either completed or explicitly not
run because of a retained higher-precedence stop.

## Outcome and non-effects

The canonical outcome is `BLOCKED` with:

- `fault_campaign_started=false`;
- zero executed and 26 explicitly not-run phases;
- complete chronology and denominator reconciliation;
- containment `PREVENTED_FIRST_IO`;
- recovery `NOT_APPLICABLE_NO_EFFECT`;
- zero source/provider/model/embedding calls, fault injections, recovery Runs,
  spend, public effects and production mutations; and
- the original 9B3 findings retained without downgrade.

No Evidence Intake, publication, canary, production mutation or production
activation authority is created. The outcome is eligible only as sealed input
to #497's explicit blocked decision.

## Evidence integrity

The bundle binds the exact checkout SHA/tree, owner-plan digest, #494 source
blob, dependency evidence, 9B3 canonical bundle/file digests, exact phase order,
stop precedence, complete phase inventory, outcome and whole-bundle digest.
`verify` reconstructs every digest and exact inventory. Output is atomically
written with mode `0600` below a mode-`0700` directory.

```bash
python scripts/increment9_fault_campaign.py self-test

python scripts/increment9_fault_campaign.py seal-upstream-stop \
  --repo . \
  --campaign-bundle /protected/9b3/campaign-bundle.json \
  --dependency-evidence /protected/9c2/dependencies.json \
  --observed-at 2026-08-16T00:00:00.000000Z \
  --output /protected/9c2/fault-bundle.json

python scripts/increment9_fault_campaign.py verify \
  --bundle /protected/9c2/fault-bundle.json
```
