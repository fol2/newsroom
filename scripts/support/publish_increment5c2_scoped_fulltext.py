"""Apply, verify and publish the exact Increment 5C2 scoped full-text repair."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_HEAD = "6c528755e2103c033244d2a0a4b58a0b4a62dfb7"
EXPECTED_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
PRODUCT_BRANCH = "agent/increment-5c2-six-named-tools"
CHECKPOINT_BRANCH = "checkpoint/increment-5c2-six-named-tools-20260807"
PATCH_PATH = (
    Path(__file__).resolve().parent
    / "patches"
    / "increment5c2_scoped_fulltext.patch"
)
PATCH_SHA256 = "67227c6f0ba8f7a2c238f24973946a422c5f8c0d3ccf6e9e80d79de679690998"
PRODUCT_FILES = (
    "newsroom/authority/neo4j_fulltext_reader.py",
    "newsroom/increment5/fulltext_retriever.py",
    "newsroom/projection/neo4j/_adapter.py",
    "newsroom/tests/increment5b2_helpers.py",
    "newsroom/tests/test_increment5b2_fulltext_retriever.py",
    "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
    "newsroom/tests/test_projection_b2_neo4j_service.py",
)
FOCUSED_LOG = Path("/tmp/increment5c2-scoped-fulltext-focused.log")
FULL_LOG = Path("/tmp/increment5c2-scoped-fulltext-full.log")
CLUSTERING_LOG = Path("/tmp/increment5c2-scoped-fulltext-clustering.log")
RECEIPT = Path("/tmp/increment5c2-scoped-fulltext-receipt.json")


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
    # Verify all three mutable authorities before fetching any product object.
    # The checkpoint ref is intentionally inspected with ls-remote rather than
    # mapped below `refs/remotes/origin/checkpoint`, which conflicts with the
    # real `checkpoint/...` remote namespace.
    actual_head = remote_sha(root, PRODUCT_BRANCH)
    actual_checkpoint = remote_sha(root, CHECKPOINT_BRANCH)
    actual_main = remote_sha(root, "main")
    if actual_head != EXPECTED_HEAD:
        raise SystemExit(f"canonical 5C2 head moved: {actual_head}")
    if actual_checkpoint != EXPECTED_HEAD:
        raise SystemExit(f"5C2 checkpoint moved independently: {actual_checkpoint}")
    if actual_main != EXPECTED_MAIN:
        raise SystemExit(f"main moved before scoped full-text repair: {actual_main}")
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=8",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=root,
    )
    fetched_head = run(
        "git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True
    )
    fetched_main = run(
        "git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True
    )
    if fetched_head != EXPECTED_HEAD or fetched_main != EXPECTED_MAIN:
        raise SystemExit("fetched product or main identity changed after preflight")
    run("git", "checkout", "-q", "--detach", EXPECTED_HEAD, cwd=root)
    return root


def apply_patch(root: Path) -> None:
    raw = PATCH_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PATCH_SHA256:
        raise SystemExit("scoped full-text repair patch digest mismatch")
    run("git", "config", "user.name", "James To", cwd=root)
    run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=root,
    )
    run("git", "am", "--no-gpg-sign", PATCH_PATH.as_posix(), cwd=root)
    if run("git", "rev-parse", "HEAD^", cwd=root, capture=True) != EXPECTED_HEAD:
        raise SystemExit("scoped full-text repair parent identity drifted")
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
        raise SystemExit(f"scoped full-text repair inventory drifted: {changed}")
    run("git", "show", "--check", "--oneline", "HEAD", cwd=root)


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
        "newsroom/authority/neo4j_fulltext_reader.py",
        "newsroom/increment5/fulltext_retriever.py",
        "newsroom/projection/neo4j/_adapter.py",
        cwd=root,
    )
    focused = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5b2_fulltext_retriever.py",
            "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
            "newsroom/tests/test_increment5c2_named_tool_branch_adapters.py",
            "newsroom/tests/test_increment5c2_named_tool_dispatch.py",
            "newsroom/tests/test_increment5c2a_named_tool_branch_execution.py",
            "newsroom/tests/test_projection_b2_neo4j_service.py",
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
        raise SystemExit("scoped full-text verification mutated the product tree")
    return {"focused": focused, "full": full, "clustering": clustering}


def publish(root: Path, evidence: dict[str, str]) -> None:
    if remote_sha(root, PRODUCT_BRANCH) != EXPECTED_HEAD:
        raise SystemExit("canonical 5C2 head moved during verification")
    if remote_sha(root, CHECKPOINT_BRANCH) != EXPECTED_HEAD:
        raise SystemExit("5C2 checkpoint moved during verification")
    if remote_sha(root, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved during scoped full-text verification")
    head = run("git", "rev-parse", "HEAD", cwd=root, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    receipt = {
        "schema_version": "newsroom.increment5c2.scoped-fulltext-repair.v1",
        "parent": EXPECTED_HEAD,
        "main": EXPECTED_MAIN,
        "head": head,
        "tree": tree,
        "patch_sha256": PATCH_SHA256,
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
    root = checkout()
    apply_patch(root)
    evidence = verify(root)
    publish(root, evidence)


if __name__ == "__main__":
    main()
