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
     --observed-at OBSERVED_AT --receipt APPLY_RECEIPT \
     --repository-root REPOSITORY_ROOT
   ```

6. Recheck store integrity, the target's effective and historical views, every
   route circuit, queue state and the persistent worker state.
7. Select one explicit `QUEUED / attempt_count=0` event with retained canonical
   input, current rights and no prior ingest, failure or model-usage evidence.
   Consume its append-only single-use authority before provider I/O, run it once
   in the foreground, and seal every non-terminal result as
   `CONFIGURATION_HELD` so it cannot be retried:

   ```sh
   uv run python scripts/issue_790_conservative_disposition.py canary \
     --store STORE --proving-store PROVING_STORE --backup CANARY_BACKUP \
     --plan docs/operations/2026-08-26-issue-790-conservative-disposition.json \
     --observed-at OBSERVED_AT --receipt CANARY_RECEIPT \
     --repository-root REPOSITORY_ROOT \
     --canary-event-id EVENT_ID --canary-ledger-seq LEDGER_SEQ \
     --disposition-digest DISPOSITION_DIGEST
   ```

   Do not invoke the canary command a second time, including after a provider,
   transport, rights or local failure. The retained authority and outcome rows
   are the proof that the one attempt has been consumed.

The operation grants no publication, public dispatch, backlog drain, bulk
requeue, Production Operational Admission, wider activation, provider
substitution, model substitution, token-limit removal or unrelated spend
disposition authority. Preserve every backup and all three receipts. A restore
requires a quiescent store and separate reviewed authority so that later
unrelated ledger writes are not discarded.
