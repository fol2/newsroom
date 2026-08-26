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

List the focused checks selected for this change, their outcomes, and anything
not run. If remote automation is already available, record its observed state
once. Do not wait, poll, or rerun the same check against unchanged code,
configuration and environment merely to fill this section. Agent handover does
not override the repository's current merge policy. See `docs/testing.md`.

## Non-effects

State explicitly what this PR does not activate, mutate or authorize.
