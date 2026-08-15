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
- Lease closure cannot be appended independently: the closure Version and matching COMPLETED, RETRY_PENDING or QUARANTINED DueWork Version are committed together in one transaction, eliminating the closed-lease/LEASED-work crash gap.
- Acquisition now enforces the retained deadline upper bound as well as the due/backoff lower bound; expired work remains explicit-close authority.
- Retry failure time must be on or after the exact active lease acquisition and is rechecked inside Finding insertion.
- Routine fairness uses only a duplicate-class slot, preserving at least one selected item from every present higher-priority class.
- Renewal expiry cannot extend by more than one frozen renewal interval, including for directly constructed canonical records.
- Retry Findings require failure time within the exact active lease interval in both prevalidation and the serialised insertion predicate.
- Lease closure retains canonical `closed_at`; RELEASED completion/retry evidence must be within the effective lease, while an expired lease can still close as ORPHANED with atomic quarantine.
- Retry Findings bind the first retained acquisition and enforce the frozen maximum total elapsed horizon, including a strict bound on the scheduled backoff instant.
- RELEASED completion and retry outcomes must not outlive either the effective lease or the retained DueWork deadline, and RETRY_PENDING closure cannot predate its exact RetryFinding failure time.
- The Routine fairness slot selects the longest-waiting parsed canonical `due_at` instant first, then deadline and identity, so equivalent timestamp spellings cannot change priority.
- Retry Finding insertion rechecks the exact active lease timestamps selected by parsed-instant prevalidation, avoiding lexical timestamp ordering inside the serialised predicate.
- Starvation deadline tie-breaking also uses parsed instants, so equivalent ISO timestamp spellings cannot defer the earliest deadline.
- General same-priority scheduling orders parsed deadline instants before applying the catch-up bound.
- The retained first attempt is selected by parsed acquisition instant, and the serialised Finding insert binds the unchanged lease inventory rather than SQLite text ordering.
- RETRY_PENDING acquisition is rejected at or beyond the frozen maximum total elapsed horizon, even when its backoff due time and work deadline would otherwise permit it.
- Lease renewal reconstructs the latest retained work, rejects expiry beyond its deadline and rechecks both exact lease and work predecessors inside the serialised transaction.
- Initial lease expiry and maximum ownership are capped at the retained work deadline. Every renewal retains its exact `renewed_at` instant and is reconstructed through `renew_lease`, so an expired predecessor cannot be resurrected by direct record construction.
- Retry lease records retain an exact `authority_deadline_at` equal to the earlier of the work deadline and frozen total retry horizon; both initial and maximum expiry are reconstructed and capped at that authority boundary.
- The public lease builder requires that bound for RETRY_PENDING work rather than producing an unusable record. Renewal derives the same bound from retained DueWork and RetryFinding history, including a compatibility path that upgrades an older active lease record on its next renewal.
- That legacy upgrade clamps an older uncapped effective expiry and maximum expiry to the derived authority deadline before validating the renewal instant.
- Direct closure derives the same authority deadline from retained DueWork and RetryFinding history, so an older unrenewed retry lease cannot release an outcome after the frozen total elapsed horizon.
- Legacy retry findings without `first_attempt_at` derive it from parsed retained lease history, and legacy active leases without `closed_at` upgrade with an explicit null closure value.
- The same legacy first-attempt derivation is used before acquiring RETRY_PENDING work, so restarted pre-correction Findings remain schedulable within their frozen horizon.
- Before any legacy or current retry authority is consumed, the exact attempt lease is reconstructed, must be RELEASED rather than still ACTIVE, and must contain `failed_at` within its acquisition/expiry interval. Inconsistent legacy state remains reconciliation-blocked instead of leaking another host slot.
- Pre-acquisition retry validation additionally rejects any ACTIVE lease retained for the work, not only the immediate predecessor lease ID, so older leaked attempts cannot survive beside a new host-concurrency slot.
- Closure recomputes the deterministic lease ID from the latest LEASED work attempt and rejects any older leaked lease ID, preserving exact work/lease lineage.
