from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pickle
import re
import stat
import uuid
from pathlib import Path

import pytest

collect_ignore_glob = ["_archive/*"]


@pytest.fixture(autouse=True)
def _grok_command_version_is_not_a_live_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "newsroom.control_plane.writer.read_grok_command_semantic_version",
        lambda: "1.0.8",
    )
    monkeypatch.setattr(
        "newsroom.control_plane.cont_calibration.read_grok_command_semantic_version",
        lambda: "1.0.8",
    )

_D3_CACHE_FORMAT = "newsroom.d3-conformance-cache.v2"
_D3_CACHE_CAPACITY = 6
_D3_CACHE_TEMPLATE_KEYS = (
    ("record-1",),
    ("record-1", "record-2"),
    ("record-1", "record-b"),
    ("record-a", "record-b"),
    ("record-rollback-normal", "record-rollback-abort"),
)
_D3_MODULE = "test_increment6d3_lineage_store.py"
_RUN_UID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def _validated_template_keys(
    template_keys: object,
) -> tuple[tuple[str, ...], ...]:
    if not isinstance(template_keys, tuple) or not template_keys:
        raise ValueError("d3 cache template subset")
    if any(not isinstance(key, tuple) for key in template_keys):
        raise ValueError("d3 cache template subset")
    expected = tuple(key for key in _D3_CACHE_TEMPLATE_KEYS if key in template_keys)
    if expected != template_keys or len(expected) != len(set(expected)):
        raise ValueError("d3 cache template subset")
    return expected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _validate_directory(path: Path, *, create: bool = False) -> None:
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError(f"unsafe d3 cache directory: {path.name}")


def _validate_regular(path: Path, *, mode: int = 0o600) -> os.stat_result:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise ValueError(f"unsafe d3 cache file: {path.name}")
    return metadata


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _artifact_tree(artifact: Path, *, normalise: bool) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in sorted(artifact.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise ValueError("unsafe d3 cache artifact")
        if stat.S_ISDIR(metadata.st_mode):
            if normalise:
                path.chmod(0o700)
            elif stat.S_IMODE(metadata.st_mode) != 0o700:
                raise ValueError("unsafe d3 cache artifact directory")
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("unsupported d3 cache artifact")
        if normalise:
            path.chmod(0o600)
        elif stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ValueError("unsafe d3 cache artifact file")
        files.append(path)
    return tuple(files)


def _write_staged(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _publish_d3_cache(
    root: Path,
    run_uid: str,
    d3,
    template_keys: tuple[tuple[str, ...], ...],
) -> None:
    token = uuid.uuid4().hex
    artifact = root / f"artifact-{run_uid}-{token}"
    artifact.mkdir(mode=0o700)
    bundle = d3._prepare_shared_conformance_cache(artifact, template_keys)
    artifact_files = _artifact_tree(artifact, normalise=True)

    bundle_stage = root / f"bundle-{token}.stage"
    bundle_path = root / "bundle.pickle"
    _write_staged(bundle_stage, pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL))
    os.replace(bundle_stage, bundle_path)

    file_paths = (*artifact_files, bundle_path)
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
        for path in sorted(file_paths)
    ]
    manifest = {
        "capacity": _D3_CACHE_CAPACITY,
        "files": files,
        "format": _D3_CACHE_FORMAT,
        "payload_root": artifact.name,
        "template_keys": [list(key) for key in template_keys],
    }
    rendered = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    manifest_stage = root / f"manifest-{token}.stage"
    _write_staged(manifest_stage, rendered)
    os.replace(manifest_stage, root / "manifest.json")
    _fsync_directory(root)


def _load_d3_cache(
    root: Path, expected_template_keys: tuple[tuple[str, ...], ...]
) -> object:
    selected = _validated_template_keys(expected_template_keys)
    manifest_path = root / "manifest.json"
    _validate_regular(manifest_path)
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or raw != (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    ):
        raise ValueError("non-canonical d3 cache manifest")
    if set(manifest) != {
        "capacity",
        "files",
        "format",
        "payload_root",
        "template_keys",
    }:
        raise ValueError("d3 cache manifest fields")
    if (
        manifest["format"] != _D3_CACHE_FORMAT
        or manifest["capacity"] != _D3_CACHE_CAPACITY
        or manifest["template_keys"] != [list(key) for key in selected]
    ):
        raise ValueError("d3 cache manifest contract")
    payload_name = manifest["payload_root"]
    if (
        not isinstance(payload_name, str)
        or not payload_name.startswith("artifact-")
        or Path(payload_name).name != payload_name
    ):
        raise ValueError("d3 cache payload root")
    artifact = root / payload_name
    _validate_directory(artifact)
    discovered = _artifact_tree(artifact, normalise=False)
    expected_paths = {path.relative_to(root).as_posix() for path in discovered}
    expected_paths.add("bundle.pickle")
    entries = manifest["files"]
    if not isinstance(entries, list) or len(entries) != len(expected_paths):
        raise ValueError("d3 cache file inventory")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
            raise ValueError("d3 cache file entry")
        relative = entry["path"]
        if (
            not isinstance(relative, str)
            or relative not in expected_paths
            or relative in seen
        ):
            raise ValueError("d3 cache file path")
        seen.add(relative)
        path = root / relative
        metadata = _validate_regular(path)
        if entry["size"] != metadata.st_size or entry["sha256"] != _sha256(path):
            raise ValueError("d3 cache file digest")
    if seen != expected_paths:
        raise ValueError("d3 cache files incomplete")
    return pickle.loads((root / "bundle.pickle").read_bytes())


def _ensure_d3_cache(
    root: Path,
    run_uid: str,
    d3,
    *,
    template_keys: tuple[tuple[str, ...], ...] = _D3_CACHE_TEMPLATE_KEYS,
    hydrate_root: Path | None = None,
) -> None:
    selected = _validated_template_keys(template_keys)
    if _RUN_UID.fullmatch(run_uid) is None:
        raise ValueError("invalid d3 cache run uid")
    _validate_directory(root, create=True)
    lock_path = root / "producer.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ValueError("unsafe d3 cache lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if not (root / "manifest.json").exists():
            _publish_d3_cache(root, run_uid, d3, selected)
        bundle = _load_d3_cache(root, selected)
    finally:
        os.close(descriptor)
    if hydrate_root is None:
        d3._install_shared_conformance_cache(bundle, expected_template_keys=selected)
    else:
        d3._install_shared_conformance_cache(
            bundle,
            expected_template_keys=selected,
            hydrate_root=hydrate_root,
        )


def _selected_for_d3_cache(config: pytest.Config) -> bool:
    worker = getattr(config, "workerinput", None)
    if not isinstance(worker, dict) or not str(worker.get("workerid", "")).startswith(
        "gw"
    ):
        return False
    return any(
        _D3_MODULE in os.fspath(argument) for argument in config.invocation_params.args
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if not _selected_for_d3_cache(config):
        return
    worker = config.workerinput
    run_uid = worker.get("testrunuid")
    if not isinstance(run_uid, str) or _RUN_UID.fullmatch(run_uid) is None:
        raise pytest.UsageError("invalid xdist testrunuid for d3 cache")
    basetemp = config._tmp_path_factory.getbasetemp()
    common_root = basetemp.parent
    from newsroom.tests import test_increment6d3_lineage_store as d3

    try:
        template_keys = d3._selected_shared_template_keys(
            tuple(os.fspath(argument) for argument in config.invocation_params.args)
        )
        _ensure_d3_cache(
            common_root / f"newsroom-d3-{run_uid}",
            run_uid,
            d3,
            template_keys=template_keys,
            hydrate_root=basetemp / "d3-hydrated",
        )
    except Exception as exc:
        raise pytest.UsageError(f"d3 shared cache invalid: {exc}") from exc
