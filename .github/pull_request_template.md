Lifecycle: canonical
Delivery-Atom: REPLACE-ME
Canonical-PR: self
Checkpoint-Ref: NONE
Close-When: merged
Branch-Retention: delete-after-merge

<!--
Required lifecycle metadata:
- the six visible metadata lines above must remain the first six body lines
- hidden comments, fenced examples and later fields are never authoritative
- canonical: Canonical-PR self, Close-When merged, Branch-Retention delete-after-merge
- support: draft, support/ branch, reference canonical #, never merge, Branch-Retention keep
- preflight: draft, preflight/ branch, reference canonical #, never merge, Branch-Retention keep
- GitHub deletes canonical heads on merge; housekeeping never DELETE git refs.
See docs/operations/pr-lifecycle.md.
-->

## Scope

Describe the independently attributable delivery atom.

## Exact state

```text
base:
head:
tree:
commits over base:
changed files:
```

## Verification

List the one decision-validated exact-head SDLC core receipt that supplies
canonical complete deterministic evidence. Record fast CI and any manually run
legacy diagnostics as compatibility signals only. For Tier S, add only the
affected lanes selected by the route. Reserve the signed exact-main closeout
attestation for Tier M. Record one feature-complete stop and its review state.

## Non-effects

State explicitly what this PR does not activate, mutate or authorize.
