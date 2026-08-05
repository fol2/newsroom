from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"lifecycle token/ref anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    workflow = ".github/workflows/pr-lifecycle.yml"
    replace_once(
        workflow,
        """    permissions:\n      contents: read\n      pull-requests: read\n    runs-on: ubuntu-latest\n    steps:\n""",
        """    permissions:\n      contents: read\n      pull-requests: read\n    runs-on: ubuntu-latest\n    env:\n      GITHUB_TOKEN: ${{ github.token }}\n    steps:\n""",
    )
    replace_once(
        workflow,
        """    env:\n      PR_HOUSEKEEPING_APPLY: CLOSE_ELIGIBLE_DISPOSABLE_PRS\n""",
        """    env:\n      GITHUB_TOKEN: ${{ github.token }}\n      PR_HOUSEKEEPING_APPLY: CLOSE_ELIGIBLE_DISPOSABLE_PRS\n""",
    )

    checks = "newsroom/checks/pr_lifecycle.py"
    replace_once(
        checks,
        """_REPOSITORY = re.compile(\n    r\"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$\"\n)\nHOUSEKEEPING_LABEL = \"infra\"\n""",
        """_REPOSITORY = re.compile(\n    r\"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$\"\n)\n_COMMIT_SHA = re.compile(r\"^[0-9a-f]{40}$\")\nHOUSEKEEPING_LABEL = \"infra\"\n""",
    )
    replace_once(
        checks,
        """    labels: frozenset[str] = frozenset()\n    head_repository: str | None = None\n""",
        """    labels: frozenset[str] = frozenset()\n    head_repository: str | None = None\n    head_sha: str | None = None\n""",
    )
    replace_once(
        checks,
        """        if self.head_repository is not None:\n            _validate_repository(self.head_repository, field=\"head_repository\")\n""",
        """        if self.head_repository is not None:\n            _validate_repository(self.head_repository, field=\"head_repository\")\n        if self.head_sha is not None and (\n            not isinstance(self.head_sha, str)\n            or _COMMIT_SHA.fullmatch(self.head_sha) is None\n        ):\n            raise PrLifecycleError(\n                \"pull-request head SHA must be lowercase full commit text\"\n            )\n""",
    )

    cli = "scripts/sdlc/pr_lifecycle.py"
    replace_once(
        cli,
        """    def branch_exists(self, ref: str) -> bool:\n        encoded = quote(ref, safe=\"\")\n        value = self.request(\n            \"GET\",\n            f\"/git/ref/heads/{encoded}\",\n            allow_not_found=True,\n        )\n        return value is not None\n""",
        """    def branch_sha(self, ref: str) -> str | None:\n        encoded = quote(ref, safe=\"\")\n        value = self.request(\n            \"GET\",\n            f\"/git/ref/heads/{encoded}\",\n            allow_not_found=True,\n        )\n        if value is None:\n            return None\n        if not isinstance(value, dict):\n            raise GithubApiError(f\"branch {ref} response is malformed\")\n        raw_object = value.get(\"object\")\n        if not isinstance(raw_object, dict):\n            raise GithubApiError(f\"branch {ref} object is malformed\")\n        sha = raw_object.get(\"sha\")\n        if (\n            not isinstance(sha, str)\n            or len(sha) != 40\n            or any(character not in \"0123456789abcdef\" for character in sha)\n        ):\n            raise GithubApiError(f\"branch {ref} SHA is malformed\")\n        return sha\n\n    def branch_exists(self, ref: str) -> bool:\n        return self.branch_sha(ref) is not None\n""",
    )
    replace_once(
        cli,
        """        head_ref = head[\"ref\"]\n        raw_head_repository = head.get(\"repo\")\n""",
        """        head_ref = head[\"ref\"]\n        head_sha = str(head[\"sha\"])\n        raw_head_repository = head.get(\"repo\")\n""",
    )
    replace_once(
        cli,
        """        labels=labels,\n        head_repository=head_repository,\n    )\n""",
        """        labels=labels,\n        head_repository=head_repository,\n        head_sha=head_sha,\n    )\n""",
    )
    replace_once(
        cli,
        """        if action.delete_branch is not None:\n            if (\n                current.head_repository != repository\n                or current.head_ref != action.delete_branch\n                or checkpoint is None\n                or not client.branch_exists(checkpoint)\n            ):\n                raise GithubApiError(\n                    f\"pull request #{action.pr_number} branch deletion is no longer safe\"\n                )\n""",
        """        if action.delete_branch is not None:\n            checkpoint_sha = (\n                None if checkpoint is None else client.branch_sha(checkpoint)\n            )\n            head_sha = client.branch_sha(current.head_ref)\n            if (\n                current.head_repository != repository\n                or current.head_ref != action.delete_branch\n                or current.head_sha is None\n                or checkpoint_sha != current.head_sha\n                or head_sha != current.head_sha\n            ):\n                raise GithubApiError(\n                    f\"pull request #{action.pr_number} branch deletion is no longer safe\"\n                )\n""",
    )
    replace_once(
        cli,
        """        client.comment(action.pr_number, comment)\n        client.close_pull_request(action.pr_number)\n        if action.delete_branch is not None:\n            client.delete_branch(action.delete_branch)\n""",
        """        client.comment(action.pr_number, comment)\n        client.close_pull_request(action.pr_number)\n        if action.delete_branch is not None:\n            assert checkpoint is not None\n            final_head_sha = client.branch_sha(action.delete_branch)\n            final_checkpoint_sha = client.branch_sha(checkpoint)\n            if (\n                current.head_sha is None\n                or final_head_sha != current.head_sha\n                or final_checkpoint_sha != current.head_sha\n            ):\n                raise GithubApiError(\n                    f\"pull request #{action.pr_number} branch changed before deletion\"\n                )\n            client.delete_branch(action.delete_branch)\n""",
    )

    tests = "newsroom/tests/test_pr_lifecycle.py"
    replace_once(
        tests,
        """import json\nimport os\nfrom pathlib import Path\nimport subprocess\nimport sys\n""",
        """import importlib.util\nimport json\nimport os\nfrom pathlib import Path\nimport subprocess\nimport sys\n""",
    )
    replace_once(
        tests,
        """    BranchRetention,\n    CloseWhen,\n""",
        """    BranchRetention,\n    CloseAction,\n    CloseWhen,\n    HousekeepingPlan,\n""",
    )
    replace_once(
        tests,
        """    head_repository: str | None = \"fol2/newsroom\",\n) -> OpenPullRequest:\n""",
        """    head_repository: str | None = \"fol2/newsroom\",\n    head_sha: str | None = \"a\" * 40,\n) -> OpenPullRequest:\n""",
    )
    replace_once(
        tests,
        """        labels=labels,\n        head_repository=head_repository,\n    )\n""",
        """        labels=labels,\n        head_repository=head_repository,\n        head_sha=head_sha,\n    )\n""",
    )
    replace_once(
        tests,
        """def test_workflow_separates_dry_run_and_two_key_apply() -> None:\n""",
        """def test_apply_rejects_checkpoint_not_bound_to_current_head() -> None:\n    repository_root = Path(__file__).resolve().parents[2]\n    module_path = repository_root / \"scripts/sdlc/pr_lifecycle.py\"\n    spec = importlib.util.spec_from_file_location(\n        \"test_pr_lifecycle_cli\",\n        module_path,\n    )\n    assert spec is not None and spec.loader is not None\n    module = importlib.util.module_from_spec(spec)\n    sys.modules[spec.name] = module\n    spec.loader.exec_module(module)\n\n    class FakeClient:\n        def __init__(self) -> None:\n            self.effects: list[str] = []\n\n        def get_pull_request(self, number: int):\n            assert number == 11\n            return {\n                \"number\": 11,\n                \"body\": body(\n                    lifecycle=\"support\",\n                    canonical=\"#10\",\n                    close_when=\"canonical-merged\",\n                    retention=\"delete-after-checkpoint\",\n                ),\n                \"draft\": True,\n                \"head\": {\n                    \"ref\": \"support/increment-5b2-correction\",\n                    \"sha\": \"a\" * 40,\n                    \"repo\": {\"full_name\": \"fol2/newsroom\"},\n                },\n                \"labels\": [{\"name\": HOUSEKEEPING_LABEL}],\n                \"created_at\": \"2026-08-05T12:00:00Z\",\n            }\n\n        def pull_request_is_merged(self, number: int) -> bool:\n            return number == 10\n\n        def branch_sha(self, ref: str):\n            if ref == \"checkpoint/increment-5b2\":\n                return \"b\" * 40\n            return \"a\" * 40\n\n        def comment(self, *_args):\n            self.effects.append(\"comment\")\n\n        def close_pull_request(self, *_args):\n            self.effects.append(\"close\")\n\n        def delete_branch(self, *_args):\n            self.effects.append(\"delete\")\n\n    client = FakeClient()\n    plan = HousekeepingPlan(\n        close_actions=(\n            CloseAction(\n                pr_number=11,\n                reason=\"canonical PR #10 is merged\",\n                delete_branch=\"support/increment-5b2-correction\",\n            ),\n        ),\n        warnings=(),\n    )\n    with pytest.raises(module.GithubApiError, match=\"no longer safe\"):\n        module._apply_plan(\n            client,\n            plan,\n            lifecycles={},\n            repository=\"fol2/newsroom\",\n        )\n    assert client.effects == []\n\n\ndef test_workflow_separates_dry_run_and_two_key_apply() -> None:\n""",
    )
    replace_once(
        tests,
        """    assert \"PR_HOUSEKEEPING_APPLY: CLOSE_ELIGIBLE_DISPOSABLE_PRS\" in workflow\n    assert \"python scripts/sdlc/pr_lifecycle.py\" not in workflow\n""",
        """    assert \"PR_HOUSEKEEPING_APPLY: CLOSE_ELIGIBLE_DISPOSABLE_PRS\" in workflow\n    assert workflow.count(\"GITHUB_TOKEN: ${{ github.token }}\") == 2\n    assert \"python scripts/sdlc/pr_lifecycle.py\" not in workflow\n""",
    )
    replace_once(
        tests,
        """def test_checkpoint_deletion_fails_closed_without_verified_ref() -> None:\n""",
        """def test_pull_request_head_sha_must_be_full_lowercase_commit() -> None:\n    with pytest.raises(PrLifecycleError, match=\"head SHA\"):\n        open_pr(\n            11,\n            pr_body=body(),\n            draft=True,\n            head_ref=\"agent/increment-5b2\",\n            head_sha=\"ABC\",\n        )\n\n\ndef test_checkpoint_deletion_fails_closed_without_verified_ref() -> None:\n""",
    )

    docs = "docs/operations/pr-lifecycle.md"
    replace_once(
        docs,
        """Before every mutation, apply mode re-reads the current PR body, labels, head\nrepository, checkpoint and canonical merge state. It comments with an audit record\nbefore closing an eligible, `infra`-labelled disposable PR.\n""",
        """Both inventory jobs receive the workflow token explicitly; its effective rights\nremain constrained by each job's permission block. Before every mutation, apply mode\nre-reads the current PR body, labels, head repository, head SHA, checkpoint and\ncanonical merge state. A requested branch deletion additionally requires the\ndedicated checkpoint and current same-repository head ref to resolve to the exact\nPR head SHA before closure and again immediately before deletion. Apply mode comments\nwith an audit record before closing an eligible, `infra`-labelled disposable PR.\n""",
    )


if __name__ == "__main__":
    main()
