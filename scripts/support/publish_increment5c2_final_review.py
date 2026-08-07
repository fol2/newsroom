"""Reassemble, verify and publish the final Increment 5C2 review correction."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_PARENT = "f996ddaeb8425215560b51a0838b4ec918a3b66d"
EXPECTED_PARENT_TREE = "2bf8e071c0529a8eb3464671b2611d86483c2984"
EXPECTED_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
EXPECTED_PATCH_SHA256 = "f8113e303d58334f25a372ca6a64769810e5c0551b1c1957eb3afab13b444603"
EXPECTED_TREE = "538382fc84d8fe66ad5ab81baf2dd3e38091246d"
PRODUCT_BRANCH = "agent/increment-5c2-six-named-tools"
CHECKPOINT_BRANCH = "checkpoint/increment-5c2-six-named-tools-20260807"
PART_ROOT = Path("scripts/support/patches")
PART_NAMES = tuple(
    f"increment5c2_final_review.patch.b64.part{index:02d}"
    for index in range(7)
)
PRODUCT_FILES = (
    "docs/operations/increment-5c2-six-named-tools.md",
    "docs/traceability/increment-5c2-six-named-tools.md",
    "newsroom/increment5/named_tool_authority_adapters.py",
    "newsroom/increment5/named_tool_branch_execution.py",
    "newsroom/tests/test_increment5c2_named_tool_authority_execution.py",
    "newsroom/tests/test_increment5c2_traceability.py",
)
PATCH_PATH = Path("/tmp/increment5c2-final-review-corrections.patch")
FOCUSED_LOG = Path("/tmp/increment5c2-final-review-focused.log")
FULL_LOG = Path("/tmp/increment5c2-final-review-full.log")
CLUSTERING_LOG = Path("/tmp/increment5c2-final-review-clustering.log")
RECEIPT = Path("/tmp/increment5c2-final-review-receipt.json")


def run(
    *args: str,
    cwd: Path | None = None,
    capture: bool = False,
) -> str:
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
        raise subprocess.CalledProcessError(
            completed.returncode,
            args,
            output=output,
        )
    lines = [line for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def configure_auth() -> None:
    token = os.environ["GH_TOKEN"]
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
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


def rebuild_patch() -> None:
    if tuple(path.name for path in sorted(PART_ROOT.glob("increment5c2_final_review.patch.b64.part*"))) != PART_NAMES:
        raise SystemExit("final review patch-part inventory is not exact")
    encoded = "".join(
        "".join((PART_ROOT / name).read_text(encoding="ascii").split())
        for name in PART_NAMES
    )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SystemExit("final review patch parts are not valid base64") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != EXPECTED_PATCH_SHA256:
        raise SystemExit(f"final review patch digest mismatch: {actual}")
    PATCH_PATH.write_bytes(raw)


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
    if remote_sha(root, PRODUCT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("canonical 5C2 parent moved before final review publication")
    if remote_sha(root, CHECKPOINT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("5C2 checkpoint moved before final review publication")
    if remote_sha(root, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved before final 5C2 review publication")
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
    if run("git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True) != EXPECTED_PARENT:
        raise SystemExit("fetched 5C2 parent identity drifted")
    if run("git", "rev-parse", "refs/remotes/origin/product^{tree}", cwd=root, capture=True) != EXPECTED_PARENT_TREE:
        raise SystemExit("fetched 5C2 parent tree drifted")
    run("git", "checkout", "-q", "--detach", EXPECTED_PARENT, cwd=root)
    return root


def apply_patch(root: Path) -> tuple[str, str]:
    run("git", "config", "user.name", "James To", cwd=root)
    run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=root,
    )
    run("git", "am", "--no-gpg-sign", PATCH_PATH.as_posix(), cwd=root)
    if run("git", "rev-parse", "HEAD^", cwd=root, capture=True) != EXPECTED_PARENT:
        raise SystemExit("final review correction parent identity drifted")
    changed = tuple(
        line
        for line in run(
            "git",
            "diff",
            "--name-only",
            "HEAD^",
            "HEAD",
            cwd=root,
            capture=True,
        ).splitlines()
        if line
    )
    if tuple(sorted(changed)) != tuple(sorted(PRODUCT_FILES)):
        raise SystemExit(f"final review correction inventory drifted: {changed}")
    run("git", "show", "--check", "--oneline", "HEAD", cwd=root)
    head = run("git", "rev-parse", "HEAD", cwd=root, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)
    if tree != EXPECTED_TREE:
        raise SystemExit(f"final review correction tree mismatch: {tree}")
    return head, tree


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
        "newsroom/increment5/named_tool_authority_adapters.py",
        "newsroom/increment5/named_tool_branch_execution.py",
        cwd=root,
    )
    focused = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5c2_named_tool_authority_execution.py",
            "newsroom/tests/test_increment5c2_named_tool_dispatch.py",
            "newsroom/tests/test_increment5c2_named_tool_branch_adapters.py",
            "newsroom/tests/test_increment5c2a_named_tool_branch_execution.py",
            "newsroom/tests/test_increment5c2_traceability.py",
            "newsroom/tests/test_increment5c1_named_tool_authorization.py",
            "newsroom/tests/test_increment5c1_named_tool_contracts.py",
            "newsroom/tests/test_increment5b2_fulltext_retriever.py",
            "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
            "newsroom/tests/test_increment5b1_exact_retriever.py",
            "newsroom/tests/test_increment5b3_vector_retriever.py",
            "newsroom/tests/test_increment5b4_admitted_graph_retriever.py",
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
        raise SystemExit("final 5C2 verification mutated the product tree")
    return {"focused": focused, "full": full, "clustering": clustering}


def publish(root: Path, head: str, tree: str, evidence: dict[str, str]) -> None:
    if remote_sha(root, PRODUCT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("canonical 5C2 head moved during final verification")
    if remote_sha(root, CHECKPOINT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("5C2 checkpoint moved during final verification")
    if remote_sha(root, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved during final 5C2 verification")
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    receipt = {
        "schema_version": "newsroom.increment5c2.final-review-correction.v1",
        "parent": EXPECTED_PARENT,
        "parent_tree": EXPECTED_PARENT_TREE,
        "main": EXPECTED_MAIN,
        "head": head,
        "tree": tree,
        "patch_sha256": EXPECTED_PATCH_SHA256,
        "files": list(PRODUCT_FILES),
        **evidence,
    }
    RECEIPT.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


def main() -> None:
    configure_auth()
    rebuild_patch()
    root = checkout()
    head, tree = apply_patch(root)
    evidence = verify(root)
    publish(root, head, tree, evidence)


if __name__ == "__main__":
    main()
