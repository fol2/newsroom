"""Verify and publish the exact reviewed Increment 5B4 nine-file atom."""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

REPO = "fol2/newsroom"
SUPPORT_BRANCH = "support/run-increment-5b4-reviewed-hardening-v2-20260806"
PAYLOAD_COMMIT = "9546b1a7e22376110578a5140087b6a6e9d96622"
BASE = "7976909e58a47749ac39fa212f5ecac325294ace"
PAYLOAD_SHA = "02049f9d5b446a77344bc52f167ab98bc2c42170b3d2356fc299308f90e09a13"
CORRUPTED_OFFSET = 14_936
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
FOCUSED = tuple(path for path in PATHS if path.startswith("newsroom/tests/"))
BRANCHES = (
    "agent/increment-5b4-admitted-graph",
    "staging/increment-5b4-admitted-graph-final-20260807",
    "checkpoint/increment-5b4-admitted-graph-final-20260807",
)
ARCHIVE = Path("/tmp/increment5b4-nine-files.tgz")
WORKTREE = Path("/tmp/increment5b4-nine-worktree.tgz")
FOCUSED_LOG = Path("/tmp/increment5b4-nine-focused.log")
FULL_LOG = Path("/tmp/increment5b4-nine-full.log")
RECEIPT = Path("/tmp/increment5b4-nine-receipt.txt")


def command(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        check=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def tested(args: tuple[str, ...], *, cwd: Path, log: Path) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout or ""
    log.write_text(output, encoding="utf-8")
    print(output, end="")
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, args, output=output)
    lines = output.splitlines()
    return lines[-1] if lines else ""


def authenticate() -> None:
    token = os.environ["GH_TOKEN"]
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    command(
        "git",
        "config",
        "--global",
        "http.https://github.com/.extraheader",
        f"AUTHORIZATION: basic {encoded}",
    )


def materialize_payload(payload_repo: Path) -> None:
    encoded = "".join(
        "".join(
            command(
                "git",
                "show",
                f"{PAYLOAD_COMMIT}:scripts/support/increment5b4-nine/part-{part:02d}.b64",
                cwd=payload_repo,
                capture=True,
            ).split()
        )
        for part in range(6)
    )
    if len(encoded) != 47_832 or encoded[CORRUPTED_OFFSET] != "s":
        raise SystemExit("known support payload shape drifted")
    encoded = encoded[:CORRUPTED_OFFSET] + "k" + encoded[CORRUPTED_OFFSET + 1 :]
    raw = base64.b64decode(encoded, validate=True)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != PAYLOAD_SHA:
        raise SystemExit(f"payload digest mismatch: expected={PAYLOAD_SHA} actual={actual}")
    ARCHIVE.write_bytes(raw)


def extract_exact(product: Path) -> None:
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


def normalize_reviewed_eof(product: Path) -> None:
    for relative in (
        "newsroom/tests/test_increment5b4_admitted_graph_retriever.py",
        "newsroom/tests/test_increment5b4_neo4j_authority_port.py",
    ):
        path = product / relative
        text = path.read_text(encoding="utf-8")
        if not text.endswith("\n\n") or text.endswith("\n\n\n"):
            raise SystemExit(f"reviewed EOF boundary drifted: {relative}")
        path.write_text(text[:-1], encoding="utf-8")


def prepare_repo(path: Path, refspec: str) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir()
    command("git", "init", "-q", cwd=path)
    command("git", "remote", "add", "origin", f"https://github.com/{REPO}.git", cwd=path)
    command("git", "fetch", "--no-tags", "--depth=30", "origin", refspec, cwd=path)


def main() -> None:
    authenticate()
    payload = Path("payload")
    product = Path("product")
    prepare_repo(payload, f"refs/heads/{SUPPORT_BRANCH}:refs/heads/publisher-base")
    command("git", "cat-file", "-e", f"{PAYLOAD_COMMIT}^{{commit}}", cwd=payload)
    materialize_payload(payload)

    prepare_repo(product, "refs/heads/main:refs/remotes/origin/main")
    command("git", "checkout", "-q", "--detach", BASE, cwd=product)
    remote_main = command("git", "ls-remote", "origin", "refs/heads/main", cwd=product, capture=True).split()[0]
    if remote_main != BASE:
        raise SystemExit(f"main moved: expected={BASE} actual={remote_main}")
    extract_exact(product)
    normalize_reviewed_eof(product)

    # The complete suite contains code/tree binding tests. Commit the exact atom
    # locally before testing, but publish nothing until every gate below passes.
    command("git", "config", "user.name", "James To", cwd=product)
    command("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=product)
    command("git", "add", "--", *PATHS, cwd=product)
    command("git", "diff", "--cached", "--check", cwd=product)
    command("git", "commit", "-q", "-m", "Increment 5B4: bounded admitted graph retriever", cwd=product)

    count = command("git", "rev-list", "--count", f"{BASE}..HEAD", cwd=product, capture=True)
    actual_paths = tuple(
        line
        for line in command("git", "diff", "--name-only", f"{BASE}..HEAD", cwd=product, capture=True).splitlines()
        if line
    )
    if count != "1" or tuple(sorted(actual_paths)) != tuple(sorted(PATHS)):
        raise SystemExit(f"invalid product atom: count={count} paths={actual_paths}")
    if command("git", "diff", "--name-only", cwd=product, capture=True):
        raise SystemExit("tracked product tree is not clean before verification")

    command("uv", "sync", "--frozen", cwd=product)
    command(
        "python",
        "-m",
        "compileall",
        "-q",
        *(path for path in PATHS if path.endswith(".py")),
        cwd=product,
    )
    focused = tested(("uv", "run", "pytest", "-q", *FOCUSED), cwd=product, log=FOCUSED_LOG)
    full = tested(("uv", "run", "pytest", "-q"), cwd=product, log=FULL_LOG)
    if command("git", "diff", "--name-only", cwd=product, capture=True):
        raise SystemExit("verification mutated tracked product bytes")

    head = command("git", "rev-parse", "HEAD", cwd=product, capture=True)
    tree = command("git", "rev-parse", "HEAD^{tree}", cwd=product, capture=True)
    parent = command("git", "rev-parse", "HEAD^", cwd=product, capture=True)
    RECEIPT.write_text(
        "\n".join(
            (
                "schema=newsroom.increment5b4.nine-file-materialization.v3",
                f"payload_sha256={PAYLOAD_SHA}",
                f"payload_commit={PAYLOAD_COMMIT}",
                f"head={head}",
                f"tree={tree}",
                f"parent={parent}",
                f"focused={focused}",
                f"full={full}",
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
    for branch in BRANCHES:
        command("git", "push", "--force", "origin", f"HEAD:refs/heads/{branch}", cwd=product)
    print(RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
