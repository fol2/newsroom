"""Idempotent exact-part publisher with isolated remote-ref probes."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import shutil
import subprocess

from scripts.support import publish_increment5c2_final_review as publisher


def _run(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def _exact_rebuild_patch() -> None:
    encoded = "".join(
        "".join((publisher.PART_ROOT / name).read_text(encoding="ascii").split())
        for name in publisher.PART_NAMES
    )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SystemExit("final review canonical patch parts are not valid base64") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != publisher.EXPECTED_PATCH_SHA256:
        raise SystemExit(f"final review canonical patch digest mismatch: {actual}")
    publisher.PATCH_PATH.write_bytes(raw)


def _remote_tree(branch: str) -> tuple[str, str]:
    slug = branch.replace("/", "-")
    root = Path(f"probe-{slug}")
    shutil.rmtree(root, ignore_errors=True)
    _run("git", "init", "-q", root.as_posix())
    _run(
        "git",
        "remote",
        "add",
        "origin",
        f"https://github.com/{publisher.REPOSITORY}.git",
        cwd=root,
    )
    sha = publisher.remote_sha(root, branch)
    _run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "origin",
        f"{sha}:refs/newsroom/current",
        cwd=root,
    )
    tree = _run(
        "git", "rev-parse", "refs/newsroom/current^{tree}", cwd=root, capture=True
    )
    return sha, tree


def main() -> None:
    publisher.configure_auth()
    product_sha, product_tree = _remote_tree(publisher.PRODUCT_BRANCH)
    checkpoint_sha, checkpoint_tree = _remote_tree(publisher.CHECKPOINT_BRANCH)
    main_sha, _main_tree = _remote_tree("main")

    if main_sha != publisher.EXPECTED_MAIN:
        raise SystemExit(f"main moved before final 5C2 publication: {main_sha}")

    if product_sha != publisher.EXPECTED_PARENT:
        if (
            product_tree == publisher.EXPECTED_TREE
            and checkpoint_sha == product_sha
            and checkpoint_tree == publisher.EXPECTED_TREE
        ):
            print(
                "final Increment 5C2 correction already published exactly: "
                f"{product_sha} tree={product_tree}"
            )
            return
        raise SystemExit(
            "canonical 5C2 ref moved to an unexpected product: "
            f"head={product_sha} tree={product_tree} checkpoint={checkpoint_sha}"
        )

    if checkpoint_sha != publisher.EXPECTED_PARENT:
        raise SystemExit(
            f"5C2 checkpoint moved before final publication: {checkpoint_sha}"
        )

    publisher.rebuild_patch = _exact_rebuild_patch
    publisher.main()


if __name__ == "__main__":
    main()
