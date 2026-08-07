from __future__ import annotations

import base64
import gzip
import json
import os
from pathlib import Path
import tempfile

from scripts.support import publish_increment5c2_source_scope as base


def main() -> None:
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GH_TOKEN is required")
    root = Path.cwd()
    authenticated_origin = f"https://x-access-token:{token}@github.com/fol2/newsroom.git"
    base.run("git", "config", "user.name", "James To", cwd=root)
    base.run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=root,
    )
    base.run("git", "remote", "set-url", "origin", authenticated_origin, cwd=root)
    base.run(
        "git",
        "fetch",
        "--no-tags",
        "origin",
        f"refs/heads/{base.CANONICAL_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=root,
    )
    if base.run("git", "rev-parse", "refs/remotes/origin/product", cwd=root).stdout.strip() != base.EXPECTED_HEAD:
        raise SystemExit("canonical branch moved before source-scope publication")
    if base.run("git", "rev-parse", "refs/remotes/origin/main", cwd=root).stdout.strip() != base.EXPECTED_MAIN:
        raise SystemExit("main moved before source-scope publication")

    product = Path(tempfile.mkdtemp(prefix="increment5c2-source-scope-clone-")) / "product"
    product.mkdir()
    base.run("git", "init", "-q", cwd=product)
    base.run("git", "remote", "add", "origin", authenticated_origin, cwd=product)
    base.run("git", "fetch", "--no-tags", "--depth=1", "origin", base.EXPECTED_HEAD, cwd=product)
    base.run("git", "checkout", "--detach", "-q", "FETCH_HEAD", cwd=product)
    base.run("git", "config", "user.name", "James To", cwd=product)
    base.run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=product,
    )
    patch = product.parent / "source-scope.patch"
    patch.write_bytes(gzip.decompress(base64.b64decode(base.PATCH_B64)))
    base.run("git", "am", str(patch), cwd=product)
    head = base.run("git", "rev-parse", "HEAD", cwd=product).stdout.strip()
    tree = base.run("git", "rev-parse", "HEAD^{tree}", cwd=product).stdout.strip()

    base.run("uv", "lock", "--check", cwd=product)
    base.run("uv", "sync", "--dev", "--locked", cwd=product)
    focused = base.run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5b2_fulltext_retriever.py",
            "newsroom/tests/test_increment5b2_neo4j_authority_port.py",
        ),
        cwd=product,
        log=base.FOCUSED_LOG,
    )
    full = base.run_logged(
        ("uv", "run", "pytest", "-q"),
        cwd=product,
        log=base.FULL_LOG,
    )
    if base.run("git", "status", "--porcelain", "--untracked-files=no", cwd=product).stdout.strip():
        raise SystemExit("verification mutated tracked product bytes")
    if not (product / ".git").is_dir():
        raise SystemExit("standalone verification checkout has no metadata directory")

    base.run(
        "git",
        "fetch",
        "--no-tags",
        "origin",
        f"refs/heads/{base.CANONICAL_BRANCH}:refs/remotes/origin/product-final",
        "refs/heads/main:refs/remotes/origin/main-final",
        cwd=product,
    )
    if base.run("git", "rev-parse", "refs/remotes/origin/product-final", cwd=product).stdout.strip() != base.EXPECTED_HEAD:
        raise SystemExit("canonical branch moved during source-scope verification")
    if base.run("git", "rev-parse", "refs/remotes/origin/main-final", cwd=product).stdout.strip() != base.EXPECTED_MAIN:
        raise SystemExit("main moved during source-scope verification")
    base.run("git", "push", "origin", f"HEAD:refs/heads/{base.CANONICAL_BRANCH}", cwd=product)
    base.run("git", "push", "origin", f"HEAD:refs/heads/{base.CHECKPOINT_BRANCH}", cwd=product)
    base.RECEIPT.write_text(
        json.dumps(
            {
                "schema_version": "newsroom.increment5c2.source-scope-publication.v2",
                "base": base.EXPECTED_HEAD,
                "head": head,
                "tree": tree,
                "focused": focused,
                "full": full,
                "canonical_branch": base.CANONICAL_BRANCH,
                "checkpoint_branch": base.CHECKPOINT_BRANCH,
                "standalone_git_metadata": True,
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
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(base.RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
