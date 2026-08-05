from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"remaining lifecycle review anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    cli = "scripts/sdlc/pr_lifecycle.py"
    replace_once(
        cli,
        """validate_pull_request_event = _CONTRACT.validate_pull_request_event


_API = "https://api.github.com"
""",
        """validate_pull_request_event = _CONTRACT.validate_pull_request_event
validate_pull_request_lifecycle = (
    _CONTRACT.validate_pull_request_lifecycle
)


_API = "https://api.github.com"
""",
    )
    replace_once(
        cli,
        """def inventory(*, apply: bool) -> int:
""",
        """def _verified_merged_canonical_prs(
    client: GithubClient,
    *,
    open_prs: tuple[OpenPullRequest, ...],
    lifecycles: dict[int, object],
) -> frozenset[int]:
    open_numbers = {item.number for item in open_prs}
    referenced = {
        getattr(lifecycle, "canonical_pr")
        for lifecycle in lifecycles.values()
        if getattr(lifecycle, "canonical_pr") is not None
    }
    verified: dict[int, object] = {}
    for number in sorted(referenced - open_numbers):
        raw = client.get_pull_request(number)
        if raw.get("merged_at") is None:
            continue
        canonical_pr = _open_pr_from_json(raw)
        canonical_lifecycle = parse_pr_lifecycle(canonical_pr.body)
        validate_pull_request_lifecycle(
            canonical_lifecycle,
            pr_number=canonical_pr.number,
            draft=canonical_pr.draft,
            head_ref=canonical_pr.head_ref,
        )
        if not canonical_lifecycle.canonical_is_self:
            raise GithubApiError(
                f"merged pull request #{number} is not canonical"
            )
        verified[number] = canonical_lifecycle

    for pr in open_prs:
        lifecycle = lifecycles[pr.number]
        canonical_number = getattr(lifecycle, "canonical_pr")
        if (
            not getattr(lifecycle, "is_disposable")
            or canonical_number in open_numbers
        ):
            continue
        canonical_lifecycle = verified.get(canonical_number)
        if canonical_lifecycle is None:
            continue
        if (
            getattr(canonical_lifecycle, "delivery_atom")
            != getattr(lifecycle, "delivery_atom")
        ):
            raise GithubApiError(
                f"#{pr.number} delivery atom differs from merged canonical "
                f"#{canonical_number}"
            )
    return frozenset(verified)


def inventory(*, apply: bool) -> int:
""",
    )
    replace_once(
        cli,
        """    referenced_canonical = {
        lifecycle.canonical_pr
        for lifecycle in lifecycles.values()
        if lifecycle.canonical_pr is not None
    }
    open_numbers = {item.number for item in open_prs}
    merged_canonical = frozenset(
        number
        for number in sorted(referenced_canonical - open_numbers)
        if client.pull_request_is_merged(number)
    )
""",
        """    merged_canonical = _verified_merged_canonical_prs(
        client,
        open_prs=open_prs,
        lifecycles=lifecycles,
    )
""",
    )
    replace_once(
        cli,
        """        lifecycle = parse_pr_lifecycle(current.body)
        if not lifecycle.is_disposable:
""",
        """        lifecycle = parse_pr_lifecycle(current.body)
        validate_pull_request_lifecycle(
            lifecycle,
            pr_number=current.number,
            draft=current.draft,
            head_ref=current.head_ref,
        )
        if not lifecycle.is_disposable:
""",
    )

    tests = "newsroom/tests/test_pr_lifecycle.py"
    replace_once(
        tests,
        """def test_apply_rejects_checkpoint_not_bound_to_current_head() -> None:
""",
        """def test_merged_canonical_metadata_must_match_disposable_atom() -> None:
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


def test_apply_rejects_checkpoint_not_bound_to_current_head() -> None:
""",
    )

    docs = "docs/operations/pr-lifecycle.md"
    replace_once(
        docs,
        """Both inventory jobs receive the workflow token explicitly; its effective rights
remain constrained by each job's permission block. Before every mutation, apply mode
re-reads the current PR body, labels, head repository, head SHA, checkpoint and
canonical merge state.
""",
        """Both inventory jobs receive the workflow token explicitly; its effective rights
remain constrained by each job's permission block. Closed merged canonical PRs are
reloaded, parsed and required to declare canonical/self lifecycle metadata with the
same delivery atom as every disposable reference. Before every mutation, apply mode
re-reads and revalidates the current PR body, draft state, branch prefix, labels,
head repository, head SHA, checkpoint and canonical merge state.
""",
    )


if __name__ == "__main__":
    main()
