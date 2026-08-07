"""Close Increment 5C only after the merged exact main head passes Tier-M."""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os
import re
import subprocess
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

REPO = "fol2/newsroom"
PR_5C2 = 347
ISSUE_5C1 = 328
ISSUE_5C2 = 329
PARENT_5C = 252
PROGRAMME = 145
PARENT_5D = 253
ISSUE_5D1 = 330
ACCEPTED_5C1_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
EXPECTED_5C_TREE = "538382fc84d8fe66ad5ab81baf2dd3e38091246d"
WORKFLOWS = (
    "ci.yml",
    "authority-a2a.yml",
    "authority-a2b.yml",
    "projection-b1.yml",
    "projection-b2-neo4j.yml",
    "evidence.yml",
)
API = "https://api.github.com"
TOKEN = os.environ["GH_TOKEN"]


def request(method: str, path: str, payload: object | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "newsroom-increment5c-closeout",
        },
    )
    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read()
            return None if not raw else json.loads(raw)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API {method} {path} failed: {exc.code} {body}") from exc


def git_output(*args: str) -> str:
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


def main_identity() -> tuple[str, str]:
    root = "increment5c-main-probe"
    subprocess.run(("rm", "-rf", root), check=True)
    subprocess.run(("git", "init", "-q", root), check=True)
    subprocess.run(
        ("git", "-C", root, "remote", "add", "origin", f"https://github.com/{REPO}.git"),
        check=True,
    )
    subprocess.run(
        ("git", "-C", root, "fetch", "--no-tags", "--depth=20", "origin", "main"),
        check=True,
    )
    head = git_output("git", "-C", root, "rev-parse", "FETCH_HEAD")
    tree = git_output("git", "-C", root, "rev-parse", "FETCH_HEAD^{tree}")
    ancestor = subprocess.run(
        ("git", "-C", root, "merge-base", "--is-ancestor", ACCEPTED_5C1_MAIN, head),
        check=False,
    )
    if ancestor.returncode != 0:
        subprocess.run(
            ("git", "-C", root, "fetch", "--no-tags", "origin", ACCEPTED_5C1_MAIN),
            check=True,
        )
        subprocess.run(
            ("git", "-C", root, "merge-base", "--is-ancestor", ACCEPTED_5C1_MAIN, head),
            check=True,
        )
    return head, tree


def wait_for_merge() -> tuple[str, str]:
    deadline = time.monotonic() + 50 * 60
    while time.monotonic() < deadline:
        pr = request("GET", f"/repos/{REPO}/pulls/{PR_5C2}")
        if pr.get("merged"):
            head, tree = main_identity()
            if tree != EXPECTED_5C_TREE:
                raise SystemExit(f"merged 5C main tree is unexpected: {head} {tree}")
            if pr.get("merge_commit_sha") != head:
                raise SystemExit(
                    f"main is not the exact 5C2 squash merge: main={head} pr={pr.get('merge_commit_sha')}"
                )
            return head, tree
        time.sleep(15)
    raise SystemExit("timed out waiting for PR #347 to merge")


def dispatch(workflow: str) -> None:
    request(
        "POST",
        f"/repos/{REPO}/actions/workflows/{quote(workflow, safe='')}/dispatches",
        {"ref": "main"},
    )


def exact_run(workflow: str, head: str, not_before: datetime) -> dict[str, Any] | None:
    query = urlencode({"branch": "main", "event": "workflow_dispatch", "per_page": 30})
    payload = request(
        "GET", f"/repos/{REPO}/actions/workflows/{quote(workflow, safe='')}/runs?{query}"
    )
    for run in payload.get("workflow_runs", []):
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if run.get("head_sha") == head and created >= not_before:
            return run
    return None


def wait_runs(head: str, started: datetime) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + 35 * 60
    observed: dict[str, dict[str, Any]] = {}
    while time.monotonic() < deadline:
        for workflow in WORKFLOWS:
            run = exact_run(workflow, head, started)
            if run is not None:
                observed[workflow] = run
        failed = {
            name: run.get("conclusion")
            for name, run in observed.items()
            if run.get("status") == "completed" and run.get("conclusion") != "success"
        }
        if failed:
            raise SystemExit(f"Increment 5C main-head workflows failed: {failed}")
        if len(observed) == len(WORKFLOWS) and all(
            run.get("status") == "completed" and run.get("conclusion") == "success"
            for run in observed.values()
        ):
            return observed
        time.sleep(15)
    raise SystemExit(
        "timed out waiting for Increment 5C main workflows: "
        + repr({k: (v.get('status'), v.get('conclusion'), v.get('id')) for k, v in observed.items()})
    )


def unresolved_threads() -> list[str]:
    query = """
    query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){
      pullRequest(number:$number){reviewThreads(first:100){nodes{id isResolved}}}
    }}
    """
    payload = request(
        "POST", "/graphql",
        {"query": query, "variables": {"owner": "fol2", "name": "newsroom", "number": PR_5C2}},
    )
    nodes = payload["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    return [node["id"] for node in nodes if not node["isResolved"]]


def issue(number: int) -> dict[str, Any]:
    return request("GET", f"/repos/{REPO}/issues/{number}")


def comment(number: int, body: str) -> None:
    request("POST", f"/repos/{REPO}/issues/{number}/comments", {"body": body})


def close(number: int) -> None:
    request(
        "PATCH", f"/repos/{REPO}/issues/{number}",
        {"state": "closed", "state_reason": "completed"},
    )


def replace_status(body: str, text: str) -> str:
    replacement = f"## Status\n\n{text.strip()}\n"
    pattern = re.compile(r"## Status\n\n.*?(?=\n## )", re.DOTALL)
    if pattern.search(body):
        return pattern.sub(replacement.rstrip(), body, count=1)
    return replacement + "\n" + body


def update_status(number: int, text: str) -> None:
    current = issue(number)
    body = current.get("body") or ""
    request(
        "PATCH", f"/repos/{REPO}/issues/{number}",
        {"body": replace_status(body, text)},
    )


def main() -> None:
    main_head, main_tree = wait_for_merge()
    started = datetime.now(UTC)
    for workflow in WORKFLOWS:
        dispatch(workflow)
    runs = wait_runs(main_head, started)
    current_head, current_tree = main_identity()
    if (current_head, current_tree) != (main_head, main_tree):
        raise SystemExit("main moved during Increment 5C Tier-M qualification")
    threads = unresolved_threads()
    if threads:
        raise SystemExit(f"unresolved PR #347 threads block 5C closeout: {threads}")

    run_text = ", ".join(f"{name}={runs[name]['id']}" for name in WORKFLOWS)
    for child, label in ((ISSUE_5C1, "5C1"), (ISSUE_5C2, "5C2")):
        if issue(child).get("state") != "closed":
            comment(
                child,
                f"{label} tracking is reconciled as completed after the exact merged 5C main head "
                f"`{main_head}` / tree `{main_tree}` passed the aggregate Tier-M gate. "
                f"Runs: {run_text}. Zero unresolved PR #347 review threads.",
            )
            close(child)

    comment(
        PARENT_5C,
        "Increment 5C is complete. Both bounded named-tool atoms are merged and the exact "
        f"integrated main head `{main_head}` / tree `{main_tree}` passed all six permanent "
        f"workflows: {run_text}. Review threads are zero. This closes only the named read-only "
        "tool milestone; hybrid composition and truthful Retrieval Context remain 5D, and no "
        "production activation or operational admission is granted.",
    )
    close(PARENT_5C)

    update_status(
        PROGRAMME,
        "**Increment 5A, 5B and 5C are complete. Increment 5D1/#330 is active.**\n\n"
        f"Accepted Increment 5C boundary: `main@{main_head}` / tree `{main_tree}`. "
        "5D2/#331 and 5E/#254 remain dependency-queued.",
    )
    comment(
        PROGRAMME,
        f"Live continuation record: Increment 5C/#252 completed on `main@{main_head}` "
        f"(tree `{main_tree}`) after aggregate Tier-M runs {run_text}. 5D1/#330 is now the sole "
        "active Increment 5 implementation atom.",
    )
    update_status(
        PARENT_5D,
        "**Active. 5D1/#330 is the sole active child; 5D2/#331 remains dependency-queued.**\n\n"
        f"Accepted predecessor: Increment 5C/#252 on `main@{main_head}`.",
    )
    update_status(
        ISSUE_5D1,
        "**Active — owner-authorised after completion of Increment 5C/#252.**\n\n"
        f"Implementation base: `main@{main_head}` / tree `{main_tree}`. "
        "5D2/#331 remains blocked until this atom is merged and closed.",
    )
    comment(
        ISSUE_5D1,
        f"Implementation is activated on exact base `main@{main_head}` after the 5C Tier-M closeout. "
        "Scope remains exact-first one-request composition, deterministic fusion and authoritative "
        "dependency-root deduplication only; hydration/context authority remains #331.",
    )
    print(json.dumps({"main": main_head, "tree": main_tree, "runs": {k: v['id'] for k, v in runs.items()}}, sort_keys=True))


if __name__ == "__main__":
    main()
