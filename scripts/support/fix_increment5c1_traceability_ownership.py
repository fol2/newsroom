"""Repair the exact Increment 5C1 closed-world ownership statement."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import subprocess

REPOSITORY = "fol2/newsroom"
EXPECTED_MAIN = "c77624dba9b9bee87278eb9be5621ef35ee3df85"
EXPECTED_HEAD = "307a480175aa01014234a6252a0fac6b1662dc76"
PRODUCT_BRANCH = "agent/increment-5c1-named-tool-authorization"
CHECKPOINT_BRANCH = "checkpoint/increment-5c1-named-tool-authorization-20260807"
PRODUCT_FILES = (
    "docs/traceability/increment-5c1-named-tool-authorization.md",
    "newsroom/tests/test_increment5c1_named_tool_contracts.py",
)
FOCUSED_LOG = Path("/tmp/increment5c1-traceability-focused.log")
FULL_LOG = Path("/tmp/increment5c1-traceability-full.log")
RECEIPT = Path("/tmp/increment5c1-traceability-receipt.txt")


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


def checkout() -> Path:
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
        "--depth=3",
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
        raise SystemExit(f"canonical 5C1 head moved: {actual_head}")
    if actual_main != EXPECTED_MAIN:
        raise SystemExit(f"main moved during 5C1 traceability repair: {actual_main}")
    run("git", "checkout", "-q", "--detach", EXPECTED_HEAD, cwd=root)
    return root


def patch(root: Path) -> None:
    traceability = root / PRODUCT_FILES[0]
    text = traceability.read_text(encoding="utf-8")
    old = '''5C1 provides common mechanics needed by parent #252 for named read-only tools,\nincluding strict request shape, local authenticated actor/purpose/scope checks,\nhard bounds and inspectable authorization receipts. Parent delivery of\n`GRAG-033`, `GRAG-034`, `GRAG-035` and `TRI-022` remains incomplete until 5C2\nexecutes all six named tools through their reviewed branch or authority ports.\n'''
    new = '''5C1 provides common mechanics needed by parent #252 for named read-only tools,\nincluding strict request shape, local authenticated actor/purpose/scope checks,\nhard bounds and inspectable authorization receipts. Parent delivery of\n`GRAG-033` and `GRAG-034` remains incomplete until 5C2 executes all six named\ntools through their reviewed branch or authority ports. `GRAG-035` and\n`TRI-022` remain owned by the composed Retrieval Context boundary in 5D/#253.\n'''
    text = replace_once(
        text,
        old,
        new,
        field="5C closed-world ownership paragraph",
    )
    traceability.write_text(text, encoding="utf-8")

    tests = root / PRODUCT_FILES[1]
    text = tests.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from datetime import UTC, datetime, timedelta\n\nimport pytest\n",
        "from datetime import UTC, datetime, timedelta\nfrom pathlib import Path\n\nimport pytest\n",
        field="traceability test Path import",
    )
    anchor = '''def test_contract_module_is_branch_neutral_and_network_free() -> None:\n'''
    addition = '''def test_traceability_retains_exact_closed_world_5c_ownership() -> None:\n    root = Path(__file__).resolve().parents[2]\n    local = (\n        root / "docs/traceability/increment-5c1-named-tool-authorization.md"\n    ).read_text(encoding="utf-8")\n    accepted = (\n        root / "docs/traceability/increment-5-production-retrieval.md"\n    ).read_text(encoding="utf-8")\n    assert "The exact 5C set is:\\n\\n`GRAG-033`, `GRAG-034`." in accepted\n    assert (\n        "Parent delivery of\\n`GRAG-033` and `GRAG-034` remains incomplete "\n        "until 5C2"\n    ) in local\n    assert (\n        "`GRAG-035` and\\n`TRI-022` remain owned by the composed Retrieval "\n        "Context boundary in 5D/#253."\n    ) in local\n    assert "`GRAG-033`, `GRAG-034`, `GRAG-035`" not in local\n\n\n'''
    text = replace_once(
        text,
        anchor,
        addition + anchor,
        field="closed-world traceability regression",
    )
    tests.write_text(text, encoding="utf-8")


def verify_and_publish(root: Path) -> None:
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
        raise SystemExit(f"5C1 traceability inventory drifted: {actual}")
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "Increment 5C1: retain exact parent requirement ownership",
        cwd=root,
    )
    head = run("git", "rev-parse", "HEAD", cwd=root, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)

    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    focused = run_logged(
        (
            "uv",
            "run",
            "pytest",
            "-q",
            "newsroom/tests/test_increment5c1_named_tool_authorization.py",
            "newsroom/tests/test_increment5c1_named_tool_contracts.py",
            "newsroom/tests/test_increment5a_traceability.py",
        ),
        cwd=root,
        log=FOCUSED_LOG,
    )
    full = run_logged(
        ("uv", "run", "pytest", "-q"),
        cwd=root,
        log=FULL_LOG,
    )
    status = run(
        "git", "status", "--porcelain", "--untracked-files=no", cwd=root, capture=True
    )
    if status:
        raise SystemExit(f"verification mutated tracked product bytes: {status}")
    current_main = run(
        "git", "ls-remote", "origin", "refs/heads/main", cwd=root, capture=True
    ).split()[0]
    current_product = run(
        "git",
        "ls-remote",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}",
        cwd=root,
        capture=True,
    ).split()[0]
    current_checkpoint = run(
        "git",
        "ls-remote",
        "origin",
        f"refs/heads/{CHECKPOINT_BRANCH}",
        cwd=root,
        capture=True,
    ).split()[0]
    if current_main != EXPECTED_MAIN:
        raise SystemExit(f"main moved before traceability publication: {current_main}")
    if current_product != EXPECTED_HEAD or current_checkpoint != EXPECTED_HEAD:
        raise SystemExit(
            "5C1 refs moved before traceability publication: "
            f"product={current_product} checkpoint={current_checkpoint}"
        )
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    RECEIPT.write_text(
        "\n".join(
            (
                "schema=newsroom.increment5c1.traceability-ownership-repair.v1",
                f"parent={EXPECTED_HEAD}",
                f"head={head}",
                f"tree={tree}",
                f"focused={focused}",
                f"full={full}",
                "files=2",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    print(RECEIPT.read_text(encoding="utf-8"), end="")


def main() -> None:
    configure_auth()
    root = checkout()
    patch(root)
    verify_and_publish(root)


if __name__ == "__main__":
    main()
