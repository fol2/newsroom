"""Materialize, verify, and publish the exact post-5B Increment 5C1 atom."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_BASE = "c77624dba9b9bee87278eb9be5621ef35ee3df85"
EXPECTED_BASE_TREE = "3db568c08949f14a72257fdc72949174064bece4"
SOURCE_BRANCH = "support/materialize-increment-5c1-20260806"
EXPECTED_SOURCE = "8ac3b7d49a8f103797428895a0fa58dd6ad3ea88"
PRODUCT_BRANCH = "agent/increment-5c1-named-tool-authorization"
CHECKPOINT_BRANCH = "checkpoint/increment-5c1-named-tool-authorization-20260807"
PRODUCT_FILES = (
    "docs/operations/increment-5c1-named-tool-authorization.md",
    "docs/traceability/increment-5c1-named-tool-authorization.md",
    "newsroom/increment5/named_tool_authorization.py",
    "newsroom/increment5/named_tool_contracts.py",
    "newsroom/tests/test_increment5c1_named_tool_authorization.py",
    "newsroom/tests/test_increment5c1_named_tool_contracts.py",
)
FOCUSED_LOG = Path("/tmp/increment5c1-post5b-focused.log")
FULL_LOG = Path("/tmp/increment5c1-post5b-full.log")
RECEIPT = Path("/tmp/increment5c1-post5b-receipt.json")


def run(
    *args: str,
    cwd: Path | None = None,
    capture: bool = False,
    binary: bool = False,
) -> str | bytes:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=not binary,
        stdout=subprocess.PIPE if capture else None,
    )
    if not capture:
        return b"" if binary else ""
    output = completed.stdout
    if binary:
        assert isinstance(output, bytes)
        return output
    assert isinstance(output, str)
    return output.strip()


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
    if completed.returncode:
        print(output, end="")
        raise subprocess.CalledProcessError(
            completed.returncode,
            args,
            output=output,
        )
    lines = output.splitlines()
    return lines[-1] if lines else ""


def replace_once(text: str, old: str, new: str, *, field: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{field} anchor drifted")
    return text.replace(old, new, 1)


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


def checkout_product() -> Path:
    root = Path("product")
    if root.exists():
        shutil.rmtree(root)
    run("git", "init", "-q", root.as_posix())
    run(
        "git",
        "remote",
        "add",
        "origin",
        f"https://github.com/{REPOSITORY}.git",
        cwd=root,
    )
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=1",
        "origin",
        "refs/heads/main:refs/remotes/origin/main",
        f"refs/heads/{SOURCE_BRANCH}:refs/remotes/origin/source",
        cwd=root,
    )
    actual_base = run(
        "git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True
    )
    actual_source = run(
        "git", "rev-parse", "refs/remotes/origin/source", cwd=root, capture=True
    )
    if actual_base != EXPECTED_BASE:
        raise SystemExit(f"main moved before 5C1 materialization: {actual_base}")
    if actual_source != EXPECTED_SOURCE:
        raise SystemExit(f"preserved 5C1 source moved: {actual_source}")
    run("git", "checkout", "-q", "--detach", EXPECTED_BASE, cwd=root)
    base_tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)
    if base_tree != EXPECTED_BASE_TREE:
        raise SystemExit(f"accepted base tree drifted: {base_tree}")
    return root


def copy_preserved_product(root: Path) -> None:
    for path in PRODUCT_FILES:
        payload = run(
            "git",
            "show",
            f"refs/remotes/origin/source:{path}",
            cwd=root,
            capture=True,
            binary=True,
        )
        assert isinstance(payload, bytes)
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)


def correct_replanned_documentation(root: Path) -> None:
    operations = root / PRODUCT_FILES[0]
    text = operations.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "Parent 5C remains open for 5C2 and 5C3.\n",
        "Parent 5C remains open for 5C2 and its Tier-M aggregate closeout.\n",
        field="operations child sequence",
    )
    text = replace_once(
        text,
        "The complete `DOPS-026` and `DOPS-067` boundaries remain 5E work across every\n"
        "executable operational surface.\n",
        "The complete `DOPS-026` and `DOPS-067` boundaries remain Increment 8/#148\n"
        "work across every executable operational surface.\n",
        field="operations DOPS ownership",
    )
    text = replace_once(
        text,
        "Before 5C2/5C3, monitoring is limited to deterministic malformed-request and\n",
        "Before 5C2, monitoring is limited to deterministic malformed-request and\n",
        field="operations monitoring sequence",
    )
    if "5C3" in text or "remain 5E work" in text:
        raise SystemExit("stale operations ownership remains")
    operations.write_text(text, encoding="utf-8")

    traceability = root / PRODUCT_FILES[1]
    text = traceability.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "`GRAG-033`, `GRAG-034`, `GRAG-035` and `TRI-022` remains incomplete until 5C2\n"
        "and 5C3 execute all six named tools through their reviewed branch or authority\n"
        "ports.\n",
        "`GRAG-033`, `GRAG-034`, `GRAG-035` and `TRI-022` remains incomplete until 5C2\n"
        "executes all six named tools through their reviewed branch or authority ports.\n",
        field="traceability child sequence",
    )
    text = replace_once(
        text,
        "the `DOPS-067` credential/source-access/network-destination boundary. Both\n"
        "remain explicitly deferred to 5E.\n",
        "the `DOPS-067` credential/source-access/network-destination boundary. Both\n"
        "remain explicitly deferred to Increment 8/#148.\n",
        field="traceability DOPS ownership",
    )
    completion_start = text.index("## Completion evidence\n")
    replacement = """## Completion evidence

The 5C1 child issue can close only after one clean product commit over the exact
accepted post-5B `main` has:

- focused request, authorization and journal tests passing;
- the complete deterministic repository suite passing;
- source-integrity and local boundary checks passing;
- exact-head substantive review with zero unresolved P1/material-P2 findings;
- zero unresolved review threads; and
- product-only squash merge with exact commit/tree evidence.

Parent #252 remains open for #329 and one parent Tier-M aggregate gate. No
successful 5C1 receipt may be described as a completed named tool, Retrieval
Context, collision decision, hydration result, operational admission, provider
approval, production activation or public effect.
"""
    text = text[:completion_start] + replacement
    if "5C3" in text or "deferred to 5E" in text:
        raise SystemExit("stale traceability ownership remains")
    traceability.write_text(text, encoding="utf-8")


def commit_candidate(root: Path) -> tuple[str, str]:
    run("git", "config", "user.name", "James To", cwd=root)
    run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
        cwd=root,
    )
    run("git", "add", "--", *PRODUCT_FILES, cwd=root)
    run("git", "diff", "--cached", "--check", cwd=root)
    actual = tuple(
        line
        for line in str(
            run("git", "diff", "--cached", "--name-only", cwd=root, capture=True)
        ).splitlines()
        if line
    )
    if tuple(sorted(actual)) != tuple(sorted(PRODUCT_FILES)):
        raise SystemExit(f"5C1 product inventory drifted: {actual}")
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "Increment 5C1: strict named-tool contracts and local authorization",
        cwd=root,
    )
    count = run(
        "git", "rev-list", "--count", f"{EXPECTED_BASE}..HEAD", cwd=root, capture=True
    )
    if count != "1":
        raise SystemExit(f"5C1 candidate is not one commit: {count}")
    return (
        str(run("git", "rev-parse", "HEAD", cwd=root, capture=True)),
        str(run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)),
    )


def verify(root: Path) -> tuple[str, str]:
    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    run(
        "python",
        "-m",
        "compileall",
        "-q",
        "newsroom/increment5/named_tool_authorization.py",
        "newsroom/increment5/named_tool_contracts.py",
        cwd=root,
    )
    focused = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5c1_named_tool_authorization.py",
            "newsroom/tests/test_increment5c1_named_tool_contracts.py",
        ),
        cwd=root,
        log=FOCUSED_LOG,
    )
    full = run_logged(
        ("uv", "run", "pytest", "-q"),
        cwd=root,
        log=FULL_LOG,
    )
    status = str(
        run("git", "status", "--porcelain", "--untracked-files=no", cwd=root, capture=True)
    )
    if status:
        raise SystemExit(f"verification mutated tracked product bytes: {status}")
    return focused, full


def publish(
    root: Path,
    *,
    head: str,
    tree: str,
    focused: str,
    full: str,
) -> None:
    current_main = str(
        run("git", "ls-remote", "origin", "refs/heads/main", cwd=root, capture=True)
    ).split()[0]
    if current_main != EXPECTED_BASE:
        raise SystemExit(f"main moved before 5C1 publication: {current_main}")
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        existing = str(
            run("git", "ls-remote", "origin", f"refs/heads/{branch}", cwd=root, capture=True)
        )
        if existing:
            raise SystemExit(f"publication ref already exists: {branch}")
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    receipt = {
        "schema_version": "newsroom.increment5c1.post5b-materialization.v1",
        "base": EXPECTED_BASE,
        "base_tree": EXPECTED_BASE_TREE,
        "source": EXPECTED_SOURCE,
        "head": head,
        "tree": tree,
        "focused": focused,
        "full": full,
        "files": list(PRODUCT_FILES),
        "product_branch": PRODUCT_BRANCH,
        "checkpoint_branch": CHECKPOINT_BRANCH,
    }
    RECEIPT.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


def main() -> None:
    configure_auth()
    root = checkout_product()
    copy_preserved_product(root)
    correct_replanned_documentation(root)
    head, tree = commit_candidate(root)
    focused, full = verify(root)
    publish(root, head=head, tree=tree, focused=focused, full=full)


if __name__ == "__main__":
    main()
