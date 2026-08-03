from __future__ import annotations

import ctypes
from copy import deepcopy
import inspect
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
from typing import Any, Callable

import pytest
from jsonschema import Draft202012Validator

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import (
    Increment5ProfileError,
    build_fixture_replay_manifest,
    build_qualification_manifest,
)
from newsroom.increment5 import profiles


_DIGEST_A = "sha256:" + "a" * 64
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_VALIDATOR_RELATIVE_PATH = Path("scripts/sdlc/increment5_profile_validator.py")
_VALIDATOR_SCRIPT = _REPOSITORY_ROOT / _VALIDATOR_RELATIVE_PATH


def _git_text(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    return completed.stdout.decode("ascii", errors="strict").strip()


def _code_identity(root: Path) -> tuple[str, str]:
    return (
        _git_text(root, "rev-parse", "--verify", "HEAD^{commit}"),
        _git_text(root, "rev-parse", "--verify", "HEAD^{tree}"),
    )


_CODE_COMMIT_SHA, _CODE_TREE_SHA = _code_identity(_REPOSITORY_ROOT)


def _fixture_manifest() -> dict[str, Any]:
    return build_fixture_replay_manifest(
        fixture_id="integrated-fixture-v3",
        fixture_manifest_digest=_DIGEST_A,
    )


def _qualification_manifest() -> dict[str, Any]:
    return build_qualification_manifest(
        dataset_id="increment5-rights-cleared-v1",
        dataset_manifest_digest=_DIGEST_A,
    )


def _validator_environment() -> dict[str, str]:
    return {
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONUTF8": "1",
    }


def _run_isolated_bytes(
    raw: bytes,
    *,
    root: Path = _REPOSITORY_ROOT,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if expected_commit is None or expected_tree is None:
        actual_commit, actual_tree = _code_identity(root)
        expected_commit = expected_commit or actual_commit
        expected_tree = expected_tree or actual_tree
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(root / _VALIDATOR_RELATIVE_PATH),
            "--expected-code-commit-sha",
            expected_commit,
            "--expected-code-tree-sha",
            expected_tree,
        ],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=root,
        env=_validator_environment(),
        timeout=30,
    )


def _run_isolated(manifest: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    return _run_isolated_bytes(canonical_json_bytes(manifest))


def _clone_exact_head(destination: Path) -> tuple[Path, str, str]:
    clone = destination / "repo"
    cloned = subprocess.run(
        [
            "git",
            "clone",
            "--shared",
            "--no-checkout",
            "--quiet",
            str(_REPOSITORY_ROOT),
            str(clone),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert cloned.returncode == 0, cloned.stderr.decode("utf-8")
    checked_out = subprocess.run(
        ["git", "-C", str(clone), "checkout", "--detach", _CODE_COMMIT_SHA],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert checked_out.returncode == 0, checked_out.stderr.decode("utf-8")
    clone_commit, clone_tree = _code_identity(clone)
    assert (clone_commit, clone_tree) == (_CODE_COMMIT_SHA, _CODE_TREE_SHA)
    return clone, clone_commit, clone_tree


def _closure_cell(
    function: Callable[..., object],
    captured_name: str,
) -> tuple[object, object]:
    for cell in function.__closure__ or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if inspect.isfunction(value) and value.__name__ == captured_name:
            return cell, value
    raise AssertionError(f"closure does not capture {captured_name}")


def _set_cell(cell: object, value: object) -> None:
    py_cell_set = ctypes.pythonapi.PyCell_Set
    py_cell_set.argtypes = (ctypes.py_object, ctypes.py_object)
    py_cell_set.restype = ctypes.c_int
    assert py_cell_set(cell, value) == 0


@pytest.mark.parametrize(
    "builder",
    (_fixture_manifest, _qualification_manifest),
)
def test_fresh_process_returns_code_tree_bound_non_authoritative_receipt(
    builder: Callable[[], dict[str, Any]],
) -> None:
    manifest = builder()
    completed = _run_isolated(manifest)

    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    raw_receipt = completed.stdout.rstrip(b"\n")
    receipt = json.loads(raw_receipt.decode("utf-8"))
    assert raw_receipt == canonical_json_bytes(receipt)
    assert receipt == {
        "authority_effect": "NONE",
        "code_commit_sha": _CODE_COMMIT_SHA,
        "code_tree_sha": _CODE_TREE_SHA,
        "manifest_digest": digest_bytes(canonical_json_bytes(manifest)),
        "production_activation_authorized": False,
        "profile_kind": manifest["profile_kind"],
        "qualification_authority_granted": False,
        "schema_version": "newsroom.increment5.profile-validation-receipt.v3",
        "tracked_checkout_clean": True,
        "validation_code_origin": "CACHE_FREE_EXACT_GIT_ARCHIVE",
        "validation_scope": (
            "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
        ),
        "worktree_imports_used": False,
    }


@pytest.mark.parametrize(
    ("builder", "mutate", "message"),
    (
        (
            _fixture_manifest,
            lambda manifest: manifest.__setitem__("qualification_eligible", True),
            "profile qualification eligibility differs",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest.__setitem__("qualification_eligible", False),
            "profile qualification eligibility differs",
        ),
        (
            _fixture_manifest,
            lambda manifest: manifest["fixture"].__setitem__(
                "production_substitution_allowed",
                True,
            ),
            "fixture replay cannot substitute",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest.__setitem__(
                "actual_neo4j_required",
                False,
            ),
            "qualification requires an actual Neo4j service",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest["dataset"].__setitem__(
                "rights_cleared",
                False,
            ),
            "qualification dataset must be rights cleared",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest["runtime_effects"].__setitem__(
                "external_calls",
                1,
            ),
            "profile runtime effects differs",
        ),
        (
            _fixture_manifest,
            lambda manifest: manifest.__setitem__("implicit_authority", True),
            "profile fields differ",
        ),
    ),
)
def test_private_semantic_check_survives_json_schema_validator_bypass(
    monkeypatch: pytest.MonkeyPatch,
    builder: Callable[[], dict[str, Any]],
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    manifest = deepcopy(builder())
    mutate(manifest)

    monkeypatch.setattr(
        Draft202012Validator,
        "iter_errors",
        lambda self, instance: iter(()),
    )

    with pytest.raises(Increment5ProfileError, match=message):
        profiles._check_profile_manifest(manifest)


def test_same_process_closure_mutation_cannot_create_qualification_authority() -> None:
    manifest = _fixture_manifest()
    manifest["qualification_eligible"] = True

    cell, original = _closure_cell(
        profiles._check_profile_manifest,
        "check_snapshot",
    )

    def bypass(snapshot: object, *, profile: object) -> None:
        return None

    try:
        _set_cell(cell, bypass)

        # Arbitrary code in the same Python process can bypass any Python
        # helper. The private helper therefore returns no certificate, boolean,
        # or authority-bearing value even under this exact attack.
        assert profiles._check_profile_manifest(manifest) is None

        # The fresh -I process imports only the cache-free exact Git tree and
        # rejects the same bytes; the mutated cell cannot cross that boundary.
        completed = _run_isolated(manifest)
        assert completed.returncode == 2
        assert completed.stderr.startswith(
            b"increment5 profile validation failed: "
        )
        assert b"qualification_eligible" in completed.stderr
        assert completed.stdout == b""
    finally:
        _set_cell(cell, original)


def test_validator_requires_matching_commit_and_tree_arguments() -> None:
    raw = canonical_json_bytes(_fixture_manifest())
    unbound = subprocess.run(
        [sys.executable, "-I", str(_VALIDATOR_SCRIPT)],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert unbound.returncode == 2
    assert b"exact code identity arguments are required" in unbound.stderr
    assert unbound.stdout == b""

    wrong_commit = _run_isolated_bytes(
        raw,
        expected_commit="0" * 40,
        expected_tree=_CODE_TREE_SHA,
    )
    assert wrong_commit.returncode == 2
    assert b"code commit SHA differs from expected identity" in wrong_commit.stderr
    assert wrong_commit.stdout == b""

    wrong_tree = _run_isolated_bytes(
        raw,
        expected_commit=_CODE_COMMIT_SHA,
        expected_tree="0" * 40,
    )
    assert wrong_tree.returncode == 2
    assert b"code tree SHA differs from expected identity" in wrong_tree.stderr
    assert wrong_tree.stdout == b""


def test_tracked_repository_code_is_rejected_before_materialization(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)

    profile_source = clone / "newsroom/increment5/profiles.py"
    profile_source.write_text(
        profile_source.read_text(encoding="utf-8")
        + "\nraise RuntimeError('dirty profile import executed')\n",
        encoding="utf-8",
    )
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 2
    assert completed.stderr == (
        b"increment5 profile validation failed: "
        b"tracked repository checkout differs from HEAD\n"
    )
    assert completed.stdout == b""


def test_ignored_bytecode_cannot_replace_materialized_validator_source(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    cache_tag = sys.implementation.cache_tag
    assert isinstance(cache_tag, str) and cache_tag

    for relative in (
        "newsroom/authority/canonical.py",
        "newsroom/increment5/profiles.py",
    ):
        source = clone / relative
        cache = source.parent / "__pycache__" / (
            f"{source.stem}.{cache_tag}.pyc"
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        poison = tmp_path / f"poison-{source.stem}.py"
        poison.write_text(
            "raise RuntimeError('ignored checkout bytecode executed')\n",
            encoding="utf-8",
        )
        py_compile.compile(
            str(poison),
            cfile=str(cache),
            dfile=str(source),
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )

    assert _git_text(
        clone,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    ) == ""
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert b"ignored checkout bytecode executed" not in completed.stderr
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt["code_commit_sha"] == clone_commit
    assert receipt["code_tree_sha"] == clone_tree
    assert receipt["validation_code_origin"] == "CACHE_FREE_EXACT_GIT_ARCHIVE"
    assert receipt["worktree_imports_used"] is False


def test_validator_materializes_exact_tree_before_repository_import() -> None:
    source = _VALIDATOR_SCRIPT.read_text(encoding="utf-8")
    main_source = source.split("def main() -> int:", 1)[1]
    assert main_source.index("_require_exact_code_tree(") < main_source.index(
        "_materialized_repository_api("
    )
    materialized_source = source.split(
        "def _materialized_repository_api(",
        1,
    )[1]
    assert materialized_source.index("_write_git_archive(") < (
        materialized_source.index(
            'importlib.import_module("newsroom.authority.canonical")'
        )
    )
    assert '"--untracked-files=no"' in source
    assert '"--untracked-files=all"' not in source


def test_isolated_validator_rejects_noncanonical_and_duplicate_json() -> None:
    valid = _fixture_manifest()
    pretty = json.dumps(valid, indent=2, sort_keys=True).encode("utf-8")
    completed = _run_isolated_bytes(pretty)
    assert completed.returncode == 2
    assert b"input is not canonical JSON" in completed.stderr

    duplicate = b'{"profile_kind":"FIXTURE_REPLAY","profile_kind":"FIXTURE_REPLAY"}'
    completed = _run_isolated_bytes(duplicate)
    assert completed.returncode == 2
    assert b"duplicate JSON object name" in completed.stderr
