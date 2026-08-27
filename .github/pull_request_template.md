Lifecycle: canonical
Delivery-Atom: REPLACE-ME
Canonical-PR: self
Checkpoint-Ref: NONE
Close-When: merged
Branch-Retention: delete-after-merge

Focus-Gates: AUTO
Manifest-Digest: AUTO
Selected-Tests: AUTO
Research-Lane: no
Full-Health: no

<!--
The first six lifecycle lines remain authoritative for PR lifecycle handling.
The Focus Gate fields record the deterministic ordinary-PR route; they do not
authorise service, research, release, deployment or activation effects.
See docs/operations/pr-lifecycle.md and docs/testing.md.
-->

## Intent

State the single coherent problem and the user or repository outcome.

## Exact state

```text
base:
head:
tree:
commits over base:
changed files:
```

## Focus Gate evidence

Record the manifest digest, F0-F4 gates, selected tests, outcomes, elapsed time,
anything deliberately not run and remaining uncertainty. Observe remote state
once; do not poll or rerun unchanged evidence.

## Review

Record the one feature-complete review and any relevant fixes. A second review
requires a material follow-up change or unresolved high-risk finding.

## Non-effects

State what this PR does not activate, mutate, publish, deploy or authorise.
