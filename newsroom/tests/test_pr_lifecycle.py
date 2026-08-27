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
    retention: str | None = None,
) -> str:
    if retention is None:
        retention = (
            "keep" if lifecycle != "canonical" else "delete-after-merge"
        )
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
    assert lifecycle.branch_retention is BranchRetention.DELETE_AFTER_MERGE


def test_parser_rejects_reserved_delivery_atom_placeholder() -> None:
    with pytest.raises(PrLifecycleError, match="placeholder"):
        parse_pr_lifecycle(body(atom="replace-me"))


def test_parser_rejects_hash_prefixed_issue_number_delivery_atom() -> None:
    with pytest.raises(
        PrLifecycleError,
        match="Delivery-Atom must be a bounded lowercase identifier",
    ):
        parse_pr_lifecycle(body(atom="#790"))


def test_parser_accepts_issue_prefixed_delivery_atom() -> None:
    assert parse_pr_lifecycle(body(atom="issue-790")).delivery_atom == "issue-790"


def test_pull_request_template_requires_a_real_delivery_atom() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    template = (
        repository_root / ".github/pull_request_template.md"
    ).read_text(encoding="utf-8")

    with pytest.raises(PrLifecycleError, match="Delivery-Atom"):
        parse_pr_lifecycle(template)


def test_parser_rejects_missing_misordered_and_unsafe_metadata() -> None:
    with pytest.raises(PrLifecycleError, match="visible leading six-line block"):
        parse_pr_lifecycle("Lifecycle: canonical")

    misordered = body().replace(
        "Delivery-Atom: increment-5b2",
        "Lifecycle: support",
        1,
    )
    with pytest.raises(PrLifecycleError, match="canonical order"):
        parse_pr_lifecycle(misordered)

    with pytest.raises(PrLifecycleError, match="safe bounded Git ref"):
        parse_pr_lifecycle(body(checkpoint="checkpoint/../escape"))


@pytest.mark.parametrize(
    "wrapped",
    (
        "<!--\n{body}\n-->",
        "```text\n{body}\n```",
        "\n{body}",
    ),
)
def test_parser_rejects_hidden_fenced_or_prefixed_metadata(
    wrapped: str,
) -> None:
    with pytest.raises(PrLifecycleError, match="visible leading six-line block"):
        parse_pr_lifecycle(
            wrapped.format(
                body=body(
                    lifecycle="support",
                    canonical="#10",
                    close_when="checkpointed",
                )
            )
        )


def test_parser_ignores_later_hidden_or_fenced_metadata_examples() -> None:
    lifecycle = parse_pr_lifecycle(
        body()
        + "\n\n<!--\n"
        + body(
            lifecycle="support",
            canonical="#999",
            close_when="checkpointed",
        )
        + "\n-->\n\n```text\n"
        + body(
            lifecycle="preflight",
            canonical="#998",
            close_when="canonical-merged",
            checkpoint="NONE",
        )
        + "\n```"
    )

    assert lifecycle.kind is LifecycleKind.CANONICAL
    assert lifecycle.delivery_atom == "increment-5b2"


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


@pytest.mark.parametrize(
    ("atom", "returncode", "needle"),
    (
        (
            "#790",
            2,
            "PR lifecycle error: Delivery-Atom must be a bounded lowercase identifier",
        ),
        ("issue-790", 0, "validated PR lifecycle: canonical / issue-790"),
    ),
)
def test_validate_event_delivery_atom_matches_ci_entry_point(
    tmp_path: Path,
    atom: str,
    returncode: int,
    needle: str,
) -> None:
    event_path = tmp_path / "pull-request-event.json"
    event_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 813,
                    "draft": False,
                    "body": body(atom=atom),
                    "head": {"ref": "jamesto/issue-790-sdk-qualification"},
                }
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["GITHUB_EVENT_PATH"] = str(event_path)
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-m",
            "scripts.sdlc.pr_lifecycle",
            "validate-event",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = result.stderr if returncode else result.stdout
    assert result.returncode == returncode, result.stderr
    assert needle in output


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



def _load_lifecycle_cli(name: str):
    repository_root = Path(__file__).resolve().parents[2]
    module_path = repository_root / "scripts/sdlc/pr_lifecycle.py"
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_apply_requires_reviewed_revision_before_api_access() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.update(
        {
            "GITHUB_REPOSITORY": "fol2/newsroom",
            "GITHUB_TOKEN": "not-used-before-guard",
            "GITHUB_SHA": "a" * 40,
            "PR_HOUSEKEEPING_APPLY": "CLOSE_ELIGIBLE_DISPOSABLE_PRS",
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
            "--evaluation-time",
            "2026-08-05T12:00:00Z",
            "--reviewed-revision",
            "b" * 40,
            "--reviewed-plan-digest",
            "sha256:" + "0" * 64,
        ],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "reviewed revision does not match" in result.stderr
    assert "GitHub API" not in result.stderr


def test_mutation_plan_digest_covers_state_actions_and_warnings() -> None:
    module = _load_lifecycle_cli("test_pr_lifecycle_plan_digest_cli")
    canonical = open_pr(
        10,
        pr_body=body(),
        draft=False,
        head_ref="agent/increment-5b2",
        head_sha="a" * 40,
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
        head_sha="b" * 40,
    )
    open_prs = (canonical, support)
    lifecycles = {
        item.number: module.parse_pr_lifecycle(item.body)
        for item in open_prs
    }
    plan = module.plan_housekeeping(
        open_prs,
        checkpoint_head_shas={
            "checkpoint/increment-5b2": "b" * 40,
        },
        repository_full_name="fol2/newsroom",
        now=NOW,
    )
    document = module._build_mutation_plan_document(
        repository="fol2/newsroom",
        revision="c" * 40,
        evaluation_time=NOW,
        open_prs=open_prs,
        lifecycles=lifecycles,
        merged_canonical_records={},
        checkpoint_head_shas={
            "checkpoint/increment-5b2": "b" * 40,
        },
        plan=plan,
    )
    digest = module._mutation_plan_digest(document)

    changed_document = json.loads(json.dumps(document))
    changed_document["checkpoint_head_shas"][
        "checkpoint/increment-5b2"
    ] = "d" * 40

    assert digest.startswith("sha256:")
    assert len(digest) == 71
    assert module._mutation_plan_digest(changed_document) != digest
    assert document["close_actions"] == [
        {
            "pr_number": 11,
            "head_sha": "b" * 40,
            "reason": (
                "declared checkpoint matches current head: "
                "checkpoint/increment-5b2"
            ),
        }
    ]
    assert document["warnings"] == []


def test_inventory_rejects_digest_drift_before_any_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_lifecycle_cli("test_pr_lifecycle_digest_apply_cli")
    canonical_json = {
        "number": 10,
        "state": "open",
        "body": body(),
        "draft": False,
        "head": {
            "ref": "agent/increment-5b2",
            "sha": "a" * 40,
            "repo": {"full_name": "fol2/newsroom"},
        },
        "labels": [],
        "created_at": "2026-08-01T12:00:00Z",
        "merged_at": None,
    }
    support_json = {
        "number": 11,
        "state": "open",
        "body": body(
            lifecycle="support",
            canonical="#10",
            close_when="checkpointed",
        ),
        "draft": True,
        "head": {
            "ref": "support/increment-5b2-correction",
            "sha": "b" * 40,
            "repo": {"full_name": "fol2/newsroom"},
        },
        "labels": [{"name": HOUSEKEEPING_LABEL}],
        "created_at": "2026-08-05T12:00:00Z",
        "merged_at": None,
    }

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self.effects: list[str] = []

        def list_open_pull_requests(self):
            return [canonical_json, support_json]

        def branch_sha(self, ref: str):
            assert ref == "checkpoint/increment-5b2"
            return "b" * 40

        def get_pull_request(self, number: int):
            return canonical_json if number == 10 else support_json

        def comment(self, *_args):
            self.effects.append("comment")

        def close_pull_request(self, *_args):
            self.effects.append("close")

    client = FakeClient()
    monkeypatch.setattr(module, "GithubClient", lambda **_kwargs: client)
    monkeypatch.setenv(
        "PR_HOUSEKEEPING_APPLY",
        "CLOSE_ELIGIBLE_DISPOSABLE_PRS",
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "fol2/newsroom")
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    plan_output = tmp_path / "plan.json"

    module.inventory(
        apply=False,
        revision="c" * 40,
        evaluation_time="2026-08-05T12:00:00Z",
        plan_output=plan_output,
    )
    plan_envelope = json.loads(plan_output.read_text(encoding="utf-8"))
    assert plan_envelope["digest"].startswith("sha256:")
    plan_document = plan_envelope["plan"]
    assert plan_document["schema"] == (
        "newsroom.pr-lifecycle-mutation-plan.v1"
    )
    assert plan_document["revision"] == "c" * 40

    with pytest.raises(
        module.PrLifecycleError,
        match="digest does not match reviewed plan",
    ):
        module.inventory(
            apply=True,
            revision="c" * 40,
            evaluation_time="2026-08-05T12:00:00Z",
            reviewed_revision="c" * 40,
            reviewed_plan_digest="sha256:" + "0" * 64,
        )
    assert client.effects == []


@pytest.mark.parametrize(
    "close_when",
    ("checkpointed", "canonical-merged"),
)
def test_inventory_apply_rejects_action_head_drift_after_digest_check(
    close_when: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_lifecycle_cli(
        f"test_pr_lifecycle_{close_when}_head_drift_cli"
    )
    canonical_is_merged = close_when == "canonical-merged"
    canonical_json = {
        "number": 10,
        "state": "closed" if canonical_is_merged else "open",
        "body": body(),
        "draft": False,
        "head": {
            "ref": "agent/increment-5b2",
            "sha": "a" * 40,
            "repo": {"full_name": "fol2/newsroom"},
        },
        "labels": [],
        "created_at": "2026-08-01T12:00:00Z",
        "merged_at": (
            "2026-08-04T12:00:00Z" if canonical_is_merged else None
        ),
    }
    support_body = body(
        lifecycle="support",
        canonical="#10",
        checkpoint=(
            "NONE"
            if canonical_is_merged
            else "checkpoint/increment-5b2"
        ),
        close_when=close_when,
    )
    planned_support_json = {
        "number": 11,
        "state": "open",
        "body": support_body,
        "draft": True,
        "head": {
            "ref": "support/increment-5b2-correction",
            "sha": "b" * 40,
            "repo": {"full_name": "fol2/newsroom"},
        },
        "labels": [{"name": HOUSEKEEPING_LABEL}],
        "created_at": "2026-08-05T12:00:00Z",
        "merged_at": None,
    }
    current_support_json = {
        **planned_support_json,
        "head": {
            **planned_support_json["head"],
            "sha": "c" * 40,
        },
    }

    class FakeClient:
        def __init__(self) -> None:
            self.effects: list[str] = []
            self.checkpoint_reads = 0

        def list_open_pull_requests(self):
            if canonical_is_merged:
                return [planned_support_json]
            return [canonical_json, planned_support_json]

        def get_pull_request(self, number: int):
            if number == 10:
                return canonical_json
            assert number == 11
            return current_support_json

        def branch_sha(self, ref: str):
            assert not canonical_is_merged
            assert ref == "checkpoint/increment-5b2"
            self.checkpoint_reads += 1
            if self.checkpoint_reads <= 2:
                return "b" * 40
            return "c" * 40

        def comment(self, *_args):
            self.effects.append("comment")

        def close_pull_request(self, *_args):
            self.effects.append("close")

    client = FakeClient()
    monkeypatch.setattr(module, "GithubClient", lambda **_kwargs: client)
    monkeypatch.setenv(
        "PR_HOUSEKEEPING_APPLY",
        "CLOSE_ELIGIBLE_DISPOSABLE_PRS",
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "fol2/newsroom")
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    plan_output = tmp_path / f"{close_when}-plan.json"

    module.inventory(
        apply=False,
        revision="d" * 40,
        evaluation_time="2026-08-05T12:00:00Z",
        plan_output=plan_output,
    )
    plan_envelope = json.loads(plan_output.read_text(encoding="utf-8"))

    with pytest.raises(
        module.GithubApiError,
        match="head SHA changed after planning",
    ):
        module.inventory(
            apply=True,
            revision="d" * 40,
            evaluation_time="2026-08-05T12:00:00Z",
            reviewed_revision="d" * 40,
            reviewed_plan_digest=plan_envelope["digest"],
        )
    assert client.effects == []


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
        checkpoint_head_shas={"checkpoint/increment-5b2": "a" * 40},
        now=NOW,
    )

    assert [item.pr_number for item in plan.close_actions] == [11]
    assert "checkpoint/increment-5b2" in plan.close_actions[0].reason
    assert set(plan.close_actions[0].__dataclass_fields__) == {
        "pr_number",
        "head_sha",
        "reason",
    }


def test_plan_excludes_stale_checkpoint_without_blocking_later_closure() -> None:
    canonical = open_pr(
        10,
        pr_body=body(),
        draft=False,
        head_ref="agent/increment-5b2",
        head_sha="d" * 40,
    )
    stale = open_pr(
        11,
        pr_body=body(
            lifecycle="support",
            canonical="#10",
            checkpoint="checkpoint/stale-support",
            close_when="checkpointed",
        ),
        draft=True,
        head_ref="support/stale-checkpoint",
        head_sha="a" * 40,
    )
    current = open_pr(
        12,
        pr_body=body(
            lifecycle="preflight",
            canonical="#10",
            checkpoint="checkpoint/current-preflight",
            close_when="checkpointed",
        ),
        draft=True,
        head_ref="preflight/current-checkpoint",
        head_sha="c" * 40,
    )

    plan = plan_housekeeping(
        (canonical, stale, current),
        checkpoint_head_shas={
            "checkpoint/stale-support": "b" * 40,
            "checkpoint/current-preflight": "c" * 40,
        },
        now=NOW,
    )

    assert [action.pr_number for action in plan.close_actions] == [12]
    assert plan.warnings == (
        "#11 declared checkpoint is stale: checkpoint/stale-support",
    )


def test_plan_rejects_malformed_checkpoint_head_sha() -> None:
    with pytest.raises(PrLifecycleError, match="checkpoint head SHA"):
        plan_housekeeping(
            (),
            checkpoint_head_shas={"checkpoint/example": "ABC"},
            now=NOW,
        )


def test_automatic_branch_deletion_metadata_is_rejected() -> None:
    legacy = parse_pr_lifecycle(body(retention="keep"))
    assert legacy.branch_retention is BranchRetention.KEEP
    with pytest.raises(
        PrLifecycleError,
        match="canonical branch retention must be delete-after-merge",
    ):
        validate_pull_request_lifecycle(
            legacy,
            pr_number=10,
            draft=False,
            head_ref="agent/increment-5b2",
        )
    validate_pull_request_lifecycle(
        legacy,
        pr_number=10,
        draft=False,
        head_ref="agent/increment-5b2",
        merged=True,
    )
    with pytest.raises(
        PrLifecycleError,
        match="canonical lifecycle must keep or delete-after-merge",
    ):
        parse_pr_lifecycle(body(retention="delete-after-checkpoint"))
    with pytest.raises(
        PrLifecycleError,
        match="disposable Branch-Retention must be keep",
    ):
        parse_pr_lifecycle(
            body(
                lifecycle="support",
                canonical="#10",
                close_when="canonical-merged",
                retention="delete-after-merge",
            )
        )
    with pytest.raises(
        PrLifecycleError,
        match="disposable Branch-Retention must be keep",
    ):
        parse_pr_lifecycle(
            body(
                lifecycle="support",
                canonical="#10",
                close_when="canonical-merged",
                retention="delete-after-checkpoint",
            )
        )


def test_plan_rejects_open_canonical_keep_retention() -> None:
    with pytest.raises(
        PrLifecycleError,
        match="canonical branch retention must be delete-after-merge",
    ):
        plan_housekeeping(
            (
                open_pr(
                    10,
                    pr_body=body(retention="keep"),
                    draft=False,
                    head_ref="agent/increment-5b2",
                ),
            ),
            now=NOW,
        )


def test_merged_canonical_legacy_keep_does_not_abort_inventory() -> None:
    module = _load_lifecycle_cli("test_pr_lifecycle_legacy_keep_cli")
    support = module._open_pr_from_json(
        {
            "number": 11,
            "body": body(
                lifecycle="support",
                canonical="#10",
                close_when="canonical-merged",
            ),
            "draft": True,
            "head": {
                "ref": "support/increment-5b2",
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
                "body": body(retention="keep"),
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

    verified = module._verified_merged_canonical_prs(
        FakeClient(),
        open_prs=(support,),
        lifecycles={support.number: module.parse_pr_lifecycle(support.body)},
    )
    assert set(verified) == {10}
    assert verified[10][1].branch_retention.value == "keep"


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


def test_plan_rejects_shared_same_repository_head_refs() -> None:
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
            retention="keep",
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
            checkpoint_head_shas={"checkpoint/increment-5b2": "a" * 40},
            repository_full_name="fol2/newsroom",
            now=NOW,
        )


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


def test_plan_requires_exact_head_sha_for_canonical_merged_action() -> None:
    support = open_pr(
        11,
        pr_body=body(
            lifecycle="support",
            canonical="#10",
            checkpoint="NONE",
            close_when="canonical-merged",
        ),
        draft=True,
        head_ref="support/increment-5b2-correction",
        head_sha=None,
    )

    plan = plan_housekeeping(
        (support,),
        merged_canonical_prs=frozenset({10}),
        now=NOW,
    )

    assert plan.close_actions == ()
    assert plan.warnings == (
        "#11 current head SHA is unavailable for exact close-plan binding",
    )


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
        checkpoint_head_shas={"checkpoint/increment-5b2": "a" * 40},
        now=NOW,
    )

    assert plan.close_actions == ()
    assert plan.warnings == (
        "#11 lacks required housekeeping label infra",
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


@pytest.mark.parametrize(
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
                head_sha="a" * 40,
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
                "state": "open",
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
                "merged_at": None,
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
                head_sha="a" * 40,
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
                head_sha="a" * 40,
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
                head_sha="a" * 40,
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
                head_sha="a" * 40,
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


def test_workflow_requires_separate_reviewed_plan_dispatch() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (
        repository_root / ".github/workflows/pr-lifecycle.yml"
    ).read_text(encoding="utf-8")
    cli = (
        repository_root / "scripts/sdlc/pr_lifecycle.py"
    ).read_text(encoding="utf-8")

    assert "inventory-plan:" in workflow
    assert "inventory-apply:" in workflow
    assert "inputs.mode == 'plan'" in workflow
    assert "inputs.mode == 'apply'" in workflow
    assert "inputs.reviewed_revision != ''" in workflow
    assert "inputs.reviewed_evaluation_time != ''" in workflow
    assert "inputs.reviewed_plan_digest != ''" in workflow
    assert (
        "inputs.confirmation == 'CLOSE_ELIGIBLE_DISPOSABLE_PRS'"
        in workflow
    )
    assert "PR_HOUSEKEEPING_APPLY: CLOSE_ELIGIBLE_DISPOSABLE_PRS" in workflow
    assert workflow.count("GITHUB_TOKEN: ${{ github.token }}") == 2
    assert workflow.count("ref: ${{ github.sha }}") == 3
    assert "actions/upload-artifact@v4" in workflow
    assert "needs: inventory-plan" not in workflow
    assert "inputs.apply == true" not in workflow
    assert "python scripts/sdlc/pr_lifecycle.py" not in workflow
    apply_permissions = workflow.split("inventory-apply:", 1)[1].split(
        "runs-on:", 1
    )[0]
    assert "contents: read" in apply_permissions
    assert "contents: write" not in workflow
    assert "--reviewed-revision" in workflow
    assert "--reviewed-plan-digest" in workflow
    assert "current mutation plan digest does not match reviewed plan" in cli
    assert "def delete_branch" not in cli
    assert "client.delete_branch" not in cli
    assert 'request("DELETE", f"/git/refs/heads/' not in cli
    assert "Automatic branch deletion: `DISABLED`" in cli


def test_pull_request_head_sha_must_be_full_lowercase_commit() -> None:
    with pytest.raises(PrLifecycleError, match="head SHA"):
        open_pr(
            11,
            pr_body=body(),
            draft=True,
            head_ref="agent/increment-5b2",
            head_sha="ABC",
        )


def test_close_action_has_no_branch_deletion_capability() -> None:
    assert set(CloseAction.__dataclass_fields__) == {
        "pr_number",
        "head_sha",
        "reason",
    }
    action = CloseAction(
        pr_number=11,
        head_sha="a" * 40,
        reason="checkpoint verified",
    )
    assert action.pr_number == 11
    assert action.head_sha == "a" * 40
    assert action.reason == "checkpoint verified"
    with pytest.raises(PrLifecycleError, match="close-action head SHA"):
        CloseAction(
            pr_number=11,
            head_sha="ABC",
            reason="checkpoint verified",
        )
