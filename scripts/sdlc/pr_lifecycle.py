#!/usr/bin/env python3
"""Validate PR lifecycle metadata and plan/apply bounded housekeeping."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from newsroom.checks.pr_lifecycle import (
    HousekeepingPlan,
    OpenPullRequest,
    PrLifecycleError,
    parse_pr_lifecycle,
    plan_housekeeping,
    validate_pull_request_event,
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

    def pull_request_is_merged(self, number: int) -> bool:
        value = self.request("GET", f"/pulls/{number}")
        if not isinstance(value, dict):
            raise GithubApiError(f"pull request #{number} response is malformed")
        return value.get("merged_at") is not None

    def branch_exists(self, ref: str) -> bool:
        encoded = quote(ref, safe="")
        value = self.request(
            "GET",
            f"/git/ref/heads/{encoded}",
            allow_not_found=True,
        )
        return value is not None

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


def inventory(*, apply: bool) -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if apply and os.environ.get("PR_HOUSEKEEPING_APPLY") != "true":
        raise PrLifecycleError(
            "apply mode requires PR_HOUSEKEEPING_APPLY=true"
        )
    client = GithubClient(repository=repository, token=token)
    raw_prs = client.list_open_pull_requests()
    open_prs = tuple(_open_pr_from_json(item) for item in raw_prs)

    lifecycles = {
        item.number: parse_pr_lifecycle(item.body)
        for item in open_prs
    }
    referenced_canonical = {
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
        lifecycle = lifecycles[action.pr_number]
        checkpoint = getattr(lifecycle, "checkpoint_ref")
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
