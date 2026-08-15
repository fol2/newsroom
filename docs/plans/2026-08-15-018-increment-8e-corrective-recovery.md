# Increment 8E corrective recovery authority

Issue: #467

## Boundary

This correction remains fixture and replay evidence only. It introduces no live
recovery authority, provider, credential, egress, spend, publication, shadow,
canary, permanent-locality or production effect.

## Corrected invariants

- `FaultInjectionRun` is reconstructed from canonical bytes and its exact
  scenario, expected outcome, observed outcome, derived status and non-effect
  flag are checked before retained scalar columns are written.
- `RecoveryAuthority` accepts only an idle schema-v32 SQLite connection with
  foreign-key enforcement already enabled and rechecks that setting immediately
  before every write; the authority does not silently change caller policy.
- Every `DueWork` supplied to catch-up planning is reconstructed, checked against
  the complete operational payload/state rules and compared with the supplied
  object before parsed-deadline ordering or bounded selection.
- A failed backup removes only the incomplete destination created by that
  attempt, so the same absent path can be retried while pre-existing paths remain
  protected by exclusive creation.
- Restore validates completion evidence before copying, rejects an absent
  destination parent and removes its own incomplete destination after copy or
  logical-integrity failure.

## Evidence

- focused recovery suite: 16 passed;
- complete Increment 8 suite: 131 passed;
- new regressions cover disabled foreign keys, active transactions,
  self-consistent fault forgery, detached DueWork, retry after failed backup,
  missing restore parent and partial-restore cleanup.

Authoritative exact-head CI, substantive review and merge evidence are recorded
on the canonical pull request before issue closure.
