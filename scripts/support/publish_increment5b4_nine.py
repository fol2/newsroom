"""Publish the exact reviewed nine-file Increment 5B4 atom from immutable support chunks."""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

REPOSITORY = "fol2/newsroom"
SUPPORT_BRANCH = "support/run-increment-5b4-reviewed-hardening-v2-20260806"
PAYLOAD_COMMIT = "9546b1a7e22376110578a5140087b6a6e9d96622"
EXPECTED_BASE = "7976909e58a47749ac39fa212f5ecac325294ace"
PAYLOAD_SHA256 = "02049f9d5b446a77344bc52f167ab98bc2c42170b3d2356fc299308f90e09a13"
CORRUPTED_OFFSET = 14_936
CORRUPTED_VALUE = "s"
CORRECT_VALUE = "k"
CANONICAL_BRANCH = "agent/increment-5b4-admitted-graph"
STAGING_BRANCH = "staging/increment-5b4-admitted-graph-final-20260807"
CHECKPOINT_BRANCH = "checkpoint/increment-5b4-admitted-graph-final-20260807"

PATHS = (
    "docs/operations/increment-5b4-admitted-graph-retriever.md",
    "docs/traceability/increment-5b4-admitted-graph-retriever.md",
    "newsroom/authority/neo4j_admitted_graph_reader.py",
    "newsroom/increment5/admitted_graph_retriever.py",
    "newsroom/tests/test_increment5b4_admitted_graph_retriever.py",
    "newsroom/tests/test_increment5b4_neo4j_authority_port.py",
    "newsroom/tests/test_increment5b4_neo4j_service.py",
    "newsroom/tests/test_integrated_c1_sdlc_contract.py",
    "newsroom/tests/test_sdlc_classifier.py",
)
FOCUSED = (
    "newsroom/tests/test_increment5b4_admitted_graph_retriever.py",
    "newsroom/tests/test_increment5b4_neo4j_authority_port.py",
    "newsroom/tests/test_increment5b4_neo4j_service.py",
    "newsroom/tests/test_integrated_c1_sdlc_contract.py",
    "newsroom/tests/test_sdlc_classifier.py",
)
FOCUSED_LOG = Path("/tmp/increment5b4-nine-focused.log")
FULL_LOG = Path("/tmp/increment5b4-nine-full.log")
RECEIPT = Path("/tmp/increment5b4-nine-receipt.txt")
ARCHIVE = Path("/tmp/increment5b4-nine-files.tgz")
WORKTREE = Path("/tmp/increment5b4-nine-worktree.tgz")


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
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout or ""
    log.write_text(output, encoding="utf-8")
    print(output, end="")
    if completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, args, output=output)
    lines = output.splitlines()
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


def reconstruct_payload(payload_repo: Path) -> None:
    encoded_parts: list[str] = []
    for part in range(6):
        content = run(
            "git",
            "show",
            f"{PAYLOAD_COMMIT}:scripts/support/increment5b4-nine/part-{part:02d}.b64",
            cwd=payload_repo,
            capture=True,
        )
        encoded_parts.append("".join(content.split()))
    encoded = "".join(encoded_parts)
    if len(encoded) != 47_832:
        raise SystemExit(f"payload base64 length drifted: {len(encoded)}")
    if encoded[CORRUPTED_OFFSET] != CORRUPTED_VALUE:
        raise SystemExit(
            "known support-carrier byte drifted: "
            f"offset={CORRUPTED_OFFSET} actual={encoded[CORRUPTED_OFFSET]!r}"
        )
    encoded = (
        encoded[:CORRUPTED_OFFSET]
        + CORRECT_VALUE
        + encoded[CORRUPTED_OFFSET + 1 :]
    )
    raw = base64.b64decode(encoded, validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PAYLOAD_SHA256:
        raise SystemExit(f"payload digest mismatch: expected={PAYLOAD_SHA256} actual={digest}")
    ARCHIVE.write_bytes(raw)


def extract_product(product: Path) -> None:
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        members = archive.getmembers()
        names = tuple(member.name.removeprefix("./") for member in members if member.isfile())
        if tuple(sorted(names)) != tuple(sorted(PATHS)):
            raise SystemExit(f"payload inventory mismatch: {names}")
        root = product.resolve()
        for member in members:
            destination = (product / member.name).resolve()
            if destination != root and root not in destination.parents:
                raise SystemExit(f"unsafe payload path: {member.name}")
        archive.extractall(product, filter="data")


def main() -> None:
    configure_auth()
    payload_repo = Path("payload")
    product = Path("product")
    for path in (payload_repo, product):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir()

    run("git", "init", "-q", cwd=payload_repo)
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=payload_repo)
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=30",
        "origin",
        f"refs/heads/{SUPPORT_BRANCH}:refs/heads/publisher-base",
        cwd=payload_repo,
    )
    run("git", "cat-file", "-e", f"{PAYLOAD_COMMIT}^{{commit}}", cwd=payload_repo)
    reconstruct_payload(payload_repo)

    run("git", "init", "-q", cwd=product)
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=product)
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "origin",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=product,
    )
    run("git", "checkout", "-q", "--detach", EXPECTED_BASE, cwd=product)
    remote_main = run("git", "ls-remote", "origin", "refs/heads/main", cwd=product, capture=True).split()[0]
    if remote_main != EXPECTED_BASE:
        raise SystemExit(f"main moved: expected={EXPECTED_BASE} actual={remote_main}")
    extract_product(product)

    run("uv", "sync", "--frozen", cwd=product)
    run(
        "python",
        "-m",
        "compileall",
        "-q",
        *(path for path in PATHS if path.endswith(".py")),
        cwd=product,
    )
    focused_summary = run_logged(("uv", "run", "pytest", "-q", *FOCUSED), cwd=product, log=FOCUSED_LOG)
    full_summary = run_logged(("uv", "run", "pytest", "-q"), cwd=product, log=FULL_LOG)

    run("git", "config", "user.name", "James To", cwd=product)
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=product)
    run("git", "add", "--", *PATHS, cwd=product)
    run("git", "diff", "--cached", "--check", cwd=product)
    run("git", "commit", "-q", "-m", "Increment 5B4: bounded admitted graph retriever", cwd=product)

    count = run("git", "rev-list", "--count", f"{EXPECTED_BASE}..HEAD", cwd=product, capture=True)
    actual_paths = tuple(
        line
        for line in run("git", "diff", "--name-only", f"{EXPECTED_BASE}..HEAD", cwd=product, capture=True).splitlines()
        if line
    )
    if count != "1" or tuple(sorted(actual_paths)) != tuple(sorted(PATHS)):
        raise SystemExit(f"invalid product atom: count={count} paths={actual_paths}")

    head = run("git", "rev-parse", "HEAD", cwd=product, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=product, capture=True)
    parent = run("git", "rev-parse", "HEAD^", cwd=product, capture=True)
    RECEIPT.write_text(
        "\n".join(
            (
                "schema=newsroom.increment5b4.nine-file-materialization.v2",
                f"payload_sha256={PAYLOAD_SHA256}",
                f"payload_commit={PAYLOAD_COMMIT}",
                f"head={head}",
                f"tree={tree}",
                f"parent={parent}",
                f"focused={focused_summary}",
                f"full={full_summary}",
                "files=9",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        (
            "tar",
            "--exclude=.git",
            "--exclude=.venv",
            "--exclude=.pytest_cache",
            "--exclude=**/__pycache__",
            "-czf",
            str(WORKTREE),
            ".",
        ),
        cwd=product,
        check=True,
    )
    for branch in (CANONICAL_BRANCH, STAGING_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "--force", "origin", f"HEAD:refs/heads/{branch}", cwd=product)
    print(RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
