from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"lifecycle stale-plan anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    cli = "scripts/sdlc/pr_lifecycle.py"
    replace_once(
        cli,
        """        validate_pull_request_lifecycle(
            lifecycle,
            pr_number=current.number,
            draft=current.draft,
            head_ref=current.head_ref,
        )
        if not lifecycle.is_disposable:
""",
        """        validate_pull_request_lifecycle(
            lifecycle,
            pr_number=current.number,
            draft=current.draft,
            head_ref=current.head_ref,
        )
        planned_lifecycle = lifecycles.get(action.pr_number)
        if planned_lifecycle is None or lifecycle != planned_lifecycle:
            raise GithubApiError(
                f"pull request #{action.pr_number} lifecycle changed after planning"
            )
        expected_delete_branch = (
            current.head_ref
            if lifecycle.branch_retention.value == "delete-after-checkpoint"
            else None
        )
        if action.delete_branch != expected_delete_branch:
            raise GithubApiError(
                f"pull request #{action.pr_number} retention differs from its plan"
            )
        if not lifecycle.is_disposable:
""",
    )
    replace_once(
        cli,
        """        elif lifecycle.close_when.value == "canonical-merged":
            if (
                lifecycle.canonical_pr is None
                or not client.pull_request_is_merged(lifecycle.canonical_pr)
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} canonical PR is not merged"
                )
""",
        """        elif lifecycle.close_when.value == "canonical-merged":
            if lifecycle.canonical_pr is None:
                raise GithubApiError(
                    f"pull request #{action.pr_number} lacks a canonical PR"
                )
            raw_canonical = client.get_pull_request(lifecycle.canonical_pr)
            if raw_canonical.get("merged_at") is None:
                raise GithubApiError(
                    f"pull request #{action.pr_number} canonical PR is not merged"
                )
            canonical_pr = _open_pr_from_json(raw_canonical)
            canonical_lifecycle = parse_pr_lifecycle(canonical_pr.body)
            validate_pull_request_lifecycle(
                canonical_lifecycle,
                pr_number=canonical_pr.number,
                draft=canonical_pr.draft,
                head_ref=canonical_pr.head_ref,
            )
            if (
                not canonical_lifecycle.canonical_is_self
                or canonical_lifecycle.delivery_atom
                != lifecycle.delivery_atom
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} delivery atom differs "
                    "from its current merged canonical PR"
                )
""",
    )

    tests = "newsroom/tests/test_pr_lifecycle.py"
    replace_once(
        tests,
        """def test_apply_rejects_checkpoint_not_bound_to_current_head() -> None:
""",
        """def test_apply_rejects_retention_change_after_planning() -> None:
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
""",
    )


if __name__ == "__main__":
    main()
