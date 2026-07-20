from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import BinaryIO
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Callable, Protocol

from .objects import (
    BlobIdentity,
    ObjectIntegrityError,
    ObjectLimitError,
    ObjectLimits,
)
from .types import UtcTimestamp


class _FaultHook(Protocol):
    def __call__(self, checkpoint: str) -> None:
        ...


@dataclass(slots=True)
class _StagedBlob:
    stage_id: str
    staged_name: str
    path: Path
    identity: BlobIdentity
    created_at: UtcTimestamp


@dataclass(slots=True)
class _PinnedBlob:
    fd: int
    path: Path
    identity: BlobIdentity
    installed_new: bool = False
    closed: bool = False

    def close(self) -> None:
        if not self.closed:
            os.close(self.fd)
            self.closed = True

    def __enter__(self) -> _PinnedBlob:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _GovernedCAS:
    """Bounded, same-filesystem content-addressed byte store.

    SQLite remains the source of authority.  This class implements durable byte
    installation and pinned-file verification; it never decides rights or use.
    """

    def __init__(
        self,
        root: Path,
        *,
        limits: ObjectLimits,
        clock: Callable[[], UtcTimestamp] = UtcTimestamp.now,
        fault_hook: _FaultHook | None = None,
        disk_usage: Callable[[Path], shutil._ntuple_diskusage] = shutil.disk_usage,
    ) -> None:
        self.root = Path(root)
        self.limits = limits
        self._clock = clock
        self._fault_hook = fault_hook or (lambda _checkpoint: None)
        self._disk_usage = disk_usage
        self.staging_root = self.root / "staging"
        self.objects_root = self.root / "objects"
        self._prepare_roots()

    def _fault(self, checkpoint: str) -> None:
        self._fault_hook(checkpoint)

    @staticmethod
    def _validate_owner_mode(path: Path, *, directory: bool) -> None:
        if path.is_symlink():
            raise ObjectIntegrityError(f"CAS path cannot be a symlink: {path}")
        info = path.stat()
        if directory and not stat.S_ISDIR(info.st_mode):
            raise ObjectIntegrityError(f"CAS path must be a directory: {path}")
        if not directory and not stat.S_ISREG(info.st_mode):
            raise ObjectIntegrityError(f"CAS path must be a regular file: {path}")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ObjectIntegrityError("CAS paths must be owned by the authority writer")
        if directory and stat.S_IMODE(info.st_mode) & 0o077:
            raise ObjectIntegrityError("CAS directories must not grant group/other access")

    @staticmethod
    def _directory_fd(path: Path) -> int:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        try:
            return os.open(path, flags)
        except OSError as exc:
            raise ObjectIntegrityError(
                f"cannot open CAS directory for durability: {path}"
            ) from exc

    def _fsync_directory(self, path: Path) -> None:
        self._fault("before_directory_fsync")
        descriptor = self._directory_fd(path)
        try:
            os.fsync(descriptor)
        except OSError as exc:
            raise ObjectIntegrityError(
                f"CAS directory fsync failed: {path}"
            ) from exc
        finally:
            os.close(descriptor)
        self._fault("after_directory_fsync")

    def _mkdir_durable(self, path: Path, *, parent: Path) -> None:
        if path.exists():
            self._validate_owner_mode(path, directory=True)
            return
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
        self._validate_owner_mode(path, directory=True)
        self._fsync_directory(parent)

    def _prepare_roots(self) -> None:
        parent = self.root.parent
        if self.root.exists():
            self._validate_owner_mode(self.root, directory=True)
        else:
            parent.mkdir(parents=True, exist_ok=True)
            if parent.is_symlink():
                raise ObjectIntegrityError("CAS parent cannot be a symlink")
            self.root.mkdir(mode=0o700)
            os.chmod(self.root, 0o700)
            self._validate_owner_mode(self.root, directory=True)
            self._fsync_directory(parent)
        self._mkdir_durable(self.staging_root, parent=self.root)
        self._mkdir_durable(self.objects_root, parent=self.root)
        # Persist both child directory entries.
        self._fsync_directory(self.root)

    def _check_disk_headroom(self, incoming_bytes: int) -> None:
        usage = self._disk_usage(self.root)
        if usage.free - incoming_bytes < self.limits.min_free_bytes:
            raise ObjectLimitError("CAS disk-headroom requirement is not met")

    @staticmethod
    def _chunks(source: bytes | bytearray | memoryview | BinaryIO | Iterable[bytes], chunk_size: int) -> Iterator[bytes]:
        if isinstance(source, (bytes, bytearray, memoryview)):
            data = bytes(source)
            for offset in range(0, len(data), chunk_size):
                yield data[offset : offset + chunk_size]
            return
        read = getattr(source, "read", None)
        if callable(read):
            while True:
                chunk = read(chunk_size)
                if chunk in (b"", None):
                    break
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise TypeError("object stream read() must return bytes")
                yield bytes(chunk)
            return
        if not isinstance(source, Iterable):
            raise TypeError("object source must be bytes, a binary stream, or byte chunks")
        for chunk in source:
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise TypeError("object source chunks must be bytes")
            data = bytes(chunk)
            if data:
                yield data

    def stage(
        self,
        source: bytes | bytearray | memoryview | BinaryIO | Iterable[bytes],
        *,
        object_class: str,
    ) -> _StagedBlob:
        maximum = self.limits.maximum_for(object_class)
        self._check_disk_headroom(min(maximum, self.limits.io_chunk_bytes))
        descriptor, raw_name = tempfile.mkstemp(
            prefix="stage-", suffix=".tmp", dir=self.staging_root
        )
        path = Path(raw_name)
        os.fchmod(descriptor, 0o600)
        hasher = hashlib.sha256()
        size = 0
        try:
            self._fault("before_stage_stream")
            for chunk in self._chunks(source, self.limits.io_chunk_bytes):
                new_size = size + len(chunk)
                if new_size > maximum or new_size > int(self.limits.max_staging_bytes):
                    raise ObjectLimitError("object exceeds bounded staging limit")
                self._check_disk_headroom(len(chunk))
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise ObjectIntegrityError("CAS staging write made no progress")
                    view = view[written:]
                hasher.update(chunk)
                size = new_size
                self._fault("after_stage_chunk")
            self.limits.require_object_size(object_class, size)
            self._fault("before_stage_file_fsync")
            os.fsync(descriptor)
            self._fault("after_stage_file_fsync")
        except Exception:
            try:
                os.close(descriptor)
            finally:
                path.unlink(missing_ok=True)
                self._fsync_directory(self.staging_root)
            raise
        os.close(descriptor)
        identity = BlobIdentity(
            blob_digest=f"sha256:{hasher.hexdigest()}", size_bytes=size
        )
        self._fsync_directory(self.staging_root)
        return _StagedBlob(
            stage_id=path.stem,
            staged_name=path.name,
            path=path,
            identity=identity,
            created_at=self._clock(),
        )

    def _object_directory(self, identity: BlobIdentity) -> Path:
        hex_digest = identity.blob_digest.split(":", 1)[1]
        return self.objects_root / hex_digest[:2]

    def object_path(self, identity: BlobIdentity) -> Path:
        hex_digest = identity.blob_digest.split(":", 1)[1]
        return self._object_directory(identity) / hex_digest

    @staticmethod
    def _open_read_only(path: Path) -> int:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        try:
            return os.open(path, flags)
        except OSError as exc:
            raise ObjectIntegrityError(f"cannot open installed blob: {path}") from exc

    @staticmethod
    def _hash_fd(fd: int, chunk_size: int) -> tuple[str, int]:
        os.lseek(fd, 0, os.SEEK_SET)
        hasher = hashlib.sha256()
        size = 0
        while True:
            data = os.read(fd, chunk_size)
            if not data:
                break
            hasher.update(data)
            size += len(data)
        os.lseek(fd, 0, os.SEEK_SET)
        return f"sha256:{hasher.hexdigest()}", size

    def verify_pinned(self, pinned: _PinnedBlob) -> None:
        if pinned.closed:
            raise ObjectIntegrityError("pinned blob is closed")
        self._fault("before_pinned_rehash")
        digest, size = self._hash_fd(pinned.fd, self.limits.io_chunk_bytes)
        info = os.fstat(pinned.fd)
        if not stat.S_ISREG(info.st_mode):
            raise ObjectIntegrityError("pinned blob is not a regular file")
        if info.st_nlink < 1:
            raise ObjectIntegrityError("pinned blob was unlinked before commit")
        if stat.S_IMODE(info.st_mode) & 0o222:
            raise ObjectIntegrityError("installed blob remains writable")
        if digest != pinned.identity.blob_digest or size != pinned.identity.size_bytes:
            raise ObjectIntegrityError("pinned blob digest or size changed")
        try:
            path_info = pinned.path.stat(follow_symlinks=False)
        except FileNotFoundError as exc:
            raise ObjectIntegrityError("installed blob path is missing") from exc
        if not stat.S_ISREG(path_info.st_mode) or (
            path_info.st_dev != info.st_dev or path_info.st_ino != info.st_ino
        ):
            raise ObjectIntegrityError("installed blob path no longer names pinned inode")
        self._fault("after_pinned_rehash")

    def install(self, staged: _StagedBlob) -> _PinnedBlob:
        if staged.path.parent != self.staging_root or staged.path.name != staged.staged_name:
            raise ObjectIntegrityError("staged object path escaped the CAS staging root")
        self._validate_owner_mode(staged.path, directory=False)
        directory = self._object_directory(staged.identity)
        self._mkdir_durable(directory, parent=self.objects_root)
        final_path = self.object_path(staged.identity)
        installed_new = False
        self._fault("before_atomic_install")
        try:
            try:
                os.link(staged.path, final_path, follow_symlinks=False)
                installed_new = True
            except FileExistsError:
                installed_new = False
            self._fault("after_atomic_install")
            if final_path.is_symlink():
                raise ObjectIntegrityError("installed object path cannot be a symlink")
            os.chmod(final_path, 0o400, follow_symlinks=False)
            fd = self._open_read_only(final_path)
            try:
                self._fault("before_installed_file_fsync")
                os.fsync(fd)
                self._fault("after_installed_file_fsync")
                self._fsync_directory(directory)
                pinned = _PinnedBlob(
                    fd=fd,
                    path=final_path,
                    identity=staged.identity,
                    installed_new=installed_new,
                )
                self.verify_pinned(pinned)
                return pinned
            except Exception:
                os.close(fd)
                raise
        except Exception:
            if installed_new:
                try:
                    final_path.unlink(missing_ok=True)
                    self._fsync_directory(directory)
                except Exception:
                    # Preserve the original durability/integrity failure.  A later
                    # reconciliation will remove an unreferenced orphan.
                    pass
            raise

    def pin(self, identity: BlobIdentity) -> _PinnedBlob:
        path = self.object_path(identity)
        fd = self._open_read_only(path)
        pinned = _PinnedBlob(fd=fd, path=path, identity=identity)
        try:
            self.verify_pinned(pinned)
            return pinned
        except Exception:
            pinned.close()
            raise

    def read_range(
        self, pinned: _PinnedBlob, *, offset: int, length: int
    ) -> bytes:
        self.limits.require_range(
            total_size=pinned.identity.size_bytes,
            offset=offset,
            length=length,
        )
        self.verify_pinned(pinned)
        remaining = length
        position = offset
        pieces: list[bytes] = []
        while remaining:
            chunk = os.pread(
                pinned.fd,
                min(remaining, self.limits.io_chunk_bytes),
                position,
            )
            if not chunk:
                raise ObjectIntegrityError("installed blob ended before approved range")
            pieces.append(chunk)
            position += len(chunk)
            remaining -= len(chunk)
        return b"".join(pieces)

    def finish_stage(self, staged: _StagedBlob) -> None:
        self._fault("before_stage_cleanup_unlink")
        staged.path.unlink(missing_ok=True)
        self._fault("after_stage_cleanup_unlink")
        self._fsync_directory(self.staging_root)

    def discard_stage(self, staged: _StagedBlob) -> None:
        try:
            staged.path.unlink(missing_ok=True)
        finally:
            self._fsync_directory(self.staging_root)

    def unlink(self, identity: BlobIdentity) -> bool:
        path = self.object_path(identity)
        directory = path.parent
        self._fault("before_blob_unlink")
        try:
            path.unlink()
            removed = True
        except FileNotFoundError:
            removed = False
        self._fault("after_blob_unlink")
        if directory.exists():
            self._fsync_directory(directory)
        return removed


    def cleanup_unreferenced_installed(
        self, *, known_digests: frozenset[str]
    ) -> tuple[str, ...]:
        """Remove crash-left installed files that have no SQLite blob identity."""

        removed: list[str] = []
        modified_directories: set[Path] = set()
        for directory in sorted(self.objects_root.iterdir()):
            if directory.is_symlink() or not directory.is_dir():
                raise ObjectIntegrityError(
                    "unexpected entry in CAS objects root"
                )
            self._validate_owner_mode(directory, directory=True)
            if len(directory.name) != 2 or any(
                char not in "0123456789abcdef" for char in directory.name
            ):
                raise ObjectIntegrityError(
                    "invalid content-addressed directory name"
                )
            for path in sorted(directory.iterdir()):
                if path.is_symlink() or not path.is_file():
                    raise ObjectIntegrityError(
                        "unexpected entry in CAS object directory"
                    )
                if (
                    len(path.name) != 64
                    or not path.name.startswith(directory.name)
                    or any(
                        char not in "0123456789abcdef"
                        for char in path.name
                    )
                ):
                    raise ObjectIntegrityError(
                        "invalid content-addressed object name"
                    )
                digest = f"sha256:{path.name}"
                if digest in known_digests:
                    continue
                path.unlink()
                removed.append(digest)
                modified_directories.add(directory)
        for directory in sorted(modified_directories):
            self._fsync_directory(directory)
            try:
                directory.rmdir()
            except OSError:
                continue
            self._fsync_directory(self.objects_root)
        return tuple(removed)

    def cleanup_staging(self, *, keep_names: frozenset[str]) -> tuple[str, ...]:
        removed: list[str] = []
        for path in sorted(self.staging_root.iterdir()):
            if path.name in keep_names:
                continue
            if path.is_symlink() or not path.is_file():
                raise ObjectIntegrityError("unexpected entry in CAS staging root")
            path.unlink()
            removed.append(path.name)
        if removed:
            self._fsync_directory(self.staging_root)
        return tuple(removed)


__all__ = ["_GovernedCAS", "_PinnedBlob", "_StagedBlob"]
