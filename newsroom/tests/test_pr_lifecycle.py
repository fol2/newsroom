from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from newsroom.checks.pr_lifecycle import (
    HOUSEKEEPING_LABEL,
    BranchRetention,
    CloseAction,
    CloseWhen,
    HousekeepingPlan,
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
    labels: frozenset[str] = frozenset({HOUSEKEEPING_LABEL}),
    head_repository: str | None = "fol2/newsroom",
    head_sha: str | None = "a" * 40,
) -> OpenPullRequest:
    return OpenPullRequest(
        number=number,
        body=pr_body,
        draft=draft,
        head_ref=head_ref,
        created_at=NOW - timedelta(days=age_days),
        labels=labels,
        head_repository=head_repository,
        head_sha=head_sha,
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


def test_workflow_module_entrypoint_runs_without_installed_package(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    event_path = tmp_path / "pull-request-event.json"
    event_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 10,
                    "draft": False,
                    "body": body(),
                    "head": {"ref": "agent/increment-5b2"},
                }
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-m",
            "scripts.sdlc.pr_lifecycle",
            "validate-event",
            "--event",
            str(event_path),
        ],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "validated PR lifecycle: canonical / increment-5b2" in result.stdout


def test_apply_requires_exact_confirmation_before_api_access() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.update(
        {
            "GITHUB_REPOSITORY": "fol2/newsroom",
            "GITHUB_TOKEN": "not-used-before-guard",
            "PR_HOUSEKEEPING_APPLY": "true",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-m",
            "scripts.sdlc.pr_lifecycle",
            "inventory",
            "--apply",
        ],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "exact housekeeping confirmation" in result.stderr
    assert "GitHub API" not in result.stderr


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
        repository_full_name="fol2/newsroom",
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


def test_checkpoint_ref_requires_dedicated_namespace() -> None:
    with pytest.raises(PrLifecycleError, match="checkpoint/ namespace"):
        parse_pr_lifecycle(
            body(
                lifecycle="support",
                canonical="#10",
                checkpoint="main",
                close_when="checkpointed",
            )
        )


def test_unlabelled_disposable_is_never_closed() -> None:
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
        labels=frozenset(),
    )
    plan = plan_housekeeping(
        (canonical, support),
        existing_checkpoint_refs=frozenset(
            {"checkpoint/increment-5b2"}
        ),
        now=NOW,
    )

    assert plan.close_actions == ()
    assert plan.warnings == (
        "#11 lacks required housekeeping label infra",
    )


def test_external_fork_branch_is_never_deleted() -> None:
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
        head_repository="external/newsroom-fork",
    )
    with pytest.raises(PrLifecycleError, match="external repository"):
        plan_housekeeping(
            (support,),
            merged_canonical_prs=frozenset({10}),
            existing_checkpoint_refs=frozenset(
                {"checkpoint/increment-5b2"}
            ),
            repository_full_name="fol2/newsroom",
            now=NOW,
        )


def test_merged_canonical_metadata_must_match_disposable_atom() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(
        "test_pr_lifecycle_merged_cli",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    support = module._open_pr_from_json(
        {
            "number": 11,
            "body": body(
                lifecycle="support",
                atom="increment-5b3",
                canonical="#10",
                close_when="canonical-merged",
            ),
            "draft": True,
            "head": {
                "ref": "support/increment-5b3",
                "sha": "a" * 40,
                "repo": {"full_name": "fol2/newsroom"},
            },
            "labels": [{"name": HOUSEKEEPING_LABEL}],
            "created_at": "2026-08-05T12:00:00Z",
        }
    )

    class FakeClient:
        def get_pull_request(self, number: int):
            assert number == 10
            return {
                "number": 10,
                "body": body(atom="different-atom"),
                "draft": False,
                "head": {
                    "ref": "agent/different-atom",
                    "sha": "b" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [],
                "created_at": "2026-08-01T12:00:00Z",
                "merged_at": "2026-08-02T12:00:00Z",
            }

    lifecycles = {
        support.number: module.parse_pr_lifecycle(support.body)
    }
    with pytest.raises(module.GithubApiError, match="delivery atom differs"):
        module._verified_merged_canonical_prs(
            FakeClient(),
            open_prs=(support,),
            lifecycles=lifecycles,
        )


def test_apply_revalidates_current_disposable_surface() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(
        "test_pr_lifecycle_surface_cli",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class FakeClient:
        def __init__(self) -> None:
            self.effects: list[str] = []

        def get_pull_request(self, number: int):
            assert number == 11
            return {
                "number": 11,
                "body": body(
                    lifecycle="support",
                    canonical="#10",
                    close_when="checkpointed",
                ),
                "draft": False,
                "head": {
                    "ref": "support/increment-5b2-correction",
                    "sha": "a" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [{"name": HOUSEKEEPING_LABEL}],
                "created_at": "2026-08-05T12:00:00Z",
            }

        def comment(self, *_args):
            self.effects.append("comment")

        def close_pull_request(self, *_args):
            self.effects.append("close")

        def delete_branch(self, *_args):
            self.effects.append("delete")

    client = FakeClient()
    plan = HousekeepingPlan(
        close_actions=(
            CloseAction(
                pr_number=11,
                reason="declared checkpoint exists",
            ),
        ),
        warnings=(),
    )
    with pytest.raises(module.PrLifecycleError, match="must remain drafts"):
        module._apply_plan(
            client,
            plan,
            lifecycles={},
            repository="fol2/newsroom",
        )
    assert client.effects == []


def test_checkpointed_keep_closure_requires_current_head_checkpoint() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(
        "test_pr_lifecycle_checkpoint_keep_cli",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    support_body = body(
        lifecycle="support",
        canonical="#10",
        close_when="checkpointed",
        retention="keep",
    )

    class FakeClient:
        def __init__(self) -> None:
            self.effects: list[str] = []

        def get_pull_request(self, number: int):
            assert number == 11
            return {
                "number": 11,
                "body": support_body,
                "draft": True,
                "head": {
                    "ref": "support/increment-5b2-correction",
                    "sha": "a" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [{"name": HOUSEKEEPING_LABEL}],
                "created_at": "2026-08-05T12:00:00Z",
            }

        def branch_sha(self, ref: str):
            assert ref == "checkpoint/increment-5b2"
            return "b" * 40

        def comment(self, *_args):
            self.effects.append("comment")

        def close_pull_request(self, *_args):
            self.effects.append("close")

        def delete_branch(self, *_args):
            self.effects.append("delete")

    client = FakeClient()
    plan = HousekeepingPlan(
        close_actions=(
            CloseAction(
                pr_number=11,
                reason="declared checkpoint exists",
            ),
        ),
        warnings=(),
    )
    with pytest.raises(module.GithubApiError, match="current head"):
        module._apply_plan(
            client,
            plan,
            lifecycles={11: module.parse_pr_lifecycle(support_body)},
            repository="fol2/newsroom",
        )
    assert client.effects == []


@pytest.mark.parametrize(
    ("canonical_state", "canonical_atom", "expected_error"),
    (
        ("closed", "increment-5b2", "no longer open"),
        ("open", "different-atom", "delivery atom differs"),
    ),
)
def test_checkpointed_apply_revalidates_current_canonical(
    canonical_state: str,
    canonical_atom: str,
    expected_error: str,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(
        "test_pr_lifecycle_checkpoint_canonical_cli",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    support_body = body(
        lifecycle="support",
        canonical="#10",
        close_when="checkpointed",
        retention="keep",
    )
    planned_canonical_body = body()

    class FakeClient:
        def __init__(self) -> None:
            self.effects: list[str] = []

        def get_pull_request(self, number: int):
            if number == 11:
                return {
                    "number": 11,
                    "state": "open",
                    "body": support_body,
                    "draft": True,
                    "head": {
                        "ref": "support/increment-5b2-correction",
                        "sha": "a" * 40,
                        "repo": {"full_name": "fol2/newsroom"},
                    },
                    "labels": [{"name": HOUSEKEEPING_LABEL}],
                    "created_at": "2026-08-05T12:00:00Z",
                    "merged_at": None,
                }
            assert number == 10
            return {
                "number": 10,
                "state": canonical_state,
                "body": body(atom=canonical_atom),
                "draft": False,
                "head": {
                    "ref": f"agent/{canonical_atom}",
                    "sha": "b" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [],
                "created_at": "2026-08-01T12:00:00Z",
                "merged_at": None,
            }

        def branch_sha(self, ref: str):
            assert ref == "checkpoint/increment-5b2"
            return "a" * 40

        def comment(self, *_args):
            self.effects.append("comment")

        def close_pull_request(self, *_args):
            self.effects.append("close")

        def delete_branch(self, *_args):
            self.effects.append("delete")

    client = FakeClient()
    plan = HousekeepingPlan(
        close_actions=(
            CloseAction(
                pr_number=11,
                reason="declared checkpoint exists",
            ),
        ),
        warnings=(),
    )
    with pytest.raises(module.GithubApiError, match=expected_error):
        module._apply_plan(
            client,
            plan,
            lifecycles={
                10: module.parse_pr_lifecycle(planned_canonical_body),
                11: module.parse_pr_lifecycle(support_body),
            },
            repository="fol2/newsroom",
        )
    assert client.effects == []


def test_apply_refuses_branch_shared_by_another_open_pr() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(
        "test_pr_lifecycle_shared_head_cli",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    support_body = body(
        lifecycle="support",
        canonical="#10",
        close_when="canonical-merged",
        retention="delete-after-checkpoint",
    )

    current_raw = {
        "number": 11,
        "state": "open",
        "body": support_body,
        "draft": True,
        "head": {
            "ref": "support/shared-head",
            "sha": "a" * 40,
            "repo": {"full_name": "fol2/newsroom"},
        },
        "labels": [{"name": HOUSEKEEPING_LABEL}],
        "created_at": "2026-08-05T12:00:00Z",
        "merged_at": None,
    }
    shared_raw = {
        "number": 12,
        "state": "open",
        "body": body(
            lifecycle="support",
            canonical="#10",
            close_when="canonical-merged",
            retention="keep",
        ),
        "draft": True,
        "head": {
            "ref": "support/shared-head",
            "sha": "a" * 40,
            "repo": {"full_name": "fol2/newsroom"},
        },
        "labels": [{"name": HOUSEKEEPING_LABEL}],
        "created_at": "2026-08-05T12:01:00Z",
        "merged_at": None,
    }

    class FakeClient:
        def __init__(self) -> None:
            self.effects: list[str] = []

        def get_pull_request(self, number: int):
            if number == 11:
                return current_raw
            assert number == 10
            return {
                "number": 10,
                "state": "closed",
                "body": body(),
                "draft": False,
                "head": {
                    "ref": "agent/increment-5b2",
                    "sha": "b" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [],
                "created_at": "2026-08-01T12:00:00Z",
                "merged_at": "2026-08-02T12:00:00Z",
            }

        def list_open_pull_requests(self):
            return [current_raw, shared_raw]

        def branch_sha(self, ref: str):
            assert ref in {
                "checkpoint/increment-5b2",
                "support/shared-head",
            }
            return "a" * 40

        def comment(self, *_args):
            self.effects.append("comment")

        def close_pull_request(self, *_args):
            self.effects.append("close")

        def delete_branch(self, *_args):
            self.effects.append("delete")

    client = FakeClient()
    plan = HousekeepingPlan(
        close_actions=(
            CloseAction(
                pr_number=11,
                reason="canonical PR #10 is merged",
                delete_branch="support/shared-head",
            ),
        ),
        warnings=(),
    )
    with pytest.raises(module.GithubApiError, match="shared by open PR #12"):
        module._apply_plan(
            client,
            plan,
            lifecycles={11: module.parse_pr_lifecycle(support_body)},
            repository="fol2/newsroom",
        )
    assert client.effects == []


def test_apply_rejects_retention_change_after_planning() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(
        "test_pr_lifecycle_retention_cli",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    planned_body = body(
        lifecycle="support",
        canonical="#10",
        close_when="canonical-merged",
        retention="delete-after-checkpoint",
    )

    class FakeClient:
        def __init__(self) -> None:
            self.effects: list[str] = []

        def get_pull_request(self, number: int):
            assert number == 11
            return {
                "number": 11,
                "body": body(
                    lifecycle="support",
                    canonical="#10",
                    close_when="canonical-merged",
                    retention="keep",
                ),
                "draft": True,
                "head": {
                    "ref": "support/increment-5b2-correction",
                    "sha": "a" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [{"name": HOUSEKEEPING_LABEL}],
                "created_at": "2026-08-05T12:00:00Z",
            }

        def comment(self, *_args):
            self.effects.append("comment")

        def close_pull_request(self, *_args):
            self.effects.append("close")

        def delete_branch(self, *_args):
            self.effects.append("delete")

    client = FakeClient()
    plan = HousekeepingPlan(
        close_actions=(
            CloseAction(
                pr_number=11,
                reason="canonical PR #10 is merged",
                delete_branch="support/increment-5b2-correction",
            ),
        ),
        warnings=(),
    )
    with pytest.raises(module.GithubApiError, match="changed after planning"):
        module._apply_plan(
            client,
            plan,
            lifecycles={11: module.parse_pr_lifecycle(planned_body)},
            repository="fol2/newsroom",
        )
    assert client.effects == []


def test_apply_revalidates_current_merged_canonical_binding() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(
        "test_pr_lifecycle_canonical_apply_cli",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    support_body = body(
        lifecycle="support",
        canonical="#10",
        close_when="canonical-merged",
        retention="keep",
    )

    class FakeClient:
        def __init__(self) -> None:
            self.effects: list[str] = []

        def get_pull_request(self, number: int):
            if number == 11:
                return {
                    "number": 11,
                    "body": support_body,
                    "draft": True,
                    "head": {
                        "ref": "support/increment-5b2-correction",
                        "sha": "a" * 40,
                        "repo": {"full_name": "fol2/newsroom"},
                    },
                    "labels": [{"name": HOUSEKEEPING_LABEL}],
                    "created_at": "2026-08-05T12:00:00Z",
                }
            assert number == 10
            return {
                "number": 10,
                "body": body(atom="unrelated-atom"),
                "draft": False,
                "head": {
                    "ref": "agent/unrelated-atom",
                    "sha": "b" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [],
                "created_at": "2026-08-01T12:00:00Z",
                "merged_at": "2026-08-02T12:00:00Z",
            }

        def comment(self, *_args):
            self.effects.append("comment")

        def close_pull_request(self, *_args):
            self.effects.append("close")

        def delete_branch(self, *_args):
            self.effects.append("delete")

    client = FakeClient()
    plan = HousekeepingPlan(
        close_actions=(
            CloseAction(
                pr_number=11,
                reason="canonical PR #10 is merged",
            ),
        ),
        warnings=(),
    )
    with pytest.raises(module.GithubApiError, match="delivery atom differs"):
        module._apply_plan(
            client,
            plan,
            lifecycles={11: module.parse_pr_lifecycle(support_body)},
            repository="fol2/newsroom",
        )
    assert client.effects == []


def test_apply_rejects_checkpoint_not_bound_to_current_head() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(
        "test_pr_lifecycle_cli",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class FakeClient:
        def __init__(self) -> None:
            self.effects: list[str] = []

        def get_pull_request(self, number: int):
            if number == 11:
                return {
                    "number": 11,
                    "body": body(
                        lifecycle="support",
                        canonical="#10",
                        close_when="canonical-merged",
                        retention="delete-after-checkpoint",
                    ),
                    "draft": True,
                    "head": {
                        "ref": "support/increment-5b2-correction",
                        "sha": "a" * 40,
                        "repo": {"full_name": "fol2/newsroom"},
                    },
                    "labels": [{"name": HOUSEKEEPING_LABEL}],
                    "created_at": "2026-08-05T12:00:00Z",
                }
            assert number == 10
            return {
                "number": 10,
                "body": body(),
                "draft": False,
                "head": {
                    "ref": "agent/increment-5b2",
                    "sha": "c" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [],
                "created_at": "2026-08-01T12:00:00Z",
                "merged_at": "2026-08-02T12:00:00Z",
            }

        def branch_sha(self, ref: str):
            if ref == "checkpoint/increment-5b2":
                return "b" * 40
            return "a" * 40

        def comment(self, *_args):
            self.effects.append("comment")

        def close_pull_request(self, *_args):
            self.effects.append("close")

        def delete_branch(self, *_args):
            self.effects.append("delete")

    client = FakeClient()
    plan = HousekeepingPlan(
        close_actions=(
            CloseAction(
                pr_number=11,
                reason="canonical PR #10 is merged",
                delete_branch="support/increment-5b2-correction",
            ),
        ),
        warnings=(),
    )
    with pytest.raises(module.GithubApiError, match="no longer safe"):
        module._apply_plan(
            client,
            plan,
            lifecycles={
                11: module.parse_pr_lifecycle(
                    body(
                        lifecycle="support",
                        canonical="#10",
                        close_when="canonical-merged",
                        retention="delete-after-checkpoint",
                    )
                )
            },
            repository="fol2/newsroom",
        )
    assert client.effects == []


def test_workflow_separates_dry_run_and_two_key_apply() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (
        repository_root / ".github/workflows/pr-lifecycle.yml"
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


def test_pull_request_head_sha_must_be_full_lowercase_commit() -> None:
    with pytest.raises(PrLifecycleError, match="head SHA"):
        open_pr(
            11,
            pr_body=body(),
            draft=True,
            head_ref="agent/increment-5b2",
            head_sha="ABC",
        )


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
