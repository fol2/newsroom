from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"PR lifecycle correction anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    workflow = ".github/workflows/pr-lifecycle.yml"
    path = ROOT / workflow
    path.write_text(
        """name: PR Lifecycle

on:
  pull_request_target:
    types:
      - opened
      - edited
      - reopened
      - converted_to_draft
      - ready_for_review
      - synchronize
      - labeled
      - unlabeled
  schedule:
    - cron: "17 6 * * 1"
  workflow_dispatch:
    inputs:
      apply:
        description: Close eligible disposable PRs after reviewing the dry run
        required: true
        type: boolean
        default: false
      confirmation:
        description: Type CLOSE_ELIGIBLE_DISPOSABLE_PRS to authorize apply
        required: false
        type: string
        default: ""

jobs:
  validate:
    if: github.event_name == 'pull_request_target'
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.repository.default_branch }}
          persist-credentials: false

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Validate lifecycle metadata
        run: python -m scripts.sdlc.pr_lifecycle validate-event

  inventory-dry-run:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.repository.default_branch }}
          persist-credentials: false

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Build read-only lifecycle inventory
        run: python -m scripts.sdlc.pr_lifecycle inventory

  inventory-apply:
    if: >-
      github.event_name == 'workflow_dispatch' &&
      inputs.apply == true &&
      inputs.confirmation == 'CLOSE_ELIGIBLE_DISPOSABLE_PRS'
    needs: inventory-dry-run
    permissions:
      contents: write
      issues: write
      pull-requests: write
    runs-on: ubuntu-latest
    env:
      PR_HOUSEKEEPING_APPLY: CLOSE_ELIGIBLE_DISPOSABLE_PRS
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.repository.default_branch }}
          persist-credentials: false

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Revalidate and apply eligible lifecycle closures
        run: python -m scripts.sdlc.pr_lifecycle inventory --apply
""",
        encoding="utf-8",
    )

    checks = "newsroom/checks/pr_lifecycle.py"
    replace_once(
        checks,
        """_REF_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_MAX_DISPOSABLE_PER_CANONICAL = 2
_STALE_AFTER = timedelta(days=7)
""",
        """_REF_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_REPOSITORY = re.compile(
    r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$"
)
HOUSEKEEPING_LABEL = "infra"
_MAX_DISPOSABLE_PER_CANONICAL = 2
_STALE_AFTER = timedelta(days=7)
""",
    )
    replace_once(
        checks,
        """class OpenPullRequest:
    number: int
    body: str
    draft: bool
    head_ref: str
    created_at: datetime
""",
        """class OpenPullRequest:
    number: int
    body: str
    draft: bool
    head_ref: str
    created_at: datetime
    labels: frozenset[str] = frozenset()
    head_repository: str | None = None
""",
    )
    replace_once(
        checks,
        """        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise PrLifecycleError("pull-request creation time must be timezone-aware")
""",
        """        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise PrLifecycleError("pull-request creation time must be timezone-aware")
        if not isinstance(self.labels, frozenset) or any(
            not isinstance(label, str) or not label or label != label.strip()
            for label in self.labels
        ):
            raise PrLifecycleError("pull-request labels must be immutable text")
        if self.head_repository is not None:
            _validate_repository(self.head_repository, field="head_repository")
""",
    )
    replace_once(
        checks,
        """def plan_housekeeping(
    open_pull_requests: Iterable[OpenPullRequest],
    *,
    merged_canonical_prs: frozenset[int] = frozenset(),
    existing_checkpoint_refs: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> HousekeepingPlan:
""",
        """def plan_housekeeping(
    open_pull_requests: Iterable[OpenPullRequest],
    *,
    merged_canonical_prs: frozenset[int] = frozenset(),
    existing_checkpoint_refs: frozenset[str] = frozenset(),
    repository_full_name: str | None = None,
    now: datetime | None = None,
) -> HousekeepingPlan:
""",
    )
    replace_once(
        checks,
        """    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise PrLifecycleError("housekeeping time must be timezone-aware")

    prs = tuple(sorted(open_pull_requests, key=lambda item: item.number))
""",
        """    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise PrLifecycleError("housekeeping time must be timezone-aware")
    if repository_full_name is not None:
        _validate_repository(
            repository_full_name,
            field="repository_full_name",
        )

    prs = tuple(sorted(open_pull_requests, key=lambda item: item.number))
""",
    )
    replace_once(
        checks,
        """        if not lifecycle.is_disposable:
            continue
        assert lifecycle.canonical_pr is not None
        close_reason: str | None = None
""",
        """        if not lifecycle.is_disposable:
            continue
        assert lifecycle.canonical_pr is not None
        if HOUSEKEEPING_LABEL not in pr.labels:
            warnings.append(
                f"#{pr.number} lacks required housekeeping label "
                f"{HOUSEKEEPING_LABEL}"
            )
            continue
        close_reason: str | None = None
""",
    )
    replace_once(
        checks,
        """            delete_branch = pr.head_ref
        actions.append(
""",
        """            if (
                repository_full_name is None
                or pr.head_repository != repository_full_name
            ):
                raise PrLifecycleError(
                    f"#{pr.number} branch deletion cannot target an external repository"
                )
            delete_branch = pr.head_ref
        actions.append(
""",
    )
    replace_once(
        checks,
        """def _validate_lifecycle_shape(lifecycle: PrLifecycle) -> None:
    if lifecycle.kind is LifecycleKind.CANONICAL:
""",
        """def _validate_lifecycle_shape(lifecycle: PrLifecycle) -> None:
    if (
        lifecycle.checkpoint_ref is not None
        and not lifecycle.checkpoint_ref.startswith("checkpoint/")
    ):
        raise PrLifecycleError(
            "checkpoint ref must use the dedicated checkpoint/ namespace"
        )
    if lifecycle.kind is LifecycleKind.CANONICAL:
""",
    )
    replace_once(
        checks,
        """def _validate_ref(value: str, *, field: str) -> str:
""",
        """def _validate_repository(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise PrLifecycleError(f"{field} must be owner/name")
    return value


def _validate_ref(value: str, *, field: str) -> str:
""",
    )
    replace_once(
        checks,
        """    "HousekeepingPlan",
    "LifecycleKind",
""",
        """    "HOUSEKEEPING_LABEL",
    "HousekeepingPlan",
    "LifecycleKind",
""",
    )

    cli = "scripts/sdlc/pr_lifecycle.py"
    replace_once(
        cli,
        """import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any
""",
        """import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any
""",
    )
    replace_once(
        cli,
        """from newsroom.checks.pr_lifecycle import (
    HousekeepingPlan,
    OpenPullRequest,
    PrLifecycleError,
    parse_pr_lifecycle,
    plan_housekeeping,
    validate_pull_request_event,
)


_API = "https://api.github.com"
""",
        """_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "newsroom"
    / "checks"
    / "pr_lifecycle.py"
)
_CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "newsroom_pr_lifecycle_contract",
    _CONTRACT_PATH,
)
if _CONTRACT_SPEC is None or _CONTRACT_SPEC.loader is None:
    raise RuntimeError("cannot load exact PR lifecycle contract")
_CONTRACT = importlib.util.module_from_spec(_CONTRACT_SPEC)
sys.modules[_CONTRACT_SPEC.name] = _CONTRACT
_CONTRACT_SPEC.loader.exec_module(_CONTRACT)

HOUSEKEEPING_LABEL = _CONTRACT.HOUSEKEEPING_LABEL
HousekeepingPlan = _CONTRACT.HousekeepingPlan
OpenPullRequest = _CONTRACT.OpenPullRequest
PrLifecycleError = _CONTRACT.PrLifecycleError
parse_pr_lifecycle = _CONTRACT.parse_pr_lifecycle
plan_housekeeping = _CONTRACT.plan_housekeeping
validate_pull_request_event = _CONTRACT.validate_pull_request_event


_API = "https://api.github.com"
""",
    )
    replace_once(
        cli,
        """    def pull_request_is_merged(self, number: int) -> bool:
""",
        """    def get_pull_request(self, number: int) -> dict[str, object]:
        value = self.request("GET", f"/pulls/{number}")
        if not isinstance(value, dict):
            raise GithubApiError(f"pull request #{number} response is malformed")
        return value

    def pull_request_is_merged(self, number: int) -> bool:
""",
    )
    replace_once(
        cli,
        """    if apply and os.environ.get("PR_HOUSEKEEPING_APPLY") != "true":
        raise PrLifecycleError(
            "apply mode requires PR_HOUSEKEEPING_APPLY=true"
        )
""",
        """    if (
        apply
        and os.environ.get("PR_HOUSEKEEPING_APPLY")
        != "CLOSE_ELIGIBLE_DISPOSABLE_PRS"
    ):
        raise PrLifecycleError(
            "apply mode requires the exact housekeeping confirmation"
        )
""",
    )
    replace_once(
        cli,
        """        existing_checkpoint_refs=existing_checkpoints,
        now=datetime.now(timezone.utc),
    )
""",
        """        existing_checkpoint_refs=existing_checkpoints,
        repository_full_name=repository,
        now=datetime.now(timezone.utc),
    )
""",
    )
    replace_once(
        cli,
        """        head_ref = head["ref"]
        created_at = datetime.fromisoformat(
            str(value["created_at"]).replace("Z", "+00:00")
        )
""",
        """        head_ref = head["ref"]
        raw_head_repository = head.get("repo")
        if raw_head_repository is None:
            head_repository = None
        elif isinstance(raw_head_repository, dict):
            head_repository = str(raw_head_repository["full_name"])
        else:
            raise TypeError
        raw_labels = value.get("labels", [])
        if not isinstance(raw_labels, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("name"), str)
            for item in raw_labels
        ):
            raise TypeError
        labels = frozenset(str(item["name"]) for item in raw_labels)
        created_at = datetime.fromisoformat(
            str(value["created_at"]).replace("Z", "+00:00")
        )
""",
    )
    replace_once(
        cli,
        """        head_ref=head_ref,  # type: ignore[arg-type]
        created_at=created_at,
    )
""",
        """        head_ref=head_ref,  # type: ignore[arg-type]
        created_at=created_at,
        labels=labels,
        head_repository=head_repository,
    )
""",
    )
    replace_once(
        cli,
        """    for action in plan.close_actions:
        lifecycle = lifecycles[action.pr_number]
        checkpoint = getattr(lifecycle, "checkpoint_ref")
        comment = "\\n".join(
""",
        """    for action in plan.close_actions:
        current = _open_pr_from_json(
            client.get_pull_request(action.pr_number)
        )
        lifecycle = parse_pr_lifecycle(current.body)
        if not lifecycle.is_disposable:
            raise GithubApiError(
                f"pull request #{action.pr_number} is no longer disposable"
            )
        if HOUSEKEEPING_LABEL not in current.labels:
            raise GithubApiError(
                f"pull request #{action.pr_number} lost its housekeeping label"
            )
        checkpoint = lifecycle.checkpoint_ref
        if lifecycle.close_when.value == "checkpointed":
            if checkpoint is None or not client.branch_exists(checkpoint):
                raise GithubApiError(
                    f"pull request #{action.pr_number} checkpoint is no longer present"
                )
        elif lifecycle.close_when.value == "canonical-merged":
            if (
                lifecycle.canonical_pr is None
                or not client.pull_request_is_merged(lifecycle.canonical_pr)
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} canonical PR is not merged"
                )
        else:
            raise GithubApiError(
                f"pull request #{action.pr_number} close condition changed"
            )
        if action.delete_branch is not None:
            if (
                current.head_repository != repository
                or current.head_ref != action.delete_branch
                or checkpoint is None
                or not client.branch_exists(checkpoint)
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} branch deletion is no longer safe"
                )
        comment = "\\n".join(
""",
    )

    docs = "docs/operations/pr-lifecycle.md"
    replace_once(
        docs,
        """The branch starts with `support/`. After the exact product tree is verified,
re-parented and checkpointed, close the support PR in the same work session.
""",
        """The branch starts with `support/`. After the exact product tree is verified,
re-parented and checkpointed, close the support PR in the same work session. The
repository's existing `infra` label is the explicit automation opt-in; metadata
alone never authorizes automated closure.
""",
    )
    replace_once(
        docs,
        """Branch deletion is never permitted without an independently resolvable checkpoint.
""",
        """Every non-`NONE` checkpoint uses the dedicated `checkpoint/` namespace.
Branch deletion is never permitted without an independently resolvable checkpoint
and is never attempted for a branch owned by another repository or fork.
""",
    )
    replace_once(
        docs,
        """Weekly scheduled runs and manual dispatches build a repository-wide
inventory. Scheduled execution is dry-run only.

Manual apply requires both:

1. workflow-dispatch input `apply=true`; and
2. the workflow-provided `PR_HOUSEKEEPING_APPLY=true` environment guard.

Apply mode comments with an audit record before closing an eligible disposable PR.
""",
        """Weekly scheduled runs and manual dispatches build a repository-wide
inventory. The dry-run job has read-only permissions. A separate write-capable
apply job can run only after the dry run succeeds.

Manual apply requires all three independently checked values:

1. workflow-dispatch input `apply=true`;
2. workflow-dispatch input `confirmation=CLOSE_ELIGIBLE_DISPOSABLE_PRS`; and
3. the exact `PR_HOUSEKEEPING_APPLY=CLOSE_ELIGIBLE_DISPOSABLE_PRS` process guard.

Before every mutation, apply mode re-reads the current PR body, labels, head
repository, checkpoint and canonical merge state. It comments with an audit record
before closing an eligible, `infra`-labelled disposable PR.
""",
    )

    tests = "newsroom/tests/test_pr_lifecycle.py"
    replace_once(
        tests,
        """from datetime import datetime, timedelta, timezone

import pytest
""",
        """from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
""",
    )
    replace_once(
        tests,
        """from newsroom.checks.pr_lifecycle import (
    BranchRetention,
""",
        """from newsroom.checks.pr_lifecycle import (
    HOUSEKEEPING_LABEL,
    BranchRetention,
""",
    )
    replace_once(
        tests,
        """    age_days: int = 0,
) -> OpenPullRequest:
""",
        """    age_days: int = 0,
    labels: frozenset[str] = frozenset({HOUSEKEEPING_LABEL}),
    head_repository: str | None = "fol2/newsroom",
) -> OpenPullRequest:
""",
    )
    replace_once(
        tests,
        """        head_ref=head_ref,
        created_at=NOW - timedelta(days=age_days),
    )
""",
        """        head_ref=head_ref,
        created_at=NOW - timedelta(days=age_days),
        labels=labels,
        head_repository=head_repository,
    )
""",
    )
    replace_once(
        tests,
        """def test_plan_never_closes_canonical_and_closes_checkpointed_support() -> None:
""",
        """def test_workflow_module_entrypoint_runs_without_installed_package(
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
""",
    )
    replace_once(
        tests,
        """        existing_checkpoint_refs=frozenset(
            {"checkpoint/increment-5b2"}
        ),
        now=NOW,
    )

    assert plan.close_actions == (
""",
        """        existing_checkpoint_refs=frozenset(
            {"checkpoint/increment-5b2"}
        ),
        repository_full_name="fol2/newsroom",
        now=NOW,
    )

    assert plan.close_actions == (
""",
    )
    replace_once(
        tests,
        """def test_checkpoint_deletion_fails_closed_without_verified_ref() -> None:
""",
        """def test_checkpoint_ref_requires_dedicated_namespace() -> None:
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
    assert "python scripts/sdlc/pr_lifecycle.py" not in workflow


def test_checkpoint_deletion_fails_closed_without_verified_ref() -> None:
""",
    )


if __name__ == "__main__":
    main()
