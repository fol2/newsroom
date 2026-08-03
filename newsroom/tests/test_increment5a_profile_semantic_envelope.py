from __future__ import annotations

import ctypes
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
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
_TRUSTED_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))


def _trusted_git() -> Path:
    seen: set[Path] = set()
    for candidate in _TRUSTED_GIT_CANDIDATES:
        try:
            path = candidate.resolve(strict=True)
        except OSError:
            continue
        if path in seen:
            continue
        seen.add(path)
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise AssertionError("trusted system Git is unavailable")


_TRUSTED_GIT = _trusted_git()


def _trusted_python() -> Path:
    seen: set[Path] = set()
    for candidate in (Path("/usr/bin/python3"), Path("/bin/python3")):
        try:
            path = candidate.resolve(strict=True)
        except OSError:
            continue
        if path in seen:
            continue
        seen.add(path)
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise AssertionError("trusted system Python is unavailable")


def _python_runtime_root(python: Path) -> Path:
    completed = subprocess.run(
        [
            str(python),
            "-I",
            "-S",
            "-c",
            "import sys; print(sys.base_prefix)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8"))
    return Path(
        completed.stdout.decode("utf-8", errors="strict").strip()
    ).resolve(strict=True)


_TRUSTED_PYTHON = _trusted_python()
_TRUSTED_PYTHON_ROOT = _python_runtime_root(_TRUSTED_PYTHON)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


_TRUSTED_GIT_DIGEST = _file_digest(_TRUSTED_GIT)
_TRUSTED_PYTHON_DIGEST = _file_digest(_TRUSTED_PYTHON)


def _git_command(root: Path, *arguments: str) -> list[str]:
    return [
        str(_TRUSTED_GIT),
        f"--git-dir={root / '.git'}",
        "--no-replace-objects",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.untrackedCache=false",
        *arguments,
    ]


def _git_bytes(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        _git_command(root, *arguments),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
        env={
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        },
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    return completed.stdout


def _git_text(root: Path, *arguments: str) -> str:
    return _git_bytes(root, *arguments).decode("ascii", errors="strict").strip()


def _code_identity(root: Path, commit: str = "HEAD") -> tuple[str, str]:
    resolved_commit = _git_text(root, "rev-parse", "--verify", f"{commit}^{{commit}}")
    resolved_tree = _git_text(
        root,
        "rev-parse",
        "--verify",
        f"{resolved_commit}^{{tree}}",
    )
    return resolved_commit, resolved_tree


def _validator_blob(root: Path, commit: str) -> bytes:
    return _git_bytes(
        root,
        "cat-file",
        "blob",
        f"{commit}:{_VALIDATOR_RELATIVE_PATH.as_posix()}",
    )


_CODE_COMMIT_SHA, _CODE_TREE_SHA = _code_identity(_REPOSITORY_ROOT)
_VALIDATOR_BLOB = _validator_blob(_REPOSITORY_ROOT, _CODE_COMMIT_SHA)
_VALIDATOR_BLOB_DIGEST = digest_bytes(_VALIDATOR_BLOB)


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


def _validator_environment(
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    environment = {
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONUTF8": "1",
    }
    if overrides:
        environment.update(overrides)
    return environment


def _run_isolated_bytes(
    raw: bytes,
    tmp_path: Path,
    *,
    root: Path = _REPOSITORY_ROOT,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
    expected_validator_digest: str | None = None,
    source: bytes | None = None,
    environment_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    actual_commit, actual_tree = _code_identity(root, expected_commit or "HEAD")
    expected_commit = expected_commit or actual_commit
    expected_tree = expected_tree or actual_tree
    source = source if source is not None else _validator_blob(root, expected_commit)
    expected_validator_digest = expected_validator_digest or digest_bytes(source)
    manifest_path = tmp_path / (
        "manifest-" + hashlib.sha256(raw + os.urandom(8)).hexdigest() + ".json"
    )
    manifest_path.write_bytes(raw)
    return subprocess.run(
        [
            str(_TRUSTED_PYTHON),
            "-I",
            "-S",
            "-",
            "--repository-root",
            str(root.resolve(strict=True)),
            "--manifest-path",
            str(manifest_path.resolve(strict=True)),
            "--expected-code-commit-sha",
            expected_commit,
            "--expected-code-tree-sha",
            expected_tree,
            "--expected-validator-blob-digest",
            expected_validator_digest,
        ],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=root,
        env=_validator_environment(environment_overrides),
        timeout=30,
    )


def _run_isolated(
    manifest: dict[str, Any],
    tmp_path: Path,
    **kwargs: object,
) -> subprocess.CompletedProcess[bytes]:
    return _run_isolated_bytes(
        canonical_json_bytes(manifest),
        tmp_path,
        **kwargs,
    )


def _clone_exact_head(destination: Path) -> tuple[Path, str, str]:
    clone = destination / "repo"
    completed = subprocess.run(
        [
            str(_TRUSTED_GIT),
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
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    completed = subprocess.run(
        [
            str(_TRUSTED_GIT),
            f"--git-dir={clone / '.git'}",
            f"--work-tree={clone}",
            "checkout",
            "--detach",
            _CODE_COMMIT_SHA,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    commit, tree = _code_identity(clone)
    assert (commit, tree) == (_CODE_COMMIT_SHA, _CODE_TREE_SHA)
    return clone, commit, tree


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


@pytest.mark.parametrize("builder", (_fixture_manifest, _qualification_manifest))
def test_exact_blob_process_returns_non_authoritative_receipt(
    builder: Callable[[], dict[str, Any]],
    tmp_path: Path,
) -> None:
    manifest = builder()
    completed = _run_isolated(manifest, tmp_path)

    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    raw_receipt = completed.stdout.rstrip(b"\n")
    receipt = json.loads(raw_receipt.decode("utf-8"))
    assert raw_receipt == canonical_json_bytes(receipt)
    expected_public = (
        "sha256:6783030456d1d4ba5744a70932ee2982c099a3cf324ad98e2d05413216d7d571"
        if manifest["profile_kind"] == "FIXTURE_REPLAY"
        else "sha256:5d48af523da006bec804893f0bd42b411a466ca29103a8dde8fc46db49ced354"
    )
    expected_structural = (
        "sha256:7c2e50d952109d834d944c120b8f9a5adcc59c6f39106430fa8728c5ad25c9a0"
        if manifest["profile_kind"] == "FIXTURE_REPLAY"
        else "sha256:7b055832c33f9d9bf25f3401fce936bba3a2310da8f272038de4f0625356685b"
    )
    assert receipt == {
        "authority_effect": "NONE",
        "executed_source_identity_attested": False,
        "git_executable_digest_observed": _TRUSTED_GIT_DIGEST,
        "git_executable_path_observed": str(_TRUSTED_GIT),
        "git_runtime_trust_attested": False,
        "inner_receipt_only": True,
        "manifest_digest": digest_bytes(canonical_json_bytes(manifest)),
        "outer_runtime_binding_required": True,
        "outer_signed_workflow_binding_required": True,
        "profile_kind": manifest["profile_kind"],
        "profile_public_schema_digest": expected_public,
        "profile_structural_schema_digest": expected_structural,
        "production_activation_authorized": False,
        "python_executable_digest_observed": _TRUSTED_PYTHON_DIGEST,
        "python_executable_path_observed": str(_TRUSTED_PYTHON),
        "python_runtime_root_observed": str(_TRUSTED_PYTHON_ROOT),
        "qualification_authority_granted": False,
        "reviewed_code_commit_sha": _CODE_COMMIT_SHA,
        "reviewed_code_tree_sha": _CODE_TREE_SHA,
        "reviewed_contract_digest": (
            "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c"
        ),
        "reviewed_validator_blob_digest": _VALIDATOR_BLOB_DIGEST,
        "runtime_closure_identity_attested": False,
        "runtime_identity_claim_effect": "NONE",
        "schema_version": (
            "newsroom.increment5.profile-validation-inner-receipt.v6"
        ),
        "self_reported_isolated_no_site": True,
        "self_reported_repository_object_access": "EXACT_COMMIT_BLOBS_ONLY",
        "self_reported_third_party_import_paths_absent": True,
        "self_reported_validator_launch_mode": (
            "PYTHON_ISOLATED_NO_SITE_STDIN"
        ),
        "self_reported_worktree_or_index_used": False,
        "source_identity_claim_effect": "NONE",
        "validation_evidence_admissible": False,
        "validation_scope": "INNER_PROFILE_STRUCTURE_AND_SEMANTICS_ONLY",
    }


def test_modified_stdin_source_cannot_create_admissible_evidence(
    tmp_path: Path,
) -> None:
    marker_field = b'"modified_stdin_source_executed": True,\n            '
    modified_source = _VALIDATOR_BLOB.replace(
        b'            "authority_effect": "NONE",\n',
        b'            ' + marker_field + b'"authority_effect": "NONE",\n',
        1,
    )
    assert modified_source != _VALIDATOR_BLOB
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        tmp_path,
        source=modified_source,
        expected_validator_digest=_VALIDATOR_BLOB_DIGEST,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt["modified_stdin_source_executed"] is True
    assert receipt["executed_source_identity_attested"] is False
    assert receipt["runtime_closure_identity_attested"] is False
    assert receipt["outer_signed_workflow_binding_required"] is True
    assert receipt["outer_runtime_binding_required"] is True
    assert receipt["validation_evidence_admissible"] is False
    assert receipt["source_identity_claim_effect"] == "NONE"
    assert receipt["runtime_identity_claim_effect"] == "NONE"
    assert "validator_blob_digest" not in receipt
    assert "validator_source_origin" not in receipt
    assert "python_runtime_policy" not in receipt


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
                "production_substitution_allowed", True
            ),
            "fixture replay cannot substitute",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest.__setitem__("actual_neo4j_required", False),
            "qualification requires an actual Neo4j service",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest["dataset"].__setitem__(
                "rights_cleared", False
            ),
            "qualification dataset must be rights cleared",
        ),
        (
            _qualification_manifest,
            lambda manifest: manifest["runtime_effects"].__setitem__(
                "external_calls", 1
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
def test_isolated_stdlib_semantics_reject_mutations(
    builder: Callable[[], dict[str, Any]],
    mutate: Callable[[dict[str, Any]], None],
    message: str,
    tmp_path: Path,
) -> None:
    manifest = deepcopy(builder())
    mutate(manifest)
    completed = _run_isolated(manifest, tmp_path)
    assert completed.returncode == 2
    assert message.encode("utf-8") in completed.stderr
    assert completed.stdout == b""


def test_private_semantic_check_survives_json_schema_validator_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _qualification_manifest()
    manifest["runtime_effects"]["external_calls"] = 1
    monkeypatch.setattr(
        Draft202012Validator,
        "iter_errors",
        lambda self, instance: iter(()),
    )
    with pytest.raises(Increment5ProfileError, match="profile runtime effects differs"):
        profiles._check_profile_manifest(manifest)


def test_same_process_closure_mutation_cannot_cross_exact_blob_process(
    tmp_path: Path,
) -> None:
    manifest = _fixture_manifest()
    manifest["qualification_eligible"] = True
    cell, original = _closure_cell(profiles._check_profile_manifest, "check_snapshot")

    def bypass(snapshot: object, *, profile: object) -> None:
        return None

    try:
        _set_cell(cell, bypass)
        assert profiles._check_profile_manifest(manifest) is None
        completed = _run_isolated(manifest, tmp_path)
        assert completed.returncode == 2
        assert b"profile qualification eligibility differs" in completed.stderr
        assert completed.stdout == b""
    finally:
        _set_cell(cell, original)


def test_direct_checkout_execution_is_rejected(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(_fixture_manifest()))
    completed = subprocess.run(
        [
            str(_TRUSTED_PYTHON),
            "-I",
            "-S",
            str(_REPOSITORY_ROOT / _VALIDATOR_RELATIVE_PATH),
            "--repository-root",
            str(_REPOSITORY_ROOT),
            "--manifest-path",
            str(manifest_path),
            "--expected-code-commit-sha",
            _CODE_COMMIT_SHA,
            "--expected-code-tree-sha",
            _CODE_TREE_SHA,
            "--expected-validator-blob-digest",
            _VALIDATOR_BLOB_DIGEST,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert completed.returncode == 2
    assert b"must execute from an exact Git blob" in completed.stderr
    assert completed.stdout == b""


def test_exact_identity_and_validator_digest_are_required(tmp_path: Path) -> None:
    raw = canonical_json_bytes(_fixture_manifest())
    wrong_tree = _run_isolated_bytes(
        raw,
        tmp_path,
        expected_tree="0" * 40,
    )
    assert wrong_tree.returncode == 2
    assert b"code tree SHA differs from expected identity" in wrong_tree.stderr

    wrong_validator = _run_isolated_bytes(
        raw,
        tmp_path,
        expected_validator_digest="sha256:" + "0" * 64,
    )
    assert wrong_validator.returncode == 2
    assert b"validator blob digest differs from expected identity" in (
        wrong_validator.stderr
    )


@pytest.mark.parametrize("index_flag", ("--assume-unchanged", "--skip-worktree"))
def test_hidden_checkout_validator_mutation_cannot_execute(
    index_flag: str,
    tmp_path: Path,
) -> None:
    clone, commit, tree = _clone_exact_head(tmp_path)
    validator_path = clone / _VALIDATOR_RELATIVE_PATH
    marker = tmp_path / (index_flag.removeprefix("--") + "-executed")
    completed = subprocess.run(
        [
            str(_TRUSTED_GIT),
            f"--git-dir={clone / '.git'}",
            f"--work-tree={clone}",
            "update-index",
            index_flag,
            _VALIDATOR_RELATIVE_PATH.as_posix(),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    validator_path.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )

    completed = _run_isolated(
        _fixture_manifest(),
        tmp_path,
        root=clone,
        expected_commit=commit,
        expected_tree=tree,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert not marker.exists()
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt["reviewed_validator_blob_digest"] == digest_bytes(
        _validator_blob(clone, commit)
    )
    assert receipt["executed_source_identity_attested"] is False
    assert receipt["outer_signed_workflow_binding_required"] is True
    assert receipt["validation_evidence_admissible"] is False
    assert receipt["self_reported_worktree_or_index_used"] is False


def test_hostile_site_packages_and_pythonpath_are_not_loaded(tmp_path: Path) -> None:
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    site_marker = tmp_path / "sitecustomize-loaded"
    schema_marker = tmp_path / "jsonschema-loaded"
    (hostile / "sitecustomize.py").write_text(
        f"open({str(site_marker)!r}, 'w').write('loaded')\n",
        encoding="utf-8",
    )
    (hostile / "jsonschema.py").write_text(
        f"open({str(schema_marker)!r}, 'w').write('loaded')\n",
        encoding="utf-8",
    )
    completed = _run_isolated(
        _qualification_manifest(),
        tmp_path,
        environment_overrides={
            "PYTHONPATH": str(hostile),
            "PYTHONSTARTUP": str(hostile / "sitecustomize.py"),
        },
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert not site_marker.exists()
    assert not schema_marker.exists()
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt["self_reported_isolated_no_site"] is True
    assert receipt["self_reported_third_party_import_paths_absent"] is True
    assert receipt["runtime_closure_identity_attested"] is False
    assert receipt["validation_evidence_admissible"] is False


def test_caller_path_cannot_replace_git(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "fake-git-invoked"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        f"printf invoked > {marker!s}\n"
        "exit 97\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    completed = _run_isolated(
        _fixture_manifest(),
        tmp_path,
        environment_overrides={"PATH": str(fake_bin)},
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert not marker.exists()
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt["git_executable_path_observed"] == str(_TRUSTED_GIT)
    assert receipt["git_executable_digest_observed"] == _TRUSTED_GIT_DIGEST
    assert receipt["git_runtime_trust_attested"] is False
    assert receipt["outer_runtime_binding_required"] is True


def test_git_blob_reader_enforces_cap_before_retaining_overflow() -> None:
    namespace: dict[str, object] = {
        "__name__": "increment5_profile_validator_test",
    }
    exec(compile(_VALIDATOR_BLOB, "<exact-validator-blob>", "exec"), namespace)
    error_type = namespace["ProfileInputError"]
    read_output = namespace["_read_git_output"]
    trusted_git = namespace["_trusted_git"]
    git, _ = trusted_git(_REPOSITORY_ROOT)  # type: ignore[operator]
    with pytest.raises(error_type, match="exceeds the byte limit"):  # type: ignore[arg-type]
        read_output(  # type: ignore[operator]
            git,
            _REPOSITORY_ROOT,
            (
                "cat-file",
                "blob",
                f"{_CODE_COMMIT_SHA}:{_VALIDATOR_RELATIVE_PATH.as_posix()}",
            ),
            maximum_bytes=1_024,
            label="bounded validator blob",
        )


def test_validator_source_has_no_checkout_or_third_party_validation_path() -> None:
    source = _VALIDATOR_BLOB.decode("utf-8", errors="strict")
    assert "from jsonschema" not in source
    assert "import jsonschema" not in source
    assert "import newsroom" not in source
    assert "Draft202012Validator" not in source
    assert "git status" not in source
    assert "update-index" not in source
    assert "tarfile" not in source
    assert "git archive" not in source
    assert "cat-file" in source
    assert "EXACT_COMMIT_BLOBS_ONLY" in source
    assert "PYTHON_ISOLATED_NO_SITE_STDIN" in source
    assert 'sys.argv[0] != "-"' in source
    assert "validation_evidence_admissible" in source
    assert "executed_source_identity_attested" in source
    assert "runtime_closure_identity_attested" in source
    assert "outer_signed_workflow_binding_required" in source
    assert '"validator_source_origin"' not in source
    assert '"validator_blob_digest"' not in source
    assert '"python_runtime_policy"' not in source


def test_isolated_validator_rejects_noncanonical_and_duplicate_json(
    tmp_path: Path,
) -> None:
    pretty = json.dumps(_fixture_manifest(), indent=2, sort_keys=True).encode("utf-8")
    completed = _run_isolated_bytes(pretty, tmp_path)
    assert completed.returncode == 2
    assert b"profile manifest is not canonical JSON" in completed.stderr

    duplicate = b'{"profile_kind":"FIXTURE_REPLAY","profile_kind":"FIXTURE_REPLAY"}'
    completed = _run_isolated_bytes(duplicate, tmp_path)
    assert completed.returncode == 2
    assert b"duplicate JSON object name" in completed.stderr
