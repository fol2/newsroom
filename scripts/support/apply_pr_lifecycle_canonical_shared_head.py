from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"canonical/shared-head anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "scripts/sdlc/pr_lifecycle.py",
        "\n\ndef _apply_plan(\n",
        """


def _validated_current_canonical(
    client: GithubClient,
    *,
    action_pr_number: int,
    lifecycle: object,
    planned_lifecycles: dict[int, object],
    require_merged: bool,
) -> object:
    canonical_number = getattr(lifecycle, "canonical_pr", None)
    if (
        isinstance(canonical_number, bool)
        or not isinstance(canonical_number, int)
        or canonical_number <= 0
    ):
        raise GithubApiError(
            f"pull request #{action_pr_number} lacks a canonical PR"
        )

    raw_canonical = client.get_pull_request(canonical_number)
    planned_canonical = planned_lifecycles.get(canonical_number)
    if require_merged or planned_canonical is None:
        if raw_canonical.get("merged_at") is None:
            raise GithubApiError(
                f"pull request #{action_pr_number} canonical PR is not merged"
            )
    elif (
        raw_canonical.get("state") != "open"
        or raw_canonical.get("merged_at") is not None
    ):
        raise GithubApiError(
            f"pull request #{action_pr_number} canonical PR is no longer open"
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
        != getattr(lifecycle, "delivery_atom", None)
    ):
        raise GithubApiError(
            f"pull request #{action_pr_number} delivery atom differs "
            "from its current canonical PR"
        )
    if (
        planned_canonical is not None
        and canonical_lifecycle != planned_canonical
    ):
        raise GithubApiError(
            f"pull request #{action_pr_number} canonical lifecycle changed "
            "after planning"
        )
    return canonical_lifecycle


def _require_exclusive_current_head(
    client: GithubClient,
    *,
    current: OpenPullRequest,
    repository: str,
) -> None:
    if current.head_repository != repository:
        raise GithubApiError(
            f"pull request #{current.number} branch belongs to another repository"
        )
    for raw in client.list_open_pull_requests():
        candidate = _open_pr_from_json(raw)
        if candidate.number == current.number:
            continue
        if (
            candidate.head_repository == repository
            and candidate.head_ref == current.head_ref
        ):
            raise GithubApiError(
                f"pull request #{current.number} branch is shared by open PR "
                f"#{candidate.number}"
            )


def _apply_plan(
""",
    )

    replace_once(
        "scripts/sdlc/pr_lifecycle.py",
        """        checkpoint = lifecycle.checkpoint_ref
        if lifecycle.close_when.value == "checkpointed":
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
        elif lifecycle.close_when.value == "canonical-merged":
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
        else:
""",
        """        checkpoint = lifecycle.checkpoint_ref
        if lifecycle.close_when.value == "checkpointed":
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
            _validated_current_canonical(
                client,
                action_pr_number=action.pr_number,
                lifecycle=lifecycle,
                planned_lifecycles=lifecycles,
                require_merged=False,
            )
        elif lifecycle.close_when.value == "canonical-merged":
            _validated_current_canonical(
                client,
                action_pr_number=action.pr_number,
                lifecycle=lifecycle,
                planned_lifecycles=lifecycles,
                require_merged=True,
            )
        else:
""",
    )

    replace_once(
        "scripts/sdlc/pr_lifecycle.py",
        """            if (
                current.head_repository != repository
                or current.head_ref != action.delete_branch
                or current.head_sha is None
                or checkpoint_sha != current.head_sha
                or head_sha != current.head_sha
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} branch deletion is no longer safe"
                )
        comment = "\\n".join(
""",
        """            if (
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
        comment = "\\n".join(
""",
    )

    replace_once(
        "scripts/sdlc/pr_lifecycle.py",
        """            if (
                current.head_sha is None
                or final_head_sha != current.head_sha
                or final_checkpoint_sha != current.head_sha
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} branch changed before deletion"
                )
            client.delete_branch(action.delete_branch)
""",
        """            if (
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
    )

    replace_once(
        "newsroom/tests/test_pr_lifecycle.py",
        """def test_apply_rejects_retention_change_after_planning() -> None:
""",
        """@pytest.mark.parametrize(
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
""",
    )


if __name__ == "__main__":
    main()
