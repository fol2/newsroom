#!/usr/bin/env python3
"""Validate lifecycle metadata and bind apply to an exact reviewed plan."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_CONTRACT_PATH = (
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
validate_pull_request_lifecycle = (
    _CONTRACT.validate_pull_request_lifecycle
)


_API = "https://api.github.com"
_API_VERSION = "2022-11-28"


class GithubApiError(RuntimeError):
    """The bounded GitHub housekeeping API call failed."""


class GithubClient:
    def __init__(self, *, repository: str, token: str) -> None:
        if (
            not isinstance(repository, str)
            or repository.count("/") != 1
            or any(not part for part in repository.split("/"))
        ):
            raise GithubApiError("GITHUB_REPOSITORY must be owner/name")
        if not isinstance(token, str) or not token:
            raise GithubApiError("GITHUB_TOKEN is required")
        self._repository = repository
        self._token = token

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        allow_not_found: bool = False,
    ) -> Any:
        url = f"{_API}/repos/{self._repository}{path}"
        data = (
            None
            if payload is None
            else json.dumps(payload, sort_keys=True).encode("utf-8")
        )
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "newsroom-pr-lifecycle-v1",
                "X-GitHub-Api-Version": _API_VERSION,
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as exc:
            if allow_not_found and exc.code == 404:
                return None
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise GithubApiError(
                f"GitHub API {method} {path} failed: HTTP {exc.code}: {detail}"
            ) from exc
        except (OSError, URLError) as exc:
            raise GithubApiError(
                f"GitHub API {method} {path} is unavailable"
            ) from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GithubApiError(
                f"GitHub API {method} {path} returned malformed JSON"
            ) from exc

    def list_open_pull_requests(self) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        page = 1
        while True:
            value = self.request(
                "GET",
                f"/pulls?state=open&per_page=100&page={page}",
            )
            if not isinstance(value, list):
                raise GithubApiError("open pull-request response is malformed")
            rows = [item for item in value if isinstance(item, dict)]
            if len(rows) != len(value):
                raise GithubApiError("open pull-request row is malformed")
            results.extend(rows)
            if len(value) < 100:
                return results
            page += 1
            if page > 20:
                raise GithubApiError("open pull-request pagination is unbounded")

    def get_pull_request(self, number: int) -> dict[str, object]:
        value = self.request("GET", f"/pulls/{number}")
        if not isinstance(value, dict):
            raise GithubApiError(f"pull request #{number} response is malformed")
        return value

    def pull_request_is_merged(self, number: int) -> bool:
        value = self.request("GET", f"/pulls/{number}")
        if not isinstance(value, dict):
            raise GithubApiError(f"pull request #{number} response is malformed")
        return value.get("merged_at") is not None

    def branch_sha(self, ref: str) -> str | None:
        encoded = quote(ref, safe="")
        value = self.request(
            "GET",
            f"/git/ref/heads/{encoded}",
            allow_not_found=True,
        )
        if value is None:
            return None
        if not isinstance(value, dict):
            raise GithubApiError(f"branch {ref} response is malformed")
        raw_object = value.get("object")
        if not isinstance(raw_object, dict):
            raise GithubApiError(f"branch {ref} object is malformed")
        sha = raw_object.get("sha")
        if (
            not isinstance(sha, str)
            or len(sha) != 40
            or any(character not in "0123456789abcdef" for character in sha)
        ):
            raise GithubApiError(f"branch {ref} SHA is malformed")
        return sha

    def branch_exists(self, ref: str) -> bool:
        return self.branch_sha(ref) is not None

    def comment(self, number: int, body: str) -> None:
        self.request(
            "POST",
            f"/issues/{number}/comments",
            payload={"body": body},
        )

    def close_pull_request(self, number: int) -> None:
        value = self.request(
            "PATCH",
            f"/pulls/{number}",
            payload={"state": "closed"},
        )
        if not isinstance(value, dict) or value.get("state") != "closed":
            raise GithubApiError(f"pull request #{number} did not close")


def validate_event(path: Path) -> int:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PrLifecycleError("cannot read GitHub event payload") from exc
    if not isinstance(value, dict):
        raise PrLifecycleError("GitHub event payload must be an object")
    lifecycle = validate_pull_request_event(value)
    print(
        "validated PR lifecycle: "
        f"{lifecycle.kind.value} / {lifecycle.delivery_atom}"
    )
    _write_summary(
        "\n".join(
            (
                "## PR lifecycle validation",
                "",
                f"- Lifecycle: `{lifecycle.kind.value}`",
                f"- Delivery atom: `{lifecycle.delivery_atom}`",
                "- Result: **PASS**",
            )
        )
    )
    return 0


def _verified_merged_canonical_prs(
    client: GithubClient,
    *,
    open_prs: tuple[OpenPullRequest, ...],
    lifecycles: dict[int, object],
) -> dict[int, tuple[OpenPullRequest, object]]:
    open_numbers = {item.number for item in open_prs}
    referenced = {
        getattr(lifecycle, "canonical_pr")
        for lifecycle in lifecycles.values()
        if getattr(lifecycle, "canonical_pr") is not None
    }
    verified: dict[int, tuple[OpenPullRequest, object]] = {}
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
        verified[number] = (canonical_pr, canonical_lifecycle)

    for pr in open_prs:
        lifecycle = lifecycles[pr.number]
        canonical_number = getattr(lifecycle, "canonical_pr")
        if (
            not getattr(lifecycle, "is_disposable")
            or canonical_number in open_numbers
        ):
            continue
        verified_record = verified.get(canonical_number)
        if verified_record is None:
            continue
        canonical_lifecycle = verified_record[1]
        if (
            getattr(canonical_lifecycle, "delivery_atom")
            != getattr(lifecycle, "delivery_atom")
        ):
            raise GithubApiError(
                f"#{pr.number} delivery atom differs from merged canonical "
                f"#{canonical_number}"
            )
    return verified


def _validated_commit_sha(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PrLifecycleError(
            f"{field} must be a lowercase full commit SHA"
        )
    return value


def _validated_plan_digest(value: str, *, field: str) -> str:
    prefix = "sha256:"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise PrLifecycleError(
            f"{field} must be sha256:<64 lowercase hex characters>"
        )
    payload = value[len(prefix) :]
    if (
        len(payload) != 64
        or any(character not in "0123456789abcdef" for character in payload)
    ):
        raise PrLifecycleError(
            f"{field} must be sha256:<64 lowercase hex characters>"
        )
    return value


def _parse_evaluation_time(value: str | None) -> datetime:
    if value is None or not value:
        return datetime.now(timezone.utc).replace(microsecond=0)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PrLifecycleError(
            "plan evaluation time must be RFC3339 UTC seconds"
        ) from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timezone.utc.utcoffset(parsed)
        or parsed.microsecond != 0
        or not value.endswith("Z")
    ):
        raise PrLifecycleError(
            "plan evaluation time must be RFC3339 UTC seconds"
        )
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _lifecycle_record(lifecycle: object) -> dict[str, object]:
    canonical_pr = getattr(lifecycle, "canonical_pr")
    return {
        "kind": getattr(lifecycle, "kind").value,
        "delivery_atom": getattr(lifecycle, "delivery_atom"),
        "canonical_pr": canonical_pr,
        "checkpoint_ref": getattr(lifecycle, "checkpoint_ref"),
        "close_when": getattr(lifecycle, "close_when").value,
        "branch_retention": getattr(lifecycle, "branch_retention").value,
    }


def _pull_request_record(
    pr: OpenPullRequest,
    lifecycle: object,
) -> dict[str, object]:
    return {
        "number": pr.number,
        "body_sha256": "sha256:"
        + sha256(pr.body.encode("utf-8")).hexdigest(),
        "draft": pr.draft,
        "head_ref": pr.head_ref,
        "head_repository": pr.head_repository,
        "head_sha": pr.head_sha,
        "created_at": _utc_text(pr.created_at),
        "labels": sorted(pr.labels),
        "lifecycle": _lifecycle_record(lifecycle),
    }


def _build_mutation_plan_document(
    *,
    repository: str,
    revision: str,
    evaluation_time: datetime,
    open_prs: tuple[OpenPullRequest, ...],
    lifecycles: dict[int, object],
    merged_canonical_records: dict[
        int,
        tuple[OpenPullRequest, object],
    ],
    checkpoint_head_shas: dict[str, str],
    plan: HousekeepingPlan,
) -> dict[str, object]:
    return {
        "schema": "newsroom.pr-lifecycle-mutation-plan.v1",
        "repository": repository,
        "revision": revision,
        "evaluation_time": _utc_text(evaluation_time),
        "open_pull_requests": [
            _pull_request_record(pr, lifecycles[pr.number])
            for pr in sorted(open_prs, key=lambda item: item.number)
        ],
        "verified_merged_canonical_pull_requests": [
            _pull_request_record(pr, lifecycle)
            for _, (pr, lifecycle) in sorted(
                merged_canonical_records.items()
            )
        ],
        "checkpoint_head_shas": {
            ref: checkpoint_head_shas[ref]
            for ref in sorted(checkpoint_head_shas)
        },
        "close_actions": [
            {
                "pr_number": action.pr_number,
                "head_sha": action.head_sha,
                "reason": action.reason,
            }
            for action in plan.close_actions
        ],
        "warnings": list(plan.warnings),
    }


def _canonical_plan_bytes(document: dict[str, object]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _mutation_plan_digest(document: dict[str, object]) -> str:
    return "sha256:" + sha256(_canonical_plan_bytes(document)).hexdigest()


def _write_plan_document(
    path: Path,
    document: dict[str, object],
    *,
    plan_digest: str,
) -> None:
    path.write_text(
        json.dumps(
            {
                "digest": plan_digest,
                "plan": document,
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def inventory(
    *,
    apply: bool,
    revision: str,
    evaluation_time: str | None = None,
    reviewed_revision: str | None = None,
    reviewed_plan_digest: str | None = None,
    plan_output: Path | None = None,
) -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if (
        apply
        and os.environ.get("PR_HOUSEKEEPING_APPLY")
        != "CLOSE_ELIGIBLE_DISPOSABLE_PRS"
    ):
        raise PrLifecycleError(
            "apply mode requires the exact housekeeping confirmation"
        )

    executing_revision = _validated_commit_sha(
        revision,
        field="executing revision",
    )
    evaluated_at = _parse_evaluation_time(evaluation_time)
    expected_digest: str | None = None
    if apply:
        reviewed = _validated_commit_sha(
            reviewed_revision or "",
            field="reviewed revision",
        )
        if reviewed != executing_revision:
            raise PrLifecycleError(
                "reviewed revision does not match executing revision"
            )
        expected_digest = _validated_plan_digest(
            reviewed_plan_digest or "",
            field="reviewed plan digest",
        )

    client = GithubClient(repository=repository, token=token)
    raw_prs = client.list_open_pull_requests()
    open_prs = tuple(_open_pr_from_json(item) for item in raw_prs)

    lifecycles = {
        item.number: parse_pr_lifecycle(item.body)
        for item in open_prs
    }
    merged_canonical_records = _verified_merged_canonical_prs(
        client,
        open_prs=open_prs,
        lifecycles=lifecycles,
    )
    checkpoint_refs = {
        lifecycle.checkpoint_ref
        for lifecycle in lifecycles.values()
        if lifecycle.checkpoint_ref is not None
    }
    checkpoint_head_shas = {
        ref: sha
        for ref in sorted(checkpoint_refs)
        if (sha := client.branch_sha(ref)) is not None
    }
    plan = plan_housekeeping(
        open_prs,
        merged_canonical_prs=frozenset(merged_canonical_records),
        checkpoint_head_shas=checkpoint_head_shas,
        repository_full_name=repository,
        now=evaluated_at,
    )
    document = _build_mutation_plan_document(
        repository=repository,
        revision=executing_revision,
        evaluation_time=evaluated_at,
        open_prs=open_prs,
        lifecycles=lifecycles,
        merged_canonical_records=merged_canonical_records,
        checkpoint_head_shas=checkpoint_head_shas,
        plan=plan,
    )
    plan_digest = _mutation_plan_digest(document)
    if plan_output is not None:
        _write_plan_document(
            plan_output,
            document,
            plan_digest=plan_digest,
        )

    if apply:
        assert expected_digest is not None
        if plan_digest != expected_digest:
            raise PrLifecycleError(
                "current mutation plan digest does not match reviewed plan"
            )
        _apply_plan(
            client,
            plan,
            lifecycles=lifecycles,
            repository=repository,
        )
    output = _render_plan(
        plan,
        open_count=len(open_prs),
        apply=apply,
        revision=executing_revision,
        evaluation_time=evaluated_at,
        plan_digest=plan_digest,
    )
    print(output)
    _write_summary(output)
    return 0


def _open_pr_from_json(value: dict[str, object]) -> OpenPullRequest:
    try:
        number = int(value["number"])
        body = value.get("body") or ""
        draft = value["draft"]
        head = value["head"]
        if not isinstance(head, dict):
            raise TypeError
        head_ref = head["ref"]
        head_sha = str(head["sha"])
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
    except (KeyError, TypeError, ValueError) as exc:
        raise GithubApiError("open pull-request inventory row is malformed") from exc
    return OpenPullRequest(
        number=number,
        body=str(body),
        draft=draft,  # type: ignore[arg-type]
        head_ref=head_ref,  # type: ignore[arg-type]
        created_at=created_at,
        labels=labels,
        head_repository=head_repository,
        head_sha=head_sha,
    )



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


def _apply_plan(
    client: GithubClient,
    plan: HousekeepingPlan,
    *,
    lifecycles: dict[int, object],
    repository: str,
) -> None:
    recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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
        if current.head_sha != action.head_sha:
            raise GithubApiError(
                f"pull request #{action.pr_number} head SHA changed after planning"
            )
        lifecycle = parse_pr_lifecycle(current.body)
        validate_pull_request_lifecycle(
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
        if not lifecycle.is_disposable:
            raise GithubApiError(
                f"pull request #{action.pr_number} is no longer disposable"
            )
        if lifecycle.branch_retention.value != "keep":
            raise GithubApiError(
                f"pull request #{action.pr_number} requests housekeeping "
                "Git-ref deletion"
            )
        if HOUSEKEEPING_LABEL not in current.labels:
            raise GithubApiError(
                f"pull request #{action.pr_number} lost its housekeeping label"
            )
        checkpoint = lifecycle.checkpoint_ref
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
            raise GithubApiError(
                f"pull request #{action.pr_number} close condition changed"
            )
        comment = "\n".join(
            (
                "Automated lifecycle housekeeping closure.",
                "",
                f"- Repository: `{repository}`",
                f"- Recorded at: `{recorded_at}`",
                f"- Reason: {action.reason}",
                f"- Checkpoint: `{checkpoint or 'NONE'}`",
                "- Automatic branch deletion: `DISABLED`",
                "- Branch retention: `keep`",
                "",
                "This action never merges or auto-closes a canonical PR.",
            )
        )
        client.comment(action.pr_number, comment)
        client.close_pull_request(action.pr_number)


def _render_plan(
    plan: HousekeepingPlan,
    *,
    open_count: int,
    apply: bool,
    revision: str,
    evaluation_time: datetime,
    plan_digest: str,
) -> str:
    lines = [
        "## PR lifecycle housekeeping",
        "",
        f"- Mode: `{'APPLY' if apply else 'PLAN'}`",
        f"- Immutable revision: `{revision}`",
        f"- Plan evaluation time: `{_utc_text(evaluation_time)}`",
        f"- Reviewed mutation plan digest: `{plan_digest}`",
        f"- Open PRs inspected: `{open_count}`",
        f"- Disposable PRs eligible for closure: `{len(plan.close_actions)}`",
        f"- Warnings: `{len(plan.warnings)}`",
        "- Automatic branch deletion: `DISABLED`",
        "",
    ]
    if plan.close_actions:
        lines.extend(
            (
                "| PR | Reason |",
                "|---:|---|",
            )
        )
        lines.extend(
            f"| #{item.pr_number} | {item.reason} |"
            for item in plan.close_actions
        )
        lines.append("")
    if plan.warnings:
        lines.append("### Warnings")
        lines.extend(f"- {warning}" for warning in plan.warnings)
        lines.append("")
    if not plan.close_actions and not plan.warnings:
        lines.append("No lifecycle action is required.")
    return "\n".join(lines)


def _write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(text)
        handle.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-event")
    validate.add_argument(
        "--event",
        type=Path,
        default=Path(os.environ.get("GITHUB_EVENT_PATH", "")),
    )

    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--apply", action="store_true")
    inventory_parser.add_argument(
        "--revision",
        default=os.environ.get("GITHUB_SHA", ""),
    )
    inventory_parser.add_argument(
        "--evaluation-time",
        default="",
    )
    inventory_parser.add_argument(
        "--reviewed-revision",
        default="",
    )
    inventory_parser.add_argument(
        "--reviewed-plan-digest",
        default="",
    )
    inventory_parser.add_argument(
        "--plan-output",
        type=Path,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-event":
            if not str(args.event):
                raise PrLifecycleError("GitHub event path is required")
            return validate_event(args.event)
        if args.command == "inventory":
            return inventory(
                apply=args.apply,
                revision=args.revision,
                evaluation_time=args.evaluation_time,
                reviewed_revision=args.reviewed_revision,
                reviewed_plan_digest=args.reviewed_plan_digest,
                plan_output=args.plan_output,
            )
        raise PrLifecycleError("unsupported lifecycle command")
    except (PrLifecycleError, GithubApiError) as exc:
        print(f"PR lifecycle error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
