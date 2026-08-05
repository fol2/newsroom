from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"checkpoint head-binding anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "scripts/sdlc/pr_lifecycle.py",
        """        if lifecycle.close_when.value == "checkpointed":
            if checkpoint is None or not client.branch_exists(checkpoint):
                raise GithubApiError(
                    f"pull request #{action.pr_number} checkpoint is no longer present"
                )
""",
        """        if lifecycle.close_when.value == "checkpointed":
            checkpoint_sha = (
                None if checkpoint is None else client.branch_sha(checkpoint)
            )
            if (
                current.head_sha is None
                or checkpoint_sha != current.head_sha
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} checkpoint no longer "
                    "identifies its current head"
                )
""",
    )

    replace_once(
        "newsroom/tests/test_pr_lifecycle.py",
        """def test_apply_rejects_retention_change_after_planning() -> None:
""",
        """def test_checkpointed_keep_closure_requires_current_head_checkpoint() -> None:
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


def test_apply_rejects_retention_change_after_planning() -> None:
""",
    )


if __name__ == "__main__":
    main()
