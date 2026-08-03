#!/usr/bin/env python3
"""Validate one canonical Increment 5 profile in a clean exact Git tree.

The receipt proves only that exact manifest bytes passed the reviewed profile
structure and semantic checks in the stated clean Git commit/tree. It grants no
qualification, production, component, source, model, provider, spend, write, or
public-effect authority.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


_MAX_INPUT_BYTES = 1_048_576
_MAX_GIT_OUTPUT_BYTES = 65_536
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_EXPECTED_FLAGS = frozenset(
    {
        "--expected-code-commit-sha",
        "--expected-code-tree-sha",
    }
)


class ProfileInputError(ValueError):
    """The isolated validator input or exact-code identity is invalid."""


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ProfileInputError(f"duplicate JSON object name: {name}")
        result[name] = value
    return result


def _fail(message: str) -> int:
    sys.stderr.write(f"increment5 profile validation failed: {message}\n")
    return 2


def _canonical_git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise ProfileInputError(f"{field} must be 40 lowercase hexadecimal characters")
    return value


def _parse_code_identity_args(argv: list[str]) -> tuple[str, str]:
    if len(argv) != 4:
        raise ProfileInputError(
            "exact code identity arguments are required: "
            "--expected-code-commit-sha <sha> "
            "--expected-code-tree-sha <sha>"
        )
    values: dict[str, str] = {}
    for index in range(0, len(argv), 2):
        flag = argv[index]
        if flag not in _EXPECTED_FLAGS:
            raise ProfileInputError(f"unsupported argument: {flag}")
        if flag in values:
            raise ProfileInputError(f"duplicate argument: {flag}")
        values[flag] = argv[index + 1]
    if frozenset(values) != _EXPECTED_FLAGS:
        raise ProfileInputError("exact code identity arguments are incomplete")
    return (
        _canonical_git_sha(
            values["--expected-code-commit-sha"],
            "expected code commit SHA",
        ),
        _canonical_git_sha(
            values["--expected-code-tree-sha"],
            "expected code tree SHA",
        ),
    )


def _git_executable() -> Path:
    raw = shutil.which("git")
    if raw is None:
        raise ProfileInputError("Git is unavailable for exact code-tree validation")
    path = Path(raw).resolve()
    if not path.is_file():
        raise ProfileInputError("Git executable is not a regular file")
    try:
        path.relative_to(_REPOSITORY_ROOT)
    except ValueError:
        return path
    raise ProfileInputError("Git executable cannot come from the repository checkout")


def _git_environment(git: Path) -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": str(git.parent),
    }


def _run_git(git: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            [str(git), "-C", str(_REPOSITORY_ROOT), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            env=_git_environment(git),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProfileInputError("cannot inspect the exact Git code tree") from exc
    if (
        completed.returncode != 0
        or len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES
        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES
    ):
        raise ProfileInputError("cannot inspect the exact Git code tree")
    return completed.stdout


def _git_sha(git: Path, revision: str, field: str) -> str:
    raw = _run_git(git, "rev-parse", "--verify", revision)
    try:
        value = raw.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise ProfileInputError(f"{field} is not canonical Git text") from exc
    return _canonical_git_sha(value, field)


def _require_exact_code_tree(
    expected_commit: str,
    expected_tree: str,
) -> tuple[str, str]:
    """Verify a clean exact checkout before repository validation code is imported."""

    git = _git_executable()
    actual_commit = _git_sha(git, "HEAD^{commit}", "code commit SHA")
    actual_tree = _git_sha(git, "HEAD^{tree}", "code tree SHA")
    status = _run_git(git, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ProfileInputError("repository checkout is not clean")
    if actual_commit != expected_commit:
        raise ProfileInputError("code commit SHA differs from expected identity")
    if actual_tree != expected_tree:
        raise ProfileInputError("code tree SHA differs from expected identity")
    return actual_commit, actual_tree


def _load_repository_api() -> tuple[Any, Any, Any, Any, Any]:
    """Import reviewed repository code only after the clean-tree gate passes."""

    if str(_REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPOSITORY_ROOT))
    from newsroom.authority.canonical import (
        CanonicalizationError,
        canonical_json_bytes,
        digest_bytes,
    )
    from newsroom.increment5.profiles import (
        Increment5ProfileError,
        _check_profile_manifest,
    )

    return (
        CanonicalizationError,
        canonical_json_bytes,
        digest_bytes,
        Increment5ProfileError,
        _check_profile_manifest,
    )


def main() -> int:
    try:
        expected_commit, expected_tree = _parse_code_identity_args(sys.argv[1:])
        actual_commit, actual_tree = _require_exact_code_tree(
            expected_commit,
            expected_tree,
        )
    except ProfileInputError as exc:
        return _fail(str(exc))

    try:
        (
            canonicalization_error_type,
            canonical_json_bytes,
            digest_bytes,
            profile_error_type,
            check_profile_manifest,
        ) = _load_repository_api()
    except Exception as exc:  # pragma: no cover - fail-closed import boundary
        return _fail(f"cannot load reviewed profile validator: {exc}")

    raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    if len(raw) > _MAX_INPUT_BYTES:
        return _fail("input exceeds 1048576 bytes")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
        canonical = canonical_json_bytes(value)
    except (
        UnicodeError,
        json.JSONDecodeError,
        canonicalization_error_type,
        ProfileInputError,
    ) as exc:
        return _fail(str(exc))

    if raw != canonical:
        return _fail("input is not canonical JSON")
    if not isinstance(value, dict):
        return _fail("profile manifest must be an object")

    try:
        check_profile_manifest(value)
    except profile_error_type as exc:
        return _fail(str(exc))

    profile_kind = value.get("profile_kind")
    if not isinstance(profile_kind, str):
        return _fail("profile kind is not canonical text")

    receipt = {
        "authority_effect": "NONE",
        "code_commit_sha": actual_commit,
        "code_tree_sha": actual_tree,
        "manifest_digest": digest_bytes(raw),
        "production_activation_authorized": False,
        "profile_kind": profile_kind,
        "qualification_authority_granted": False,
        "repository_clean": True,
        "schema_version": "newsroom.increment5.profile-validation-receipt.v2",
        "validation_scope": (
            "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_CLEAN_CODE_TREE"
        ),
    }
    sys.stdout.buffer.write(canonical_json_bytes(receipt) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
