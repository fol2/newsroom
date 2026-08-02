from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

import newsroom.increment5.github_attempts as github_attempts_module
import scripts.sdlc.increment5_github_admission as admission_bootstrap
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import Increment5ContractError
from newsroom.increment5.admission_anchors import (
    ADMISSION_SOURCE_BUNDLE_IDENTITY,
    ADMISSION_SOURCE_MANIFEST_DIGEST,
)
from scripts.sdlc.increment5_github_admission import AdmissionSourceError


_MANIFEST_SCHEMA = "newsroom.increment5.admission-source-manifest.v1"
_REQUIRED_REVIEWED_FILES = {
    "newsroom/increment5/approval.py",
    "newsroom/increment5/_approval_v1.py",
    "newsroom/increment5/admission_anchors.py",
    "newsroom/increment5/github_attempts.py",
    "newsroom/increment5/_github_attempts_v1.py",
    "newsroom/increment5/main_qualification.py",
    "newsroom/increment5/_main_qualification_v2.py",
    "scripts/sdlc/increment5_github_admission.py",
    "scripts/sdlc/_increment5_github_admission_impl.py",
    "scripts/sdlc/collection_binding.py",
}


def _git_blob(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324


def _write_fake_bundle(root: Path) -> tuple[Path, Path, str, str]:
    files = {
        relative: (relative + "\n").encode("utf-8")
        for relative in _REQUIRED_REVIEWED_FILES
    }
    for relative, payload in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    identities = {
        relative: _git_blob(payload)
        for relative, payload in files.items()
    }
    identity_inputs = {
        "schema_version": _MANIFEST_SCHEMA,
        "files": identities,
    }
    bundle_identity = digest_bytes(canonical_json_bytes(identity_inputs))
    manifest = {
        **identity_inputs,
        "source_bundle_identity": bundle_identity,
    }
    manifest_path = root / "scripts/sdlc/increment5_admission_source_v1.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    return (
        manifest_path,
        root / "scripts/sdlc/_increment5_github_admission_impl.py",
        digest_bytes(manifest_path.read_bytes()),
        bundle_identity,
    )


def test_reviewed_source_manifest_is_canonical_and_exact() -> None:
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "scripts/sdlc/increment5_admission_source_v1.json"
    )
    data = manifest_path.read_bytes()
    value = json.loads(data.decode("utf-8"))
    assert data == canonical_json_bytes(value)
    assert digest_bytes(data) == ADMISSION_SOURCE_MANIFEST_DIGEST
    assert value["source_bundle_identity"] == ADMISSION_SOURCE_BUNDLE_IDENTITY
    assert _REQUIRED_REVIEWED_FILES.issubset(value["files"])
    identity, verifier_digest = (
        github_attempts_module._verify_reviewed_source_bundle(
            manifest_path=manifest_path,
            expected_manifest_digest=ADMISSION_SOURCE_MANIFEST_DIGEST,
            expected_source_bundle_identity=ADMISSION_SOURCE_BUNDLE_IDENTITY,
            implementation_path=(
                Path(__file__).resolve().parents[2]
                / "scripts/sdlc/_increment5_github_admission_impl.py"
            ),
            repository_root=Path(__file__).resolve().parents[2],
        )
    )
    assert identity == ADMISSION_SOURCE_BUNDLE_IDENTITY
    assert verifier_digest == digest_bytes(
        (
            Path(__file__).resolve().parents[2]
            / "scripts/sdlc/_increment5_github_admission_impl.py"
        ).read_bytes()
    )


def test_parent_and_child_reject_changed_reviewed_source(tmp_path: Path) -> None:
    manifest, implementation, expected_digest, bundle_identity = (
        _write_fake_bundle(tmp_path)
    )
    parent_identity, _ = github_attempts_module._verify_reviewed_source_bundle(
        manifest_path=manifest,
        expected_manifest_digest=expected_digest,
        expected_source_bundle_identity=bundle_identity,
        implementation_path=implementation,
        repository_root=tmp_path,
    )
    child_files, child_identity = admission_bootstrap.validate_source_manifest(
        path=manifest,
        expected_digest=expected_digest,
        expected_source_bundle_identity=bundle_identity,
        repository_root=tmp_path,
    )
    assert parent_identity == child_identity == bundle_identity
    assert child_files["newsroom/increment5/github_attempts.py"]

    implementation.write_text("changed\n", encoding="utf-8")
    with pytest.raises(
        Increment5ContractError,
        match="reviewed admission source differs",
    ):
        github_attempts_module._verify_reviewed_source_bundle(
            manifest_path=manifest,
            expected_manifest_digest=expected_digest,
            expected_source_bundle_identity=bundle_identity,
            implementation_path=implementation,
            repository_root=tmp_path,
        )
    with pytest.raises(
        AdmissionSourceError,
        match="reviewed source differs",
    ):
        admission_bootstrap.validate_source_manifest(
            path=manifest,
            expected_digest=expected_digest,
            expected_source_bundle_identity=bundle_identity,
            repository_root=tmp_path,
        )


def test_child_verifies_source_before_repository_imports() -> None:
    source = inspect.getsource(admission_bootstrap.main)
    assert source.index("validate_source_manifest(") < source.index(
        "_install_synthetic_packages("
    )
    parent_source = inspect.getsource(github_attempts_module)
    assert "--expected-source-manifest-digest" in parent_source
    assert "--expected-source-bundle-identity" in parent_source
    assert "captured_verify_source_bundle" in parent_source
    assert "newsroom/increment5/github_attempts.py" in parent_source
    assert "newsroom/increment5/approval.py" in parent_source
