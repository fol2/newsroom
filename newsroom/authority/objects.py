from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .canonical import digest_bytes, validate_sha256_digest
from .types import RightsStatus, UtcTimestamp


class ObjectStoreError(RuntimeError):
    """Base class for governed-object failures."""


class ObjectAdmissionError(ObjectStoreError):
    """Raised when rights or scope do not permit object installation."""


class ObjectIntegrityError(ObjectStoreError):
    """Raised when installed bytes do not match their governed identity."""


@dataclass(frozen=True, slots=True)
class GovernedObject:
    digest: str
    size_bytes: int
    object_class: str
    rights_status: RightsStatus
    security_scope: str
    retention_scope: str
    installed_at: UtcTimestamp


class GovernedObjectStore:
    """Local immutable content-addressed storage.

    Installation finishes and verifies durable local bytes before a caller may
    ask the SQLite authority writer to register or reference the object. A crash
    before the ledger reference therefore leaves only a collectable orphan.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.root.is_dir() or self.root.is_symlink():
            raise ObjectStoreError("governed object root must be a real directory")

    def path_for(self, digest: str) -> Path:
        normalized = validate_sha256_digest(digest)
        hexadecimal = normalized.removeprefix("sha256:")
        return self.root / "sha256" / hexadecimal[:2] / hexadecimal[2:]

    def install(
        self,
        data: bytes,
        *,
        object_class: str,
        rights_status: RightsStatus,
        security_scope: str,
        retention_scope: str,
        installed_at: UtcTimestamp | None = None,
    ) -> GovernedObject:
        if not isinstance(data, bytes):
            raise ObjectAdmissionError("governed object data must be immutable bytes")
        if not object_class.strip() or not security_scope.strip() or not retention_scope.strip():
            raise ObjectAdmissionError("object class and scopes must be non-empty")
        if not rights_status.permits_installation:
            raise ObjectAdmissionError(
                f"rights status {rights_status.value} does not permit installation"
            )
        timestamp = installed_at or UtcTimestamp.now()
        digest = digest_bytes(data)
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.exists():
            self.verify(digest)
            return GovernedObject(
                digest=digest,
                size_bytes=len(data),
                object_class=object_class,
                rights_status=rights_status,
                security_scope=security_scope,
                retention_scope=retention_scope,
                installed_at=timestamp,
            )

        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=".install-",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path = Path(temporary_name)
            if digest_bytes(temporary_path.read_bytes()) != digest:
                raise ObjectIntegrityError("temporary object digest changed during install")
            try:
                os.link(temporary_path, target)
            except FileExistsError:
                self.verify(digest)
            self._fsync_directory(target.parent)
        except OSError as exc:
            raise ObjectStoreError(f"governed object installation failed: {exc}") from exc
        finally:
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass

        self.verify(digest)
        return GovernedObject(
            digest=digest,
            size_bytes=len(data),
            object_class=object_class,
            rights_status=rights_status,
            security_scope=security_scope,
            retention_scope=retention_scope,
            installed_at=timestamp,
        )

    def verify(self, digest: str) -> int:
        target = self.path_for(digest)
        if not target.exists() or not target.is_file() or target.is_symlink():
            raise ObjectIntegrityError("governed object is missing or not a regular file")
        data = target.read_bytes()
        if digest_bytes(data) != validate_sha256_digest(digest):
            raise ObjectIntegrityError("governed object digest mismatch")
        return len(data)

    def read(self, digest: str) -> bytes:
        self.verify(digest)
        return self.path_for(digest).read_bytes()

    def collect_orphans(
        self,
        *,
        referenced_digests: Iterable[str],
        grace_seconds: int,
        now_epoch: float | None = None,
    ) -> tuple[str, ...]:
        if grace_seconds < 0:
            raise ValueError("grace_seconds must be non-negative")
        referenced = {validate_sha256_digest(item) for item in referenced_digests}
        now = time.time() if now_epoch is None else now_epoch
        removed: list[str] = []
        algorithm_root = self.root / "sha256"
        if not algorithm_root.exists():
            return ()
        for prefix_dir in algorithm_root.iterdir():
            if not prefix_dir.is_dir() or prefix_dir.is_symlink():
                continue
            for candidate in prefix_dir.iterdir():
                if not candidate.is_file() or candidate.is_symlink():
                    continue
                hexadecimal = f"{prefix_dir.name}{candidate.name}"
                if len(hexadecimal) != 64:
                    continue
                digest = f"sha256:{hexadecimal}"
                try:
                    validate_sha256_digest(digest)
                except ValueError:
                    continue
                if digest in referenced:
                    continue
                age = now - candidate.stat().st_mtime
                if age < grace_seconds:
                    continue
                candidate.unlink()
                removed.append(digest)
            try:
                prefix_dir.rmdir()
            except OSError:
                pass
        self._fsync_directory(algorithm_root)
        return tuple(sorted(removed))

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if not path.exists():
            return
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
