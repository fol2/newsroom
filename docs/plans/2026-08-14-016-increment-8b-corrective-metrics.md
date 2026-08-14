# Increment 8B corrective metrics authority

Issue: #464  
Parent: #148  
Dependency: #463

## Corrected authority boundary

A Metric Report is now constructed from the exact canonical Evaluation Plan,
Epoch and qualification Run, plus one canonical `ReviewedCaseOutcome` for each
prospective, reviewable Case. Each outcome embeds the frozen Case and the
primary human ReviewLabel. The label token is the digest of the complete
per-Case assessment, so caller-supplied aggregate counts or booleans cannot be
substituted for reviewed evidence.

The report derives, rather than accepts:

- total reviewed Case exposure;
- every pre-registered rate numerator and denominator;
- all nine Required Slice memberships, completed counts and successes;
- negative, unchanged and failure-heavy stratum exposure;
- every zero-tolerance count; and
- the separately reported false-development, missed-development and
  false-correction error measurements.

Canonical reconstruction checks the complete Plan/Epoch/Run chain, every Case,
ReviewLabel, assessment, rate, performance result, slice result, zero-tolerance
record, source contribution and ablation. The release authority additionally
compares the report's exact Case and primary-label identities with its retained
append-only records.

Source contribution evidence retains sorted dependency-root digests and the
report emits the root-to-source inventory. Shared wire or upstream roots are
therefore visible and cannot masquerade as independently attributable sources.

## Decision rules

A confirmed zero-tolerance finding is always `FAIL`, including when another
exposure is insufficient. Missing total, slice, stratum or authorised-reviewer
exposure is `NOT_EVALUATED`. Target metric, slice or performance failure is
`FAIL`; ablation evidence remains non-decision-bearing.

Development and correction errors are mandatory separate measurements. Their
record explicitly forbids a post-hoc threshold; Increment 8B does not invent a
new release value outside the frozen readiness contract.

## Non-effects

This correction performs deterministic fixture/replay measurement only. It
adds no persistence migration and authorises no live provider, credential,
egress, spend, locality activation, shadow, canary or production effect.
