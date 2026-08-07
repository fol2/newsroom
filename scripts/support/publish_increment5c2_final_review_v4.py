"""Standalone exact publisher for the final Increment 5C2 correction."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterable

REPOSITORY = "fol2/newsroom"
PRODUCT_BRANCH = "agent/increment-5c2-six-named-tools"
CHECKPOINT_BRANCH = "checkpoint/increment-5c2-six-named-tools-20260807"
EXPECTED_PARENT = "f996ddaeb8425215560b51a0838b4ec918a3b66d"
EXPECTED_PARENT_TREE = "2bf8e071c0529a8eb3464671b2611d86483c2984"
EXPECTED_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
EXPECTED_PATCH_SHA256 = "f8113e303d58334f25a372ca6a64769810e5c0551b1c1957eb3afab13b444603"
EXPECTED_TREE = "538382fc84d8fe66ad5ab81baf2dd3e38091246d"
PART_ROOT = Path("scripts/support/patches")
PART_NAMES = tuple(
    f"increment5c2_final_review.patch.b64.part{index:02d}" for index in range(7)
)
PATCH_PATH = Path("/tmp/increment5c2-final-review-corrections.patch")
PRODUCT_ROOT = Path("product-v4")
FOCUSED_LOG = Path("/tmp/increment5c2-final-review-v4-focused.log")
FULL_LOG = Path("/tmp/increment5c2-final-review-v4-full.log")
CLUSTERING_LOG = Path("/tmp/increment5c2-final-review-v4-clustering.log")
RECEIPT = Path("/tmp/increment5c2-final-review-v4-receipt.json")
EXPECTED_FILES = (
    "docs/operations/increment-5c2-six-named-tools.md",
    "docs/traceability/increment-5c2-six-named-tools.md",
    "newsroom/increment5/named_tool_authority_adapters.py",
    "newsroom/increment5/named_tool_branch_execution.py",
    "newsroom/tests/test_increment5c2_named_tool_authority_execution.py",
    "newsroom/tests/test_increment5c2_traceability.py",
)


def run(
    *args: str,
    cwd: Path | None = None,
    capture: bool = False,
    stdout_path: Path | None = None,
) -> str:
    stdout = subprocess.PIPE if capture else None
    stream = None
    if stdout_path is not None:
        stream = stdout_path.open("w", encoding="utf-8")
        stdout = stream
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            check=True,
            text=True,
            stdout=stdout,
            stderr=subprocess.STDOUT if stdout_path is not None else None,
        )
    finally:
        if stream is not None:
            stream.close()
    return completed.stdout.strip() if capture else ""


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def rebuild_patch() -> bytes:
    encoded = "".join(
        "".join((PART_ROOT / name).read_text(encoding="ascii").split())
        for name in PART_NAMES
    )
    try:
        patch = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SystemExit("final 5C2 canonical chunks are not valid Base64") from exc
    actual = sha256(patch)
    if actual != EXPECTED_PATCH_SHA256:
        raise SystemExit(f"final 5C2 patch digest mismatch: {actual}")
    PATCH_PATH.write_bytes(patch)
    return patch


def remote_sha(root: Path, branch: str) -> str:
    result = run(
        "git", "ls-remote", "origin", f"refs/heads/{branch}", cwd=root, capture=True
    )
    rows = [line.split() for line in result.splitlines() if line.strip()]
    exact = [sha for sha, ref in rows if ref == f"refs/heads/{branch}"]
    if len(exact) != 1:
        raise SystemExit(f"required remote branch did not resolve exactly once: {branch}")
    return exact[0]


def remote_tree(branch: str) -> tuple[str, str]:
    root = Path("probe-v4")
    shutil.rmtree(root, ignore_errors=True)
    run("git", "init", "-q", root.as_posix())
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=root)
    sha = remote_sha(root, branch)
    run(
        "git", "fetch", "--no-tags", "--depth=1", "origin", sha, cwd=root
    )
    tree = run("git", "rev-parse", "FETCH_HEAD^{tree}", cwd=root, capture=True)
    return sha, tree


def exact_inventory(root: Path, parent: str, expected: Iterable[str]) -> None:
    actual = tuple(
        line
        for line in run(
            "git", "diff", "--name-only", parent, "HEAD", cwd=root, capture=True
        ).splitlines()
        if line
    )
    if tuple(sorted(actual)) != tuple(sorted(expected)):
        raise SystemExit(f"final 5C2 file inventory drifted: {actual}")


def main() -> None:
    configure_auth()
    product_sha, product_tree = remote_tree(PRODUCT_BRANCH)
    checkpoint_sha, checkpoint_tree = remote_tree(CHECKPOINT_BRANCH)
    main_sha, _main_tree = remote_tree("main")
    if main_sha != EXPECTED_MAIN:
        raise SystemExit(f"main moved before final 5C2 publication: {main_sha}")
    if product_sha != EXPECTED_PARENT:
        if (
            product_tree == EXPECTED_TREE
            and checkpoint_sha == product_sha
            and checkpoint_tree == EXPECTED_TREE
        ):
            print(
                json.dumps(
                    {"already_published": True, "head": product_sha, "tree": product_tree},
                    sort_keys=True,
                )
            )
            return
        raise SystemExit(
            f"canonical 5C2 branch moved unexpectedly: {product_sha} tree={product_tree}"
        )
    if checkpoint_sha != EXPECTED_PARENT:
        raise SystemExit(f"5C2 checkpoint moved unexpectedly: {checkpoint_sha}")

    patch = rebuild_patch()
    shutil.rmtree(PRODUCT_ROOT, ignore_errors=True)
    run("git", "init", "-q", PRODUCT_ROOT.as_posix())
    run(
        "git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=PRODUCT_ROOT
    )
    run(
        "git",
        "fetch",
        "--no-tags",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}:refs/newsroom/product",
        "refs/heads/main:refs/newsroom/main",
        f"refs/heads/{CHECKPOINT_BRANCH}:refs/newsroom/checkpoint",
        cwd=PRODUCT_ROOT,
    )
    if run("git", "rev-parse", "refs/newsroom/product", cwd=PRODUCT_ROOT, capture=True) != EXPECTED_PARENT:
        raise SystemExit("fetched product head differs from exact preflight")
    if run("git", "rev-parse", "refs/newsroom/main", cwd=PRODUCT_ROOT, capture=True) != EXPECTED_MAIN:
        raise SystemExit("fetched main differs from exact preflight")
    if run("git", "rev-parse", "refs/newsroom/checkpoint", cwd=PRODUCT_ROOT, capture=True) != EXPECTED_PARENT:
        raise SystemExit("fetched checkpoint differs from exact preflight")
    parent_tree = run(
        "git", "rev-parse", f"{EXPECTED_PARENT}^{{tree}}", cwd=PRODUCT_ROOT, capture=True
    )
    if parent_tree != EXPECTED_PARENT_TREE:
        raise SystemExit(f"final 5C2 parent tree mismatch: {parent_tree}")

    run("git", "checkout", "-q", "--detach", EXPECTED_PARENT, cwd=PRODUCT_ROOT)
    run("git", "config", "user.name", "James To", cwd=PRODUCT_ROOT)
    run(
        "git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=PRODUCT_ROOT
    )
    subprocess.run(
        ("git", "am", "--committer-date-is-author-date"),
        cwd=PRODUCT_ROOT,
        input=patch,
        check=True,
    )
    head = run("git", "rev-parse", "HEAD", cwd=PRODUCT_ROOT, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=PRODUCT_ROOT, capture=True)
    if tree != EXPECTED_TREE:
        raise SystemExit(f"final 5C2 product tree mismatch: {tree}")
    if run("git", "rev-parse", "HEAD^", cwd=PRODUCT_ROOT, capture=True) != EXPECTED_PARENT:
        raise SystemExit("final 5C2 correction parent drifted")
    exact_inventory(PRODUCT_ROOT, EXPECTED_PARENT, EXPECTED_FILES)
    run("git", "diff", "--check", EXPECTED_PARENT, "HEAD", cwd=PRODUCT_ROOT)
    run(
        "python",
        "-m",
        "compileall",
        "-q",
        "newsroom/increment5/named_tool_authority_adapters.py",
        "newsroom/increment5/named_tool_branch_execution.py",
        "newsroom/tests/test_increment5c2_named_tool_authority_execution.py",
        "newsroom/tests/test_increment5c2_traceability.py",
        cwd=PRODUCT_ROOT,
    )
    run("uv", "lock", "--check", cwd=PRODUCT_ROOT)
    run("uv", "sync", "--dev", "--locked", cwd=PRODUCT_ROOT)

    focused = sorted(
        str(path)
        for path in (PRODUCT_ROOT / "newsroom/tests").glob("test_increment5c*.py")
    )
    focused.extend(
        str(PRODUCT_ROOT / path)
        for path in (
            "newsroom/tests/test_increment5b1_exact_retriever.py",
            "newsroom/tests/test_increment5b2_fulltext_retriever.py",
            "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
            "newsroom/tests/test_increment5b3_vector_retriever.py",
            "newsroom/tests/test_increment5b4_admitted_graph_retriever.py",
            "newsroom/tests/test_increment5b4_neo4j_authority_port.py",
        )
    )
    relative_focused = [str(Path(item).relative_to(PRODUCT_ROOT)) for item in focused]
    run(
        "uv", "run", "pytest", "-q", *relative_focused,
        cwd=PRODUCT_ROOT, stdout_path=FOCUSED_LOG,
    )
    run("uv", "run", "pytest", "-q", cwd=PRODUCT_ROOT, stdout_path=FULL_LOG)
    run(
        "uv", "run", "pytest", "-q",
        "newsroom/tests/test_eval_dataset.py",
        "newsroom/tests/test_eval_metrics.py",
        "newsroom/tests/test_newsroom_clustering_decisions.py",
        cwd=PRODUCT_ROOT, stdout_path=CLUSTERING_LOG,
    )
    if run(
        "git", "status", "--porcelain", "--untracked-files=no", cwd=PRODUCT_ROOT, capture=True
    ):
        raise SystemExit("final 5C2 verification mutated tracked bytes")

    if remote_sha(PRODUCT_ROOT, PRODUCT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("canonical 5C2 branch moved before publication")
    if remote_sha(PRODUCT_ROOT, CHECKPOINT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("5C2 checkpoint moved before publication")
    if remote_sha(PRODUCT_ROOT, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved before final 5C2 publication")
    run(
        "git", "push", "--atomic", "origin",
        f"HEAD:refs/heads/{PRODUCT_BRANCH}",
        f"HEAD:refs/heads/{CHECKPOINT_BRANCH}",
        cwd=PRODUCT_ROOT,
    )

    receipt = {
        "schema_version": "newsroom.increment5c2.final-review-publication.v4",
        "parent": EXPECTED_PARENT,
        "head": head,
        "tree": tree,
        "main": EXPECTED_MAIN,
        "patch_sha256": EXPECTED_PATCH_SHA256,
        "files": list(EXPECTED_FILES),
        "focused": FOCUSED_LOG.read_text(encoding="utf-8").splitlines()[-1],
        "full": FULL_LOG.read_text(encoding="utf-8").splitlines()[-1],
        "clustering": CLUSTERING_LOG.read_text(encoding="utf-8").splitlines()[-1],
    }
    RECEIPT.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    print(RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
