from __future__ import annotations

from dataclasses import dataclass

from .canonical import digest_bytes

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return digest_bytes(self.sql.encode("utf-8"))

    def statements(self) -> tuple[str, ...]:
        return tuple(
            statement.strip()
            for statement in self.sql.split(";")
            if statement.strip()
        )


_INITIAL_SQL = """
CREATE TABLE governed_objects (
    digest TEXT PRIMARY KEY,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    object_class TEXT NOT NULL,
    rights_status TEXT NOT NULL CHECK (rights_status IN ('PERMITTED', 'RESTRICTED')),
    security_scope TEXT NOT NULL,
    retention_scope TEXT NOT NULL,
    installed_at TEXT NOT NULL,
    CHECK (length(digest) = 71),
    CHECK (substr(digest, 1, 7) = 'sha256:')
) STRICT;

CREATE TABLE authority_aggregates (
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    current_version INTEGER NOT NULL CHECK (current_version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (aggregate_type, aggregate_id)
) STRICT;

CREATE TABLE authority_commands (
    command_id TEXT PRIMARY KEY,
    idempotency_namespace TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    semantic_request_digest TEXT NOT NULL,
    command_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    expected_aggregate_version INTEGER NOT NULL CHECK (expected_aggregate_version >= 0),
    payload_schema_version TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    payload_object_ref TEXT REFERENCES governed_objects(digest),
    principal_id TEXT NOT NULL,
    authentication_context_id TEXT NOT NULL,
    authorization_decision_id TEXT NOT NULL,
    authorization_policy_version TEXT NOT NULL,
    effective_scope_digest TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    correlation_id TEXT,
    causation_id TEXT,
    producer_version TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    result_digest TEXT NOT NULL,
    result_bytes BLOB NOT NULL,
    UNIQUE (idempotency_namespace, idempotency_key),
    CHECK (length(result_bytes) > 0)
) STRICT;

CREATE TABLE authority_aggregate_versions (
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL CHECK (aggregate_version > 0),
    command_id TEXT NOT NULL UNIQUE REFERENCES authority_commands(command_id),
    trust_scope TEXT NOT NULL CHECK (trust_scope IN ('OBSERVED', 'PROPOSED', 'ADMITTED')),
    payload_schema_version TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    payload_object_ref TEXT REFERENCES governed_objects(digest),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (aggregate_type, aggregate_id, aggregate_version),
    FOREIGN KEY (aggregate_type, aggregate_id)
        REFERENCES authority_aggregates(aggregate_type, aggregate_id)
) STRICT;

CREATE TABLE authority_audit_events (
    audit_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL UNIQUE REFERENCES authority_commands(command_id),
    event_type TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    authentication_context_id TEXT NOT NULL,
    authorization_decision_id TEXT NOT NULL,
    authorization_policy_version TEXT NOT NULL,
    effective_scope_digest TEXT NOT NULL,
    semantic_request_digest TEXT NOT NULL,
    detail_digest TEXT NOT NULL,
    recorded_at TEXT NOT NULL
) STRICT;

CREATE TABLE ledger_events (
    ledger_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    event_schema_version INTEGER NOT NULL CHECK (event_schema_version > 0),
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL CHECK (aggregate_version > 0),
    recorded_at TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES authority_commands(command_id),
    principal_id TEXT NOT NULL,
    authentication_context_id TEXT NOT NULL,
    authorization_decision_id TEXT NOT NULL,
    correlation_id TEXT,
    causation_id TEXT,
    producer_version TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    payload_object_ref TEXT REFERENCES governed_objects(digest),
    security_scope TEXT NOT NULL,
    retention_scope TEXT NOT NULL,
    trust_scope TEXT NOT NULL CHECK (trust_scope IN ('OBSERVED', 'PROPOSED', 'ADMITTED'))
) STRICT;

CREATE INDEX ledger_events_aggregate_idx
    ON ledger_events(aggregate_type, aggregate_id, aggregate_version);
CREATE INDEX ledger_events_recorded_idx ON ledger_events(recorded_at, ledger_seq);
""".strip()

MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="initial_authority_foundation", sql=_INITIAL_SQL),
)
