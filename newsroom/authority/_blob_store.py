from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
from typing import BinaryIO, Iterator

from .canonical import validate_sha256_digest
from .objects import ObjectIntegrityError, ObjectLimitError, ObjectLimits


class BlobStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StagedBlob:
    staged_path: Path
    blob_digest: str
    size_bytes: int


class PinnedBlob:
    """Verified read-only file descriptor kept open across an authority commit."""

    def __init__(
        self,
        *,
        descriptor: int,
        path: Path,
        blob_digest: str,
        size_bytes: int,
        device: int,
        inode: int,
        chunk_bytes: int,
    ) -> None:
        self._descriptor = descriptor
        self.path = path
        self.blob_digest = blob_digest
        self.size_bytes = size_bytes
        self._device = device
        self._inode = inode
        self._chunk_bytes = chunk_bytes
        self._closed = False

    def _require_open(self) -> int:
        if self._closed:
            raise ObjectIntegrityError("pinned blob is closed")
        return self._descriptor

    def verify_current(self) -> None:
        descriptor = self._require_open()
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ObjectIntegrityError("pinned blob is no longer a regular file")
        if info.st_dev != self._device or info.st_ino != self._inode:
            raise ObjectIntegrityError("pinned blob identity changed")
        if info.st_size != self.size_bytes:
            raise ObjectIntegrityError("pinned blob size changed")
        if stat.S_IMODE(info.st_mode) & 0o222:
            raise ObjectIntegrityError("installed blob became writable")
        if self.path.is_symlink() or not self.path.exists():
            raise ObjectIntegrityError("installed blob path disappeared or became a symlink")
        path_info = self.path.stat()
        if path_info.st_dev != self._device or path_info.st_ino != self._inode:
            raise ObjectIntegrityError("installed blob path no longer names the pinned inode")
        actual = self._hash_descriptor(descriptor)
        if actual != self.blob_digest:
            raise ObjectIntegrityError("pinned blob bytes changed")

    def read_bounded(self, *, max_bytes: int) -> bytes:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ObjectLimitError("maximum read bytes must be positive")
        if self.size_bytes > max_bytes:
            raise ObjectLimitError("blob exceeds bounded read limit")
        descriptor = self._require_open()
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = self.size_bytes
        while remaining:
            chunk = os.read(descriptor, min(self._chunk_bytes, remaining))
            if not chunk:
                raise ObjectIntegrityError("pinned blob ended before declared size")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ObjectIntegrityError("pinned blob grew during bounded read")
        result = b"".join(chunks)
        if len(result) != self.size_bytes:
            raise ObjectIntegrityError("bounded blob read returned the wrong size")
        return result

    def _hash_descriptor(self, descriptor: int) -> str:
        os.lseek(descriptor, 0, os.SEEK_SET)
        hasher = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, self._chunk_bytes)
            if not chunk:
                break
            total += len(chunk)
            if total > self.size_bytes:
                raise ObjectIntegrityError("blob grew during verification")
            hasher.update(chunk)
        if total != self.size_bytes:
            raise ObjectIntegrityError("blob size changed during verification")
        return f"sha256:{hasher.hexdigest()}"

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.close(self._descriptor)

    def __enter__(self) -> PinnedBlob:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _BlobStore:
    """Same-filesystem bounded CAS with fail-closed durability semantics."""

    def __init__(
        self,
        root: Path,
        *,
        limits: ObjectLimits,
        directory_fsync: Callable[[Path], None] | None = None,
        file_fsync: Callable[[int], None] = os.fsync,
        unlink: Callable[[Path], None] | None = None,
        disk_usage: Callable[[Path], object] = shutil.disk_usage,
    ) -> None:
        self.root = Path(root)
        self.limits = limits
        self._directory_fsync_override = directory_fsync
        self._file_fsync = file_fsync
        self._unlink = unlink or (lambda path: path.unlink())
        self._disk_usage = disk_usage
        self._secure_directory(self.root)
        self.staging_root = self.root / ".staging"
        created_staging = not self.staging_root.exists()
        self._secure_directory(self.staging_root)
        if created_staging:
            self._fsync_directory(self.root)
        algorithm_root = self.root / "sha256"
        created_algorithm = not algorithm_root.exists()
        self._secure_directory(algorithm_root)
        if created_algorithm:
            self._fsync_directory(self.root)

    @staticmethod
    def _secure_directory(path: Path) -> None:
        if path.exists():
            if path.is_symlink() or not path.is_dir():
                raise BlobStoreError("blob root must be a real directory")
        else:
            path.mkdir(parents=True, mode=0o700)
            os.chmod(path, 0o700)
        info = path.stat()
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise BlobStoreError("blob directory must be owned by the authority writer")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise BlobStoreError("blob directory cannot grant group or other permissions")

    def _fsync_directory(self, path: Path) -> None:
        if self._directory_fsync_override is not None:
            self._directory_fsync_override(path)
            return
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _check_headroom(self, path: Path, *, incoming_bytes: int = 0) -> None:
        usage = self._disk_usage(path)
        free = int(getattr(usage, "free"))
        required = self.limits.min_free_bytes + incoming_bytes
        if free < required:
            raise ObjectLimitError(
                f"insufficient disk headroom: free={free}, required={required}"
            )

    def stage(self, source: BinaryIO, *, object_class: str) -> StagedBlob:
        if not hasattr(source, "read"):
            raise TypeError("object source must be a binary readable stream")
        maximum = self.limits.maximum_for(object_class)
        self._check_headroom(self.staging_root, incoming_bytes=maximum)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.staging_root, prefix="stage-"
        )
        os.fchmod(descriptor, 0o600)
        path = Path(temporary_name)
        hasher = hashlib.sha256()
        total = 0
        try:
            while True:
                chunk = source.read(self.limits.io_chunk_bytes)
                if chunk in (b"", None):
                    break
                if not isinstance(chunk, bytes):
                    raise TypeError("object stream must yield bytes")
                total += len(chunk)
                if total > maximum:
                    raise ObjectLimitError(
                        f"object exceeds hard limit for {object_class}: {maximum}"
                    )
                self._check_headroom(
                    self.staging_root,
                    incoming_bytes=min(self.limits.io_chunk_bytes, maximum - total),
                )
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise BlobStoreError("staging write made no progress")
                    view = view[written:]
                hasher.update(chunk)
            self._file_fsync(descriptor)
        except Exception:
            os.close(descriptor)
            try:
                self._unlink(path)
                self._fsync_directory(self.staging_root)
            except OSError:
                pass
            raise
        os.close(descriptor)
        return StagedBlob(
            staged_path=path,
            blob_digest=f"sha256:{hasher.hexdigest()}",
            size_bytes=total,
        )

    def discard_stage(self, staged: StagedBlob) -> None:
        if staged.staged_path.exists():
            self._unlink(staged.staged_path)
            self._fsync_directory(self.staging_root)

    def path_for(self, blob_digest: str) -> Path:
        normalized = validate_sha256_digest(blob_digest, field="blob_digest")
        hexadecimal = normalized.removeprefix("sha256:")
        return self.root / "sha256" / hexadecimal[:2] / hexadecimal[2:]

    def install(self, staged: StagedBlob) -> Path:
        validate_sha256_digest(staged.blob_digest, field="blob_digest")
        if not staged.staged_path.exists() or staged.staged_path.is_symlink():
            raise ObjectIntegrityError("staged blob is missing or invalid")
        self._verify_path(
            staged.staged_path,
            expected_digest=staged.blob_digest,
            expected_size=staged.size_bytes,
            require_read_only=False,
        )
        target = self.path_for(staged.blob_digest)
        parent_created = not target.parent.exists()
        self._secure_directory(target.parent)
        if parent_created:
            self._fsync_directory(target.parent.parent)
        try:
            os.link(staged.staged_path, target)
        except FileExistsError:
            self._verify_path(
                target,
                expected_digest=staged.blob_digest,
                expected_size=staged.size_bytes,
                require_read_only=True,
            )
        else:
            descriptor = os.open(
                target,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fchmod(descriptor, 0o400)
                self._file_fsync(descriptor)
            finally:
                os.close(descriptor)
            self._fsync_directory(target.parent)
            self._verify_path(
                target,
                expected_digest=staged.blob_digest,
                expected_size=staged.size_bytes,
                require_read_only=True,
            )
        self.discard_stage(staged)
        return target

    def pin(
        self, blob_digest: str, *, expected_size: int | None = None
    ) -> PinnedBlob:
        target = self.path_for(blob_digest)
        descriptor = os.open(
            target,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ObjectIntegrityError("installed blob is not a regular file")
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise ObjectIntegrityError("installed blob owner changed")
            if stat.S_IMODE(info.st_mode) & 0o222:
                raise ObjectIntegrityError("installed blob must be read-only")
            if expected_size is not None and info.st_size != expected_size:
                raise ObjectIntegrityError("installed blob size differs from authority")
            pinned = PinnedBlob(
                descriptor=descriptor,
                path=target,
                blob_digest=validate_sha256_digest(
                    blob_digest, field="blob_digest"
                ),
                size_bytes=int(info.st_size),
                device=int(info.st_dev),
                inode=int(info.st_ino),
                chunk_bytes=self.limits.io_chunk_bytes,
            )
            pinned.verify_current()
            return pinned
        except Exception:
            os.close(descriptor)
            raise

    def verify(self, blob_digest: str, *, expected_size: int | None = None) -> int:
        with self.pin(blob_digest, expected_size=expected_size) as pinned:
            return pinned.size_bytes

    def unlink_blob(self, blob_digest: str) -> bool:
        target = self.path_for(blob_digest)
        if not target.exists():
            return False
        if target.is_symlink() or not target.is_file():
            raise ObjectIntegrityError("blob target is not a regular file")
        self._unlink(target)
        self._fsync_directory(target.parent)
        return True

    def installed_digests(self) -> Iterator[tuple[str, float]]:
        root = self.root / "sha256"
        if not root.exists():
            return
        for prefix in root.iterdir():
            if not prefix.is_dir() or prefix.is_symlink() or len(prefix.name) != 2:
                continue
            for candidate in prefix.iterdir():
                if not candidate.is_file() or candidate.is_symlink():
                    continue
                hexadecimal = prefix.name + candidate.name
                if len(hexadecimal) != 64:
                    continue
                digest = f"sha256:{hexadecimal}"
                try:
                    validate_sha256_digest(digest)
                except ValueError:
                    continue
                yield digest, candidate.stat().st_mtime

    def cleanup_staging(self, *, older_than_epoch: float) -> tuple[str, ...]:
        removed: list[str] = []
        for candidate in self.staging_root.iterdir():
            if not candidate.is_file() or candidate.is_symlink():
                continue
            if candidate.stat().st_mtime >= older_than_epoch:
                continue
            self._unlink(candidate)
            removed.append(candidate.name)
        if removed:
            self._fsync_directory(self.staging_root)
        return tuple(sorted(removed))

    def _verify_path(
        self,
        path: Path,
        *,
        expected_digest: str,
        expected_size: int,
        require_read_only: bool,
    ) -> None:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ObjectIntegrityError("blob path is not a regular file")
            if info.st_size != expected_size:
                raise ObjectIntegrityError("blob size mismatch")
            if require_read_only and stat.S_IMODE(info.st_mode) & 0o222:
                raise ObjectIntegrityError("blob is not read-only")
            os.lseek(descriptor, 0, os.SEEK_SET)
            hasher = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(descriptor, self.limits.io_chunk_bytes)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size:
                    raise ObjectIntegrityError("blob grew during verification")
                hasher.update(chunk)
            if total != expected_size:
                raise ObjectIntegrityError("blob changed during verification")
            if f"sha256:{hasher.hexdigest()}" != expected_digest:
                raise ObjectIntegrityError("blob digest mismatch")
        finally:
            os.close(descriptor)
