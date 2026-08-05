# Pull-request lifecycle and housekeeping

Open pull requests are an operational queue, not an archive. Historical evidence
belongs in commits, workflow runs, comments and checkpoint refs. A PR must remain
open only while it represents current work.

## Lifecycle classes

Every PR declares exactly one class in the first metadata block of its body.

### Canonical

A canonical PR is the only merge candidate for one delivery atom.

```text
Lifecycle: canonical
Delivery-Atom: increment-5b3
Canonical-PR: self
Checkpoint-Ref: checkpoint/increment-5b3-final-YYYYMMDD
Close-When: merged
Branch-Retention: keep
```

There may be only one open canonical PR for the same `Delivery-Atom`. A canonical
PR is never auto-closed and never uses a `support/` or `preflight/` branch.

### Support

A support PR executes or materialises a bounded correction for one canonical PR.
It is always a draft and is never merged.

```text
Lifecycle: support
Delivery-Atom: increment-5b3
Canonical-PR: #123
Checkpoint-Ref: checkpoint/increment-5b3-correction-YYYYMMDD
Close-When: checkpointed
Branch-Retention: keep
```

The branch starts with `support/`. After the exact product tree is verified,
re-parented and checkpointed, close the support PR in the same work session. The
repository's existing `infra` label is the explicit automation opt-in; metadata
alone never authorizes automated closure.

### Preflight

A preflight PR reviews or verifies an exact immutable candidate for one canonical
PR. It is always a draft and is never merged.

```text
Lifecycle: preflight
Delivery-Atom: increment-5b3
Canonical-PR: #123
Checkpoint-Ref: NONE
Close-When: canonical-merged
Branch-Retention: keep
```

The branch starts with `preflight/`.

## Metadata contract

The following six fields are mandatory and unique:

```text
Lifecycle:
Delivery-Atom:
Canonical-PR:
Checkpoint-Ref:
Close-When:
Branch-Retention:
```

`Delivery-Atom` is a bounded lowercase identifier. `Canonical-PR` is `self` or
`#<number>`. `Checkpoint-Ref` is a safe branch ref or `NONE`.

Valid close conditions are:

- `merged`: canonical PR only;
- `checkpointed`: disposable PR closes after its declared checkpoint exists;
- `canonical-merged`: disposable PR closes after its canonical PR is merged.

Valid branch retention policies are:

- `keep`;
- `delete-after-checkpoint`.

Every non-`NONE` checkpoint uses the dedicated `checkpoint/` namespace.
Branch deletion is never permitted without an independently resolvable checkpoint
and is never attempted for a branch owned by another repository or fork.

## Operating limits

- One open canonical PR per delivery atom.
- No more than two open support/preflight PRs per canonical PR.
- A disposable PR closes in the same work session after its declared condition is
  satisfied.
- No unexplained open PR may remain older than seven days.
- Closing a PR does not delete its commits or branch unless the metadata explicitly
  requests deletion and a checkpoint exists.
- Canonical PRs are never closed by automation.

## Automation

`.github/workflows/pr-lifecycle.yml` runs trusted default-branch code.

On PR creation or metadata changes it validates the event body and actual PR
surface. Weekly scheduled runs and manual dispatches build a repository-wide
inventory. The dry-run job has read-only permissions. A separate write-capable
apply job can run only after the dry run succeeds.

Manual apply requires all three independently checked values:

1. workflow-dispatch input `apply=true`;
2. workflow-dispatch input `confirmation=CLOSE_ELIGIBLE_DISPOSABLE_PRS`; and
3. the exact `PR_HOUSEKEEPING_APPLY=CLOSE_ELIGIBLE_DISPOSABLE_PRS` process guard.

Both inventory jobs receive the workflow token explicitly; its effective rights
remain constrained by each job's permission block. Before every mutation, apply mode
re-reads the current PR body, labels, head repository, head SHA, checkpoint and
canonical merge state. A requested branch deletion additionally requires the
dedicated checkpoint and current same-repository head ref to resolve to the exact
PR head SHA before closure and again immediately before deletion. Apply mode comments
with an audit record before closing an eligible, `infra`-labelled disposable PR.
It never merges or closes a canonical PR. A branch is deleted only after its declared
checkpoint ref has been verified.

## Recovery

The source of truth for recovery is:

1. the canonical merge commit or exact candidate commit;
2. the product tree identity;
3. the checkpoint ref;
4. permanent and disposable workflow runs; and
5. closure comments.

An open support PR is not a recovery mechanism and must not be retained merely as
historical evidence.
