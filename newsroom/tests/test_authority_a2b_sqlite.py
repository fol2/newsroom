from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import (
    AuthorityPersistenceError,
    HydrationRequest,
    ObjectAdmissionId,
    ObjectAdmissionPayload,
    SemanticCommand,
)
from newsroom.authority.migrations import (
    BASE_SCHEMA_VERSION,
    MIGRATION_STATEMENTS,
    apply_pending_migrations,
)
from newsroom.authority.object_migrations import OBJECT_MIGRATION_STATEMENTS

from .authority_a2b_helpers import admit, open_object_system
from .authority_helpers import command, proof


def test_fresh_a2a_a2b_migration_is_atomic_on_late_failure() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        # Rebuild the exact migration body with a late broken statement. A fresh
        # database must not retain even the A2a schema.
        faulty = (*MIGRATION_STATEMENTS, *OBJECT_MIGRATION_STATEMENTS[:-1], "CREATE TABLE broken(")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("BEGIN EXCLUSIVE")
            for statement in faulty:
                conn.execute(statement)
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "authority_commands" not in tables
        assert "object_admissions" not in tables
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 0
    finally:
        conn.close()


def test_a2a_database_upgrades_to_a2b_and_reopens(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    conn = sqlite3.connect(database, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN EXCLUSIVE")
        for statement in MIGRATION_STATEMENTS:
            conn.execute(statement)
        from newsroom.authority.migrations import MIGRATION_CHECKSUM, MIGRATION_NAME

        conn.execute(
            "INSERT INTO authority_migrations(version,name,checksum,applied_at) "
            "VALUES(?,?,?,?)",
            (BASE_SCHEMA_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, "2026-07-17T00:00:00Z"),
        )
        conn.execute(f"PRAGMA user_version={BASE_SCHEMA_VERSION}")
        conn.execute("COMMIT")
    finally:
        conn.close()
    database.chmod(0o600)

    system = open_object_system(database)
    system.close()
    reopened = open_object_system(database)
    reopened.close()


def test_a2b_schema_tamper_fails_and_releases_lock(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_object_system(database)
    system.close()
    conn = sqlite3.connect(database)
    try:
        conn.execute("DROP INDEX idx_object_deletions_blob")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(Exception, match="fingerprint"):
        open_object_system(database)

    conn = sqlite3.connect(database)
    try:
        conn.execute(
            "CREATE INDEX idx_object_deletions_blob "
            "ON object_deletions(blob_digest)"
        )
        conn.commit()
    finally:
        conn.close()
    reopened = open_object_system(database)
    reopened.close()


def test_object_backed_command_rechecks_current_admission_and_exact_bytes(
    tmp_path: Path,
) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        admission = admit(system, data=b"object payload").admission
        request = SemanticCommand(
            command_type="record.observed",
            aggregate_id=command().aggregate_id,
            expected_aggregate_version=0,
            payload=ObjectAdmissionPayload(admission.admission_id),
            idempotency_key="object-command",
        )
        # The fixture command definition is INLINE; an object-backed payload must
        # fail rather than bypass exact server command semantics.
        with pytest.raises(Exception):
            system.commands.execute(request, proof=proof())
    finally:
        system.close()


def test_historical_reference_does_not_resurrect_deleted_bytes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    system = open_object_system(database, object_root=object_root)
    admission = admit(system, data=b"redacted bytes").admission
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
    system.objects.complete_deletion(
        deletion.deletion_id,
        idempotency_key="complete",
        proof=proof(),
    )
    system.close()
    reopened = open_object_system(database, object_root=object_root)
    try:
        with pytest.raises(Exception):
            reopened.objects.hydrate(
                HydrationRequest(admission.admission_id, "project.discovery"),
                proof=proof(),
            )
        event_types = {
            event.event_type
            for event in reopened.events.after(0, limit=1000, proof=proof())
        }
        assert "governed_blob.deletion.tombstoned" in event_types
        assert "governed_blob.deletion.completed" in event_types
    finally:
        reopened.close()


def test_access_decision_and_security_provenance_are_resolvable(
    tmp_path: Path,
) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        admission = admit(system).admission
        hydrated = system.objects.hydrate(
            HydrationRequest(admission.admission_id, "project.discovery"),
            proof=proof(),
        )
        decision = hydrated.decision
        assert decision.authentication_context_id
        assert decision.authorization_request_digest.startswith("sha256:")
        assert decision.authorization_decision_id
        assert decision.canonical_digest.startswith("sha256:")
    finally:
        system.close()


def test_raw_object_state_cannot_be_mutated_without_version(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_object_system(database)
    admission = admit(system).admission
    system.close()
    conn = sqlite3.connect(database)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute(
                "UPDATE object_admissions SET security_scope='wider' "
                "WHERE admission_id=?",
                (str(admission.admission_id),),
            )
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute(
                "UPDATE blob_identities SET size_bytes=size_bytes+1 "
                "WHERE blob_digest=?",
                (admission.blob.blob_digest,),
            )
    finally:
        conn.close()
