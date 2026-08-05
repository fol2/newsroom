from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from newsroom.checks.pr_lifecycle import (
    BranchRetention,
    CloseWhen,
    LifecycleKind,
    OpenPullRequest,
    PrLifecycleError,
    parse_pr_lifecycle,
    plan_housekeeping,
    validate_pull_request_event,
    validate_pull_request_lifecycle,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def body(
    *,
    lifecycle: str = "canonical",
    atom: str = "increment-5b2",
    canonical: str = "self",
    checkpoint: str = "checkpoint/increment-5b2",
    close_when: str = "merged",
    retention: str = "keep",
) -> str:
    return "\n".join(
        (
            f"Lifecycle: {lifecycle}",
            f"Delivery-Atom: {atom}",
            f"Canonical-PR: {canonical}",
            f"Checkpoint-Ref: {checkpoint}",
            f"Close-When: {close_when}",
            f"Branch-Retention: {retention}",
            "",
            "## Scope",
            "Product change.",
        )
    )


def open_pr(
    number: int,
    *,
    pr_body: str,
    draft: bool,
    head_ref: str,
    age_days: int = 0,
) -> OpenPullRequest:
    return OpenPullRequest(
        number=number,
        body=pr_body,
        draft=draft,
        head_ref=head_ref,
        created_at=NOW - timedelta(days=age_days),
    )


def test_parse_canonical_lifecycle() -> None:
    lifecycle = parse_pr_lifecycle(body())

    assert lifecycle.kind is LifecycleKind.CANONICAL
    assert lifecycle.delivery_atom == "increment-5b2"
    assert lifecycle.canonical_pr is None
    assert lifecycle.checkpoint_ref == "checkpoint/increment-5b2"
    assert lifecycle.close_when is CloseWhen.MERGED
    assert lifecycle.branch_retention is BranchRetention.KEEP


def test_parser_rejects_missing_duplicate_and_unsafe_metadata() -> None:
    with pytest.raises(PrLifecycleError, match="missing lifecycle fields"):
        parse_pr_lifecycle("Lifecycle: canonical")
    with pytest.raises(PrLifecycleError, match="duplicate lifecycle fields"):
        parse_pr_lifecycle(body() + "\nLifecycle: support")
    with pytest.raises(PrLifecycleError, match="safe bounded Git ref"):
        parse_pr_lifecycle(body(checkpoint="checkpoint/../escape"))


def test_canonical_surface_cannot_use_disposable_semantics() -> None:
    with pytest.raises(PrLifecycleError, match="canonical lifecycle"):
        parse_pr_lifecycle(body(close_when="checkpointed"))
    lifecycle = parse_pr_lifecycle(body())
    with pytest.raises(PrLifecycleError, match="disposable branch prefix"):
        validate_pull_request_lifecycle(
            lifecycle,
            pr_number=10,
            draft=False,
            head_ref="support/not-canonical",
        )


def test_support_and_preflight_require_draft_and_matching_prefix() -> None:
    support = parse_pr_lifecycle(
        body(
            lifecycle="support",
            canonical="#10",
            close_when="checkpointed",
        )
    )
    validate_pull_request_lifecycle(
        support,
        pr_number=11,
        draft=True,
        head_ref="support/increment-5b2-correction",
    )
    with pytest.raises(PrLifecycleError, match="must remain drafts"):
        validate_pull_request_lifecycle(
            support,
            pr_number=11,
            draft=False,
            head_ref="support/increment-5b2-correction",
        )

    preflight = parse_pr_lifecycle(
        body(
            lifecycle="preflight",
            canonical="#10",
            close_when="canonical-merged",
            checkpoint="NONE",
        )
    )
    validate_pull_request_lifecycle(
        preflight,
        pr_number=12,
        draft=True,
        head_ref="preflight/increment-5b2-exact-tree",
    )


def test_validate_pull_request_event_uses_actual_surface() -> None:
    event = {
        "pull_request": {
            "number": 11,
            "draft": True,
            "body": body(
                lifecycle="support",
                canonical="#10",
                close_when="checkpointed",
            ),
            "head": {"ref": "support/increment-5b2-correction"},
        }
    }
    lifecycle = validate_pull_request_event(event)
    assert lifecycle.kind is LifecycleKind.SUPPORT
    assert lifecycle.canonical_pr == 10


def test_plan_never_closes_canonical_and_closes_checkpointed_support() -> None:
    canonical = open_pr(
        10,
        pr_body=body(),
        draft=False,
        head_ref="agent/increment-5b2",
    )
    support = open_pr(
        11,
        pr_body=body(
            lifecycle="support",
            canonical="#10",
            close_when="checkpointed",
        ),
        draft=True,
        head_ref="support/increment-5b2-correction",
    )
    plan = plan_housekeeping(
        (canonical, support),
        existing_checkpoint_refs=frozenset(
            {"checkpoint/increment-5b2"}
        ),
        now=NOW,
    )

    assert [item.pr_number for item in plan.close_actions] == [11]
    assert "checkpoint/increment-5b2" in plan.close_actions[0].reason
    assert plan.close_actions[0].delete_branch is None


def test_plan_closes_after_canonical_merge_and_can_delete_branch() -> None:
    support = open_pr(
        11,
        pr_body=body(
            lifecycle="support",
            canonical="#10",
            close_when="canonical-merged",
            retention="delete-after-checkpoint",
        ),
        draft=True,
        head_ref="support/increment-5b2-correction",
    )
    plan = plan_housekeeping(
        (support,),
        merged_canonical_prs=frozenset({10}),
        existing_checkpoint_refs=frozenset(
            {"checkpoint/increment-5b2"}
        ),
        now=NOW,
    )

    assert plan.close_actions == (
        type(plan.close_actions[0])(
            pr_number=11,
            reason="canonical PR #10 is merged",
            delete_branch="support/increment-5b2-correction",
        ),
    )


def test_plan_rejects_unknown_or_mismatched_canonical_reference() -> None:
    support = open_pr(
        11,
        pr_body=body(
            lifecycle="support",
            canonical="#10",
            close_when="checkpointed",
        ),
        draft=True,
        head_ref="support/increment-5b2-correction",
    )
    with pytest.raises(PrLifecycleError, match="neither an open nor merged"):
        plan_housekeeping((support,), now=NOW)

    canonical = open_pr(
        10,
        pr_body=body(atom="another-atom"),
        draft=False,
        head_ref="agent/another-atom",
    )
    with pytest.raises(PrLifecycleError, match="delivery atom differs"):
        plan_housekeeping((canonical, support), now=NOW)


def test_plan_rejects_multiple_canonical_prs_for_one_atom() -> None:
    first = open_pr(
        10,
        pr_body=body(),
        draft=True,
        head_ref="agent/increment-5b2-a",
    )
    second = open_pr(
        12,
        pr_body=body(),
        draft=True,
        head_ref="agent/increment-5b2-b",
    )
    with pytest.raises(PrLifecycleError, match="multiple open canonical"):
        plan_housekeeping((first, second), now=NOW)


def test_plan_rejects_more_than_two_disposable_prs_per_canonical() -> None:
    canonical = open_pr(
        10,
        pr_body=body(),
        draft=True,
        head_ref="agent/increment-5b2",
    )
    disposable = tuple(
        open_pr(
            number,
            pr_body=body(
                lifecycle="support",
                canonical="#10",
                close_when="checkpointed",
            ),
            draft=True,
            head_ref=f"support/increment-5b2-{number}",
        )
        for number in (11, 12, 13)
    )
    with pytest.raises(PrLifecycleError, match="too many open disposable"):
        plan_housekeeping((canonical, *disposable), now=NOW)


def test_plan_warns_for_unexplained_age_without_auto_closing() -> None:
    canonical = open_pr(
        10,
        pr_body=body(),
        draft=True,
        head_ref="agent/increment-5b2",
        age_days=8,
    )
    plan = plan_housekeeping((canonical,), now=NOW)

    assert plan.close_actions == ()
    assert plan.warnings == ("#10 has remained open for 8 days",)


def test_checkpoint_deletion_fails_closed_without_verified_ref() -> None:
    support = open_pr(
        11,
        pr_body=body(
            lifecycle="support",
            canonical="#10",
            close_when="canonical-merged",
            retention="delete-after-checkpoint",
        ),
        draft=True,
        head_ref="support/increment-5b2-correction",
    )
    with pytest.raises(PrLifecycleError, match="branch deletion lacks"):
        plan_housekeeping(
            (support,),
            merged_canonical_prs=frozenset({10}),
            existing_checkpoint_refs=frozenset(),
            now=NOW,
        )
