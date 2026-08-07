from __future__ import annotations

import base64
import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile

EXPECTED_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
EXPECTED_HEAD = "76c9a2f8ec48c110ef147084443be97c8c186bbf"
CANONICAL_BRANCH = "agent/increment-5c2-six-named-tools"
CHECKPOINT_BRANCH = "checkpoint/increment-5c2-fulltext-source-scope-20260807"
FOCUSED_LOG = Path("/tmp/increment5c2-source-scope-focused.log")
FULL_LOG = Path("/tmp/increment5c2-source-scope-full.log")
RECEIPT = Path("/tmp/increment5c2-source-scope-receipt.json")
PATCH_B64 = """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"""


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
    run("git", "config", "user.name", "James To", cwd=Path.cwd())
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=Path.cwd())
    run("git", "remote", "set-url", "origin", f"https://x-access-token:{token}@github.com/fol2/newsroom.git", cwd=Path.cwd())
    run("git", "fetch", "--no-tags", "origin", f"refs/heads/{CANONICAL_BRANCH}:refs/remotes/origin/product", "refs/heads/main:refs/remotes/origin/main", cwd=Path.cwd())
    if run("git", "rev-parse", "refs/remotes/origin/product", cwd=Path.cwd()).stdout.strip() != EXPECTED_HEAD:
        raise SystemExit("canonical branch moved before source-scope publication")
    if run("git", "rev-parse", "refs/remotes/origin/main", cwd=Path.cwd()).stdout.strip() != EXPECTED_MAIN:
        raise SystemExit("main moved before source-scope publication")

    product = Path(tempfile.mkdtemp(prefix="increment5c2-source-scope-")) / "product"
    run("git", "worktree", "add", "--detach", str(product), EXPECTED_HEAD, cwd=Path.cwd())
    patch = product.parent / "source-scope.patch"
    patch.write_bytes(gzip.decompress(base64.b64decode(PATCH_B64)))
    run("git", "am", str(patch), cwd=product)
    head = run("git", "rev-parse", "HEAD", cwd=product).stdout.strip()
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=product).stdout.strip()

    run("uv", "lock", "--check", cwd=product)
    run("uv", "sync", "--dev", "--locked", cwd=product)
    focused = run_logged(("uv", "run", "pytest", "-q", "newsroom/tests/test_increment5b2_fulltext_retriever.py", "newsroom/tests/test_increment5b2_neo4j_authority_port.py"), cwd=product, log=FOCUSED_LOG)
    full = run_logged(("uv", "run", "pytest", "-q"), cwd=product, log=FULL_LOG)
    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=product).stdout.strip():
        raise SystemExit("verification mutated tracked product bytes")
    run("git", "fetch", "--no-tags", "origin", f"refs/heads/{CANONICAL_BRANCH}:refs/remotes/origin/product-final", "refs/heads/main:refs/remotes/origin/main-final", cwd=product)
    if run("git", "rev-parse", "refs/remotes/origin/product-final", cwd=product).stdout.strip() != EXPECTED_HEAD:
        raise SystemExit("canonical branch moved during source-scope verification")
    if run("git", "rev-parse", "refs/remotes/origin/main-final", cwd=product).stdout.strip() != EXPECTED_MAIN:
        raise SystemExit("main moved during source-scope verification")
    run("git", "push", "origin", f"HEAD:refs/heads/{CANONICAL_BRANCH}", cwd=product)
    run("git", "push", "origin", f"HEAD:refs/heads/{CHECKPOINT_BRANCH}", cwd=product)
    RECEIPT.write_text(json.dumps({
        "schema_version": "newsroom.increment5c2.source-scope-publication.v1",
        "base": EXPECTED_HEAD,
        "head": head,
        "tree": tree,
        "focused": focused,
        "full": full,
        "canonical_branch": CANONICAL_BRANCH,
        "checkpoint_branch": CHECKPOINT_BRANCH,
        "files": [
            "newsroom/authority/_neo4j_projection_system.py",
            "newsroom/authority/neo4j_fulltext_reader.py",
            "newsroom/increment5/fulltext_contracts.py",
            "newsroom/increment5/fulltext_retriever.py",
            "newsroom/projection/neo4j/_adapter.py",
            "newsroom/tests/increment5b2_helpers.py",
            "newsroom/tests/test_increment5b2_fulltext_retriever.py",
            "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
        ],
        "complete_5c2": False,
    }, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
