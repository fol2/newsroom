# Increment 8A evaluation authority

**Issue:** #463
**Dependency:** #462 / `main@c3b28284`
**Authority schema:** v30 / `increment8_evaluation_authority_v30`

Increment 8A implements append-only Evaluation Plan, frozen Epoch, Run, Case,
review label, adjudication and release-evidence records.  The retained Plan
embeds the exact numerical 8R values and its readiness digest; an alternative
threshold or Profile is a different authority record and cannot enter the v1
qualification Epoch silently.

Qualification Cases must be prospective and event-level.  Rights-limited
material has an explicit `UNREVIEWABLE` state and cannot receive a fabricated
label.  Primary and secondary reviewers are distinct.  A disagreeing pair
requires a third independent adjudicator and the disagreement remains retained.

The release authority rejects a PASS for calibration, early stop, missing
metric or slice gates, any zero-tolerance failure, fewer than 120 Cases, fewer
than eight exposed required slices, missing primary reviews, less than the
pre-registered 20% ordinary second-review sample, missing second review for a
blocker/Urgent/zero-tolerance Case, or unresolved disagreement.

The additive v30 migration requires a content-verified exact v29 backup before
upgrade and retains all seven record classes behind update and delete guards.
Fresh-create, exact-predecessor upgrade, backup, integrity and replay are
deterministic.

This authority makes no provider request, uses no credential, performs no
external egress or spend, and cannot authorise publication, shadow, canary or
production activation.
