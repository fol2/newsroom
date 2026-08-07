"""Write a durable, factual Increment 5 live-status observation to issue #145."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO = "fol2/newsroom"
PROGRAMME = 145
PRODUCT = "agent/increment-5c2-six-named-tools"
CHECKPOINT = "checkpoint/increment-5c2-six-named-tools-20260807"
EXPECTED_FINAL_TREE = "538382fc84d8fe66ad5ab81baf2dd3e38091246d"
WORKFLOWS = (
    "publish-increment5c2-final-review-v4.yml",
    "finalize-increment5c2.yml",
    "close-increment5c.yml",
)
ISSUES = (145, 252, 253, 328, 329, 330, 331, 254, 332, 333)
TOKEN = os.environ["GH_TOKEN"]
API = "https://api.github.com"


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
            "User-Agent": "newsroom-increment5-observer",
        },
    )
    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read()
            return None if not raw else json.loads(raw)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API {method} {path} failed: {exc.code} {body}") from exc


def identity(branch: str) -> tuple[str, str]:
    root = "observer-probe"
    subprocess.run(("rm", "-rf", root), check=True)
    subprocess.run(("git", "init", "-q", root), check=True)
    subprocess.run(
        ("git", "-C", root, "remote", "add", "origin", f"https://github.com/{REPO}.git"),
        check=True,
    )
    rows = subprocess.run(
        ("git", "-C", root, "ls-remote", "origin", f"refs/heads/{branch}"),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()
    if len(rows) != 1:
        return "ABSENT", "ABSENT"
    sha = rows[0].split()[0]
    subprocess.run(
        ("git", "-C", root, "fetch", "--no-tags", "--depth=1", "origin", sha),
        check=True,
    )
    tree = subprocess.run(
        ("git", "-C", root, "rev-parse", "FETCH_HEAD^{tree}"),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    return sha, tree


def latest_run(workflow: str) -> dict[str, Any] | None:
    payload = request(
        "GET",
        f"/repos/{REPO}/actions/workflows/{quote(workflow, safe='')}/runs?per_page=1",
    )
    runs = payload.get("workflow_runs", [])
    return runs[0] if runs else None


def main() -> None:
    main_sha, main_tree = identity("main")
    product_sha, product_tree = identity(PRODUCT)
    checkpoint_sha, checkpoint_tree = identity(CHECKPOINT)
    pr = request("GET", f"/repos/{REPO}/pulls/347")
    issue_states = {number: request("GET", f"/repos/{REPO}/issues/{number}")["state"] for number in ISSUES}
    run_rows = []
    for workflow in WORKFLOWS:
        run = latest_run(workflow)
        if run is None:
            run_rows.append(f"- `{workflow}`: no run found")
        else:
            run_rows.append(
                f"- `{workflow}`: run `{run['id']}` — `{run['status']}` / `{run.get('conclusion')}` "
                f"at `{run['head_sha']}`"
            )
    exact = product_tree == EXPECTED_FINAL_TREE and checkpoint_sha == product_sha and checkpoint_tree == product_tree
    body = f"""## Automated live Increment 5 observation

This is a read-only status observation; it does not grant completion or activation authority.

- `main`: `{main_sha}` / tree `{main_tree}`
- 5C2 canonical: `{product_sha}` / tree `{product_tree}`
- 5C2 checkpoint: `{checkpoint_sha}` / tree `{checkpoint_tree}`
- exact final 5C2 tree present on both refs: `{str(exact).lower()}`
- PR #347: state=`{pr['state']}`, draft=`{str(pr['draft']).lower()}`, merged=`{str(pr['merged']).lower()}`, head=`{pr['head']['sha']}`

Support workflows:

{chr(10).join(run_rows)}

Issue states:

{', '.join(f'#{number}={state}' for number, state in issue_states.items())}

Increment 5 is officially complete only when #252, #253, #254 and #145 are closed from exact merged evidence. Until then, this record intentionally reports it as incomplete.
"""
    request("POST", f"/repos/{REPO}/issues/{PROGRAMME}/comments", {"body": body})
    print(body)


if __name__ == "__main__":
    main()
