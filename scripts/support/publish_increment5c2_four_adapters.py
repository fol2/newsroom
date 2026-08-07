from __future__ import annotations

import base64
import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile

EXPECTED_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
EXPECTED_PARENT = "07d7d7b122eaba19a4ae9ca8ba3ed38f80e2b892"
CANONICAL_BRANCH = "agent/increment-5c2-six-named-tools"
CHECKPOINT_BRANCH = "checkpoint/increment-5c2-four-typed-adapters-20260807"
FOCUSED_LOG = Path("/tmp/increment5c2-four-adapters-focused.log")
WIDE_LOG = Path("/tmp/increment5c2-four-adapters-wide.log")
FULL_LOG = Path("/tmp/increment5c2-four-adapters-full.log")
RECEIPT = Path("/tmp/increment5c2-four-adapters-receipt.json")
PATCH_B64 = """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"""


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check and result.returncode != 0:
        print(result.stdout, end="")
        raise SystemExit(result.returncode)
    return result


def run_logged(args: tuple[str, ...], *, cwd: Path, log: Path) -> str:
    result = run(*args, cwd=cwd, check=False)
    log.write_text(result.stdout, encoding="utf-8")
    print(result.stdout, end="")
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.stdout.strip().splitlines()[-1]


def main() -> None:
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GH_TOKEN is required")
    authenticated_origin = (
        f"https://x-access-token:{token}@github.com/fol2/newsroom.git"
    )
    product = Path(tempfile.mkdtemp(prefix="increment5c2-adapters-clone-")) / "product"
    product.mkdir()
    run("git", "init", "-q", cwd=product)
    run("git", "remote", "add", "origin", authenticated_origin, cwd=product)
    run("git", "fetch", "--no-tags", "--depth=1", "origin", EXPECTED_PARENT, cwd=product)
    run("git", "checkout", "--detach", "-q", "FETCH_HEAD", cwd=product)
    run("git", "config", "user.name", "James To", cwd=product)
    run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=product,
    )
    if not (product / ".git").is_dir():
        raise SystemExit("standalone product checkout has no metadata directory")

    patch = product.parent / "four-adapters.patch"
    patch.write_bytes(gzip.decompress(base64.b64decode(PATCH_B64)))
    run("git", "am", str(patch), cwd=product)
    head = run("git", "rev-parse", "HEAD", cwd=product).stdout.strip()
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=product).stdout.strip()

    run("uv", "lock", "--check", cwd=product)
    run("uv", "sync", "--dev", "--locked", cwd=product)
    focused = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5c2_named_tool_branch_adapters.py",
            "newsroom/tests/test_increment5c2a_named_tool_branch_execution.py",
            "newsroom/tests/test_increment5b2_fulltext_retriever.py",
            "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
        ),
        cwd=product,
        log=FOCUSED_LOG,
    )
    wide = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5b1_exact_retriever.py",
            "newsroom/tests/test_increment5b2_fulltext_retriever.py",
            "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
            "newsroom/tests/test_increment5b3_vector_retriever.py",
            "newsroom/tests/test_increment5b4_admitted_graph_retriever.py",
            "newsroom/tests/test_increment5c1_named_tool_authorization.py",
            "newsroom/tests/test_increment5c1_named_tool_contracts.py",
            "newsroom/tests/test_increment5c2a_named_tool_branch_execution.py",
            "newsroom/tests/test_increment5c2_named_tool_branch_adapters.py",
        ),
        cwd=product,
        log=WIDE_LOG,
    )
    full = run_logged(
        ("uv", "run", "pytest", "-q"),
        cwd=product,
        log=FULL_LOG,
    )
    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=product).stdout.strip():
        raise SystemExit("adapter verification mutated tracked product bytes")

    run(
        "git",
        "fetch",
        "--no-tags",
        "origin",
        f"refs/heads/{CANONICAL_BRANCH}:refs/remotes/origin/product-final",
        "refs/heads/main:refs/remotes/origin/main-final",
        cwd=product,
    )
    if run("git", "rev-parse", "refs/remotes/origin/product-final", cwd=product).stdout.strip() != EXPECTED_PARENT:
        raise SystemExit("canonical branch moved during adapter verification")
    if run("git", "rev-parse", "refs/remotes/origin/main-final", cwd=product).stdout.strip() != EXPECTED_MAIN:
        raise SystemExit("main moved during adapter verification")
    run("git", "push", "origin", f"HEAD:refs/heads/{CANONICAL_BRANCH}", cwd=product)
    run("git", "push", "origin", f"HEAD:refs/heads/{CHECKPOINT_BRANCH}", cwd=product)

    RECEIPT.write_text(
        json.dumps(
            {
                "schema_version": "newsroom.increment5c2.four-adapters-publication.v1",
                "parent": EXPECTED_PARENT,
                "head": head,
                "tree": tree,
                "focused": focused,
                "wide": wide,
                "full": full,
                "canonical_branch": CANONICAL_BRANCH,
                "checkpoint_branch": CHECKPOINT_BRANCH,
                "files": [
                    "newsroom/increment5/named_tool_branch_adapters.py",
                    "newsroom/increment5/named_tool_branch_execution.py",
                    "newsroom/tests/test_increment5c2_named_tool_branch_adapters.py",
                    "newsroom/tests/test_increment5c2a_named_tool_branch_execution.py",
                ],
                "complete_5c2": False,
                "remaining": [
                    "current collision and authority lookup",
                    "bounded source revision impact lookup",
                    "integrated six-tool dispatch and receipts",
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
