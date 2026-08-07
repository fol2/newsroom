"""Reassemble, verify, and publish the exact Increment 5D1 hybrid composer."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_BASE = "67ec62e4fca8b16d87af401674ffaef445feb7c4"
EXPECTED_BASE_TREE = "26db84a690ff6547aac2dc7b8ce2616e8015d286"
PRODUCT_BRANCH = "agent/increment-5d1-hybrid-composer"
CHECKPOINT_BRANCH = "checkpoint/increment-5d1-hybrid-composer-20260807"
PART_ROOT = Path("scripts/support/patches")
PARTS: tuple[tuple[str, int, str], ...] = (
    ("increment5d1_hybrid_composer.patch.gz.b64.part00", 7500, "b36a65e59b01f6ea2eb223a9e48ef6c4825cb76db887250ae1004a0cbe42c104"),
    ("increment5d1_hybrid_composer.patch.gz.b64.part01", 7500, "4892eb594ec354d6ce46e9b1852118a6604dd9d3f028a3b0900aa2e6dce898ed"),
    ("increment5d1_hybrid_composer.patch.gz.b64.part02", 7500, "fa9421d2d868e3240481cc9e05becea3ff55d03d87a1f726d2d8ab9e81b27d2b"),
    ("increment5d1_hybrid_composer.patch.gz.b64.part03", 7500, "a436c1cc06b2d66d045ee3ea0c442332eb1d12d97a04cc6ea76e05a3a2afbf97"),
    ("increment5d1_hybrid_composer.patch.gz.b64.part04", 4480, "ed4245d91872a5a07880df22e285737df57e906bc0666e67ee0d43390fd66ad6"),
)
EXPECTED_GZIP_SHA256 = "1989329807d2890c62fc4cdbc05f7f4841bb746bdaf7582b904ac1571fe51515"
EXPECTED_PATCH_SHA256 = "a62e920de8e19afa49016167b35bc055fb4bfb8bcb598e7e75b595c9d76c222b"
PRODUCT_FILES = (
    "docs/operations/increment-5d1-hybrid-composer.md",
    "docs/traceability/increment-5d1-hybrid-composer.md",
    "newsroom/increment5/hybrid_composer.py",
    "newsroom/tests/test_increment5d1_hybrid_composer.py",
)
PATCH_PATH = Path("/tmp/increment5d1-hybrid-composer.patch")
FOCUSED_LOG = Path("/tmp/increment5d1-hybrid-composer-focused.log")
FULL_LOG = Path("/tmp/increment5d1-hybrid-composer-full.log")
CLUSTERING_LOG = Path("/tmp/increment5d1-hybrid-composer-clustering.log")
RECEIPT = Path("/tmp/increment5d1-hybrid-composer-receipt.json")


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
    expected_names = tuple(name for name, _, _ in PARTS)
    actual_names = tuple(
        path.name
        for path in sorted(PART_ROOT.glob("increment5d1_hybrid_composer.patch.gz.b64.part*"))
    )
    if actual_names != expected_names:
        raise SystemExit(f"publisher payload inventory drifted: {actual_names}")

    encoded_parts: list[str] = []
    for name, expected_size, expected_sha256 in PARTS:
        raw = (PART_ROOT / name).read_bytes()
        if len(raw) != expected_size:
            raise SystemExit(f"payload part size drifted: {name}: {len(raw)}")
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != expected_sha256:
            raise SystemExit(f"payload part digest drifted: {name}: {actual_sha256}")
        encoded_parts.append("".join(raw.decode("ascii").split()))

    try:
        compressed = base64.b64decode("".join(encoded_parts), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SystemExit("publisher payload is not valid base64") from exc
    if hashlib.sha256(compressed).hexdigest() != EXPECTED_GZIP_SHA256:
        raise SystemExit("compressed publisher payload digest mismatch")
    try:
        patch = gzip.decompress(compressed)
    except OSError as exc:
        raise SystemExit("publisher payload is not valid gzip") from exc
    if hashlib.sha256(patch).hexdigest() != EXPECTED_PATCH_SHA256:
        raise SystemExit("decoded product patch digest mismatch")
    PATCH_PATH.write_bytes(patch)


def checkout() -> Path:
    root = Path("product")
    run("git", "init", "-q", root.as_posix())
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=root)
    for branch in ("main", PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        if remote_sha(root, branch) != EXPECTED_BASE:
            raise SystemExit(f"{branch} moved before 5D1 publication")
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=2",
        "origin",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=root,
    )
    if run("git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True) != EXPECTED_BASE:
        raise SystemExit("fetched main identity drifted")
    if run("git", "rev-parse", "refs/remotes/origin/main^{tree}", cwd=root, capture=True) != EXPECTED_BASE_TREE:
        raise SystemExit("fetched main tree drifted")
    run("git", "checkout", "-q", "--detach", EXPECTED_BASE, cwd=root)
    return root


def apply_patch(root: Path) -> tuple[str, str]:
    run("git", "config", "user.name", "James To", cwd=root)
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=root)
    run("git", "am", "--no-gpg-sign", PATCH_PATH.as_posix(), cwd=root)
    if run("git", "rev-parse", "HEAD^", cwd=root, capture=True) != EXPECTED_BASE:
        raise SystemExit("5D1 candidate parent identity drifted")
    changed = tuple(
        line
        for line in run(
            "git", "diff", "--name-only", "HEAD^", "HEAD", cwd=root, capture=True
        ).splitlines()
        if line
    )
    if tuple(sorted(changed)) != tuple(sorted(PRODUCT_FILES)):
        raise SystemExit(f"5D1 product inventory drifted: {changed}")
    run("git", "show", "--check", "--oneline", "HEAD", cwd=root)
    return (
        run("git", "rev-parse", "HEAD", cwd=root, capture=True),
        run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True),
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
        "newsroom/increment5/hybrid_composer.py",
        "newsroom/tests/test_increment5d1_hybrid_composer.py",
        cwd=root,
    )
    focused = run_logged(
        (
            "uv", "run", "pytest", "-q",
            "newsroom/tests/test_increment5d1_hybrid_composer.py",
            "newsroom/tests/test_increment5c2_named_tool_dispatch.py",
            "newsroom/tests/test_increment5c2_named_tool_branch_adapters.py",
            "newsroom/tests/test_increment5c2_named_tool_authority_execution.py",
            "newsroom/tests/test_increment5c2a_named_tool_branch_execution.py",
            "newsroom/tests/test_increment5c2_traceability.py",
        ),
        cwd=root,
        log=FOCUSED_LOG,
    )
    full = run_logged(("uv", "run", "pytest", "-q"), cwd=root, log=FULL_LOG)
    clustering = run_logged(
        (
            "uv", "run", "python", "scripts/eval_clustering_metrics.py",
            "--dataset", "newsroom/evals/clustering_eval_dataset_v1.jsonl",
            "--baseline", "newsroom/evals/clustering_eval_metrics_baseline_v1.json",
            "--fail-on-regression",
        ),
        cwd=root,
        log=CLUSTERING_LOG,
    )
    if run("git", "status", "--porcelain", cwd=root, capture=True):
        raise SystemExit("5D1 verification mutated the product tree")
    return {"focused": focused, "full": full, "clustering": clustering}


def publish(root: Path, head: str, tree: str, evidence: dict[str, str]) -> None:
    for branch in ("main", PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        if remote_sha(root, branch) != EXPECTED_BASE:
            raise SystemExit(f"{branch} moved during 5D1 verification")
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    receipt = {
        "schema_version": "newsroom.increment5d1.publisher.v1",
        "base": EXPECTED_BASE,
        "base_tree": EXPECTED_BASE_TREE,
        "head": head,
        "tree": tree,
        "patch_sha256": f"sha256:{EXPECTED_PATCH_SHA256}",
        "compressed_patch_sha256": f"sha256:{EXPECTED_GZIP_SHA256}",
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
