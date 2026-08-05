from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"plan/state anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/checks/pr_lifecycle.py",
        """        parsed[pr.number] = lifecycle

    canonical_by_atom: dict[str, OpenPullRequest] = {}
""",
        """        parsed[pr.number] = lifecycle

    if repository_full_name is not None:
        same_repository_heads: dict[str, list[int]] = {}
        for pr in prs:
            if pr.head_repository != repository_full_name:
                continue
            same_repository_heads.setdefault(pr.head_ref, []).append(pr.number)
        shared_heads = {
            ref: tuple(numbers)
            for ref, numbers in same_repository_heads.items()
            if len(numbers) > 1
        }
        if shared_heads:
            detail = ", ".join(
                f"{ref}: " + ", ".join(f"#{number}" for number in numbers)
                for ref, numbers in sorted(shared_heads.items())
            )
            raise PrLifecycleError(
                "open pull requests share same-repository head refs: " + detail
            )

    canonical_by_atom: dict[str, OpenPullRequest] = {}
""",
    )

    replace_once(
        "scripts/sdlc/pr_lifecycle.py",
        """    recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for action in plan.close_actions:
        current = _open_pr_from_json(
            client.get_pull_request(action.pr_number)
        )
        lifecycle = parse_pr_lifecycle(current.body)
""",
        """    recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for action in plan.close_actions:
        raw_current = client.get_pull_request(action.pr_number)
        if (
            raw_current.get("state") != "open"
            or raw_current.get("merged_at") is not None
        ):
            raise GithubApiError(
                f"pull request #{action.pr_number} is no longer open and unmerged"
            )
        current = _open_pr_from_json(raw_current)
        lifecycle = parse_pr_lifecycle(current.body)
""",
    )

    replace_once(
        "newsroom/tests/test_pr_lifecycle.py",
        """def test_plan_warns_for_unexplained_age_without_auto_closing() -> None:
""",
        """def test_plan_rejects_shared_same_repository_head_refs() -> None:
    canonical = open_pr(
        10,
        pr_body=body(),
        draft=False,
        head_ref="agent/increment-5b2",
    )
    keep = open_pr(
        11,
        pr_body=body(
            lifecycle="support",
            canonical="#10",
            close_when="checkpointed",
            retention="keep",
        ),
        draft=True,
        head_ref="support/shared-head",
    )
    delete = open_pr(
        12,
        pr_body=body(
            lifecycle="support",
            canonical="#10",
            close_when="checkpointed",
            retention="delete-after-checkpoint",
        ),
        draft=True,
        head_ref="support/shared-head",
    )

    with pytest.raises(
        PrLifecycleError,
        match="share same-repository head refs",
    ):
        plan_housekeeping(
            (canonical, keep, delete),
            existing_checkpoint_refs=frozenset(
                {"checkpoint/increment-5b2"}
            ),
            repository_full_name="fol2/newsroom",
            now=NOW,
        )


def test_plan_warns_for_unexplained_age_without_auto_closing() -> None:
""",
    )

    replace_once(
        "newsroom/tests/test_pr_lifecycle.py",
        """def test_apply_revalidates_current_disposable_surface() -> None:
""",
        """@pytest.mark.parametrize(
    ("current_state", "merged_at"),
    (
        ("closed", None),
        ("closed", "2026-08-05T12:30:00Z"),
        ("open", "2026-08-05T12:30:00Z"),
    ),
)
def test_apply_requires_action_pr_to_remain_open_and_unmerged(
    current_state: str,
    merged_at: str | None,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(
        "test_pr_lifecycle_action_state_cli",
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
    )

    class FakeClient:
        def __init__(self) -> None:
            self.effects: list[str] = []

        def get_pull_request(self, number: int):
            assert number == 11
            return {
                "number": 11,
                "state": current_state,
                "body": support_body,
                "draft": True,
                "head": {
                    "ref": "support/increment-5b2-correction",
                    "sha": "a" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [{"name": HOUSEKEEPING_LABEL}],
                "created_at": "2026-08-05T12:00:00Z",
                "merged_at": merged_at,
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
    with pytest.raises(module.GithubApiError, match="open and unmerged"):
        module._apply_plan(
            client,
            plan,
            lifecycles={11: module.parse_pr_lifecycle(support_body)},
            repository="fol2/newsroom",
        )
    assert client.effects == []


def test_apply_revalidates_current_disposable_surface() -> None:
""",
    )


if __name__ == "__main__":
    main()
