"""Idempotent verifier/publisher for the Increment 5C2 authority atom."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from scripts.support import publish_increment5c2_authority_v2 as v2

AUTHORITY_CHECKPOINT_BRANCH = "checkpoint/increment-5c2-authority-tools-20260807"


def run(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def clone_current() -> tuple[Path, str]:
    root = Path("product")
    run("git", "init", "-q", root.as_posix())
    run("git", "remote", "add", "origin", f"https://github.com/{v2.REPOSITORY}.git", cwd=root)
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=10",
        "origin",
        f"refs/heads/{v2.PRODUCT_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        f"refs/heads/{v2.CHECKPOINT_BRANCH}:refs/remotes/origin/checkpoint",
        cwd=root,
    )
    head = run("git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True)
    main = run("git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True)
    checkpoint = run(
        "git", "rev-parse", "refs/remotes/origin/checkpoint", cwd=root, capture=True
    )
    if main != v2.EXPECTED_MAIN:
        raise SystemExit(f"main moved during authority publication: {main}")
    if checkpoint not in {v2.EXPECTED_PARENT, head}:
        raise SystemExit(f"canonical checkpoint is neither parent nor product head: {checkpoint}")
    run("git", "checkout", "-q", "--detach", head, cwd=root)
    return root, head


def verify_existing(root: Path, head: str) -> None:
    parent = run("git", "rev-parse", "HEAD^", cwd=root, capture=True)
    if parent != v2.EXPECTED_PARENT:
        raise SystemExit(
            f"canonical 5C2 head moved beyond the authority atom: {head} parent={parent}"
        )
    actual = tuple(
        line
        for line in run(
            "git",
            "diff",
            "--name-only",
            f"{v2.EXPECTED_PARENT}..HEAD",
            cwd=root,
            capture=True,
        ).splitlines()
        if line
    )
    if tuple(sorted(actual)) != tuple(sorted(v2.PRODUCT_FILES)):
        raise SystemExit(f"existing authority atom inventory drifted: {actual}")
    run("git", "apply", "--reverse", "--check", v2.PATCH_PATH.as_posix(), cwd=root)


def create_candidate(root: Path) -> str:
    run("git", "apply", "--index", "--whitespace=error-all", v2.PATCH_PATH.as_posix(), cwd=root)
    actual = tuple(
        line
        for line in run(
            "git", "diff", "--cached", "--name-only", cwd=root, capture=True
        ).splitlines()
        if line
    )
    if tuple(sorted(actual)) != tuple(sorted(v2.PRODUCT_FILES)):
        raise SystemExit(f"authority atom inventory drifted: {actual}")
    run("git", "diff", "--cached", "--check", cwd=root)
    run("git", "config", "user.name", "James To", cwd=root)
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=root)
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "Increment 5C2: add fixed authority-backed named tools",
        cwd=root,
    )
    return run("git", "rev-parse", "HEAD", cwd=root, capture=True)


def verify_tests(root: Path) -> tuple[str, str]:
    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    relative_tests = tuple(
        path.relative_to(root).as_posix()
        for path in sorted((root / "newsroom/tests").glob("test_increment5c*.py"))
    )
    focused = v2.run_logged(
        ("uv", "run", "pytest", "-q", *relative_tests),
        cwd=root,
        path=v2.FOCUSED_LOG,
    )
    full = v2.run_logged(
        ("uv", "run", "pytest", "-q"),
        cwd=root,
        path=v2.FULL_LOG,
    )
    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=root, capture=True):
        raise SystemExit("verified authority atom mutated tracked bytes")
    return focused, full


def publish(root: Path, head: str, *, created: bool) -> None:
    remote_product = run(
        "git", "ls-remote", "origin", f"refs/heads/{v2.PRODUCT_BRANCH}", cwd=root, capture=True
    ).split()[0]
    remote_checkpoint = run(
        "git", "ls-remote", "origin", f"refs/heads/{v2.CHECKPOINT_BRANCH}", cwd=root, capture=True
    ).split()[0]
    expected_product = v2.EXPECTED_PARENT if created else head
    if remote_product != expected_product:
        raise SystemExit(f"product ref moved before publication: {remote_product}")
    if remote_checkpoint not in {v2.EXPECTED_PARENT, head}:
        raise SystemExit(f"checkpoint ref moved before publication: {remote_checkpoint}")
    if created:
        run("git", "push", "origin", f"HEAD:refs/heads/{v2.PRODUCT_BRANCH}", cwd=root)
    if remote_checkpoint != head:
        run("git", "push", "origin", f"HEAD:refs/heads/{v2.CHECKPOINT_BRANCH}", cwd=root)
    authority_remote = run(
        "git",
        "ls-remote",
        "origin",
        f"refs/heads/{AUTHORITY_CHECKPOINT_BRANCH}",
        cwd=root,
        capture=True,
    )
    if authority_remote:
        existing = authority_remote.split()[0]
        if existing != head:
            raise SystemExit(f"authority checkpoint differs: {existing}")
    else:
        run("git", "push", "origin", f"HEAD:refs/heads/{AUTHORITY_CHECKPOINT_BRANCH}", cwd=root)


def main() -> None:
    v2.configure_auth()
    _patch, transfer = v2.recover_patch()
    root, original_head = clone_current()
    created = original_head == v2.EXPECTED_PARENT
    if created:
        head = create_candidate(root)
    else:
        verify_existing(root, original_head)
        head = original_head
    focused, full = verify_tests(root)
    publish(root, head, created=created)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)
    receipt = {
        "schema_version": "newsroom.increment5c2.authority-publication.v2",
        "parent": v2.EXPECTED_PARENT,
        "head": head,
        "tree": tree,
        "created_in_this_run": created,
        "files": list(v2.PRODUCT_FILES),
        "focused": focused,
        "full": full,
        "authority_checkpoint": AUTHORITY_CHECKPOINT_BRANCH,
        "transfer": transfer,
        "complete_5c2": False,
        "remaining": [
            "closed six-tool dispatcher and common integrated receipt",
            "operating and traceability records",
            "Tier-S service evidence and final review",
        ],
    }
    v2.RECEIPT.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(v2.RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
