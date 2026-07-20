from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    AuthorityWriterBusy,
    HydrationRequest,
    ObjectAdmissionRequest,
    ObjectIntegrityError,
    ObjectLifecycleError,
    ObjectLimits,
)

from .authority_a2b_helpers import admit, open_object_system
from .authority_helpers import proof


def installed_path(root: Path, blob_digest: str) -> Path:
    hex_digest = blob_digest.split(":", 1)[1]
    return root / "objects" / hex_digest[:2] / hex_digest


def test_directory_fsync_failure_is_not_reported_as_success(tmp_path: Path) -> None:
    calls = 0

    def fault(checkpoint: str) -> None:
        nonlocal calls
        if checkpoint == "before_directory_fsync":
            calls += 1
            if calls >= 3:
                raise OSError("directory fsync failed")

    database = tmp_path / "authority.sqlite3"
    try:
        system = open_object_system(database, fault_hook=fault)
    except OSError:
        # Root-creation durability failure is also fail-closed.
        return
    try:
        with pytest.raises(OSError, match="fsync"):
            admit(system, data=b"fsync fault")
    finally:
        system.close()


def test_post_hash_mutation_is_detected_before_authority_commit(
    tmp_path: Path,
) -> None:
    object_root = tmp_path / "objects"

    def fault(checkpoint: str) -> None:
        if checkpoint == "before_pinned_rehash":
            # Locate the newly installed file, temporarily make it writable and
            # mutate the same inode after staging hash but before SQLite commit.
            paths = [
                path
                for path in (object_root / "objects").rglob("*")
                if path.is_file()
            ]
            if paths:
                path = paths[0]
                path.chmod(0o600)
                path.write_bytes(b"mutated after hash")

    system = open_object_system(
        tmp_path / "authority.sqlite3",
        object_root=object_root,
        fault_hook=fault,
    )
    try:
        with pytest.raises(ObjectIntegrityError):
            admit(system, data=b"original bytes")
    finally:
        system.close()


def test_iterable_source_is_rechunked_to_the_configured_io_bound(
    tmp_path: Path,
) -> None:
    staged_chunks = 0

    def fault(checkpoint: str) -> None:
        nonlocal staged_chunks
        if checkpoint == "after_stage_chunk":
            staged_chunks += 1

    limits = ObjectLimits(
        global_max_bytes=1024,
        class_max_bytes={"source_capture": 1024},
        max_read_bytes=1024,
        io_chunk_bytes=4,
        max_staging_bytes=1024,
        max_range_bytes=1024,
    )
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        object_limits=limits,
        fault_hook=fault,
    )
    try:
        result = system.objects.admit(
            ObjectAdmissionRequest("source.capture", "rechunk"),
            [b"abcdefghij"],
            proof=proof(),
        )
        assert result.admission.blob.size_bytes == 10
        assert staged_chunks == 3
    finally:
        system.close()


def test_binary_stream_cannot_ignore_the_configured_read_bound(
    tmp_path: Path,
) -> None:
    staged_chunks = 0

    def fault(checkpoint: str) -> None:
        nonlocal staged_chunks
        if checkpoint == "after_stage_chunk":
            staged_chunks += 1

    class OversizedRead:
        returned = False

        def read(self, _size: int) -> bytes:
            if self.returned:
                return b""
            self.returned = True
            return b"abcdefghij"

    limits = ObjectLimits(
        global_max_bytes=1024,
        class_max_bytes={"source_capture": 1024},
        max_read_bytes=1024,
        io_chunk_bytes=4,
        max_staging_bytes=1024,
        max_range_bytes=1024,
    )
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        object_limits=limits,
        fault_hook=fault,
    )
    try:
        result = system.objects.admit(
            ObjectAdmissionRequest("source.capture", "bounded-read"),
            OversizedRead(),
            proof=proof(),
        )
        assert result.admission.blob.size_bytes == 10
        assert staged_chunks == 3
    finally:
        system.close()


def test_hydration_rehashes_the_pinned_file_after_read(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"

    def fault(checkpoint: str) -> None:
        if checkpoint == "after_range_read_before_rehash":
            paths = [
                path
                for path in (object_root / "objects").rglob("*")
                if path.is_file()
            ]
            assert len(paths) == 1
            path = paths[0]
            path.chmod(0o600)
            path.write_bytes(b"changed-during-read")
            path.chmod(0o400)

    database = tmp_path / "authority.sqlite3"
    system = open_object_system(
        database,
        object_root=object_root,
        fault_hook=fault,
    )
    try:
        admission = admit(system, data=b"original-readable-bytes").admission
        with pytest.raises(ObjectIntegrityError):
            system.objects.hydrate(
                HydrationRequest(admission.admission_id, "project.discovery"),
                proof=proof(),
            )
    finally:
        system.close()

    conn = sqlite3.connect(database)
    try:
        assert conn.execute(
            "SELECT count(*) FROM object_access_decisions"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_missing_or_corrupt_active_bytes_fail_on_reopen(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    system = open_object_system(database, object_root=object_root)
    admission = admit(system, data=b"durable bytes").admission
    system.close()
    path = installed_path(object_root, admission.blob.blob_digest)
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    path.chmod(0o400)
    with pytest.raises((AuthorityPersistenceError, ObjectIntegrityError)):
        open_object_system(database, object_root=object_root)


def test_constructor_reconciliation_failure_releases_writer_lock(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    system = open_object_system(database, object_root=object_root)
    admission = admit(system).admission
    system.close()
    path = installed_path(object_root, admission.blob.blob_digest)
    path.unlink()
    with pytest.raises(Exception):
        open_object_system(database, object_root=object_root)
    # Restore exact bytes and read-only mode, proving the failed constructor did
    # not retain the lifetime SQLite writer lock.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"governed-object-fixture")
    path.chmod(0o400)
    reopened = open_object_system(database, object_root=object_root)
    reopened.close()


def test_restart_cleans_failed_staging_files(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    system = open_object_system(database, object_root=object_root)
    system.close()
    stale = object_root / "staging" / "stale.tmp"
    stale.write_bytes(b"stale")
    stale.chmod(0o600)
    reopened = open_object_system(database, object_root=object_root)
    try:
        assert not stale.exists()
    finally:
        reopened.close()


def test_unlink_failure_is_recorded_failed_and_does_not_remove_authority(
    tmp_path: Path,
) -> None:
    seen = False

    def fault(checkpoint: str) -> None:
        nonlocal seen
        if checkpoint == "before_blob_unlink" and not seen:
            seen = True
            raise OSError("unlink failed")

    system = open_object_system(
        tmp_path / "authority.sqlite3", fault_hook=fault
    )
    try:
        admission = admit(system).admission
        system.objects.revoke(
            admission.admission_id,
            reason_code="REVOKED",
            idempotency_key="revoke",
            proof=proof(),
        )
        deletion = system.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="DELETE",
            idempotency_key="request",
            proof=proof(),
        )
        system.objects.tombstone(
            deletion.deletion_id,
            reason_code="TOMBSTONE",
            idempotency_key="tombstone",
            proof=proof(),
        )
        with pytest.raises(ObjectLifecycleError):
            system.objects.complete_deletion(
                deletion.deletion_id,
                idempotency_key="complete",
                proof=proof(),
            )
        assert system.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="DELETE",
            idempotency_key="request",
            proof=proof(),
        ).state.value in {"FAILED", "TOMBSTONED"}
    finally:
        system.close()


def test_raw_sql_cannot_mutate_a2b_immutable_records(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_object_system(database)
    admission = admit(system).admission
    system.objects.hydrate(
        HydrationRequest(admission.admission_id, "project.discovery"),
        proof=proof(),
    )
    system.close()
    conn = sqlite3.connect(database)
    try:
        for sql in (
            "UPDATE object_admissions SET allowed_use='tampered'",
            "DELETE FROM object_rights_decisions",
            "UPDATE blob_identities SET size_bytes=size_bytes+1",
            "DELETE FROM object_access_decisions",
            "DELETE FROM object_lifecycle_operations",
        ):
            with pytest.raises(sqlite3.DatabaseError, match="immutable|retained"):
                conn.execute(sql)
    finally:
        conn.close()


def test_second_writer_and_symlink_object_root_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    system = open_object_system(database, object_root=object_root)
    try:
        with pytest.raises(AuthorityWriterBusy):
            open_object_system(database, object_root=object_root)
    finally:
        system.close()

    alias = tmp_path / "objects-alias"
    alias.symlink_to(object_root, target_is_directory=True)
    with pytest.raises(ObjectIntegrityError, match="symlink"):
        open_object_system(database, object_root=alias)
