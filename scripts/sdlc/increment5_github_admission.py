from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import sys
import types
from typing import Any, Mapping


_SOURCE_MANIFEST_SCHEMA = (
    "newsroom.increment5.admission-source-manifest.v1"
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_MANIFEST_PATH = (
    Path(__file__).resolve().parent
    / "increment5_admission_source_v1.json"
)
_IMPLEMENTATION_PATH = (
    Path(__file__).resolve().parent
    / "_increment5_github_admission_impl.py"
)
_IMPLEMENTATION_RELATIVE_PATH = (
    "scripts/sdlc/_increment5_github_admission_impl.py"
)
_BOOTSTRAP_RELATIVE_PATH = "scripts/sdlc/increment5_github_admission.py"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_BLOB = re.compile(r"[0-9a-f]{40}")
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_SOURCE_FILES = 96
_REQUIRED_REVIEWED_PATHS = frozenset(
    {
        "newsroom/increment5/approval.py",
        "newsroom/increment5/_approval_v1.py",
        "newsroom/increment5/admission_anchors.py",
        "newsroom/increment5/github_attempts.py",
        "newsroom/increment5/_github_attempts_v1.py",
        "newsroom/increment5/main_qualification.py",
        "newsroom/increment5/_main_qualification_v2.py",
        _BOOTSTRAP_RELATIVE_PATH,
        _IMPLEMENTATION_RELATIVE_PATH,
        "scripts/sdlc/collection_binding.py",
    }
)


class AdmissionSourceError(ValueError):
    """Raised when the reviewed admission source bundle is not exact."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 - Git object ID


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionSourceError("source manifest has duplicate names")
        result[key] = value
    return result


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdmissionSourceError(f"{field} must be an object")
    return value


def _safe_source_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise AdmissionSourceError("source manifest path is invalid")
    lexical = PurePosixPath(relative)
    if lexical.is_absolute() or any(
        part in {"", ".", ".."} for part in lexical.parts
    ):
        raise AdmissionSourceError("source manifest path escapes repository")
    current = root
    for part in lexical.parts:
        current /= part
        if current.is_symlink():
            raise AdmissionSourceError("source manifest path is symlinked")
    resolved = current.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise AdmissionSourceError("source manifest file is unavailable")
    return resolved


def validate_source_manifest(
    *,
    path: Path,
    expected_digest: str,
    expected_source_bundle_identity: str,
    repository_root: Path = _REPOSITORY_ROOT,
) -> tuple[dict[str, str], str]:
    root = repository_root.resolve()
    for value, label in (
        (expected_digest, "expected source manifest digest"),
        (expected_source_bundle_identity, "expected source bundle identity"),
    ):
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise AdmissionSourceError(f"{label} is invalid")
    if path.resolve() != (
        root / "scripts/sdlc/increment5_admission_source_v1.json"
    ):
        raise AdmissionSourceError("source manifest path is not fixed")
    if path.is_symlink() or not path.is_file():
        raise AdmissionSourceError("source manifest is unavailable")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AdmissionSourceError("source manifest is unreadable") from exc
    if not 0 < len(data) <= _MAX_MANIFEST_BYTES:
        raise AdmissionSourceError("source manifest size is invalid")
    if _sha256(data) != expected_digest:
        raise AdmissionSourceError("source manifest digest differs")
    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeError, json.JSONDecodeError, AdmissionSourceError) as exc:
        raise AdmissionSourceError("source manifest is invalid JSON") from exc
    if data != _canonical_json_bytes(value):
        raise AdmissionSourceError("source manifest is not canonical JSON")
    manifest = _mapping(value, field="source_manifest")
    if set(manifest) != {"schema_version", "source_bundle_identity", "files"}:
        raise AdmissionSourceError("source manifest shape differs")
    if manifest.get("schema_version") != _SOURCE_MANIFEST_SCHEMA:
        raise AdmissionSourceError("source manifest version differs")
    files_value = _mapping(
        manifest.get("files"),
        field="source_manifest.files",
    )
    if not 0 < len(files_value) <= _MAX_SOURCE_FILES:
        raise AdmissionSourceError("source manifest inventory size differs")
    files: dict[str, str] = {}
    for relative, expected_blob in files_value.items():
        if not isinstance(relative, str):
            raise AdmissionSourceError("source manifest path is invalid")
        if (
            not isinstance(expected_blob, str)
            or _GIT_BLOB.fullmatch(expected_blob) is None
        ):
            raise AdmissionSourceError(
                "source manifest blob identity is invalid"
            )
        files[relative] = expected_blob
    if not _REQUIRED_REVIEWED_PATHS.issubset(files):
        raise AdmissionSourceError("source manifest lacks authority sources")
    expected_identity = _sha256(
        _canonical_json_bytes(
            {
                "schema_version": _SOURCE_MANIFEST_SCHEMA,
                "files": files,
            }
        )
    )
    if (
        manifest.get("source_bundle_identity") != expected_identity
        or expected_identity != expected_source_bundle_identity
    ):
        raise AdmissionSourceError("source bundle identity differs")
    for relative, expected_blob in files.items():
        source = _safe_source_path(root, relative)
        try:
            payload = source.read_bytes()
        except OSError as exc:
            raise AdmissionSourceError("reviewed source is unreadable") from exc
        if _git_blob_sha(payload) != expected_blob:
            raise AdmissionSourceError(
                f"reviewed source differs: {relative}"
            )
    return files, expected_identity


def _install_synthetic_packages(root: Path) -> None:
    packages = {
        "newsroom": root / "newsroom",
        "newsroom.authority": root / "newsroom" / "authority",
        "newsroom.increment5": root / "newsroom" / "increment5",
        "scripts": root / "scripts",
        "scripts.sdlc": root / "scripts" / "sdlc",
    }
    for name, path in packages.items():
        module = types.ModuleType(name)
        module.__path__ = [path.as_posix()]  # type: ignore[attr-defined]
        module.__package__ = name
        sys.modules[name] = module


def _load_implementation_for_import():
    spec = importlib.util.spec_from_file_location(
        "scripts.sdlc._increment5_github_admission_impl",
        _IMPLEMENTATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise AdmissionSourceError("admission implementation is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source-manifest-path", required=True)
    parser.add_argument("--expected-source-manifest-digest", required=True)
    parser.add_argument("--expected-source-bundle-identity", required=True)
    arguments, remaining = parser.parse_known_args(argv)
    try:
        validate_source_manifest(
            path=Path(arguments.source_manifest_path),
            expected_digest=arguments.expected_source_manifest_digest,
            expected_source_bundle_identity=(
                arguments.expected_source_bundle_identity
            ),
        )
    except AdmissionSourceError as exc:
        print(
            "EVIDENCE_MISMATCH:increment5-admission-source:" + str(exc),
            file=sys.stderr,
        )
        return 2
    _install_synthetic_packages(_REPOSITORY_ROOT)
    sys.argv = [_IMPLEMENTATION_PATH.as_posix(), *remaining]
    try:
        runpy.run_path(_IMPLEMENTATION_PATH, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

_implementation = _load_implementation_for_import()
validate_authenticated_decision_artifact = (
    _implementation.validate_authenticated_decision_artifact
)
