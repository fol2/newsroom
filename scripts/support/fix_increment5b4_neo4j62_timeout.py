"""Repair the Increment 5B4 managed-transaction timeout binding."""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

REPOSITORY = "fol2/newsroom"
EXPECTED_MAIN = "88d1b14b41354f56f325d173d0021ad0fd20abc2"
EXPECTED_HEAD = "5b5cbb569cfd4f70648656763595b151fbe74d68"
PRODUCT_BRANCH = "agent/increment-5b-tierm-service-reconciliation"
CHECKPOINT_BRANCH = "checkpoint/increment-5b-tierm-service-reconciliation-20260807"
PRODUCT_FILES = (
    "newsroom/authority/neo4j_admitted_graph_reader.py",
    "newsroom/tests/test_increment5b4_neo4j_authority_port.py",
)
FOCUSED_LOG = Path("/tmp/increment5b4-neo4j62-timeout-focused.log")
FULL_LOG = Path("/tmp/increment5b4-neo4j62-timeout-full.log")
RECEIPT = Path("/tmp/increment5b4-neo4j62-timeout-receipt.txt")


def run(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


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
    run("git", "init", "-q", root.as_posix())
    run("git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git", cwd=root)
    run(
        "git",
        "fetch",
        "--no-tags",
        "--depth=2",
        "origin",
        f"refs/heads/{PRODUCT_BRANCH}:refs/remotes/origin/product",
        "refs/heads/main:refs/remotes/origin/main",
        cwd=root,
    )
    actual_head = run("git", "rev-parse", "refs/remotes/origin/product", cwd=root, capture=True)
    actual_main = run("git", "rev-parse", "refs/remotes/origin/main", cwd=root, capture=True)
    if actual_head != EXPECTED_HEAD:
        raise SystemExit(f"canonical product head moved: {actual_head}")
    if actual_main != EXPECTED_MAIN:
        raise SystemExit(f"main moved during Neo4j timeout repair: {actual_main}")
    run("git", "checkout", "-q", "--detach", EXPECTED_HEAD, cwd=root)
    return root


def patch(root: Path) -> None:
    reader = root / "newsroom/authority/neo4j_admitted_graph_reader.py"
    text = reader.read_text(encoding="utf-8")
    old = '''            with self._session() as session:\n                rows = session.execute_read(work, timeout=timeout_seconds)\n'''
    new = '''            setattr(work, "timeout", timeout_seconds)\n            with self._session() as session:\n                rows = session.execute_read(work)\n'''
    if text.count(old) != 2:
        raise SystemExit("managed transaction timeout call sites drifted")
    reader.write_text(text.replace(old, new), encoding="utf-8")

    tests = root / "newsroom/tests/test_increment5b4_neo4j_authority_port.py"
    text = tests.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    assert getattr(query, "timeout", 5.0) is not None\n    assert driver.session_instance.execute_calls[0][2] == {\n        "timeout": pytest.approx(5.0)\n    }\n''',
        '''    work, args, kwargs = driver.session_instance.execute_calls[0]\n    assert args == ()\n    assert kwargs == {}\n    assert getattr(work, "timeout") == pytest.approx(5.0)\n''',
        field="root managed timeout assertion",
    )
    text = replace_once(
        text,
        '''    query = driver.transaction.calls[0][2]\n    timeout = getattr(query, "timeout", None)\n    if timeout is not None:\n        assert timeout == pytest.approx(0.003)\n''',
        '''    work, args, kwargs = driver.session_instance.execute_calls[0]\n    assert args == ()\n    assert kwargs == {}\n    assert getattr(work, "timeout") == pytest.approx(0.003)\n''',
        field="reduced managed timeout assertion",
    )
    anchor = '''    assert params["temporal_lower_bound"] == LOWER\n    assert params["absolute_row_limit"] == GRAPH_MAX_FANOUT + 1\n'''
    insertion = '''    assert params["temporal_lower_bound"] == LOWER\n    assert params["absolute_row_limit"] == GRAPH_MAX_FANOUT + 1\n    work, args, kwargs = driver.session_instance.execute_calls[0]\n    assert args == ()\n    assert kwargs == {}\n    assert getattr(work, "timeout") == pytest.approx(5.0)\n'''
    text = replace_once(
        text,
        anchor,
        insertion,
        field="frontier managed timeout assertion",
    )
    tests.write_text(text, encoding="utf-8")


def verify_and_publish(root: Path) -> None:
    run("uv", "lock", "--check", cwd=root)
    run("uv", "sync", "--dev", "--locked", cwd=root)
    run("git", "config", "user.name", "James To", cwd=root)
    run("git", "config", "user.email", "105634418+fol2@users.noreply.github.com", cwd=root)
    run("git", "add", "--", *PRODUCT_FILES, cwd=root)
    run("git", "diff", "--cached", "--check", cwd=root)
    actual = tuple(
        filter(None, run("git", "diff", "--cached", "--name-only", cwd=root, capture=True).splitlines())
    )
    if tuple(sorted(actual)) != tuple(sorted(PRODUCT_FILES)):
        raise SystemExit(f"product inventory drifted: {actual}")
    run(
        "git",
        "commit",
        "-q",
        "-m",
        "Increment 5B4: bind Neo4j 6.2 managed transaction timeout",
        cwd=root,
    )

    with FOCUSED_LOG.open("w", encoding="utf-8") as stream:
        subprocess.run(
            (
                "uv",
                "run",
                "pytest",
                "-q",
                "newsroom/tests/test_increment5b4_neo4j_authority_port.py",
            ),
            cwd=root,
            check=True,
            text=True,
            stdout=stream,
        )
    with FULL_LOG.open("w", encoding="utf-8") as stream:
        subprocess.run(
            ("uv", "run", "pytest", "-q"),
            cwd=root,
            check=True,
            text=True,
            stdout=stream,
        )

    head = run("git", "rev-parse", "HEAD", cwd=root, capture=True)
    tree = run("git", "rev-parse", "HEAD^{tree}", cwd=root, capture=True)
    if run("git", "status", "--porcelain", cwd=root, capture=True):
        raise SystemExit("verified product tree is not clean")
    for branch in (PRODUCT_BRANCH, CHECKPOINT_BRANCH):
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}", cwd=root)
    RECEIPT.write_text(
        "\n".join(
            (
                "schema=newsroom.increment5b.neo4j62-timeout-repair.v1",
                f"parent={EXPECTED_HEAD}",
                f"head={head}",
                f"tree={tree}",
                f"focused={FOCUSED_LOG.read_text(encoding='utf-8').splitlines()[-1]}",
                f"full={FULL_LOG.read_text(encoding='utf-8').splitlines()[-1]}",
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
