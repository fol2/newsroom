"""Atomic v38 lossless authorization-request residual storage."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping

from .authorisation_scope_content_migrations import (
    AuthorisationScopeContentMigrationRecord,
)
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical

AUTHORIZATION_REQUEST_STORAGE_SCHEMA_VERSION = 38
AUTHORIZATION_REQUEST_STORAGE_MIGRATION_NAME = (
    "authorization_request_residual_storage_v38"
)
AUTHORIZATION_REQUEST_STORAGE_PREDECESSOR_FINGERPRINT = (
    "sha256:4003bc1eb0124845189a50e561b39da33bfde75ab8eabd19ddf9c7f807417d3d"
)
AUTHORIZATION_REQUEST_INDEXED_FIELDS = (
    "request_digest",
    "authentication_context_id",
    "principal_id",
    "authority_domain",
    "operation_type",
    "required_scope",
)
AUTHORIZATION_REQUEST_STORAGE_MARKER = b"v38"


def _canonical_object(data: bytes) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
        if not isinstance(value, dict) or canonical_json_bytes(value) != data:
            raise ValueError("noncanonical object")
    except (UnicodeError, ValueError) as exc:
        raise ValueError("stored authorization request is not canonical") from exc
    return value


def _indexed_request_fields(row: Mapping[str, object]) -> dict[str, object]:
    return {name: str(row[name]) for name in AUTHORIZATION_REQUEST_INDEXED_FIELDS}


def authorization_request_residual_from_v37_row(
    row: Mapping[str, object],
) -> bytes:
    """Authenticate a v37 request and return its lossless residual object."""

    data = bytes(row["canonical_bytes"])
    value = _canonical_object(data)
    indexed = _indexed_request_fields(row)
    if any(value.get(name) != expected for name, expected in indexed.items()):
        raise ValueError("stored authorization request fields differ")
    if digest_bytes(data) != str(row["canonical_record_digest"]):
        raise ValueError("stored authorization request record digest differs")
    unsigned = dict(value)
    unsigned.pop("request_digest", None)
    if digest_canonical(unsigned) != indexed["request_digest"]:
        raise ValueError("stored authorization request digest differs")
    return canonical_json_bytes(
        {key: item for key, item in value.items() if key not in indexed}
    )


def authorization_request_bytes_from_v38_row(
    row: Mapping[str, object],
) -> bytes:
    """Reconstruct the original canonical request bytes from a v38 row."""

    if bytes(row["storage_request_marker"]) != AUTHORIZATION_REQUEST_STORAGE_MARKER:
        raise ValueError("stored authorization request format differs")
    residual = _canonical_object(bytes(row["storage_request_residual"]))
    collisions = set(residual).intersection(AUTHORIZATION_REQUEST_INDEXED_FIELDS)
    if collisions:
        raise ValueError("stored authorization request residual collides")
    return canonical_json_bytes({**residual, **_indexed_request_fields(row)})


def _rows(
    connection: sqlite3.Connection, *, after_rowid: int = 0
) -> Iterator[dict[str, object]]:
    cursor = connection.execute(
        "SELECT rowid,* FROM authorization_requests WHERE rowid>? "
        "ORDER BY rowid LIMIT 256",
        (after_rowid,),
    )
    names = tuple(item[0] for item in cursor.description)
    for row in cursor:
        yield dict(zip(names, row, strict=True))


def migrate_authorization_request_storage(
    connection: sqlite3.Connection,
    *,
    expected_history: tuple[tuple[int, str, str], ...],
) -> None:
    from .migrations import schema_fingerprint

    if not connection.in_transaction:
        raise sqlite3.DatabaseError("v38 migration requires an active transaction")
    if (
        connection.execute("PRAGMA user_version").fetchone()[0]
        not in (0, 34, 35, 36, 37)
        or schema_fingerprint(connection)
        != AUTHORIZATION_REQUEST_STORAGE_PREDECESSOR_FINGERPRINT
        or tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT version,name,checksum FROM authority_migrations "
                "ORDER BY version"
            )
        )
        != expected_history
    ):
        raise sqlite3.DatabaseError("v38 migration requires exact checked schema v37")

    def residual(row: Mapping[str, object]) -> bytes:
        try:
            return authorization_request_residual_from_v37_row(row)
        except ValueError as exc:
            raise sqlite3.IntegrityError(
                "stored authorization request differs before v38 conversion"
            ) from exc

    # Authenticate the complete predecessor stream before mutating any request.
    after_rowid = 0
    while True:
        batch = _rows(connection, after_rowid=after_rowid)
        seen = False
        for row in batch:
            residual(row)
            after_rowid = int(row["rowid"])
            seen = True
        if not seen:
            break

    connection.execute("DROP TRIGGER immutable_authorization_requests_update")
    after_rowid = 0
    while True:
        batch = _rows(connection, after_rowid=after_rowid)
        seen = False
        for row in batch:
            residual_bytes = residual(row)
            connection.execute(
                "UPDATE authorization_requests SET canonical_bytes=? WHERE rowid=?",
                (residual_bytes, row["rowid"]),
            )
            after_rowid = int(row["rowid"])
            seen = True
        if not seen:
            break
    connection.execute(
        "ALTER TABLE authorization_requests RENAME COLUMN canonical_bytes "
        "TO storage_request_residual"
    )
    connection.execute(
        "ALTER TABLE authorization_requests ADD COLUMN storage_request_marker "
        "BLOB NOT NULL DEFAULT X'763338' CHECK(storage_request_marker=X'763338')"
    )
    connection.execute("""CREATE TRIGGER immutable_authorization_requests_update
        BEFORE UPDATE ON authorization_requests BEGIN
        SELECT RAISE(ABORT,'immutable authorization request'); END""")
    connection.execute("""CREATE TRIGGER authorization_request_storage_guard
        BEFORE INSERT ON authorization_requests
        WHEN NEW.storage_request_marker != X'763338'
        BEGIN SELECT RAISE(ABORT,'authorization request storage differs'); END""")


AUTHORIZATION_REQUEST_STORAGE_MIGRATION_STATEMENTS = (
    "validate exact v37 schema, history and every full canonical request "
    "before conversion",
    "replace each request canonical value with its canonical residual in a "
    "second rowid-keyset pass",
    "rename residual storage and require the exact v38 marker",
    "preserve both request digests, indexed fields, timestamps, keys, references and immutable guards",
)
AUTHORIZATION_REQUEST_STORAGE_MIGRATION_CHECKSUM = digest_canonical(
    {
        "version": AUTHORIZATION_REQUEST_STORAGE_SCHEMA_VERSION,
        "name": AUTHORIZATION_REQUEST_STORAGE_MIGRATION_NAME,
        "statements": list(AUTHORIZATION_REQUEST_STORAGE_MIGRATION_STATEMENTS),
    }
)
AUTHORIZATION_REQUEST_STORAGE_MIGRATION = AuthorisationScopeContentMigrationRecord(
    AUTHORIZATION_REQUEST_STORAGE_SCHEMA_VERSION,
    AUTHORIZATION_REQUEST_STORAGE_MIGRATION_NAME,
    AUTHORIZATION_REQUEST_STORAGE_MIGRATION_CHECKSUM,
)
