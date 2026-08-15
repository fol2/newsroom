# Increment 8D corrective observability and security

Issue: #466
Parent: #148
Dependencies satisfied: #462, #463 and #464

## Corrective contract

- HTTP `206 Partial Content` is retained as `PARTIAL`, never as a complete changed observation.
- Health freshness is decided using the full timestamp precision. The rendered integer age is evidence only and cannot floor an over-threshold observation into a healthy verdict.
- Every CLOSED Incident binds its exact closure-evidence digest in canonical bytes. Different closure evidence therefore produces a different immutable Incident digest.
- Incident transitions reconstruct and validate the exact canonical retained record before deriving the next Version, rejecting caller-mutated dataclass fields and malformed closure evidence.

## Evidence

Focused regressions cover `206`, the exact freshness threshold and threshold plus one microsecond, malformed closure evidence, closure-digest identity and caller-mutated Incident objects. The complete Increment 8 test set remains green.

## Non-effects

Fixture observability and security evidence only. No live credential, provider, egress, incident action, spend, shadow, canary, publication, production or locality effect. This atom does not construct Operational Admission.
