"""Dispatch exact-head gates and finalize Increment 5C2 only after they pass."""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os
import subprocess
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

REPO = "fol2/newsroom"
OWNER = "fol2"
NAME = "newsroom"
PR = 347
ISSUE = 329
PRODUCT_BRANCH = "agent/increment-5c2-six-named-tools"
EXPECTED_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
EXPECTED_TREE = "538382fc84d8fe66ad5ab81baf2dd3e38091246d"
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
            "User-Agent": "newsroom-increment5c2-finalizer",
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
    return subprocess.run(
        args, check=True, text=True, stdout=subprocess.PIPE
    ).stdout.strip()


def remote_sha(branch: str) -> str:
    rows = git_output(
        "git", "ls-remote", f"https://github.com/{REPO}.git", f"refs/heads/{branch}"
    ).splitlines()
    if len(rows) != 1:
        raise SystemExit(f"required branch did not resolve exactly once: {branch}")
    return rows[0].split()[0]


def remote_tree(sha: str) -> str:
    root = "finalizer-probe"
    subprocess.run(("rm", "-rf", root), check=True)
    subprocess.run(("git", "init", "-q", root), check=True)
    subprocess.run(
        ("git", "-C", root, "remote", "add", "origin", f"https://github.com/{REPO}.git"),
        check=True,
    )
    subprocess.run(
        ("git", "-C", root, "fetch", "--no-tags", "--depth=1", "origin", sha),
        check=True,
    )
    return git_output("git", "-C", root, "rev-parse", "FETCH_HEAD^{tree}")


def wait_for_product() -> str:
    deadline = time.monotonic() + 20 * 60
    last = ""
    while time.monotonic() < deadline:
        head = remote_sha(PRODUCT_BRANCH)
        tree = remote_tree(head)
        last = f"{head} tree={tree}"
        if tree == EXPECTED_TREE:
            return head
        time.sleep(15)
    raise SystemExit(f"timed out waiting for exact 5C2 product: {last}")


def dispatch(workflow: str) -> None:
    request(
        "POST",
        f"/repos/{REPO}/actions/workflows/{quote(workflow, safe='')}/dispatches",
        {"ref": PRODUCT_BRANCH},
    )


def exact_run(workflow: str, head: str, not_before: datetime) -> dict[str, Any] | None:
    query = urlencode({"branch": PRODUCT_BRANCH, "event": "workflow_dispatch", "per_page": 30})
    payload = request(
        "GET",
        f"/repos/{REPO}/actions/workflows/{quote(workflow, safe='')}/runs?{query}",
    )
    for run in payload.get("workflow_runs", []):
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if run.get("head_sha") == head and created >= not_before:
            return run
    return None


def wait_for_runs(head: str, started: datetime) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + 30 * 60
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
            raise SystemExit(f"exact-head permanent workflows failed: {failed}")
        if len(observed) == len(WORKFLOWS) and all(
            run.get("status") == "completed" and run.get("conclusion") == "success"
            for run in observed.values()
        ):
            return observed
        time.sleep(15)
    summary = {
        name: (run.get("status"), run.get("conclusion"), run.get("id"))
        for name, run in observed.items()
    }
    raise SystemExit(f"timed out waiting for exact-head workflows: {summary}")


def unresolved_review_threads() -> list[str]:
    query = """
    query($owner:String!,$name:String!,$number:Int!){
      repository(owner:$owner,name:$name){
        pullRequest(number:$number){
          id
          isDraft
          reviewThreads(first:100){nodes{id isResolved}}
        }
      }
    }
    """
    payload = request(
        "POST",
        "/graphql",
        {"query": query, "variables": {"owner": OWNER, "name": NAME, "number": PR}},
    )
    pr = payload["data"]["repository"]["pullRequest"]
    return [node["id"] for node in pr["reviewThreads"]["nodes"] if not node["isResolved"]]


def pr_node() -> tuple[str, bool]:
    query = """
    query($owner:String!,$name:String!,$number:Int!){
      repository(owner:$owner,name:$name){pullRequest(number:$number){id isDraft}}
    }
    """
    payload = request(
        "POST", "/graphql",
        {"query": query, "variables": {"owner": OWNER, "name": NAME, "number": PR}},
    )
    pr = payload["data"]["repository"]["pullRequest"]
    return pr["id"], bool(pr["isDraft"])


def mark_ready(node_id: str) -> None:
    mutation = """
    mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){
      pullRequest{id isDraft}
    }}
    """
    request("POST", "/graphql", {"query": mutation, "variables": {"id": node_id}})


def update_pr(head: str, runs: dict[str, dict[str, Any]]) -> None:
    run_lines = "\n".join(
        f"- `{name}`: run `{runs[name]['id']}` — success" for name in WORKFLOWS
    )
    body = f"""Lifecycle: canonical
Delivery-Atom: increment-5c2-six-named-tools-v1
Canonical-PR: self
Checkpoint-Ref: checkpoint/increment-5c2-six-named-tools-20260807
Close-When: merged
Branch-Retention: keep

Supports #329 and parent #252.

## Status

**Feature-complete and exact-head qualified for squash merge.**

- accepted base: `{EXPECTED_MAIN}`
- exact reviewed head: `{head}`
- exact reviewed tree: `{EXPECTED_TREE}`
- unresolved review threads: `0`

## Delivered

- four fixed typed adapters over the accepted exact, full-text, deterministic fixture-vector and admitted-graph retrievers;
- two fixed read-only SQLite authority adapters for current collision/rights-safe hydration metadata and bounded source/revision impact;
- one closed six-route dispatcher with authorization-before-dispatch and no-existence-leak behavior;
- truthful COMPLETE, INCOMPLETE, POLICY_BLOCKED, STALE and UNAVAILABLE outcomes; NO_MATCH only after completed bounded work;
- immutable authorization, execution, dispatch and raw-upstream audit receipts;
- canonical temporal validation, current-rights checks, result/response bounds and fail-closed integrity behavior;
- operations, traceability and rollback records.

## Exact-head permanent workflows

{run_lines}

The deterministic publisher also required focused 5C/affected-5B tests, the complete repository suite, compilation, locked dependencies, clustering non-regression, exact changed-file inventory and a clean tracked tree before publishing this head.

## Fixed non-effects

5C2 performs no cross-tool hybrid fusion, dependency-root deduplication, factual hydration, complete Retrieval Context construction, Candidate mutation, provider/model/embedding execution, spending, live-source access, publication or activation. `GRAG-035` and `TRI-022` remain 5D/#253. Operational admission remains Increment 8/#148.

Parent #252 remains open after this child merge for its one aggregate Tier-M closeout on the resulting exact `main` head.
"""
    request("PATCH", f"/repos/{REPO}/pulls/{PR}", {"body": body})
    request(
        "POST",
        f"/repos/{REPO}/issues/{PR}/comments",
        {"body": f"Exact-head qualification complete for `{head}` / tree `{EXPECTED_TREE}`. All six permanent workflows succeeded and review threads are zero. Proceeding with SHA-bound squash merge."},
    )


def merge(head: str) -> str:
    result = request(
        "PUT",
        f"/repos/{REPO}/pulls/{PR}/merge",
        {
            "merge_method": "squash",
            "sha": head,
            "commit_title": "Increment 5C2: execute all six bounded named read-only tools (#347)",
            "commit_message": "Completes #329. Parent #252 remains open for aggregate Tier-M closeout.",
        },
    )
    if not result.get("merged"):
        raise SystemExit(f"GitHub refused SHA-bound 5C2 merge: {result}")
    return result["sha"]


def close_issue(head: str, merge_sha: str, runs: dict[str, dict[str, Any]]) -> None:
    run_text = ", ".join(f"{name}={runs[name]['id']}" for name in WORKFLOWS)
    request(
        "POST",
        f"/repos/{REPO}/issues/{ISSUE}/comments",
        {
            "body": (
                "Increment 5C2 is complete. "
                f"Reviewed head `{head}`, tree `{EXPECTED_TREE}`, squash merge `{merge_sha}`. "
                f"Exact-head workflow runs: {run_text}. Zero unresolved review threads. "
                "No production activation or downstream Candidate authority is granted."
            )
        },
    )
    request(
        "PATCH",
        f"/repos/{REPO}/issues/{ISSUE}",
        {"state": "closed", "state_reason": "completed"},
    )


def main() -> None:
    if remote_sha("main") != EXPECTED_MAIN:
        raise SystemExit("main moved before 5C2 finalization")
    head = wait_for_product()
    started = datetime.now(UTC)
    for workflow in WORKFLOWS:
        dispatch(workflow)
    runs = wait_for_runs(head, started)
    if remote_sha(PRODUCT_BRANCH) != head or remote_tree(head) != EXPECTED_TREE:
        raise SystemExit("5C2 product moved after exact-head workflows")
    if remote_sha("main") != EXPECTED_MAIN:
        raise SystemExit("main moved after exact-head workflows")
    threads = unresolved_review_threads()
    if threads:
        raise SystemExit(f"unresolved 5C2 review threads block merge: {threads}")
    update_pr(head, runs)
    node_id, is_draft = pr_node()
    if is_draft:
        mark_ready(node_id)
    merge_sha = merge(head)
    close_issue(head, merge_sha, runs)
    print(json.dumps({"head": head, "tree": EXPECTED_TREE, "merge": merge_sha}, sort_keys=True))


if __name__ == "__main__":
    main()
