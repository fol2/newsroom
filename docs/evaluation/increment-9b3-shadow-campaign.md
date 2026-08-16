# Increment 9B3 prospective shadow campaign

- **Issue:** [#493](https://github.com/fol2/newsroom/issues/493)
- **Status:** first-I/O gate and retained stop authority implemented
- **Dependencies:** #488, #489, #490, #491 and #492
- **Executable:** `scripts/increment9_shadow_campaign.py`

## Boundary

9B3 is the first atom that may admit a decision-bearing external request, but
only after every retained first-I/O gate passes on one exact clean checkout.
The executable itself has no network client, provider SDK, model adapter,
embedding adapter, publication path or production writer. It cannot silently
cross the boundary while assessing evidence.

A missing, invalid, non-PASS, expired, future-dated or different-head record
produces `BLOCKED_BEFORE_FIRST_IO`. The resulting canonical bundle is an
explicit retained campaign stop outcome: zero Run/Attempt entries, zero source
or provider requests, zero model or embedding calls, zero spend, zero public
effects and zero production mutations. `--accept-blocked` changes only the CLI
exit status for intentional evidence capture; it never changes the receipt.

## Required gates

The exact inventory comprises:

- merged/current #488, #489, #490, #491 and #492 authorities;
- one fully resolved current Effective Manifest and prospective Run authority;
- current provider terms;
- the exact baseline credential classes (`OPENAI_CODEX_LOGIN`,
  `OPENAI_EMBEDDINGS_API`, `NEO4J_SHADOW_WRITER`);
- enforced egress allowlist, prefunded non-replenishing wallet, protected
  storage, kill switch and absence of a human emergency stop;
- a production non-mutation baseline; and
- one rights record for each of HK-01, HK-02, HK-04, RAD-01, RAD-02, UK-01,
  UK-02, UK-03, UK-05 and UK-10.

Each rights record must bind the exact OD-001 record subject and carry three
unique reviewer-provider families. AI risk acceptance is not treated as access
permission. Exact terms and access evidence remain mandatory.

## Gate record format

Every file in the gate directory is strict canonical JSON using
`newsroom.increment9.campaign-gate.v1`. Unknown files/gates, duplicate names,
extra fields and non-canonical bytes fail closed. Records bind:

- gate ID, PASS/non-PASS status and issuer;
- exact main SHA/tree;
- observation and expiry times;
- subject and evidence digests;
- credential-class inventory where applicable; and
- independent reviewer-provider families where applicable.

The evidence producer, not this sealer, owns the substantive proof. A digest is
never manufactured for missing proof.

## Retained bundle

`assess` emits a mode-0600, atomically replaced canonical bundle containing:

1. immutable launch receipt and complete finding inventory;
2. reconciled empty Run/Attempt inventory when blocked pre-I/O;
3. exact budget/exposure report, including every OD-008 minimum;
4. explicit `BLOCKED`, `INCONCLUSIVE`, `FAILED`, `EARLY_STOPPED` or `COMPLETED`
   outcome vocabulary (the preflight sealer emits only BLOCKED or the not-yet-
   executed INCONCLUSIVE handoff);
5. no-public-effect and production-nonmutation counts; and
6. component and whole-bundle SHA-256 identities.

`verify` reconstructs all component and bundle digests from exact canonical
bytes and revalidates blocked non-effect invariants. Any edit is rejected.

## Commands

```bash
python scripts/increment9_shadow_campaign.py self-test

python scripts/increment9_shadow_campaign.py assess \
  --repo . \
  --gate-directory /protected/increment9/gates \
  --campaign-id EPOCH_ID \
  --output /protected/increment9/campaign-bundle.json

python scripts/increment9_shadow_campaign.py verify \
  --bundle /protected/increment9/campaign-bundle.json
```

A genuinely authorised launch receipt is only a handoff to the separately
controlled prospective runner. It does not claim that the 28-day window or any
minimum exposure has completed. Publication, Evidence Intake, canary,
production activation and production mutation remain false in every receipt.

## Current execution rule

Until all ten source rights records, current terms/access evidence, three
independent rights reviews, exact runtime packages/credentials, live isolated
deployment receipts, frozen Epoch/Run authority, wallet, kill switch and
production baseline are retained at the same exact head, the only truthful
9B3 outcome is `BLOCKED_BEFORE_FIRST_IO`. No unchanged-head launch retry is
permitted after a failed or blocked material gate without new evidence.
