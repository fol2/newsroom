"""Recover, verify, and publish the rebuilt Increment 5C2 authority atom."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

REPOSITORY = "fol2/newsroom"
EXPECTED_PARENT = "172548babaee7f7ea1a28c38878b6ac90e949077"
EXPECTED_MAIN = "72e0ade55ec05ff6de907319cb9baeeefe30d1ca"
PRODUCT_BRANCH = "agent/increment-5c2-six-named-tools"
CHECKPOINT_BRANCH = "checkpoint/increment-5c2-six-named-tools-20260807"
TRANSFER_ROOT = Path("scripts/support/data/increment5c2_authority_patch_v2")
PRODUCT_FILES = (
    "newsroom/increment5/named_tool_authority_execution.py",
    "newsroom/increment5/named_tool_authority_adapters.py",
    "newsroom/tests/test_increment5c2_named_tool_authority_execution.py",
)
FOCUSED_LOG = Path("/tmp/increment5c2-authority-focused.log")
FULL_LOG = Path("/tmp/increment5c2-authority-full.log")
RECEIPT = Path("/tmp/increment5c2-authority-publication.json")
PATCH_PATH = Path("/tmp/increment5c2-authority.patch")


def run(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def run_logged(args: tuple[str, ...], *, cwd: Path, path: Path) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode:
        print(completed.stdout)
        raise subprocess.CalledProcessError(completed.returncode, args)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else "PASS"


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


def recover_patch() -> tuple[bytes, dict[str, object]]:
    parts = sorted(TRANSFER_ROOT.glob("part*.b64"))
    if len(parts) < 2:
        raise SystemExit(f"incomplete v2 transfer: found {len(parts)} part(s)")
    texts: list[str] = []
    inventory: list[dict[str, object]] = []
    for part in parts:
        raw = part.read_bytes()
        text = re.sub(rb"\s+", b"", raw).decode("ascii")
        if not text or re.fullmatch(r"[A-Za-z0-9+/=]+", text) is None:
            raise SystemExit(f"invalid Base64 text in {part}")
        texts.append(text)
        inventory.append(
            {
                "path": part.as_posix(),
                "characters": len(text),
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
    stream = "".join(texts)
    if len(stream) % 4:
        raise SystemExit(
            f"incomplete v2 Base64 stream: {len(stream)} characters (mod 4={len(stream) % 4})"
        )
    try:
        encoded = base64.b64decode(stream, validate=True)
    except ValueError as exc:
        raise SystemExit("v2 Base64 stream is invalid") from exc
    try:
        patch = gzip.decompress(encoded) if encoded.startswith(b"\x1f\x8b") else encoded
    except (OSError, EOFError) as exc:
        raise SystemExit("v2 compressed patch is incomplete or corrupt") from exc
    if not patch.startswith(b"diff --git "):
        raise SystemExit("recovered payload is not a Git patch")
    if patch.count(b"diff --git ") != len(PRODUCT_FILES):
        raise SystemExit("recovered patch does not contain exactly three file diffs")
    PATCH_PATH.write_bytes(patch)
    return patch, {
        "parts": inventory,
        "stream_characters": len(stream),
        "encoded_sha256": hashlib.sha256(encoded).hexdigest(),
        "patch_bytes": len(patch),
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
    }


def clone_product() -> Path:
    root = Path("product")
    run("git", "init", "-q", root.as_posix())
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=root)
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=8",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        f"refs/heads/{CHECKPOINT_BRANCH}:refs/remotes/origin/checkpoint",
        cwd=root,
    )
    product = run("git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True)
    main = run("git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True)
    checkpoint = run(
        "git", "rev-parse", "refs/remotes/origin/checkpoint", cwd=root, capture=True
    )
    if product != EXPECTED_PARENT:
        raise SystemExit(f"canonical 5C2 head moved: {product}")
    if checkpoint != EXPECTED_PARENT:
        raise SystemExit(f"5C2 checkpoint head differs: {checkpoint}")
    if main != EXPECTED_MAIN:
        raise SystemExit(f"main moved during 5C2 authority publication: {main}")
    run("git", "checkout", "-q", "--detach", EXPECTED_PARENT, cwd=root)
    return root


def verify_and_publish(root: Path, transfer: dict[str, object]) -> None:
    run("git", "apply", "--index", "--whitespace=error-all", PATCH_PATH.as_posix(), cwd=root)
    actual = tuple(
        line
        for line in run(
            "git", "diff", "--cached", "--name-only", cwd=root, capture=True
        ).splitlines()
        if line
    )
    if tuple(sorted(actual)) != tuple(sorted(PRODUCT_FILES)):
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
    head = run("git", "rev-parse", "HEAD", cwd=root, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)

    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    tests = tuple(
        path.as_posix()
        for path in sorted((root / "newsroom/tests").glob("test_increment5c*.py"))
    )
    relative_tests = tuple(str(Path(path).relative_to(root)) for path in tests)
    focused = run_logged(
        ("uv", "run", "pytest", "-q", *relative_tests),
        cwd=root,
        path=FOCUSED_LOG,
    )
    full = run_logged(
        ("uv", "run", "pytest", "-q"),
        cwd=root,
        path=FULL_LOG,
    )
    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=root, capture=True):
        raise SystemExit("verified authority atom mutated tracked bytes")

    remote_product = run(
        "git", "ls-remote", "origin", f"refs/heads/{PRODUCT_BRANCH}", cwd=root, capture=True
    ).split()[0]
    remote_checkpoint = run(
        "git", "ls-remote", "origin", f"refs/heads/{CHECKPOINT_BRANCH}", cwd=root, capture=True
    ).split()[0]
    remote_main = run(
        "git", "ls-remote", "origin", "refs/heads/main", cwd=root, capture=True
    ).split()[0]
    if (remote_product, remote_checkpoint, remote_main) != (
        EXPECTED_PARENT,
        EXPECTED_PARENT,
        EXPECTED_MAIN,
    ):
        raise SystemExit("remote refs moved before authority atom publication")

    run("git", "push", "origin", f"HEAD:refs/heads/{PRODUCT_BRANCH}", cwd=root)
    run("git", "push", "origin", f"HEAD:refs/heads/{CHECKPOINT_BRANCH}", cwd=root)
    receipt = {
        "schema_version": "newsroom.increment5c2.authority-publication.v1",
        "parent": EXPECTED_PARENT,
        "head": head,
        "tree": tree,
        "files": list(PRODUCT_FILES),
        "focused": focused,
        "full": full,
        "transfer": transfer,
        "complete_5c2": False,
        "remaining": [
            "closed six-tool dispatcher and common integrated receipt",
            "operating and traceability records",
            "Tier-S service evidence and final review",
        ],
    }
    RECEIPT.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


def main() -> None:
    configure_auth()
    patch, transfer = recover_patch()
    del patch
    root = clone_product()
    verify_and_publish(root, transfer)


if __name__ == "__main__":
    main()
