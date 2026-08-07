"""Fix the exact Increment 5C2 actual-Neo4j probe Cypher fixture."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_HEAD = "2d19fa61e64e83674ed2b4f3c48992d76bc53b32"
EXPECTED_TREE = "4adf04d289a1bbb9f89709445302a938196ee065"
EXPECTED_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
PRODUCT_BRANCH = "agent/increment-5c2-six-named-tools"
CHECKPOINT_BRANCH = "checkpoint/increment-5c2-six-named-tools-20260807"
PRODUCT_FILE = "newsroom/tests/test_projection_b2_neo4j_service.py"
FOCUSED_LOG = Path("/tmp/increment5c2-neo4j-probe-focused.log")
FULL_LOG = Path("/tmp/increment5c2-neo4j-probe-full.log")
CLUSTERING_LOG = Path("/tmp/increment5c2-neo4j-probe-clustering.log")
RECEIPT = Path("/tmp/increment5c2-neo4j-probe-receipt.json")


def run(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def run_logged(args: tuple[str, ...], *, cwd: Path, log: Path) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout
    log.write_text(output, encoding="utf-8")
    print(output, end="")
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, args, output=output)
    lines = [line for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def configure_auth() -> None:
    encoded = base64.b64encode(
        f"x-access-token:{os.environ['GH_TOKEN']}".encode()
    ).decode()
    run(
        "git",
        "config",
        "--global",
        "http.https://github.com/.extraheader",
        f"AUTHORIZATION: basic {encoded}",
    )


def remote_sha(root: Path, branch: str) -> str:
    value = run(
        "git",
        "ls-remote",
        "origin",
        f"refs/heads/{branch}",
        cwd=root,
        capture=True,
    )
    if not value:
        raise SystemExit(f"required remote branch is absent: {branch}")
    return value.split()[0]


def checkout() -> Path:
    root = Path("product")
    run("git", "init", "-q", root.as_posix())
    run(
        "git",
        "remote",
        "add",
        "origin",
        f"https://github.com/{REPOSITORY}.git",
        cwd=root,
    )
    if remote_sha(root, PRODUCT_BRANCH) != EXPECTED_HEAD:
        raise SystemExit("canonical 5C2 head moved before probe repair")
    if remote_sha(root, CHECKPOINT_BRANCH) != EXPECTED_HEAD:
        raise SystemExit("5C2 checkpoint moved before probe repair")
    if remote_sha(root, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved before probe repair")
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=12",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=root,
    )
    if run(
        "git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True
    ) != EXPECTED_HEAD:
        raise SystemExit("fetched 5C2 head identity drifted")
    if run(
        "git",
        "rev-parse",
        "refs/remotes/origin/product^{tree}",
        cwd=root,
        capture=True,
    ) != EXPECTED_TREE:
        raise SystemExit("fetched 5C2 head tree drifted")
    run("git", "checkout", "-q", "--detach", EXPECTED_HEAD, cwd=root)
    return root


def patch(root: Path) -> None:
    path = root / PRODUCT_FILE
    text = path.read_text(encoding="utf-8")
    old = '                    "}})",\n'
    new = '                    "})",\n'
    if text.count(old) != 1:
        raise SystemExit("actual-Neo4j probe closing-brace anchor drifted")
    if text.count(new) != 0:
        raise SystemExit("actual-Neo4j probe appears already repaired")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    run("git", "config", "user.name", "James To", cwd=root)
    run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=root,
    )
    run("git", "add", "--", PRODUCT_FILE, cwd=root)
    run("git", "diff", "--cached", "--check", cwd=root)
    changed = run(
        "git", "diff", "--cached", "--name-only", cwd=root, capture=True
    ).splitlines()
    if changed != [PRODUCT_FILE]:
        raise SystemExit(f"probe syntax repair inventory drifted: {changed}")
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "Increment 5C2: fix actual Neo4j scope probe syntax",
        cwd=root,
    )


def verify(root: Path) -> dict[str, str]:
    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    run(
        "uv",
        "run",
        "python",
        "-m",
        "compileall",
        "-q",
        PRODUCT_FILE,
        cwd=root,
    )
    focused = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            PRODUCT_FILE,
            "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
            "newsroom/tests/test_increment5b2_fulltext_retriever.py",
            "newsroom/tests/test_increment5c2_named_tool_branch_adapters.py",
            "newsroom/tests/test_increment5c2_named_tool_dispatch.py",
            "newsroom/tests/test_increment5c2_traceability.py",
        ),
        cwd=root,
        log=FOCUSED_LOG,
    )
    full = run_logged(
        ("uv", "run", "pytest", "-q"),
        cwd=root,
        log=FULL_LOG,
    )
    clustering = run_logged(
        (
            "uv",
            "run",
            "python",
            "scripts/eval_clustering_metrics.py",
            "--dataset",
            "newsroom/evals/clustering_eval_dataset_v1.jsonl",
            "--baseline",
            "newsroom/evals/clustering_eval_metrics_baseline_v1.json",
            "--fail-on-regression",
        ),
        cwd=root,
        log=CLUSTERING_LOG,
    )
    if run("git", "status", "--porcelain", cwd=root, capture=True):
        raise SystemExit("probe repair verification mutated the product tree")
    return {"focused": focused, "full": full, "clustering": clustering}


def publish(root: Path, evidence: dict[str, str]) -> None:
    if remote_sha(root, PRODUCT_BRANCH) != EXPECTED_HEAD:
        raise SystemExit("canonical 5C2 head moved during probe verification")
    if remote_sha(root, CHECKPOINT_BRANCH) != EXPECTED_HEAD:
        raise SystemExit("5C2 checkpoint moved during probe verification")
    if remote_sha(root, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved during probe verification")
    head = run("git", "rev-parse", "HEAD", cwd=root, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    receipt = {
        "schema_version": "newsroom.increment5c2.neo4j-probe-syntax-repair.v1",
        "parent": EXPECTED_HEAD,
        "parent_tree": EXPECTED_TREE,
        "main": EXPECTED_MAIN,
        "head": head,
        "tree": tree,
        "files": [PRODUCT_FILE],
        **evidence,
    }
    RECEIPT.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


def main() -> None:
    configure_auth()
    root = checkout()
    patch(root)
    evidence = verify(root)
    publish(root, evidence)


if __name__ == "__main__":
    main()
