# Increment 8F1 corrective product admission authority

Issue: #479

## Boundary

This atom corrects product-side fixture qualification authority only. It does
not activate the readiness gates, execute qualification, alter SDLC workflows,
or grant a live provider, credential, egress, spend, publication, shadow,
canary, permanent-locality or production effect.

## Corrected invariants

- Every evidence object is reconstructed from its canonical bytes and compared
  with the supplied dataclass before any detached field is trusted.
- Capacity, health, observability, security, reconciliation, backup, restore,
  fault, Handoff-anchor, hardware and cost/licence semantics are recomputed and
  cross-bound to the release decision and strict Metric Report.
- The canonical, owner-approved frozen Operational Profile is retained and all
  profile-scoped evidence is bound to its exact digest.
- Post-restore reconciliation identifies the exact Restore Run and restored
  logical state; rollback evidence binds that same state.
- The Qualification Packet retains the complete canonical evidence inventory as
  well as its digest inventory. Its parser verifies exact schema, key sets,
  canonical bytes, digests, passing semantics, non-effect flags, schema-v32
  identity, readiness digest and cross-evidence relationships.
- Rollback and independent-verification gates are typed canonical evidence
  records retained inside the packet; bare caller-supplied digests are no longer
  accepted as proof that either artifact exists.
- `build_operational_admission_decision()` reconstructs that entire packet and
  requires exact dataclass equality and an admission owner distinct from the
  independent verifier before it can emit
  `FIXTURE_OPERATIONAL_ADMITTED` and planning-only Increment 9 eligibility.
- The Operational Admission decision has its own strict canonical parser and
  fixed non-activation semantics.

## Local evidence

- focused 8F product tests: 12 passed;
- complete Increment 8 tests: 139 passed;
- Ruff and `git diff --check`: passed.

Exact-head substantive review and authoritative CI/SDLC evidence are recorded
on the canonical pull request before merge and issue closure.
