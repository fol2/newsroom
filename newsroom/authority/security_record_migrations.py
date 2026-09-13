"""Atomic v37 lossless compaction of duplicated authentication context fields."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
import sqlite3

from .authorisation_scope_content_migrations import AuthorisationScopeContentMigrationRecord
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical

SECURITY_RECORD_SCHEMA_VERSION = 37
SECURITY_RECORD_MIGRATION_NAME = "authentication_context_compaction_v37"
SECURITY_RECORD_PREDECESSOR_FINGERPRINT = (
    "sha256:df4cd39f154791d3e5680ac4fa501c2a076427d0ea18caff40145319c08647d0"
)
AUTHENTICATION_CONTEXT_FIELDS = (
    "authentication_context_id", "principal_id", "authority_domain",
    "authentication_method", "assurance_class", "credential_binding_digest",
    "authenticated_at", "expires_at",
)


def _validate_old_context(row: Mapping[str, object]) -> None:
    data = bytes(row["canonical_bytes"])
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
        if not isinstance(value, dict) or canonical_json_bytes(value) != data:
            raise ValueError("noncanonical object")
    except (UnicodeError, ValueError) as exc:
        raise sqlite3.IntegrityError("stored authentication context is not canonical") from exc
    expected = {name: str(row[name]) for name in AUTHENTICATION_CONTEXT_FIELDS}
    if value != expected or digest_bytes(data) != str(row["canonical_digest"]):
        raise sqlite3.IntegrityError("stored authentication context fields or digest differ")


def migrate_security_records(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> None:
    from .migrations import schema_fingerprint

    if not connection.in_transaction:
        raise sqlite3.DatabaseError("v37 migration requires an active transaction")
    if (
        connection.execute("PRAGMA user_version").fetchone()[0] not in (0, 34, 35, 36)
        or schema_fingerprint(connection) != SECURITY_RECORD_PREDECESSOR_FINGERPRINT
        or tuple(tuple(row) for row in connection.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        )) != expected_history
    ):
        raise sqlite3.DatabaseError("v37 migration requires exact checked schema v36")

    def rows() -> Iterator[dict[str, object]]:
        cursor = connection.execute("SELECT * FROM authentication_contexts ORDER BY rowid")
        names = tuple(item[0] for item in cursor.description)
        for row in cursor:
            yield dict(zip(names, row, strict=True))

    # Authenticate every old context before replacing any redundant bytes.
    for row in rows():
        _validate_old_context(row)
    connection.execute("DROP TRIGGER immutable_authentication_contexts_update")
    for row in rows():
        _validate_old_context(row)
        connection.execute(
            "UPDATE authentication_contexts SET canonical_bytes=? WHERE authentication_context_id=?",
            (b"v37", row["authentication_context_id"]),
        )
    connection.execute(
        "ALTER TABLE authentication_contexts RENAME COLUMN canonical_bytes TO storage_context_marker"
    )
    connection.execute("""CREATE TRIGGER immutable_authentication_contexts_update
        BEFORE UPDATE ON authentication_contexts BEGIN
        SELECT RAISE(ABORT,'immutable authentication context'); END""")
    connection.execute("""CREATE TRIGGER authentication_context_storage_guard
        BEFORE INSERT ON authentication_contexts
        WHEN NEW.storage_context_marker != X'763337'
        BEGIN SELECT RAISE(ABORT,'authentication context storage differs'); END""")


SECURITY_RECORD_MIGRATION_STATEMENTS = (
    "validate exact v36 schema, history and every canonical authentication context before conversion",
    "replace authentication canonical bytes with v37 marker and reconstruct all eight indexed fields",
    "preserve context digests, every key and reference, and immutable storage guards",
    "retain authorization request and decision representations unchanged",
)
SECURITY_RECORD_MIGRATION_CHECKSUM = digest_canonical({
    "version": SECURITY_RECORD_SCHEMA_VERSION,
    "name": SECURITY_RECORD_MIGRATION_NAME,
    "statements": list(SECURITY_RECORD_MIGRATION_STATEMENTS),
})
SECURITY_RECORD_MIGRATION = AuthorisationScopeContentMigrationRecord(
    SECURITY_RECORD_SCHEMA_VERSION, SECURITY_RECORD_MIGRATION_NAME,
    SECURITY_RECORD_MIGRATION_CHECKSUM,
)
