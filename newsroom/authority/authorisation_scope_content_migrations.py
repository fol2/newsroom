"""Atomic v36 migration for content-addressed authorisation scope bytes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
import sqlite3

from . import graphiti_accounted_zero_migrations as predecessor
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical

AUTHORISATION_SCOPE_CONTENT_SCHEMA_VERSION = 36
AUTHORISATION_SCOPE_CONTENT_MIGRATION_NAME = "authorisation_shared_scope_content_v36"
AUTHORISATION_SCOPE_CONTENT_PREDECESSOR_FINGERPRINT = (
    "sha256:e6f107455a75986a977008073e3882780155d51b73660b1a2ed780a2e573455a"
)
AuthorisationScopeContentMigrationRecord = predecessor.GraphitiAccountedZeroMigrationRecord
_SCOPE_MARKER = b"v36"


def _decode_old_decision(row: Mapping[str, object]) -> tuple[bytes, str]:
    data = bytes(row["canonical_bytes"])
    scopes_bytes = bytes(row["effective_scopes"])
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise sqlite3.IntegrityError("stored authorization decision JSON is invalid") from exc
    scopes = value.get("effective_scopes") if isinstance(value, dict) else None
    if canonical_json_bytes(value) != data or not isinstance(scopes, list) or not all(
        isinstance(item, str) for item in scopes
    ) or canonical_json_bytes(scopes) != scopes_bytes:
        raise sqlite3.IntegrityError("stored authorization decision is not canonical")
    expected = {
        "authorization_decision_id": str(row["authorization_decision_id"]),
        "authentication_context_id": str(row["authentication_context_id"]),
        "authorization_request_digest": str(row["authorization_request_digest"]),
        "authorization_policy_version": str(row["authorization_policy_version"]),
        "effective_scopes": scopes,
        "effective_scope_digest": str(row["effective_scope_digest"]),
        "allowed": bool(row["allowed"]),
        "reason_code": str(row["reason_code"]),
        "decided_at": str(row["decided_at"]),
    }
    if value != expected or digest_bytes(data) != str(row["canonical_digest"]):
        raise sqlite3.IntegrityError("stored authorization decision fields mismatch")
    return scopes_bytes, digest_bytes(scopes_bytes)


def migrate_authorisation_scope_content(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if (
        version not in (0, 34, 35)
        or (version != 0 and predecessor._helpers._schema_fingerprint(connection)
            != AUTHORISATION_SCOPE_CONTENT_PREDECESSOR_FINGERPRINT)
        or tuple(tuple(row) for row in connection.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        )) != expected_history
    ):
        raise sqlite3.DatabaseError("v36 migration requires exact checked schema v35")

    def rows() -> Iterator[dict[str, object]]:
        cursor = connection.execute("SELECT * FROM authorization_decisions")
        names = tuple(item[0] for item in cursor.description)
        for row in cursor:
            yield dict(zip(names, row, strict=True))

    # Reject every old contradiction before changing the representation.
    for row in rows():
        _decode_old_decision(row)
    connection.execute("""CREATE TABLE authorization_scope_contents(
        scope_content_digest TEXT PRIMARY KEY,
        canonical_bytes BLOB NOT NULL UNIQUE,
        CHECK(length(canonical_bytes)>0)
    ) STRICT""")
    connection.execute("DROP TRIGGER immutable_authorization_decisions_update")
    connection.execute(
        "ALTER TABLE authorization_decisions ADD COLUMN scope_content_digest TEXT "
        "REFERENCES authorization_scope_contents(scope_content_digest)"
    )
    for row in rows():
        scopes_bytes, scope_digest = _decode_old_decision(row)
        connection.execute(
            "INSERT OR IGNORE INTO authorization_scope_contents VALUES(?,?)",
            (scope_digest, scopes_bytes),
        )
        retained = connection.execute(
            "SELECT canonical_bytes FROM authorization_scope_contents "
            "WHERE scope_content_digest=?", (scope_digest,),
        ).fetchone()
        if retained is None or bytes(retained[0]) != scopes_bytes:
            raise sqlite3.IntegrityError("authorization scope digest collision")
        connection.execute(
            "UPDATE authorization_decisions SET effective_scopes=?,canonical_bytes=?,"
            "scope_content_digest=? WHERE authorization_decision_id=?",
            (_SCOPE_MARKER, _SCOPE_MARKER, scope_digest,
             row["authorization_decision_id"]),
        )
    connection.execute(
        "ALTER TABLE authorization_decisions RENAME COLUMN effective_scopes "
        "TO storage_scope_marker"
    )
    connection.execute(
        "ALTER TABLE authorization_decisions RENAME COLUMN canonical_bytes "
        "TO storage_decision_marker"
    )
    connection.execute("""CREATE TRIGGER immutable_authorization_scope_contents_update
        BEFORE UPDATE ON authorization_scope_contents BEGIN
        SELECT RAISE(ABORT,'immutable authorization scope content'); END""")
    connection.execute("""CREATE TRIGGER immutable_authorization_scope_contents_delete
        BEFORE DELETE ON authorization_scope_contents BEGIN
        SELECT RAISE(ABORT,'retained authorization scope content'); END""")
    connection.execute("""CREATE TRIGGER immutable_authorization_decisions_update
        BEFORE UPDATE ON authorization_decisions BEGIN
        SELECT RAISE(ABORT,'immutable authorization decision'); END""")
    connection.execute("""CREATE TRIGGER authorization_decision_storage_guard
        BEFORE INSERT ON authorization_decisions
        WHEN NEW.scope_content_digest IS NULL
          OR NEW.storage_scope_marker != X'763336'
          OR NEW.storage_decision_marker != X'763336'
        BEGIN SELECT RAISE(ABORT,'authorization decision storage differs'); END""")


AUTHORISATION_SCOPE_CONTENT_MIGRATION_STATEMENTS = (
    "validate exact v35 schema, history and every canonical decision before conversion",
    "deduplicate canonical scope bytes by SHA-256 content digest",
    "replace repeated decision blobs with fixed v36 markers and a scope-content foreign key",
    "retain immutable scope and decision guards including non-null storage binding",
)
AUTHORISATION_SCOPE_CONTENT_MIGRATION_CHECKSUM = digest_canonical({
    "version": AUTHORISATION_SCOPE_CONTENT_SCHEMA_VERSION,
    "name": AUTHORISATION_SCOPE_CONTENT_MIGRATION_NAME,
    "statements": list(AUTHORISATION_SCOPE_CONTENT_MIGRATION_STATEMENTS),
})
AUTHORISATION_SCOPE_CONTENT_MIGRATION = AuthorisationScopeContentMigrationRecord(
    AUTHORISATION_SCOPE_CONTENT_SCHEMA_VERSION,
    AUTHORISATION_SCOPE_CONTENT_MIGRATION_NAME,
    AUTHORISATION_SCOPE_CONTENT_MIGRATION_CHECKSUM,
)
