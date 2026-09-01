"""Immutable SQLite snapshots for operational evidence readers."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile


class ReadOnlySnapshotError(RuntimeError):
    """A stable read-only snapshot could not be established."""


def _stat_identity(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "name": path.name,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        # Nanosecond epoch values exceed the canonical JSON safe-integer range.
        "mtime_ns": str(stat.st_mtime_ns),
    }


def _copy_with_digest(source: Path, destination: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as source_handle, destination.open("xb") as output:
        while chunk := source_handle.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    shutil.copystat(source, destination)
    return digest.hexdigest()


def _source_paths(database: Path) -> tuple[Path, ...]:
    wal = Path(f"{database}-wal")
    shm = Path(f"{database}-shm")
    if wal.exists() != shm.exists():
        raise ReadOnlySnapshotError(
            f"store has an incomplete WAL sidecar pair: {database}"
        )
    return (database, wal, shm) if wal.exists() else (database,)


@dataclass(frozen=True, slots=True)
class ReadOnlySnapshot:
    connection: sqlite3.Connection
    source_path: str
    source_files: tuple[dict[str, object], ...]
    snapshot_files: tuple[dict[str, object], ...]


@contextmanager
def read_only_snapshot(path: str | Path) -> Iterator[ReadOnlySnapshot]:
    """Copy a WAL store, verify source invariance, and expose query-only SQLite."""

    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ReadOnlySnapshotError(f"store does not exist: {resolved}")
    source_paths = _source_paths(resolved)
    has_wal = len(source_paths) == 3
    before = tuple(_stat_identity(item) for item in source_paths)
    with tempfile.TemporaryDirectory(prefix="newsroom-readonly-") as scratch:
        copied = Path(scratch) / resolved.name
        copied_paths = tuple(
            Path(f"{copied}{suffix}") for suffix in ("", "-wal", "-shm")
        ) if has_wal else (copied,)
        digests = tuple(
            _copy_with_digest(source, destination)
            for source, destination in zip(source_paths, copied_paths, strict=True)
        )
        copied_identities = tuple(
            {
                "name": destination.name,
                "size": destination.stat().st_size,
                "sha256": digest,
            }
            for destination, digest in zip(copied_paths, digests, strict=True)
        )
        current_paths = _source_paths(resolved)
        if (
            current_paths != source_paths
            or tuple(_stat_identity(item) for item in current_paths) != before
        ):
            raise ReadOnlySnapshotError(
                f"store changed while taking a read-only snapshot: {resolved}"
            )
        uri = f"{copied.as_uri()}?mode=ro"
        if not has_wal:
            uri += "&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        try:
            apply_control_plane_sqlite_profile(connection, query_only=True, wal=False)
            yield ReadOnlySnapshot(
                connection=connection,
                source_path=str(resolved),
                source_files=tuple(
                    {**identity, "sha256": digest}
                    for identity, digest in zip(before, digests, strict=True)
                ),
                snapshot_files=copied_identities,
            )
        finally:
            connection.close()
            current_paths = _source_paths(resolved)
            if (
                current_paths != source_paths
                or tuple(_stat_identity(item) for item in current_paths) != before
            ):
                raise ReadOnlySnapshotError(
                    f"store changed while reading its snapshot: {resolved}"
                )
