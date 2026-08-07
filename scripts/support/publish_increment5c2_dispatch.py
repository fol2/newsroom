"""Verify and publish the exact Increment 5C2 six-tool dispatcher atom."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Iterable

REPOSITORY = "fol2/newsroom"
SUPPORT_ROOT = Path(__file__).resolve().parent
TRANSFER_ROOT = SUPPORT_ROOT / "data" / "increment5c2_dispatch_patch"
PRODUCT_ROOT = Path("product")
FOCUSED_LOG = Path("/tmp/increment5c2-dispatch-focused.log")
FULL_LOG = Path("/tmp/increment5c2-dispatch-full.log")
EVAL_LOG = Path("/tmp/increment5c2-dispatch-clustering.log")
RECEIPT = Path("/tmp/increment5c2-dispatch-receipt.json")


def run(
    *args: str,
    cwd: Path | None = None,
    capture: bool = False,
    stdout_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    stdout = subprocess.PIPE if capture else None
    stream = None
    if stdout_path is not None:
        stream = stdout_path.open("w", encoding="utf-8")
        stdout = stream
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            check=True,
            text=True,
            stdout=stdout,
            stderr=subprocess.STDOUT if stdout_path is not None else None,
            env=env,
        )
    finally:
        if stream is not None:
            stream.close()
    return completed.stdout.strip() if capture else ""


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def load_transfer() -> tuple[dict[str, object], bytes]:
    manifest = json.loads((TRANSFER_ROOT / "manifest.json").read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "canonical_branch",
        "checkpoint_branch",
        "expected_parent",
        "expected_parent_tree",
        "expected_main",
        "commit_timestamp",
        "patch_bytes",
        "patch_sha256",
        "gzip_bytes",
        "gzip_sha256",
        "base64_chars",
        "base64_sha256",
        "parts",
        "product_files",
        "expected_blob_shas",
    }
    if set(manifest) != required:
        raise SystemExit("dispatcher transfer manifest keys drifted")
    if manifest["schema_version"] != "newsroom.increment5c2.dispatch-transfer.v1":
        raise SystemExit("dispatcher transfer schema is not accepted")
    raw_parts = manifest["parts"]
    if not isinstance(raw_parts, list) or not raw_parts:
        raise SystemExit("dispatcher transfer parts are malformed")
    encoded_parts: list[str] = []
    expected_names: list[str] = []
    for item in raw_parts:
        if not isinstance(item, dict) or set(item) != {"name", "chars"}:
            raise SystemExit("dispatcher transfer part entry is malformed")
        name = item["name"]
        chars = item["chars"]
        if not isinstance(name, str) or isinstance(chars, bool) or not isinstance(chars, int):
            raise SystemExit("dispatcher transfer part metadata has wrong types")
        text = "".join((TRANSFER_ROOT / name).read_text(encoding="ascii").split())
        if len(text) != chars:
            raise SystemExit(f"dispatcher transfer part length mismatch: {name}")
        encoded_parts.append(text)
        expected_names.append(name)
    if expected_names != sorted(expected_names):
        raise SystemExit("dispatcher transfer part names are not sorted")
    encoded = "".join(encoded_parts)
    encoded_bytes = encoded.encode("ascii")
    if len(encoded) != manifest["base64_chars"]:
        raise SystemExit("dispatcher Base64 length mismatch")
    if sha256(encoded_bytes) != manifest["base64_sha256"]:
        raise SystemExit("dispatcher Base64 digest mismatch")
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise SystemExit("dispatcher Base64 payload is invalid") from exc
    if len(compressed) != manifest["gzip_bytes"]:
        raise SystemExit("dispatcher gzip length mismatch")
    if sha256(compressed) != manifest["gzip_sha256"]:
        raise SystemExit("dispatcher gzip digest mismatch")
    try:
        patch = gzip.decompress(compressed)
    except gzip.BadGzipFile as exc:
        raise SystemExit("dispatcher gzip payload is invalid") from exc
    if len(patch) != manifest["patch_bytes"]:
        raise SystemExit("dispatcher patch length mismatch")
    if sha256(patch) != manifest["patch_sha256"]:
        raise SystemExit("dispatcher patch digest mismatch")
    return manifest, patch


def remote_sha(root: Path, ref: str) -> str:
    result = run("git", "ls-remote", "origin", ref, cwd=root, capture=True)
    if not result:
        raise SystemExit(f"required remote ref is absent: {ref}")
    rows = [line.split() for line in result.splitlines() if line.strip()]
    exact = [commit for commit, name in rows if name == ref]
    if len(exact) != 1:
        raise SystemExit(f"remote ref did not resolve exactly once: {ref}")
    return exact[0]


def exact_inventory(root: Path, parent: str, expected_files: Iterable[str]) -> None:
    actual = tuple(
        line
        for line in run(
            "git", "diff", "--name-only", parent, "HEAD", cwd=root, capture=True
        ).splitlines()
        if line
    )
    expected = tuple(sorted(expected_files))
    if tuple(sorted(actual)) != expected:
        raise SystemExit(f"dispatcher product inventory drifted: {actual}")


def verify_blobs(root: Path, expected: dict[str, object]) -> None:
    if not isinstance(expected, dict):
        raise SystemExit("dispatcher expected blob inventory is malformed")
    actual: dict[str, str] = {}
    for path, digest in sorted(expected.items()):
        if not isinstance(path, str) or not isinstance(digest, str):
            raise SystemExit("dispatcher expected blob identity has wrong types")
        actual[path] = run("git", "rev-parse", f"HEAD:{path}", cwd=root, capture=True)
    if actual != expected:
        raise SystemExit(f"dispatcher product blob identities drifted: {actual}")


def main() -> None:
    configure_auth()
    manifest, patch = load_transfer()
    parent = str(manifest["expected_parent"])
    main_sha = str(manifest["expected_main"])
    canonical_branch = str(manifest["canonical_branch"])
    checkpoint_branch = str(manifest["checkpoint_branch"])
    expected_files = tuple(str(item) for item in manifest["product_files"])
    expected_blobs = manifest["expected_blob_shas"]

    run("git", "init", "-q", PRODUCT_ROOT.as_posix())
    run(
        "git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git",
        cwd=PRODUCT_ROOT,
    )
    run(
        "git", "fetch", "--no-tags", "origin",
        f"refs/heads/{canonical_branch}:refs/newsroom/canonical",
        "refs/heads/main:refs/newsroom/main",
        f"refs/heads/{checkpoint_branch}:refs/newsroom/checkpoint",
        cwd=PRODUCT_ROOT,
    )
    canonical_sha = run("git", "rev-parse", "refs/newsroom/canonical", cwd=PRODUCT_ROOT, capture=True)
    fetched_main = run("git", "rev-parse", "refs/newsroom/main", cwd=PRODUCT_ROOT, capture=True)
    checkpoint_sha = run("git", "rev-parse", "refs/newsroom/checkpoint", cwd=PRODUCT_ROOT, capture=True)
    if canonical_sha != parent:
        raise SystemExit(f"canonical 5C2 head moved: {canonical_sha}")
    if fetched_main != main_sha:
        raise SystemExit(f"main moved before dispatcher verification: {fetched_main}")
    parent_tree = run("git", "rev-parse", f"{parent}^{{tree}}", cwd=PRODUCT_ROOT, capture=True)
    if parent_tree != manifest["expected_parent_tree"]:
        raise SystemExit("dispatcher parent tree identity mismatch")
    subprocess.run(("git", "merge-base", "--is-ancestor", checkpoint_sha, parent), cwd=PRODUCT_ROOT, check=True)

    run("git", "checkout", "-q", "--detach", parent, cwd=PRODUCT_ROOT)
    run("git", "config", "user.name", "James To", cwd=PRODUCT_ROOT)
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=PRODUCT_ROOT)
    subprocess.run(("git", "apply", "--index", "--whitespace=error-all", "-"), cwd=PRODUCT_ROOT, input=patch, check=True)
    run("git", "diff", "--cached", "--check", cwd=PRODUCT_ROOT)
    staged = tuple(
        line for line in run("git", "diff", "--cached", "--name-only", cwd=PRODUCT_ROOT, capture=True).splitlines() if line
    )
    if tuple(sorted(staged)) != tuple(sorted(expected_files)):
        raise SystemExit(f"dispatcher staged inventory drifted: {staged}")

    timestamp = str(manifest["commit_timestamp"])
    commit_env = dict(os.environ)
    commit_env["GIT_AUTHOR_DATE"] = timestamp
    commit_env["GIT_COMMITTER_DATE"] = timestamp
    run(
        "git", "commit", "-q", "-m", "Increment 5C2: add closed six-tool dispatcher",
        cwd=PRODUCT_ROOT, env=commit_env,
    )
    head = run("git", "rev-parse", "HEAD", cwd=PRODUCT_ROOT, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=PRODUCT_ROOT, capture=True)
    if run("git", "rev-parse", "HEAD^", cwd=PRODUCT_ROOT, capture=True) != parent:
        raise SystemExit("dispatcher commit parent drifted")
    exact_inventory(PRODUCT_ROOT, parent, expected_files)
    verify_blobs(PRODUCT_ROOT, expected_blobs)
    run("git", "diff", "--check", parent, "HEAD", cwd=PRODUCT_ROOT)
    run("python", "-m", "compileall", "-q", expected_files[0], cwd=PRODUCT_ROOT)
    run("uv", "lock", "--check", cwd=PRODUCT_ROOT)
    run("uv", "sync", "--dev", "--locked", cwd=PRODUCT_ROOT)

    focused_tests = (
        "newsroom/tests/test_increment5c1_named_tool_authorization.py",
        "newsroom/tests/test_increment5c1_named_tool_contracts.py",
        "newsroom/tests/test_increment5c2a_named_tool_branch_execution.py",
        "newsroom/tests/test_increment5c2_named_tool_branch_adapters.py",
        "newsroom/tests/test_increment5c2_named_tool_authority_execution.py",
        "newsroom/tests/test_increment5c2_named_tool_dispatch.py",
    )
    run("uv", "run", "pytest", "-q", *focused_tests, cwd=PRODUCT_ROOT, stdout_path=FOCUSED_LOG)
    run("uv", "run", "pytest", "-q", cwd=PRODUCT_ROOT, stdout_path=FULL_LOG)
    run(
        "uv", "run", "python", "scripts/eval_clustering_metrics.py",
        "--dataset", "newsroom/evals/clustering_eval_dataset_v1.jsonl",
        "--baseline", "newsroom/evals/clustering_eval_metrics_baseline_v1.json",
        "--fail-on-regression", cwd=PRODUCT_ROOT, stdout_path=EVAL_LOG,
    )

    if run("git", "status", "--porcelain", "--untracked-files=no", cwd=PRODUCT_ROOT, capture=True):
        raise SystemExit("dispatcher verification mutated tracked bytes")
    if remote_sha(PRODUCT_ROOT, f"refs/heads/{canonical_branch}") != parent:
        raise SystemExit("canonical 5C2 branch moved before dispatcher publication")
    if remote_sha(PRODUCT_ROOT, "refs/heads/main") != main_sha:
        raise SystemExit("main moved before dispatcher publication")
    current_checkpoint = remote_sha(PRODUCT_ROOT, f"refs/heads/{checkpoint_branch}")
    subprocess.run(("git", "merge-base", "--is-ancestor", current_checkpoint, head), cwd=PRODUCT_ROOT, check=True)
    run(
        "git", "push", "--atomic", "origin",
        f"HEAD:refs/heads/{canonical_branch}",
        f"HEAD:refs/heads/{checkpoint_branch}",
        cwd=PRODUCT_ROOT,
    )

    receipt = {
        "schema_version": "newsroom.increment5c2.dispatch-publication.v1",
        "parent": parent,
        "head": head,
        "tree": tree,
        "main": main_sha,
        "canonical_branch": canonical_branch,
        "checkpoint_branch": checkpoint_branch,
        "patch_sha256": manifest["patch_sha256"],
        "focused": FOCUSED_LOG.read_text(encoding="utf-8").splitlines()[-1],
        "full": FULL_LOG.read_text(encoding="utf-8").splitlines()[-1],
        "clustering": EVAL_LOG.read_text(encoding="utf-8").splitlines()[-1],
        "files": list(expected_files),
        "complete_5c2": False,
        "remaining": [
            "5C2 operating and traceability records",
            "Tier-S affected service evidence and exact-head review",
        ],
    }
    RECEIPT.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
