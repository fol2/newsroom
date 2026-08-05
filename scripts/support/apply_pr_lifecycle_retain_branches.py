from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def write(relative_path: str, text: str) -> None:
    (ROOT / relative_path).write_text(text, encoding="utf-8")


def replace_once(relative_path: str, old: str, new: str) -> None:
    text = read(relative_path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"retain-branches anchor differs for {relative_path}: count={count}"
        )
    write(relative_path, text.replace(old, new, 1))


def replace_count(relative_path: str, old: str, new: str, expected: int) -> None:
    text = read(relative_path)
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"retain-branches repeated anchor differs for {relative_path}: "
            f"expected={expected} actual={count}"
        )
    write(relative_path, text.replace(old, new))


def function_span(text: str, name: str) -> tuple[int, int]:
    marker = f"def {name}("
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"missing function: {name}")
    candidates = [
        position
        for position in (
            text.find("\ndef ", start + len(marker)),
            text.find("\n@pytest.mark", start + len(marker)),
        )
        if position >= 0
    ]
    end = min(candidates) if candidates else len(text)
    return start, end


def replace_function(relative_path: str, name: str, replacement: str) -> None:
    text = read(relative_path)
    start, end = function_span(text, name)
    write(relative_path, text[:start] + replacement.rstrip() + "\n\n" + text[end + 1 :])


def remove_function(relative_path: str, name: str) -> None:
    text = read(relative_path)
    start, end = function_span(text, name)
    write(relative_path, text[:start] + text[end + 1 :])


def patch_contract() -> None:
    path = "newsroom/checks/pr_lifecycle.py"
    replace_once(
        path,
        """@dataclass(frozen=True, slots=True)
class CloseAction:
    pr_number: int
    reason: str
    delete_branch: str | None = None
""",
        """@dataclass(frozen=True, slots=True)
class CloseAction:
    pr_number: int
    reason: str
""",
    )
    replace_once(
        path,
        """    _validate_ref(head_ref, field="head_ref")

    if lifecycle.kind is LifecycleKind.CANONICAL:
""",
        """    _validate_ref(head_ref, field="head_ref")
    if lifecycle.branch_retention is not BranchRetention.KEEP:
        raise PrLifecycleError(
            "automatic branch deletion is unsupported; "
            "Branch-Retention must be keep"
        )

    if lifecycle.kind is LifecycleKind.CANONICAL:
""",
    )
    deletion_shape = """    if (
        lifecycle.branch_retention is BranchRetention.DELETE_AFTER_CHECKPOINT
        and lifecycle.checkpoint_ref is None
    ):
        raise PrLifecycleError(
            "branch deletion requires a checkpoint ref"
        )
"""
    replace_count(path, deletion_shape, "", 1)
    replace_once(
        path,
        """        delete_branch: str | None = None
        if lifecycle.branch_retention is BranchRetention.DELETE_AFTER_CHECKPOINT:
            if (
                lifecycle.checkpoint_ref is None
                or lifecycle.checkpoint_ref not in existing_checkpoint_refs
            ):
                raise PrLifecycleError(
                    f"#{pr.number} branch deletion lacks a verified checkpoint"
                )
            if (
                repository_full_name is None
                or pr.head_repository != repository_full_name
            ):
                raise PrLifecycleError(
                    f"#{pr.number} branch deletion cannot target an external repository"
                )
            delete_branch = pr.head_ref
        actions.append(
            CloseAction(
                pr_number=pr.number,
                reason=close_reason,
                delete_branch=delete_branch,
            )
        )
""",
        """        actions.append(
            CloseAction(
                pr_number=pr.number,
                reason=close_reason,
            )
        )
""",
    )
    replace_once(
        path,
        """    if lifecycle.kind is LifecycleKind.CANONICAL:
""",
        """    if lifecycle.branch_retention is not BranchRetention.KEEP:
        raise PrLifecycleError(
            "automatic branch deletion is unsupported; "
            "Branch-Retention must be keep"
        )
    if lifecycle.kind is LifecycleKind.CANONICAL:
""",
    )
    deletion_shape_tail = """    if (
        lifecycle.branch_retention is BranchRetention.DELETE_AFTER_CHECKPOINT
        and lifecycle.checkpoint_ref is None
    ):
        raise PrLifecycleError("branch deletion requires checkpoint ref")
"""
    replace_count(path, deletion_shape_tail, "", 1)


def patch_cli() -> None:
    path = "scripts/sdlc/pr_lifecycle.py"
    replace_once(
        path,
        """    def delete_branch(self, ref: str) -> None:
        encoded = quote(ref, safe="")
        self.request("DELETE", f"/git/refs/heads/{encoded}")

""",
        "",
    )
    remove_function(path, "_require_exclusive_current_head")
    replace_once(
        path,
        """        expected_delete_branch = (
            current.head_ref
            if lifecycle.branch_retention.value == "delete-after-checkpoint"
            else None
        )
        if action.delete_branch != expected_delete_branch:
            raise GithubApiError(
                f"pull request #{action.pr_number} retention differs from its plan"
            )
""",
        """        if lifecycle.branch_retention.value != "keep":
            raise GithubApiError(
                f"pull request #{action.pr_number} requests unsupported "
                "automatic branch deletion"
            )
""",
    )
    replace_once(
        path,
        """        if action.delete_branch is not None:
            checkpoint_sha = (
                None if checkpoint is None else client.branch_sha(checkpoint)
            )
            head_sha = client.branch_sha(current.head_ref)
            if (
                current.head_repository != repository
                or current.head_ref != action.delete_branch
                or current.head_sha is None
                or checkpoint_sha != current.head_sha
                or head_sha != current.head_sha
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} branch deletion is no longer safe"
                )
            _require_exclusive_current_head(
                client,
                current=current,
                repository=repository,
            )
""",
        "",
    )
    replace_once(
        path,
        """                f"- Branch deletion: `{action.delete_branch or 'NONE'}`",
""",
        """                "- Automatic branch deletion: `DISABLED`",
                "- Branch retention: `keep`",
""",
    )
    replace_once(
        path,
        """        client.comment(action.pr_number, comment)
        client.close_pull_request(action.pr_number)
        if action.delete_branch is not None:
            assert checkpoint is not None
            final_head_sha = client.branch_sha(action.delete_branch)
            final_checkpoint_sha = client.branch_sha(checkpoint)
            if (
                current.head_sha is None
                or final_head_sha != current.head_sha
                or final_checkpoint_sha != current.head_sha
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} branch changed before deletion"
                )
            _require_exclusive_current_head(
                client,
                current=current,
                repository=repository,
            )
            client.delete_branch(action.delete_branch)
""",
        """        client.comment(action.pr_number, comment)
        client.close_pull_request(action.pr_number)
""",
    )
    replace_once(
        path,
        """        f"- Age warnings: `{len(plan.warnings)}`",
        "",
""",
        """        f"- Age warnings: `{len(plan.warnings)}`",
        "- Automatic branch deletion: `DISABLED`",
        "",
""",
    )
    replace_once(
        path,
        """        lines.extend(
            (
                "| PR | Reason | Delete branch |",
                "|---:|---|---|",
            )
        )
        lines.extend(
            f"| #{item.pr_number} | {item.reason} | "
            f"`{item.delete_branch or 'NONE'}` |"
            for item in plan.close_actions
        )
""",
        """        lines.extend(
            (
                "| PR | Reason |",
                "|---:|---|",
            )
        )
        lines.extend(
            f"| #{item.pr_number} | {item.reason} |"
            for item in plan.close_actions
        )
""",
    )


def patch_tests() -> None:
    path = "newsroom/tests/test_pr_lifecycle.py"
    replace_once(
        path,
        """    assert plan.close_actions[0].delete_branch is None
""",
        """    assert set(plan.close_actions[0].__dataclass_fields__) == {
        "pr_number",
        "reason",
    }
""",
    )
    replace_function(
        path,
        "test_plan_closes_after_canonical_merge_and_can_delete_branch",
        """def test_automatic_branch_deletion_metadata_is_rejected() -> None:
    with pytest.raises(
        PrLifecycleError,
        match="automatic branch deletion is unsupported",
    ):
        parse_pr_lifecycle(
            body(
                lifecycle="support",
                canonical="#10",
                close_when="canonical-merged",
                retention="delete-after-checkpoint",
            )
        )
""",
    )

    text = read(path)
    start, end = function_span(text, "test_plan_rejects_shared_same_repository_head_refs")
    section = text[start:end]
    if section.count('retention="delete-after-checkpoint"') != 1:
        raise SystemExit("shared-head test deletion-retention anchor differs")
    section = section.replace(
        'retention="delete-after-checkpoint"',
        'retention="keep"',
        1,
    )
    write(path, text[:start] + section + text[end:])

    for name in (
        "test_external_fork_branch_is_never_deleted",
        "test_apply_refuses_branch_shared_by_another_open_pr",
        "test_apply_rejects_retention_change_after_planning",
        "test_apply_rejects_checkpoint_not_bound_to_current_head",
    ):
        remove_function(path, name)

    replace_function(
        path,
        "test_workflow_separates_dry_run_and_two_key_apply",
        """def test_workflow_separates_dry_run_and_two_key_apply() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (
        repository_root / ".github/workflows/pr-lifecycle.yml"
    ).read_text(encoding="utf-8")
    cli = (
        repository_root / "scripts/sdlc/pr_lifecycle.py"
    ).read_text(encoding="utf-8")

    assert "inventory-dry-run:" in workflow
    assert "inventory-apply:" in workflow
    assert "inputs.apply == true" in workflow
    assert (
        "inputs.confirmation == 'CLOSE_ELIGIBLE_DISPOSABLE_PRS'"
        in workflow
    )
    assert "PR_HOUSEKEEPING_APPLY: CLOSE_ELIGIBLE_DISPOSABLE_PRS" in workflow
    assert workflow.count("GITHUB_TOKEN: ${{ github.token }}") == 2
    assert "python scripts/sdlc/pr_lifecycle.py" not in workflow
    apply_permissions = workflow.split("inventory-apply:", 1)[1].split(
        "runs-on:", 1
    )[0]
    assert "contents: read" in apply_permissions
    assert "contents: write" not in workflow
    assert "def delete_branch" not in cli
    assert "client.delete_branch" not in cli
    assert 'request("DELETE", f"/git/refs/heads/' not in cli
    assert "Automatic branch deletion: `DISABLED`" in cli
""",
    )
    replace_function(
        path,
        "test_checkpoint_deletion_fails_closed_without_verified_ref",
        """def test_close_action_has_no_branch_deletion_capability() -> None:
    assert set(CloseAction.__dataclass_fields__) == {"pr_number", "reason"}
    action = CloseAction(pr_number=11, reason="checkpoint verified")
    assert action.pr_number == 11
    assert action.reason == "checkpoint verified"
""",
    )


def patch_static_files() -> None:
    template = """Lifecycle: canonical
Delivery-Atom: replace-me
Canonical-PR: self
Checkpoint-Ref: NONE
Close-When: merged
Branch-Retention: keep

<!--
Required lifecycle metadata:
- canonical: Canonical-PR self, Close-When merged, Branch-Retention keep
- support: draft, support/ branch, reference canonical #, never merge
- preflight: draft, preflight/ branch, reference canonical #, never merge
- Branch-Retention must always be keep; automated branch deletion is unsupported.
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

List focused tests, complete repository evidence, permanent workflows and current
review state.

## Non-effects

State explicitly what this PR does not activate, mutate or authorize.
"""
    write(".github/pull_request_template.md", template)

    docs = """# Pull-request lifecycle and housekeeping

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
`#<number>`. `Checkpoint-Ref` is a safe branch ref or `NONE`. Every non-`NONE`
checkpoint uses the dedicated `checkpoint/` namespace.

Valid close conditions are:

- `merged`: canonical PR only;
- `checkpointed`: disposable PR closes only when its declared checkpoint resolves
  to its current head and its canonical binding remains valid;
- `canonical-merged`: disposable PR closes only after its canonical PR is
  independently revalidated as merged.

`Branch-Retention` has exactly one supported value: `keep`. Automated branch
cleanup is deliberately unsupported. GitHub's ref deletion endpoint has no
compare-and-delete operation, so a check followed by deletion cannot safely bind
the mutation to the checked commit. Branch cleanup is therefore a separate manual
owner action outside this automation; checkpoint refs and disposable branches are
retained by every automated closure.

## Operating limits

- One open canonical PR per delivery atom.
- No more than two open support/preflight PRs per canonical PR.
- Duplicate same-repository open head refs fail the inventory closed.
- A disposable PR closes in the same work session after its declared condition is
  satisfied.
- No unexplained open PR may remain older than seven days.
- Canonical PRs are never closed by automation.
- Automated housekeeping never deletes a Git ref.

## Automation

`.github/workflows/pr-lifecycle.yml` runs trusted default-branch code.

On PR creation or metadata changes it validates the event body and actual PR
surface. Weekly scheduled runs and manual dispatches build a repository-wide
inventory. The dry-run job has read-only permissions. A separate apply job has
only the issue and pull-request write permissions needed to comment and close an
eligible disposable PR; repository contents remain read-only.

Manual apply requires all three independently checked values:

1. workflow-dispatch input `apply=true`;
2. workflow-dispatch input `confirmation=CLOSE_ELIGIBLE_DISPOSABLE_PRS`; and
3. the exact `PR_HOUSEKEEPING_APPLY=CLOSE_ELIGIBLE_DISPOSABLE_PRS` process guard.

Both inventory jobs receive the workflow token explicitly; its effective rights
remain constrained by each job's permission block. Before every mutation, apply
mode re-reads the current PR state, body, labels, head repository, head SHA,
checkpoint and canonical binding. The target must remain open and unmerged, the
lifecycle must match the planned snapshot, and checkpointed closures must bind the
checkpoint to the current head. Apply comments with an audit record before closing
an eligible, `infra`-labelled disposable PR. It never merges or closes a canonical
PR and never deletes a branch.

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
"""
    write("docs/operations/pr-lifecycle.md", docs)

    replace_once(
        ".github/workflows/pr-lifecycle.yml",
        """    permissions:
      contents: write
      issues: write
      pull-requests: write
""",
        """    permissions:
      contents: read
      issues: write
      pull-requests: write
""",
    )


def main() -> None:
    patch_contract()
    patch_cli()
    patch_tests()
    patch_static_files()


if __name__ == "__main__":
    main()
