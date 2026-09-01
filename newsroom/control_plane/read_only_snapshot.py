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


def _identity(path: Path) -> dict[str, object]:
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "name": path.name,
        "size": stat.st_size,
        # Nanosecond epoch values exceed the canonical JSON safe-integer range.
        "mtime_ns": str(stat.st_mtime_ns),
        "sha256": digest,
    }


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
    wal = Path(f"{resolved}-wal")
    shm = Path(f"{resolved}-shm")
    if wal.exists() != shm.exists():
        raise ReadOnlySnapshotError(
            f"store has an incomplete WAL sidecar pair: {resolved}"
        )
    source_paths = (resolved, wal, shm) if wal.exists() else (resolved,)
    before = tuple(_identity(item) for item in source_paths)
    with tempfile.TemporaryDirectory(prefix="newsroom-readonly-") as scratch:
        copied = Path(scratch) / resolved.name
        copied_paths = tuple(
            Path(f"{copied}{suffix}") for suffix in ("", "-wal", "-shm")
        ) if wal.exists() else (copied,)
        for source, destination in zip(source_paths, copied_paths, strict=True):
            shutil.copy2(source, destination)
        copied_identities = tuple(_identity(item) for item in copied_paths)
        after = tuple(_identity(item) for item in source_paths)
        if after != before:
            raise ReadOnlySnapshotError(
                f"store changed while taking a read-only snapshot: {resolved}"
            )
        uri = f"{copied.as_uri()}?mode=ro"
        if not wal.exists():
            uri += "&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        try:
            apply_control_plane_sqlite_profile(connection, query_only=True, wal=False)
            yield ReadOnlySnapshot(
                connection=connection,
                source_path=str(resolved),
                source_files=before,
                snapshot_files=copied_identities,
            )
        finally:
            connection.close()
