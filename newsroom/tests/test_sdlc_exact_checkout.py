from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts.sdlc.classify_change import (
    GitRouteError,
    resolve_commit,
    resolve_tree,
    verify_exact_clean_checkout,
)


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "SDLC Test")
    (tmp_path / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    head = resolve_commit(tmp_path, "HEAD")
    return tmp_path, head, resolve_tree(tmp_path, head)


def test_exact_clean_checkout_is_accepted(tmp_path: Path) -> None:
    repo, head, tree = _repository(tmp_path)

    verify_exact_clean_checkout(repo, head_sha=head, head_tree_sha=tree)


def test_checkout_head_must_equal_route_head(tmp_path: Path) -> None:
    repo, first, first_tree = _repository(tmp_path)
    (repo / "tracked.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "second")

    with pytest.raises(GitRouteError, match="HEAD differs"):
        verify_exact_clean_checkout(
            repo,
            head_sha=first,
            head_tree_sha=first_tree,
        )


def test_checkout_tree_must_equal_route_tree(tmp_path: Path) -> None:
    repo, head, _ = _repository(tmp_path)

    with pytest.raises(GitRouteError, match="tree differs"):
        verify_exact_clean_checkout(
            repo,
            head_sha=head,
            head_tree_sha="f" * 40,
        )


def test_tracked_or_untracked_worktree_content_blocks_route(tmp_path: Path) -> None:
    repo, head, tree = _repository(tmp_path)
    (repo / "untracked.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(GitRouteError, match="not clean"):
        verify_exact_clean_checkout(repo, head_sha=head, head_tree_sha=tree)

    (repo / "untracked.py").unlink()
    (repo / "tracked.py").write_text("VALUE = 3\n", encoding="utf-8")
    with pytest.raises(GitRouteError, match="not clean"):
        verify_exact_clean_checkout(repo, head_sha=head, head_tree_sha=tree)
