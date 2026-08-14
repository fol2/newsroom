# Increment 8C corrective operations

Issue: #465
Parent: #148
Dependency satisfied: #463

## Corrective contract

- A retry lease is reconstructed from the latest retained DueWork Version, never the oldest queued Version.
- RETRY_PENDING work becomes due only at the exact canonical RetryFinding `next_due_at`; acquisition before that instant is rejected.
- Attempts advance exactly once on each lease and a RETRY_PENDING transition requires its canonical latest-work RetryFinding.
- Initial quarantine authority accepts only the canonical ACTIVE origin. Release approval remains authenticated, append-only and history-preserving.
- Queue capacity, urgent reserve, latest-work identity and host lease capacity are rechecked inside the serialised `BEGIN IMMEDIATE` insertion statement so concurrent writers cannot oversubscribe the frozen Operational Profile.
- The authority verifies SQLite foreign-key enforcement after activation.

## Evidence

Corrective regressions cover multi-attempt retry lineage and backoff, early retry acquisition, direct quarantine construction, missing retry evidence, exact attempt advancement, concurrent queue admission and concurrent lease admission.

## Non-effects

Fixture operational authority only. No production scheduler activation, live provider, credentials, external egress, spend, shadow, canary, publication or locality effect.

## Review corrections

- Initial acquisition now commits the WorkLease and matching LEASED DueWork Version in one `BEGIN IMMEDIATE` transaction; restart cannot expose a leased item as due or strand it behind a deterministic lease identifier.
- Both queued and retry acquisition enforce their exact due instant inside that same transaction.
- Routine work that reaches the frozen starvation limit is promoted before the catch-up bound is applied.
- Terminal retry Findings cannot create RETRY_PENDING work, and Finding insertion rechecks latest-work identity inside its serialised statement.
- Version-one DueWork is reconstructed as the exact canonical QUEUED origin; every LEASED state is rejected from the general append path.
- Starvation fairness reserves at most one bounded catch-up slot for the oldest starved Routine item while retaining an Urgent item whenever the batch can contain both.
- A DueWork transition out of LEASED is conditionally inserted only after every active lease for that work is closed; retry attempts therefore cannot leak host-concurrency slots.
