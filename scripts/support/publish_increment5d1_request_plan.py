"""Publish the review-driven Increment 5D1 request-plan coherence correction."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_PARENT = "315d691ffeffba28ce67abfb02e18f2ed7fc71ed"
EXPECTED_PARENT_TREE = "ecc67815f89de71b1008c6971495a1938ae65b5f"
EXPECTED_MAIN = "67ec62e4fca8b16d87af401674ffaef445feb7c4"
PRODUCT_BRANCH = "agent/increment-5d1-hybrid-composer"
CHECKPOINT_BRANCH = "checkpoint/increment-5d1-hybrid-composer-20260807"
PART_ROOT = Path("scripts/support/patches")
PARTS: tuple[tuple[str, int, str], ...] = (
    (
        "increment5d1_request_plan.patch.gz.b64.part00",
        7500,
        "463902e8ba89a61eb0684a60bd5014ba3a87b5ddc523922ea1c263708c85307a",
    ),
    (
        "increment5d1_request_plan.patch.gz.b64.part01",
        7088,
        "208080a188d4071a56673f891661b3797cea19c740b4104690d15a4a4cf8038b",
    ),
)
EXPECTED_GZIP_SHA256 = "85329bfc0ff8a4c18751ace35d930c1276e620295e0d9bc4004303795daf41fe"
EXPECTED_PATCH_SHA256 = "318d35f7febe8154495d54e25005f684fdcb4928f8b46fdc02b7b1ddb072bbfe"
PRODUCT_FILES = (
    "docs/operations/increment-5d1-hybrid-composer.md",
    "docs/traceability/increment-5d1-hybrid-composer.md",
    "newsroom/increment5/hybrid_composer.py",
    "newsroom/tests/test_increment5d1_hybrid_composer.py",
)
PATCH_PATH = Path("/tmp/increment5d1-request-plan.patch")
FOCUSED_LOG = Path("/tmp/increment5d1-request-plan-focused.log")
FULL_LOG = Path("/tmp/increment5d1-request-plan-full.log")
CLUSTERING_LOG = Path("/tmp/increment5d1-request-plan-clustering.log")
RECEIPT = Path("/tmp/increment5d1-request-plan-receipt.json")


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
        for path in sorted(PART_ROOT.glob("increment5d1_request_plan.patch.gz.b64.part*"))
    )
    if actual_names != expected_names:
        raise SystemExit(f"request-plan payload inventory drifted: {actual_names}")

    encoded_parts: list[str] = []
    for name, expected_size, expected_digest in PARTS:
        raw = (PART_ROOT / name).read_bytes()
        if len(raw) != expected_size:
            raise SystemExit(f"request-plan part size drifted: {name}: {len(raw)}")
        actual_digest = hashlib.sha256(raw).hexdigest()
        if actual_digest != expected_digest:
            raise SystemExit(
                f"request-plan part digest drifted: {name}: {actual_digest}"
            )
        encoded_parts.append("".join(raw.decode("ascii").split()))

    try:
        compressed = base64.b64decode("".join(encoded_parts), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SystemExit("request-plan payload is not valid base64") from exc
    if hashlib.sha256(compressed).hexdigest() != EXPECTED_GZIP_SHA256:
        raise SystemExit("request-plan compressed digest mismatch")
    try:
        patch = gzip.decompress(compressed)
    except OSError as exc:
        raise SystemExit("request-plan payload is not valid gzip") from exc
    if hashlib.sha256(patch).hexdigest() != EXPECTED_PATCH_SHA256:
        raise SystemExit("request-plan decoded patch digest mismatch")
    PATCH_PATH.write_bytes(patch)


def checkout() -> Path:
    root = Path("product")
    run("git", "init", "-q", root.as_posix())
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=root)
    if remote_sha(root, PRODUCT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("canonical 5D1 parent moved before correction publication")
    if remote_sha(root, CHECKPOINT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("5D1 checkpoint moved before correction publication")
    if remote_sha(root, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved before 5D1 correction publication")
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=3",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=root,
    )
    if run("git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True) != EXPECTED_PARENT:
        raise SystemExit("fetched 5D1 parent identity drifted")
    if run("git", "rev-parse", "refs/remotes/origin/product^{tree}", cwd=root, capture=True) != EXPECTED_PARENT_TREE:
        raise SystemExit("fetched 5D1 parent tree drifted")
    if run("git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True) != EXPECTED_MAIN:
        raise SystemExit("fetched main identity drifted")
    run("git", "checkout", "-q", "--detach", EXPECTED_PARENT, cwd=root)
    return root


def apply_patch(root: Path) -> tuple[str, str]:
    run("git", "config", "user.name", "James To", cwd=root)
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=root)
    run("git", "am", "--no-gpg-sign", PATCH_PATH.as_posix(), cwd=root)
    if run("git", "rev-parse", "HEAD^", cwd=root, capture=True) != EXPECTED_PARENT:
        raise SystemExit("request-plan correction parent identity drifted")
    changed = tuple(
        line
        for line in run(
            "git", "diff", "--name-only", "HEAD^", "HEAD", cwd=root, capture=True
        ).splitlines()
        if line
    )
    if tuple(sorted(changed)) != tuple(sorted(PRODUCT_FILES)):
        raise SystemExit(f"request-plan correction inventory drifted: {changed}")
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
        raise SystemExit("request-plan verification mutated the product tree")
    return {"focused": focused, "full": full, "clustering": clustering}


def publish(root: Path, head: str, tree: str, evidence: dict[str, str]) -> None:
    if remote_sha(root, PRODUCT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("canonical 5D1 head moved during correction verification")
    if remote_sha(root, CHECKPOINT_BRANCH) != EXPECTED_PARENT:
        raise SystemExit("5D1 checkpoint moved during correction verification")
    if remote_sha(root, "main") != EXPECTED_MAIN:
        raise SystemExit("main moved during 5D1 correction verification")
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    receipt = {
        "schema_version": "newsroom.increment5d1.request-plan-correction.v1",
        "parent": EXPECTED_PARENT,
        "parent_tree": EXPECTED_PARENT_TREE,
        "main": EXPECTED_MAIN,
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
