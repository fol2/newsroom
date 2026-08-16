from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.sdlc.increment9g_closeout_receipt import (
    Increment9CloseoutCommandError,
    _git,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_generated_sdlc_evidence_does_not_weaken_exact_source_cleanliness(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _run(repository, "init", "--initial-branch=main")
    (repository / ".gitignore").write_text(
        (REPO_ROOT / ".gitignore").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("exact\n", encoding="utf-8")
    _run(repository, "add", ".gitignore", "tracked.txt")
    _run(
        repository,
        "-c",
        "user.name=Newsroom Tests",
        "-c",
        "user.email=newsroom-tests@example.invalid",
        "commit",
        "-m",
        "fixture",
    )

    artifact = repository / ".sdlc-run" / "increment9-subjects" / "subject.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    head, tree = _git(repository)
    assert head == _run(repository, "rev-parse", "HEAD")
    assert tree == _run(repository, "rev-parse", "HEAD^{tree}")

    unrelated = repository / "unexpected.txt"
    unrelated.write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(Increment9CloseoutCommandError, match="checkout is not clean"):
        _git(repository)
    unrelated.unlink()

    tracked.write_text("changed\n", encoding="utf-8")
    with pytest.raises(Increment9CloseoutCommandError, match="checkout is not clean"):
        _git(repository)
