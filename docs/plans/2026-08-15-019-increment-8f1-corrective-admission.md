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
- The Qualification Packet retains the complete canonical evidence inventory as
  well as its digest inventory. Its parser verifies exact schema, key sets,
  canonical bytes, digests, passing semantics, non-effect flags, schema-v32
  identity, readiness digest and cross-evidence relationships.
- `build_operational_admission_decision()` reconstructs that entire packet and
  requires exact dataclass equality before it can emit
  `FIXTURE_OPERATIONAL_ADMITTED` and planning-only Increment 9 eligibility.
- The Operational Admission decision has its own strict canonical parser and
  fixed non-activation semantics.

## Local evidence

- focused 8F product tests: 11 passed;
- complete Increment 8 tests: 138 passed;
- Ruff and `git diff --check`: passed.

Exact-head substantive review and authoritative CI/SDLC evidence are recorded
on the canonical pull request before merge and issue closure.
