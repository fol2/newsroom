# Pull-request lifecycle and housekeeping

Open pull requests are an operational queue, not an archive. Historical evidence
belongs in commits, workflow runs, comments and checkpoint refs. A PR remains open
only while it represents current work.

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
Branch-Retention: delete-after-merge
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

The following six fields are mandatory. They must be the visible first six
lines of the PR body, in this exact order, with no blank line, HTML comment, code
fence or prose before them:

```text
Lifecycle:
Delivery-Atom:
Canonical-PR:
Checkpoint-Ref:
Close-When:
Branch-Retention:
```

Only that leading block is authoritative. Hidden comments, fenced examples and
later repeated fields are documentation only and are never parsed as lifecycle
metadata.

`Delivery-Atom` is a bounded lowercase identifier. The reserved placeholder
`replace-me` is invalid, and the repository template deliberately starts with the
syntactically invalid `REPLACE-ME` so an untouched template fails validation.
`Canonical-PR` is `self` or `#<number>`. `Checkpoint-Ref` is a safe branch ref or
`NONE`. Every non-`NONE` checkpoint uses the dedicated `checkpoint/` namespace.

Valid close conditions are:

- `merged`: canonical PR only;
- `checkpointed`: disposable PR closes only when its declared checkpoint resolves
  to its current head and its canonical binding remains valid;
- `canonical-merged`: disposable PR closes only after its canonical PR is
  independently revalidated as merged.

`Branch-Retention` has two supported values:

- `delete-after-merge`: canonical PRs only. GitHub's repository setting
  `delete_branch_on_merge` deletes the head branch at merge time.
- `keep`: disposable support/preflight PRs only. Those PRs are never merged, so
  GitHub does not delete their heads.

`delete-after-checkpoint` is unsupported. Housekeeping never calls GitHub's ref
deletion endpoint: that API has no compare-and-delete operation, so a check
followed by deletion cannot safely bind the mutation to the checked commit.
Checkpoint refs and disposable branches remain until an owner deletes them.

## Operating limits

- One open canonical PR per delivery atom.
- No more than two open support/preflight PRs per canonical PR.
- Duplicate same-repository open head refs fail the inventory closed.
- A disposable PR closes in the same work session after its declared condition is
  satisfied.
- No unexplained open PR may remain older than seven days.
- Canonical PRs are never closed by automation.
- Canonical head branches are deleted by GitHub at merge time
  (`delete_branch_on_merge`). Automated housekeeping never deletes a Git ref.

## Automation

`.github/workflows/pr-lifecycle.yml` runs trusted default-branch code.

On PR creation or metadata changes it validates the event body and actual PR
surface. Weekly scheduled runs and `mode=plan` manual dispatches build a
repository-wide inventory at one immutable `${{ github.sha }}`. Inventory resolves
every declared checkpoint to its full commit SHA; the planner emits a checkpointed
close action only when that SHA equals the inventoried PR head. A stale checkpoint
is reported as a warning and cannot block later eligible actions. Every close
action also embeds that inventoried full PR head SHA; an action is withheld when an
exact head is unavailable.

The plan job has read-only permissions, writes the complete deterministic mutation
plan to `pr-lifecycle-plan.json`, publishes it as an artifact and prints three
review coordinates: the immutable revision, the exact RFC3339 evaluation time and
the SHA-256 plan digest. The digest covers the repository, revision, evaluation
time, every open PR surface and lifecycle, every independently verified merged
canonical, every checkpoint SHA, every proposed close action (including its exact
PR head SHA) and every warning.

Apply is a separate `mode=apply` dispatch; it is never launched automatically by
the plan job. The operator must dispatch the exact reviewed revision and supply:

1. `reviewed_revision=<40-character reviewed revision>`;
2. `reviewed_evaluation_time=<reviewed RFC3339 UTC time>`;
3. `reviewed_plan_digest=<reviewed sha256 digest>`;
4. `confirmation=CLOSE_ELIGIBLE_DISPOSABLE_PRS`; and
5. the workflow supplies the independent
   `PR_HOUSEKEEPING_APPLY=CLOSE_ELIGIBLE_DISPOSABLE_PRS` process guard.

Both jobs check out the immutable dispatch SHA. Before any mutation, apply requires
the executing revision to equal the reviewed revision, rebuilds the complete plan
at the reviewed evaluation time and requires byte-canonical digest equality. Any
new PR, changed metadata, label, head, checkpoint, canonical state, action or
warning invalidates the reviewed plan.

Both inventory jobs receive the workflow token explicitly; its effective rights
remain constrained by each job's permission block. The apply job has only the issue
and pull-request write permissions needed to comment and close an eligible
disposable PR; repository contents remain read-only. It then re-reads the current
target PR state, body, labels, head repository, head SHA, checkpoint and canonical
binding before every effect. The re-read head SHA must equal the exact SHA embedded
in the reviewed close action; any drift fails closed before a comment or closure.
It never merges or closes a canonical PR and never deletes a Git ref. GitHub
itself may delete a merged canonical head when `delete_branch_on_merge` is
enabled.

## Recovery

The source of truth for recovery is:

1. the canonical merge commit or exact candidate commit;
2. the product tree identity;
3. the checkpoint ref;
4. permanent and disposable workflow runs; and
5. closure comments.

An open support PR is not a recovery mechanism and must not be retained merely as
historical evidence. Its branch and checkpoint may remain as immutable recovery
refs until an owner performs a separate, deliberate cleanup.
