#!/usr/bin/env python3
"""Validate PR lifecycle metadata and plan/apply bounded housekeeping."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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

    def delete_branch(self, ref: str) -> None:
        encoded = quote(ref, safe="")
        self.request("DELETE", f"/git/refs/heads/{encoded}")


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
    client = GithubClient(repository=repository, token=token)
    raw_prs = client.list_open_pull_requests()
    open_prs = tuple(_open_pr_from_json(item) for item in raw_prs)

    lifecycles = {
        item.number: parse_pr_lifecycle(item.body)
        for item in open_prs
    }
    merged_canonical = _verified_merged_canonical_prs(
        client,
        open_prs=open_prs,
        lifecycles=lifecycles,
    )
    checkpoint_refs = {
        lifecycle.checkpoint_ref
        for lifecycle in lifecycles.values()
        if lifecycle.checkpoint_ref is not None
    }
    existing_checkpoints = frozenset(
        ref
        for ref in sorted(checkpoint_refs)
        if client.branch_exists(ref)
    )
    plan = plan_housekeeping(
        open_prs,
        merged_canonical_prs=merged_canonical,
        existing_checkpoint_refs=existing_checkpoints,
        repository_full_name=repository,
        now=datetime.now(timezone.utc),
    )

    if apply:
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


def _apply_plan(
    client: GithubClient,
    plan: HousekeepingPlan,
    *,
    lifecycles: dict[int, object],
    repository: str,
) -> None:
    recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for action in plan.close_actions:
        current = _open_pr_from_json(
            client.get_pull_request(action.pr_number)
        )
        lifecycle = parse_pr_lifecycle(current.body)
        validate_pull_request_lifecycle(
            lifecycle,
            pr_number=current.number,
            draft=current.draft,
            head_ref=current.head_ref,
        )
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
            checkpoint_sha = (
                None if checkpoint is None else client.branch_sha(checkpoint)
            )
            head_sha = client.branch_sha(current.head_ref)
            if (
                current.head_repository != repository
                or current.head_ref != action.delete_branch
                or current.head_sha is None
                or checkpoint_sha != current.head_sha
                or head_sha != current.head_sha
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} branch deletion is no longer safe"
                )
        comment = "\n".join(
            (
                "Automated lifecycle housekeeping closure.",
                "",
                f"- Repository: `{repository}`",
                f"- Recorded at: `{recorded_at}`",
                f"- Reason: {action.reason}",
                f"- Checkpoint: `{checkpoint or 'NONE'}`",
                f"- Branch deletion: `{action.delete_branch or 'NONE'}`",
                "",
                "This action never merges or auto-closes a canonical PR.",
            )
        )
        client.comment(action.pr_number, comment)
        client.close_pull_request(action.pr_number)
        if action.delete_branch is not None:
            assert checkpoint is not None
            final_head_sha = client.branch_sha(action.delete_branch)
            final_checkpoint_sha = client.branch_sha(checkpoint)
            if (
                current.head_sha is None
                or final_head_sha != current.head_sha
                or final_checkpoint_sha != current.head_sha
            ):
                raise GithubApiError(
                    f"pull request #{action.pr_number} branch changed before deletion"
                )
            client.delete_branch(action.delete_branch)


def _render_plan(
    plan: HousekeepingPlan,
    *,
    open_count: int,
    apply: bool,
) -> str:
    lines = [
        "## PR lifecycle housekeeping",
        "",
        f"- Mode: `{'APPLY' if apply else 'DRY_RUN'}`",
        f"- Open PRs inspected: `{open_count}`",
        f"- Disposable PRs eligible for closure: `{len(plan.close_actions)}`",
        f"- Age warnings: `{len(plan.warnings)}`",
        "",
    ]
    if plan.close_actions:
        lines.extend(
            (
                "| PR | Reason | Delete branch |",
                "|---:|---|---|",
            )
        )
        lines.extend(
            f"| #{item.pr_number} | {item.reason} | "
            f"`{item.delete_branch or 'NONE'}` |"
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-event":
            if not str(args.event):
                raise PrLifecycleError("GitHub event path is required")
            return validate_event(args.event)
        if args.command == "inventory":
            return inventory(apply=args.apply)
        raise PrLifecycleError("unsupported lifecycle command")
    except (PrLifecycleError, GithubApiError) as exc:
        print(f"PR lifecycle error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
