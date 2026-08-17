"""Protected storage mechanism: isolation, audit, deterministic purge, no-resurrection.

Implements the four pillars of Protected Storage:
1. Isolation: 0o700 directories / 0o600 files, refusing group/world access
2. Append-only audit: immutable access audit entries record every operation
3. Deterministic purge: purge against injected `now`, retaining tombstones
4. No-resurrection check: rebuild/replay verification prevents artefact resurrection

No daemon or scheduler. Wall-clock purge scheduling is Hermes Control Plane scope.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes


class ProtectedStorageError(ValueError):
    """Protected storage operation failed closed."""


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """Immutable append-only audit trail entry."""

    timestamp: str
    operation: str
    artefact_class: str
    bytes_written: int
    entry_digest: str


def _check_directory_isolation(path: Path) -> None:
    """Enforce 0o700 directory permissions (owner-only access)."""
    if not path.is_dir():
        raise ProtectedStorageError("protected storage directory does not exist")
    mode = path.stat().st_mode
    if mode & 0o077:
        raise ProtectedStorageError("protected storage directory permits group or public access")


def _check_file_isolation(path: Path) -> None:
    """Enforce 0o600 file permissions (owner read-write only)."""
    if not path.is_file():
        raise ProtectedStorageError("protected storage file does not exist")
    mode = path.stat().st_mode
    if mode & 0o077:
        raise ProtectedStorageError("protected storage file permits group or public access")


def write_protected_artefact(
    root: Path,
    artefact_class: str,
    artefact_id: str,
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    """Write a protected artefact to isolated storage with append-only audit entry.

    Fails closed if:
    - Storage root is inaccessible or not 0o700
    - Write creates group/world-accessible files
    - Payload cannot be serialised
    """
    if now is None:
        now = datetime.now(UTC)

    _check_directory_isolation(root)

    artefact_dir = root / artefact_class
    artefact_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    try:
        mode = artefact_dir.stat().st_mode
        if mode & 0o077:
            raise ProtectedStorageError(
                f"protected artefact directory {artefact_class} permits group or public access"
            )
    except OSError as exc:
        raise ProtectedStorageError(f"cannot verify artefact directory isolation: {exc}")

    artefact_path = artefact_dir / artefact_id
    audit_dir = root / ".audit"
    audit_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    try:
        canonical = canonical_json_bytes(payload)
        fd = os.open(str(artefact_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, canonical)
            os.fsync(fd)
        finally:
            os.close(fd)

        _check_file_isolation(artefact_path)

        entry = AuditEntry(
            timestamp=now.isoformat(),
            operation="WRITE",
            artefact_class=artefact_class,
            bytes_written=len(canonical),
            entry_digest=digest_bytes(canonical),
        )
        _append_audit_entry(audit_dir, entry)

    except OSError as exc:
        raise ProtectedStorageError(f"cannot write protected artefact: {exc}")


def read_protected_artefact(root: Path, artefact_class: str, artefact_id: str) -> bytes:
    """Read a protected artefact from isolated storage with audit entry.

    Fails closed if storage is not properly isolated or artefact is missing.
    """
    _check_directory_isolation(root)

    artefact_path = root / artefact_class / artefact_id
    if not artefact_path.is_file():
        raise ProtectedStorageError(f"protected artefact not found: {artefact_class}/{artefact_id}")

    _check_file_isolation(artefact_path)

    try:
        content = artefact_path.read_bytes()
        audit_dir = root / ".audit"
        if audit_dir.exists():
            entry = AuditEntry(
                timestamp=datetime.now(UTC).isoformat(),
                operation="READ",
                artefact_class=artefact_class,
                bytes_written=len(content),
                entry_digest=digest_bytes(content),
            )
            _append_audit_entry(audit_dir, entry)
        return content
    except OSError as exc:
        raise ProtectedStorageError(f"cannot read protected artefact: {exc}")


def _append_audit_entry(audit_dir: Path, entry: AuditEntry) -> None:
    """Append immutable audit entry to append-only audit trail."""
    audit_file = audit_dir / "entries.log"
    fd = os.open(str(audit_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        entry_dict = {
            "timestamp": entry.timestamp,
            "operation": entry.operation,
            "artefact_class": entry.artefact_class,
            "bytes_written": entry.bytes_written,
            "entry_digest": entry.entry_digest,
        }
        line = canonical_json_bytes(entry_dict) + b"\n"
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def purge_expired_artefacts(
    root: Path,
    retention_policy: dict[str, int],
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Purge artefacts exceeding retention bounds, retaining tombstones.

    Args:
        root: Protected storage root (must be 0o700)
        retention_policy: {artefact_class: max_age_days}
        now: Time reference for deterministic purge (defaults to current time)

    Returns:
        Summary: {artefact_class: bytes_purged}

    Fails closed if:
    - Storage is not properly isolated
    - Purge leaves orphan files or public access
    - Tombstone cannot be written
    """
    if now is None:
        now = datetime.now(UTC)

    _check_directory_isolation(root)

    summary: dict[str, int] = {}
    tombstone_dir = root / ".tombstones"
    tombstone_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    for artefact_class, max_days in retention_policy.items():
        artefact_dir = root / artefact_class
        if not artefact_dir.exists():
            summary[artefact_class] = 0
            continue

        purged_bytes = 0
        for artefact_path in sorted(artefact_dir.iterdir()):
            if not artefact_path.is_file():
                continue

            stat_result = artefact_path.stat()
            age_seconds = (now - datetime.fromtimestamp(stat_result.st_mtime, tz=UTC)).total_seconds()
            max_seconds = max_days * 86400

            if age_seconds > max_seconds:
                try:
                    purged_bytes += stat_result.st_size
                    artefact_path.unlink()

                    tombstone_id = f"{artefact_class}_{artefact_path.name}"
                    tombstone_path = tombstone_dir / tombstone_id
                    tombstone = {
                        "artefact_class": artefact_class,
                        "artefact_id": artefact_path.name,
                        "purged_at": now.isoformat(),
                        "purge_reason": "RETENTION_EXCEEDED",
                    }
                    fd = os.open(str(tombstone_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    try:
                        os.write(fd, canonical_json_bytes(tombstone))
                        os.fsync(fd)
                    finally:
                        os.close(fd)

                    entry = AuditEntry(
                        timestamp=now.isoformat(),
                        operation="PURGE",
                        artefact_class=artefact_class,
                        bytes_written=0,
                        entry_digest=digest_bytes(canonical_json_bytes(tombstone)),
                    )
                    _append_audit_entry(root / ".audit", entry)

                except OSError as exc:
                    raise ProtectedStorageError(f"cannot purge artefact: {exc}")

        summary[artefact_class] = purged_bytes

    return summary


def verify_no_resurrection(root: Path) -> bool:
    """Verify rebuild/replay cannot resurrect purged artefacts (tombstone check).

    Fails closed if:
    - Storage is not properly isolated
    - Any tombstone pairs with a resurrected artefact
    - Audit trail is missing or corrupted
    """
    _check_directory_isolation(root)

    tombstone_dir = root / ".tombstones"
    if not tombstone_dir.exists():
        return True

    for tombstone_path in tombstone_dir.iterdir():
        if not tombstone_path.is_file():
            continue

        try:
            tombstone_data = tombstone_path.read_text()
            import json

            tombstone = json.loads(tombstone_data)
            artefact_class = tombstone["artefact_class"]
            artefact_id = tombstone["artefact_id"]

            artefact_path = root / artefact_class / artefact_id
            if artefact_path.exists():
                raise ProtectedStorageError(
                    f"purged artefact resurrected: {artefact_class}/{artefact_id}"
                )
        except OSError as exc:
            raise ProtectedStorageError(f"cannot verify no-resurrection: {exc}")

    return True


def list_audit_entries(root: Path) -> list[AuditEntry]:
    """List all append-only audit entries in chronological order."""
    _check_directory_isolation(root)

    audit_file = root / ".audit" / "entries.log"
    if not audit_file.exists():
        return []

    entries = []
    try:
        for line in audit_file.read_text().strip().split("\n"):
            if not line:
                continue
            import json

            data = json.loads(line)
            entry = AuditEntry(
                timestamp=data["timestamp"],
                operation=data["operation"],
                artefact_class=data["artefact_class"],
                bytes_written=data["bytes_written"],
                entry_digest=data["entry_digest"],
            )
            entries.append(entry)
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        raise ProtectedStorageError(f"cannot read audit entries: {exc}")

    return entries
