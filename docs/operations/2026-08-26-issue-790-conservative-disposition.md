# Issue #790 conservative usage disposition

The content-addressed plan in
[`2026-08-26-issue-790-conservative-disposition.json`](2026-08-26-issue-790-conservative-disposition.json)
binds the owner approval to exactly one retained Cursor subscription CLI
invocation. It does not rewrite its `UNREPORTED` terminal, claim exact provider
telemetry, assign zero usage or release unknown spend. The effective accounting
view instead records the qualified policy's `max_total_tokens` as a
`BOUNDED_ESTIMATE`.

## Required order

1. Keep the persistent Graphiti worker unloaded and retain ledgers 1932 and
   1972 without retry.
2. Merge the reviewed change and deploy the exact successful `main` revision.
3. Back up the unpublished SQLite store and run `dry-run` against the resulting
   isolated copy:

   ```sh
   uv run python scripts/issue_790_conservative_disposition.py dry-run \
     --store STORE --scratch-store SCRATCH_STORE \
     --plan docs/operations/2026-08-26-issue-790-conservative-disposition.json \
     --observed-at OBSERVED_AT --receipt DRY_RUN_RECEIPT
   ```

4. Confirm the copy has one conservative disposition, retains no reconciliation
   or provider telemetry for the target, passes `PRAGMA quick_check`, and closes
   only `GRAPHITI_CHAT_PRIMARY` using the disposition digest.
5. Apply the same plan to the live store with a new, non-existent backup path:

   ```sh
   uv run python scripts/issue_790_conservative_disposition.py apply \
     --store STORE --backup BACKUP \
     --plan docs/operations/2026-08-26-issue-790-conservative-disposition.json \
     --observed-at OBSERVED_AT --receipt APPLY_RECEIPT
   ```

6. Recheck store integrity, the target's effective and historical views, every
   route circuit, queue state and the persistent worker state.
7. Run exactly one fresh bounded provider-backed canary. Do not retry either
   retained failed ledger. Stop if another usage, policy, transport or integrity
   blocker appears.

The operation grants no publication, public dispatch, backlog drain, bulk
requeue, Production Operational Admission, wider activation, provider
substitution or unrelated spend disposition authority. Preserve the backup and
both receipts. A restore requires a quiescent store and separate reviewed
authority so that later unrelated ledger writes are not discarded.
