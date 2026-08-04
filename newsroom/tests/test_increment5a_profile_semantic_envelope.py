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
import tempfile
import time
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
_TRUSTED_PYTHON = Path("/usr/bin/python3")
_TRUSTED_GIT = Path("/usr/bin/git")
_CONTRACT_RELATIVE_PATH = "newsroom/increment5/data/increment5a_retrieval_contract_v1.json"


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


def _trusted_git_environment(root: Path) -> dict[str, str]:
    git_dir = root / ".git"
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_DIR": str(git_dir),
        "GIT_INDEX_FILE": str(git_dir / "index"),
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_WORK_TREE": str(root),
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _trusted_git_command(root: Path, *arguments: str) -> list[str]:
    return [
        str(_TRUSTED_GIT),
        f"--git-dir={root / '.git'}",
        f"--work-tree={root}",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        *arguments,
    ]


def _exact_validator_source(root: Path, commit: str) -> tuple[str, bytes]:
    environment = _trusted_git_environment(root)
    resolved = subprocess.run(
        _trusted_git_command(
            root,
            "rev-parse",
            "--verify",
            f"{commit}:{_VALIDATOR_RELATIVE_PATH.as_posix()}",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=environment,
        timeout=20,
    )
    assert resolved.returncode == 0, resolved.stderr.decode("utf-8")
    blob = resolved.stdout.decode("ascii", errors="strict").strip()
    assert len(blob) == 40
    read = subprocess.run(
        _trusted_git_command(root, "cat-file", "blob", blob),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=environment,
        timeout=20,
    )
    assert read.returncode == 0, read.stderr.decode("utf-8")
    return blob, read.stdout


def _run_isolated_bytes(
    raw: bytes,
    *,
    root: Path = _REPOSITORY_ROOT,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
    expected_validator_blob: str | None = None,
    source_commit: str | None = None,
    environment: dict[str, str] | None = None,
    python_executable: Path = _TRUSTED_PYTHON,
) -> subprocess.CompletedProcess[bytes]:
    root = root.resolve(strict=True)
    actual_commit, actual_tree = _code_identity(root)
    expected_commit = expected_commit or actual_commit
    expected_tree = expected_tree or actual_tree
    source_commit = source_commit or actual_commit
    validator_blob, validator_source = _exact_validator_source(root, source_commit)
    expected_validator_blob = expected_validator_blob or validator_blob

    with tempfile.NamedTemporaryFile(mode="w+b") as manifest:
        manifest.write(raw)
        manifest.flush()
        os.fsync(manifest.fileno())
        manifest.seek(0)
        return subprocess.run(
            [
                str(python_executable),
                "-I",
                "-S",
                "-",
                "--repository-root",
                str(root),
                "--git-dir",
                str(root / ".git"),
                "--index-file",
                str(root / ".git/index"),
                "--manifest-fd",
                str(manifest.fileno()),
                "--expected-validator-blob-sha",
                expected_validator_blob,
                "--expected-code-commit-sha",
                expected_commit,
                "--expected-code-tree-sha",
                expected_tree,
            ],
            input=validator_source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            cwd=root,
            env=environment or _validator_environment(),
            pass_fds=(manifest.fileno(),),
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
        "executed_source_identity_attested": False,
        "external_python_packages_used": False,
        "manifest_digest": digest_bytes(canonical_json_bytes(manifest)),
        "outer_signed_workflow_binding_required": True,
        "production_activation_authorized": False,
        "profile_kind": manifest["profile_kind"],
        "python_runtime_executable": "/usr/bin/python3",
        "python_runtime_origin": "ROOT_OWNED_SYSTEM_PYTHON_NO_SITE",
        "qualification_authority_granted": False,
        "schema_version": "newsroom.increment5.profile-validation-receipt.v7",
        "site_initialization_used": False,
        "checkout_snapshot_verified_before_receipt_write": True,
        "completion_time_checkout_state_attested": False,
        "validation_code_delivery": "EXACT_COMMIT_GIT_BLOB_STDIN",
        "validation_code_identity_claim_effect": "NONE",
        "validation_code_origin": "OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED",
        "validation_data_origin": "EXACT_REVIEWED_GIT_BLOBS",
        "validation_scope": (
            "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_PREWRITE_CODE_TREE_SNAPSHOT"
        ),
        "validator_blob_sha": _exact_validator_source(
            _REPOSITORY_ROOT, _CODE_COMMIT_SHA
        )[0],
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

        # The fixed root-owned -I -S runtime uses only stdlib plus exact
        # reviewed Git blobs and rejects the same bytes; the mutated cell cannot
        # cross that boundary.
        completed = _run_isolated(manifest)
        assert completed.returncode == 2
        assert completed.stderr.startswith(
            b"increment5 profile validation failed: "
        )
        assert b"profile qualification eligibility differs" in completed.stderr
        assert completed.stdout == b""
    finally:
        _set_cell(cell, original)





def test_nonisolated_execution_rejects_before_dependency_import(
    tmp_path: Path,
) -> None:
    fake_root = tmp_path / "pythonpath"
    fake_root.mkdir()
    marker = tmp_path / "fake-dependency-imported"
    fake_root.joinpath("sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n",
        encoding="utf-8",
    )
    _, source = _exact_validator_source(_REPOSITORY_ROOT, _CODE_COMMIT_SHA)
    environment = _validator_environment()
    environment["PYTHONPATH"] = str(fake_root)
    completed = subprocess.run(
        [str(_TRUSTED_PYTHON), "-S", "-"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 2
    assert b"signed outer Git-blob launcher" in completed.stderr
    assert completed.stdout == b""
    assert not marker.exists()


def test_isolated_mode_without_no_site_is_rejected() -> None:
    _, source = _exact_validator_source(_REPOSITORY_ROOT, _CODE_COMMIT_SHA)
    completed = subprocess.run(
        [str(_TRUSTED_PYTHON), "-I", "-"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert completed.returncode == 2
    assert b"signed outer Git-blob launcher" in completed.stderr
    assert completed.stdout == b""


def test_direct_worktree_path_is_not_an_admitted_launcher() -> None:
    completed = subprocess.run(
        [str(_TRUSTED_PYTHON), "-I", "-S", str(_VALIDATOR_SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert completed.returncode == 2
    assert b"signed outer Git-blob launcher" in completed.stderr
    assert completed.stdout == b""


def test_virtualenv_pth_executes_under_i_but_not_the_admitted_runtime(
    tmp_path: Path,
) -> None:
    import venv

    environment_root = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(environment_root)
    python = environment_root / "bin/python"
    purelib_result = subprocess.run(
        [python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert purelib_result.returncode == 0, purelib_result.stderr.decode("utf-8")
    purelib = Path(purelib_result.stdout.decode("utf-8").strip())
    marker = tmp_path / "pth-executed-before-validator"
    purelib.joinpath("increment5_attack.pth").write_text(
        "import pathlib; "
        f"pathlib.Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    _, source = _exact_validator_source(_REPOSITORY_ROOT, _CODE_COMMIT_SHA)
    vulnerable_shape = subprocess.run(
        [python, "-I", "-"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert vulnerable_shape.returncode == 2
    assert marker.read_text(encoding="utf-8") == "executed"
    marker.unlink()

    wrong_runtime = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        python_executable=python,
    )
    assert wrong_runtime.returncode == 2
    assert b"trusted system Python executable is required" in wrong_runtime.stderr
    assert wrong_runtime.stdout == b""
    assert not marker.exists()

    admitted = _run_isolated(_fixture_manifest())
    assert admitted.returncode == 0, admitted.stderr.decode("utf-8")
    assert not marker.exists()
    receipt = json.loads(admitted.stdout.decode("utf-8"))
    assert receipt["python_runtime_executable"] == "/usr/bin/python3"
    assert receipt["site_initialization_used"] is False
    assert receipt["external_python_packages_used"] is False


def test_validator_requires_matching_commit_tree_and_blob_arguments() -> None:
    raw = canonical_json_bytes(_fixture_manifest())
    _, source = _exact_validator_source(_REPOSITORY_ROOT, _CODE_COMMIT_SHA)
    unbound = subprocess.run(
        [str(_TRUSTED_PYTHON), "-I", "-S", "-"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert unbound.returncode == 2
    assert b"exact outer launch arguments are required" in unbound.stderr
    assert unbound.stdout == b""

    wrong_commit = _run_isolated_bytes(
        raw,
        expected_commit="0" * 40,
        expected_tree=_CODE_TREE_SHA,
    )
    assert wrong_commit.returncode == 2
    assert b"code commit SHA differs from expected identity" in wrong_commit.stderr

    wrong_tree = _run_isolated_bytes(
        raw,
        expected_commit=_CODE_COMMIT_SHA,
        expected_tree="0" * 40,
    )
    assert wrong_tree.returncode == 2
    assert b"code tree SHA differs from expected identity" in wrong_tree.stderr

    wrong_blob = _run_isolated_bytes(raw, expected_validator_blob="0" * 40)
    assert wrong_blob.returncode == 2
    assert b"validator blob SHA differs from expected identity" in wrong_blob.stderr


def test_dirty_worktree_validator_is_never_executed_by_admitted_launcher(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    marker = tmp_path / "dirty-validator-executed"
    source = clone / _VALIDATOR_RELATIVE_PATH
    source.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "print('fabricated receipt')\n",
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
    assert not marker.exists()


def test_path_selected_fake_git_is_never_used(tmp_path: Path) -> None:
    fake_directory = tmp_path / "fake-bin"
    fake_directory.mkdir()
    marker = tmp_path / "fake-git-invoked"
    fake_git = fake_directory / "git"
    fake_git.write_text(
        "#!/usr/bin/python3\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('invoked', encoding='utf-8')\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    environment = _validator_environment()
    environment["PATH"] = f"{fake_directory}:{environment['PATH']}"
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        environment=environment,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert not marker.exists()


def test_git_replace_ref_cannot_substitute_reviewed_contract_blob(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    original_blob = _git_text(clone, "rev-parse", f"HEAD:{_CONTRACT_RELATIVE_PATH}")
    hashed = subprocess.run(
        ["git", "-C", str(clone), "hash-object", "-w", "--stdin"],
        input=b'{"poison":true}',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert hashed.returncode == 0, hashed.stderr.decode("utf-8")
    replacement_blob = hashed.stdout.decode("ascii").strip()
    replaced = subprocess.run(
        ["git", "-C", str(clone), "replace", original_blob, replacement_blob],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert replaced.returncode == 0, replaced.stderr.decode("utf-8")
    ordinary = subprocess.run(
        ["git", "-C", str(clone), "cat-file", "blob", f"HEAD:{_CONTRACT_RELATIVE_PATH}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert ordinary.stdout == b'{"poison":true}'
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")


def test_core_worktree_cannot_redirect_cleanliness_check(tmp_path: Path) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    alternate = tmp_path / "alternate-worktree"
    alternate.mkdir()
    populated = subprocess.run(
        [
            "git",
            f"--git-dir={clone / '.git'}",
            f"--work-tree={alternate}",
            "checkout",
            "--force",
            clone_commit,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert populated.returncode == 0, populated.stderr.decode("utf-8")
    configured = subprocess.run(
        ["git", "-C", str(clone), "config", "core.worktree", str(alternate)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert configured.returncode == 0, configured.stderr.decode("utf-8")
    source = clone / "scripts/sdlc/increment5_profile_validator.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# hidden actual worktree drift\n")
    assert _git_text(clone, "status", "--porcelain=v1", "--untracked-files=no") == ""
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 2
    assert b"tracked repository checkout differs from HEAD" in completed.stderr


@pytest.mark.parametrize("flag", ("--assume-unchanged", "--skip-worktree"))
def test_index_flags_that_hide_changes_are_rejected(
    tmp_path: Path,
    flag: str,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    relative = "scripts/sdlc/increment5_profile_validator.py"
    marked = subprocess.run(
        ["git", "-C", str(clone), "update-index", flag, relative],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert marked.returncode == 0, marked.stderr.decode("utf-8")
    source = clone / relative
    source.write_text(source.read_text(encoding="utf-8") + "\n# index-hidden drift\n")
    assert _git_text(clone, "status", "--porcelain=v1", "--untracked-files=no") == ""
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 2
    assert completed.stderr == (
        b"increment5 profile validation failed: "
        b"tracked index flags can hide checkout changes\n"
    )
    assert completed.stdout == b""


def test_fsmonitor_hook_cannot_hide_tracked_checkout_change(tmp_path: Path) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    hook = tmp_path / "lying-fsmonitor-v2"
    hook.write_bytes(b"#!/bin/sh\nprintf 'unchanged-token\\000'\n")
    hook.chmod(0o755)
    for name, value in (("core.fsmonitor", str(hook)), ("core.fsmonitorHookVersion", "2")):
        configured = subprocess.run(
            ["git", "-C", str(clone), "config", name, value],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        assert configured.returncode == 0, configured.stderr.decode("utf-8")
    assert _git_text(clone, "status", "--porcelain=v1", "--untracked-files=no") == ""
    source = clone / "scripts/sdlc/increment5_profile_validator.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# fsmonitor-hidden drift\n")
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 2
    assert b"tracked repository checkout differs from HEAD" in completed.stderr


def test_local_stat_config_cannot_hide_same_size_restored_mtime_edit(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    relative = "newsroom/increment5/profiles.py"
    source = clone / relative
    original = source.read_bytes()
    baseline = source.stat()
    for name, value in (
        ("core.trustctime", "false"),
        ("core.checkStat", "minimal"),
        ("core.ignoreStat", "true"),
        ("core.fileMode", "false"),
    ):
        configured = subprocess.run(
            ["git", "-C", str(clone), "config", name, value],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        assert configured.returncode == 0, configured.stderr.decode("utf-8")
    refreshed = subprocess.run(
        ["git", "-C", str(clone), "update-index", "--refresh"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert refreshed.returncode == 0, refreshed.stderr.decode("utf-8")
    changed = bytearray(original)
    offset = next(index for index, value in enumerate(changed) if 65 <= value <= 90)
    changed[offset] = 90 if changed[offset] != 90 else 89
    source.write_bytes(changed)
    os.utime(source, ns=(baseline.st_atime_ns, baseline.st_mtime_ns))
    assert source.stat().st_size == baseline.st_size
    # Git releases differ in whether this adversarial stat configuration hides
    # the edit. The validator must reject the bytes independently either way.
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


def test_bounded_blob_reader_kills_an_overflowing_producer(tmp_path: Path) -> None:
    marker = tmp_path / "producer-completed"
    emitter = tmp_path / "emit.py"
    emitter.write_text(
        "from pathlib import Path\n"
        "import os, sys, time\n"
        "os.write(sys.stdout.fileno(), b'x' * 8192)\n"
        "time.sleep(10)\n"
        f"Path({str(marker)!r}).write_text('completed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    probe = """
import sys
from pathlib import Path
sys.argv[0] = "-"
source = Path(sys.argv[1]).read_bytes()
namespace = {"__name__": "validator-probe", "__file__": sys.argv[1]}
exec(compile(source, "-", "exec"), namespace)
error = namespace["ProfileInputError"]
try:
    namespace["_capture_bounded_process"](
        [sys.executable, sys.argv[2]], env={"LC_ALL":"C"},
        timeout_seconds=20, max_stdout_bytes=1024, max_stderr_bytes=1024,
        failure_message="bounded producer failed",
    )
except error:
    pass
else:
    raise SystemExit("overflowing producer unexpectedly succeeded")
"""
    completed = subprocess.run(
        [str(_TRUSTED_PYTHON), "-I", "-S", "-c", probe, str(_VALIDATOR_SCRIPT), str(emitter)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env={"LC_ALL": "C", "PYTHONUTF8": "1"},
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert not marker.exists()


def test_completion_state_recheck_suppresses_receipt(tmp_path: Path) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    output = tmp_path / "receipt.bin"
    probe = """
import io, sys
from pathlib import Path
sys.argv[0] = "-"
source = Path(sys.argv[1]).read_bytes()
namespace = {"__name__": "validator-completion-probe", "__file__": sys.argv[1]}
exec(compile(source, "-", "exec"), namespace)
runtime = namespace["_TrustedPythonRuntime"]()
root = Path(sys.argv[2])
view = namespace["_TrustedRepositoryView"](root, root / ".git", root / ".git/index")
view.require_stable_clean_tree(sys.argv[3], sys.argv[4])
tracked = Path(sys.argv[2]) / "scripts/sdlc/increment5_profile_validator.py"
tracked.write_text(tracked.read_text(encoding="utf-8") + "\\n# completion drift\\n", encoding="utf-8")
buffer = io.BytesIO()
try:
    blob = namespace["_git_sha"](
        view,
        f"{sys.argv[3]}:scripts/sdlc/increment5_profile_validator.py",
        "validator blob SHA",
    )
    namespace["_emit_receipt"](
        runtime, view, sys.argv[3], sys.argv[4], blob,
        {"authority_effect":"NONE"}, buffer
    )
except namespace["ProfileInputError"] as exc:
    if str(exc) != "tracked repository checkout differs from HEAD": raise
else:
    raise SystemExit("completion drift emitted a receipt")
if buffer.getvalue(): raise SystemExit("receipt bytes escaped")
"""
    completed = subprocess.run(
        [
            str(_TRUSTED_PYTHON), "-I", "-S", "-c", probe,
            str(clone / _VALIDATOR_RELATIVE_PATH), str(clone),
            clone_commit, clone_tree,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=clone,
        env={"LC_ALL": "C", "PYTHONUTF8": "1"},
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert not output.exists()


def test_receipt_handoff_does_not_attest_completion_time_checkout_state(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    probe = """
import io, json, sys
from pathlib import Path
sys.argv[0] = "-"
source = Path(sys.argv[1]).read_bytes()
namespace = {"__name__": "validator-handoff-probe", "__file__": sys.argv[1]}
exec(compile(source, "-", "exec"), namespace)
runtime = namespace["_TrustedPythonRuntime"]()
root = Path(sys.argv[2])
view = namespace["_TrustedRepositoryView"](root, root / ".git", root / ".git/index")
blob = namespace["_git_sha"](
    view,
    f"{sys.argv[3]}:scripts/sdlc/increment5_profile_validator.py",
    "validator blob SHA",
)
class MutatingOutput(io.BytesIO):
    def write(self, data):
        tracked = root / "scripts/sdlc/increment5_profile_validator.py"
        tracked.write_text(
            tracked.read_text(encoding="utf-8") + "\\n# changed during handoff\\n",
            encoding="utf-8",
        )
        return super().write(data)
output = MutatingOutput()
receipt = {
    "checkout_snapshot_verified_before_receipt_write": True,
    "completion_time_checkout_state_attested": False,
}
namespace["_emit_receipt"](
    runtime, view, sys.argv[3], sys.argv[4], blob, receipt, output
)
sys.stdout.buffer.write(output.getvalue())
"""
    completed = subprocess.run(
        [
            str(_TRUSTED_PYTHON),
            "-I",
            "-S",
            "-c",
            probe,
            str(clone / _VALIDATOR_RELATIVE_PATH),
            str(clone),
            clone_commit,
            clone_tree,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=clone,
        env={"LC_ALL": "C", "PYTHONUTF8": "1"},
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt == {
        "checkout_snapshot_verified_before_receipt_write": True,
        "completion_time_checkout_state_attested": False,
    }
    assert "tracked_checkout_clean" not in receipt
    assert (
        clone / "scripts/sdlc/increment5_profile_validator.py"
    ).read_text(encoding="utf-8").endswith("# changed during handoff\n")


def test_validator_source_has_closed_outer_launch_and_repository_boundaries() -> None:
    source = _VALIDATOR_SCRIPT.read_text(encoding="utf-8")
    bootstrap = source.index('or sys.argv[0] != "-"')
    assert source.index("import sys") < bootstrap < source.index("import hashlib")
    assert '_TRUSTED_PYTHON_EXECUTABLE = Path("/usr/bin/python3")' in source
    assert "ROOT_OWNED_SYSTEM_PYTHON_NO_SITE" in source
    assert '"site_initialization_used": False' in source
    assert "jsonschema" not in source
    assert "importlib" not in source
    assert "tarfile" not in source
    assert "tempfile" not in source
    assert 'f"--git-dir={self.git_dir}"' in source
    assert 'f"--work-tree={self.root}"' in source
    assert '"--no-replace-objects"' in source
    assert '"core.fsmonitor=false"' in source
    assert '"core.trustctime=true"' in source
    assert '"core.checkStat=default"' in source
    assert '"core.ignoreStat=false"' in source
    assert '"core.fileMode=true"' in source
    assert '"ls-tree"' in source
    assert '"ls-files",\n            "-s"' in source
    assert "hashlib.sha1(usedforsecurity=False)" in source
    assert '"status",' not in source
    assert '"GIT_NO_REPLACE_OBJECTS": "1"' in source
    assert "_reject_hidden_index_flags" in source
    assert "require_validator_blob" in source
    assert '"executed_source_identity_attested": False' in source
    assert '"outer_signed_workflow_binding_required": True' in source
    assert '"validation_code_delivery": "EXACT_COMMIT_GIT_BLOB_STDIN"' in source
    assert '"checkout_snapshot_verified_before_receipt_write": True' in source
    assert '"completion_time_checkout_state_attested": False' in source
    assert '"tracked_checkout_clean"' not in source
    main = source.split("def main() -> int:", 1)[1]
    assert main.index("repository.require_stable_clean_tree(") < main.index(
        "_load_reviewed_profile_data("
    )
    assert main.index("repository.require_validator_blob(") < main.index(
        "_read_manifest_descriptor("
    )
    emit = source.split("def _emit_receipt(", 1)[1].split("def main()", 1)[0]
    assert emit.index("runtime.require_unchanged()") < emit.index(
        "repository.require_stable_clean_tree("
    ) < emit.index("repository.require_validator_blob(") < emit.index(
        "output.write(raw)"
    ) < emit.index("output.flush()")


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


def test_reviewed_documents_bind_receipt_v7_snapshot_semantics() -> None:
    evaluation = (
        _REPOSITORY_ROOT
        / "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
    ).read_text(encoding="utf-8")
    decision = (
        _REPOSITORY_ROOT
        / "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
    ).read_text(encoding="utf-8")

    assert "Every profile-validation receipt is v7" in evaluation
    assert "Every profile-validation receipt is v5" not in evaluation
    assert "checkout_snapshot_verified_before_receipt_write=true" in evaluation
    assert "completion_time_checkout_state_attested=false" in evaluation
    assert "`tracked_checkout_clean` claim" in evaluation
    assert "does not attest mutable checkout" in evaluation
    assert "completion-time drift emits no receipt" not in decision
    assert "Drift detected during that final prewrite" in decision
    assert "after output handoff are explicitly not attested" in decision
