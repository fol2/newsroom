from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pickle
import re
import sqlite3
import stat
import uuid
from pathlib import Path
from typing import Any

import pytest

_FORMAT = "newsroom.feedback-conformance-cache.v1"
_STORE = "test_increment6f2_feedback_store.py"
_CACHE_TEST = "test_increment6f2_feedback_cache.py"
_PROBE = "test_real_feedback_store_passes_required_conformance_probe"
_KEYS = (
    ("record-1",),
    ("record-1", "record-2"),
    ("record-a", "record-b"),
    ("record-rollback-normal", "record-rollback-abort"),
)
_RUN_UID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SENTINEL = Path("/__newsroom_feedback_cache__/retrieval.sqlite3")


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _safe_directory(path: Path, *, create: bool = False) -> None:
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
        raise ValueError(f"unsafe feedback cache directory: {path.name}")


def _safe_file(path: Path) -> os.stat_result:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ValueError(f"unsafe feedback cache file: {path.name}")
    return metadata


def _atomic_write(path: Path, payload: bytes) -> None:
    stage = path.with_name(f"{path.name}.{uuid.uuid4().hex}.stage")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(stage, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.replace(stage, path)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _deepcopy(value: object) -> object:
    return pickle.loads(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))


def _selected(config: pytest.Config) -> bool:
    return any(
        _STORE in os.fspath(argument) or _CACHE_TEST in os.fspath(argument)
        for argument in config.invocation_params.args
    )


def _selected_keys(arguments: tuple[str, ...], feedback: Any):
    probes = {probe.probe_id: probe for probe in feedback._CONFORMANCE_PROBES}
    selected: set[tuple[str, ...]] = set()
    conservative = False
    found = False
    for argument in arguments:
        if _CACHE_TEST in argument:
            found = True
            selected.add(("record-1",))
        if _STORE not in argument:
            continue
        found = True
        tail = argument.split(_STORE, 1)[1]
        if not tail.startswith("::"):
            conservative = True
            continue
        node = tail[2:]
        if not node.startswith(_PROBE):
            selected.add(("record-1",))
            continue
        suffix = node[len(_PROBE) :]
        if not suffix:
            conservative = True
            continue
        if not suffix.startswith("[") or not suffix.endswith("]"):
            raise ValueError("unknown exact feedback conformance probe")
        probe = probes.get(suffix[1:-1])
        if probe is None:
            raise ValueError("unknown exact feedback conformance probe")
        selected.add(feedback._RECORDS_BY_CASE.get(probe.case, ("record-1",)))
    if not found:
        raise ValueError("feedback conformance selection missing")
    if conservative:
        return _KEYS
    ordered = tuple(key for key in _KEYS if key in selected)
    return ordered or (("record-1",),)


def _snapshot(location: Any) -> dict[str, object]:
    seed = location.candidate.seed
    connection = sqlite3.connect(seed[1], isolation_level=None)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    seed_tail = _deepcopy((seed[0], *seed[2:]))
    retrieval = seed_tail[0][1]
    source = retrieval._path
    if not isinstance(source, Path):
        raise ValueError("feedback retrieval source path")
    retrieval_bytes = source.read_bytes()
    retrieval._path = _SENTINEL
    return {
        "base": location.base,
        "competing": location.competing,
        "database_bytes": Path(seed[1]).read_bytes(),
        "fixtures": location.fixtures,
        "proof": location.proof,
        "retrieval_bytes": retrieval_bytes,
        "seed_tail": seed_tail,
    }


def _build(selected: tuple[tuple[str, ...], ...], feedback: Any, root: Path):
    feedback._LOCATION_SNAPSHOTS.clear()
    templates = {}
    for index, records in enumerate(selected):
        location = feedback._build_location(root / f"template-{index}", records)
        templates[records] = _snapshot(location)
    return {
        "format": _FORMAT,
        "template_keys": selected,
        "templates": templates,
    }


def _publish(root: Path, selected, feedback: Any, build_root: Path) -> None:
    bundle = pickle.dumps(
        _build(selected, feedback, build_root), protocol=pickle.HIGHEST_PROTOCOL
    )
    _atomic_write(root / "bundle.pickle", bundle)
    manifest = {
        "bundle_digest": _digest(bundle),
        "bundle_size": len(bundle),
        "format": _FORMAT,
        "template_keys": [list(key) for key in selected],
    }
    rendered = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode() + b"\n"
    _atomic_write(root / "manifest.json", rendered)


def _load(root: Path, selected):
    manifest_path = root / "manifest.json"
    bundle_path = root / "bundle.pickle"
    _safe_file(manifest_path)
    _safe_file(bundle_path)
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    canonical = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode() + b"\n"
    if raw != canonical or set(manifest) != {
        "bundle_digest",
        "bundle_size",
        "format",
        "template_keys",
    }:
        raise ValueError("feedback cache manifest differs")
    bundle = bundle_path.read_bytes()
    if (
        manifest["format"] != _FORMAT
        or manifest["template_keys"] != [list(key) for key in selected]
        or manifest["bundle_size"] != len(bundle)
        or manifest["bundle_digest"] != _digest(bundle)
    ):
        raise ValueError("feedback cache bundle identity differs")
    value = pickle.loads(bundle)
    if not isinstance(value, dict):
        raise ValueError("feedback cache bundle malformed")
    return value


def _authorizer(args: dict[str, object]) -> object:
    from newsroom.authority.auth import StaticAuthorizer

    registry = args["command_registry"]
    scopes = {item.required_scope for item in registry.definitions()} | {
        "authority.evaluation-feedback.reconcile"
    }
    return StaticAuthorizer(
        policy_version="feedback-test-v1",
        grants_by_principal={"editor": frozenset(scopes)},
    )


def _write_private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _install_clone(feedback: Any) -> None:
    from newsroom.tests import test_increment6e2_candidate_store as candidate_fixture

    def clone(snapshot: Any, root: Path) -> Any:
        root.mkdir(mode=0o700)
        database = root / "feedback-authority.sqlite3"
        _write_private(database, snapshot.database_bytes)
        seed_tail, fixtures, proof, base, competing = _deepcopy(
            (
                snapshot.seed_tail,
                snapshot.fixtures,
                snapshot.proof,
                snapshot.base,
                snapshot.competing,
            )
        )
        collaborators = seed_tail[0]
        retrieval = collaborators[1]
        source = retrieval._path
        if not isinstance(source, Path):
            raise ValueError("feedback retrieval template path")
        retrieval_path = root / "retrieval-context.sqlite3"
        _safe_file(source)
        _write_private(retrieval_path, source.read_bytes())
        retrieval._path = retrieval_path
        seed = (collaborators, database, *seed_tail[1:])
        candidate = candidate_fixture._Location(seed, root / "candidate-collisions")
        args = candidate_fixture._collaborators(seed)
        args["authorizer"] = _authorizer(args)
        return feedback._Location(candidate, args, fixtures, proof, base, competing)

    feedback._LocationSnapshot.clone = clone


def _install(value, selected, feedback: Any, hydrate_root: Path) -> None:
    if set(value) != {"format", "template_keys", "templates"}:
        raise ValueError("feedback cache fields differ")
    if value["format"] != _FORMAT or value["template_keys"] != selected:
        raise ValueError("feedback cache contract differs")
    templates = value["templates"]
    if not isinstance(templates, dict) or tuple(templates) != selected:
        raise ValueError("feedback cache templates differ")
    hydrate_root.mkdir(mode=0o700)
    feedback._LOCATION_SNAPSHOTS.clear()
    from newsroom.tests import test_increment6e2_candidate_store as candidate_fixture

    for index, records in enumerate(selected):
        template = templates[records]
        expected = {
            "base",
            "competing",
            "database_bytes",
            "fixtures",
            "proof",
            "retrieval_bytes",
            "seed_tail",
        }
        if not isinstance(template, dict) or set(template) != expected:
            raise ValueError("feedback cache template fields differ")
        if not isinstance(template["database_bytes"], bytes) or not isinstance(
            template["retrieval_bytes"], bytes
        ):
            raise ValueError("feedback cache template bytes differ")
        seed_tail = template["seed_tail"]
        if not isinstance(seed_tail, tuple) or not seed_tail:
            raise ValueError("feedback cache seed tail differs")
        retrieval = seed_tail[0][1]
        if retrieval._path != _SENTINEL:
            raise ValueError("feedback cache retrieval sentinel differs")
        hydrated = hydrate_root / f"retrieval-{index}.sqlite3"
        _write_private(hydrated, template["retrieval_bytes"])
        retrieval._path = hydrated
        seed = (
            seed_tail[0],
            hydrate_root / f"template-{index}.sqlite3",
            *seed_tail[1:],
        )
        args = candidate_fixture._collaborators(seed)
        args["authorizer"] = _authorizer(args)
        feedback._LOCATION_SNAPSHOTS[records] = feedback._LocationSnapshot(
            template["database_bytes"],
            seed_tail,
            args,
            template["fixtures"],
            template["proof"],
            template["base"],
            template["competing"],
        )
    _install_clone(feedback)


def _ensure(root: Path, run_uid: str, selected, feedback: Any, hydrate_root: Path):
    if _RUN_UID.fullmatch(run_uid) is None:
        raise ValueError("invalid feedback cache run uid")
    _safe_directory(root, create=True)
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
            raise ValueError("unsafe feedback cache lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if not (root / "manifest.json").exists():
            _publish(root, selected, feedback, root / f"build-{run_uid}")
        value = _load(root, selected)
    finally:
        os.close(descriptor)
    _install(value, selected, feedback, hydrate_root)


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if not _selected(config):
        return
    from newsroom.tests import test_increment6f2_feedback_store as feedback

    _install_clone(feedback)
    worker = getattr(config, "workerinput", None)
    if not isinstance(worker, dict) or not str(
        worker.get("workerid", "")
    ).startswith("gw"):
        return
    run_uid = worker.get("testrunuid")
    if not isinstance(run_uid, str) or _RUN_UID.fullmatch(run_uid) is None:
        raise pytest.UsageError("invalid xdist testrunuid for feedback cache")
    basetemp = config._tmp_path_factory.getbasetemp()
    selected = _selected_keys(
        tuple(os.fspath(item) for item in config.invocation_params.args), feedback
    )
    try:
        _ensure(
            basetemp.parent / f"newsroom-feedback-{run_uid}",
            run_uid,
            selected,
            feedback,
            basetemp / "feedback-hydrated",
        )
    except Exception as exc:
        raise pytest.UsageError(f"feedback shared cache invalid: {exc}") from exc
