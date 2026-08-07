"""Build, verify, and export the exact Increment 5B Evidence finalizer repair."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_MAIN = "88d1b14b41354f56f325d173d0021ad0fd20abc2"
EXPECTED_HEAD = "80d98b277517523bc0f0963df0516973c81fa5da"
EXPECTED_TREE = "0e4985fc0fb8f522ec01646f5b684db9b7a98349"
PRODUCT_BRANCH = "agent/increment-5b-tierm-service-reconciliation"
CHECKPOINT_BRANCH = "checkpoint/increment-5b-tierm-service-reconciliation-20260807"
CARRIER_BRANCH = "support/carrier-increment5b-tierm-finalizer-env-20260807"
CARRIER_ROOT = Path("carrier/increment5b-tierm-finalizer-env")
PRODUCT_FILES = (
    ".github/workflows/evidence.yml",
    "newsroom/tests/test_sdlc_evidence_workflow.py",
)
FOCUSED_LOG = Path("/tmp/increment5b-tierm-finalizer-focused.log")
FULL_LOG = Path("/tmp/increment5b-tierm-finalizer-full.log")
RECEIPT = Path("/tmp/increment5b-tierm-finalizer-receipt.json")


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
        "--depth=6",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=root,
    )
    actual_head = run(
        "git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True
    )
    actual_main = run(
        "git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True
    )
    if actual_head != EXPECTED_HEAD:
        raise SystemExit(f"canonical product head moved: {actual_head}")
    if actual_main != EXPECTED_MAIN:
        raise SystemExit(f"main moved during finalizer repair: {actual_main}")
    run("git", "checkout", "-q", "--detach", EXPECTED_HEAD, cwd=root)
    actual_tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)
    if actual_tree != EXPECTED_TREE:
        raise SystemExit(f"canonical product tree drifted: {actual_tree}")
    return root


def patch(root: Path) -> None:
    workflow = root / ".github/workflows/evidence.yml"
    text = workflow.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "      NEWSROOM_NEO4J_PROJECTOR_USERNAME: newsroom_projector\n"
        "      NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED: '1'\n",
        "      NEWSROOM_NEO4J_PROJECTOR_USERNAME: newsroom_projector\n"
        "      NEWSROOM_NEO4J_USER: newsroom_projector\n"
        "      NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED: '1'\n",
        field="service job generic user",
    )
    workflow.write_text(text, encoding="utf-8")

    tests = root / "newsroom/tests/test_sdlc_evidence_workflow.py"
    text = tests.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",\n'
        '        "NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED": "1",\n',
        '        "NEWSROOM_NEO4J_PROJECTOR_USERNAME": "newsroom_projector",\n'
        '        "NEWSROOM_NEO4J_USER": "newsroom_projector",\n'
        '        "NEWSROOM_NEO4J_RETRIEVAL_SERVICE_REQUIRED": "1",\n',
        field="exact service job environment",
    )
    tests.write_text(text, encoding="utf-8")


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
        for line in run(
            "git", "diff", "--cached", "--name-only", cwd=root, capture=True
        ).splitlines()
        if line
    )
    if tuple(sorted(actual)) != tuple(sorted(PRODUCT_FILES)):
        raise SystemExit(f"product inventory drifted: {actual}")
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "SDLC: retain service identity through Evidence finalization",
        cwd=root,
    )
    return (
        run("git", "rev-parse", "HEAD", cwd=root, capture=True),
        run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True),
    )


def verify(root: Path) -> tuple[str, str]:
    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    focused = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5b_tierm_service_reconciliation.py",
            "newsroom/tests/test_sdlc_evidence_workflow.py",
            "newsroom/tests/test_sdlc_workflow_lane.py::test_static_environment_excludes_ambient_secrets",
            "newsroom/tests/test_sdlc_workflow_lane.py::test_service_lane_requires_route_and_passes_only_explicit_projector_secrets",
            "newsroom/tests/test_sdlc_workflow_budget.py",
        ),
        cwd=root,
        log=FOCUSED_LOG,
    )
    full = run_logged(
        ("uv", "run", "pytest", "-q"),
        cwd=root,
        log=FULL_LOG,
    )
    if run(
        "git", "status", "--porcelain", "--untracked-files=no", cwd=root, capture=True
    ):
        raise SystemExit("verified product tree is not clean")
    return focused, full


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def publish_carrier(
    root: Path,
    *,
    tested_head: str,
    tested_tree: str,
    focused: str,
    full: str,
) -> None:
    if CARRIER_ROOT.exists():
        shutil.rmtree(CARRIER_ROOT)
    CARRIER_ROOT.mkdir(parents=True)
    carrier_workflow = CARRIER_ROOT / "evidence.yml"
    carrier_test = CARRIER_ROOT / "test_sdlc_evidence_workflow.py"
    shutil.copyfile(root / PRODUCT_FILES[0], carrier_workflow)
    shutil.copyfile(root / PRODUCT_FILES[1], carrier_test)
    manifest = {
        "schema_version": "newsroom.increment5b.tierm-finalizer-carrier.v1",
        "parent": EXPECTED_HEAD,
        "parent_tree": EXPECTED_TREE,
        "main": EXPECTED_MAIN,
        "tested_head": tested_head,
        "tested_tree": tested_tree,
        "focused": focused,
        "full": full,
        "files": {
            ".github/workflows/evidence.yml": sha256(carrier_workflow),
            "newsroom/tests/test_sdlc_evidence_workflow.py": sha256(carrier_test),
        },
    }
    manifest_path = CARRIER_ROOT / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    run("git", "config", "user.name", "James To")
    run(
        "git",
        "config",
        "user.email",
        "105634418+fol2@users.noreply.github.com",
    )
    run("git", "add", "--", CARRIER_ROOT.as_posix())
    run("git", "diff", "--cached", "--check")
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "Support: export tested Increment 5B Evidence finalizer blobs",
    )
    carrier_commit = run("git", "rev-parse", "HEAD", capture=True)
    run("git", "push", "origin", f"HEAD:refs/heads/{CARRIER_BRANCH}")

    receipt = {
        **manifest,
        "carrier_branch": CARRIER_BRANCH,
        "carrier_commit": carrier_commit,
    }
    RECEIPT.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


def main() -> None:
    configure_auth()
    root = checkout_product()
    patch(root)
    tested_head, tested_tree = commit_candidate(root)
    focused, full = verify(root)
    publish_carrier(
        root,
        tested_head=tested_head,
        tested_tree=tested_tree,
        focused=focused,
        full=full,
    )


if __name__ == "__main__":
    main()
