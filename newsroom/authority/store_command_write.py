from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .auth import AuthorizationDecision, VerifiedAuthenticationContext
from .models import SemanticCommand
from .store_base import ExpectedVersionConflict


@dataclass(frozen=True, slots=True)
class CommitRows:
    command_id: str
    event_id: str
    audit_id: str
    aggregate_id: str
    current_version: int | None
    new_version: int
    ledger_seq: int
    recorded_at: str
    result_digest: str
    result_bytes: bytes
    audit_detail_digest: str


def persist_commit(
    conn: sqlite3.Connection,
    *,
    command: SemanticCommand,
    authentication: VerifiedAuthenticationContext,
    authorization: AuthorizationDecision,
    idempotency_namespace: str,
    semantic_request_digest: str,
    rows: CommitRows,
) -> None:
    conn.execute(
        """INSERT INTO authority_commands(
            command_id, idempotency_namespace, idempotency_key,
            semantic_request_digest, command_type, aggregate_type,
            aggregate_id, expected_aggregate_version,
            payload_schema_version, payload_digest, payload_object_ref,
            principal_id, authentication_context_id,
            authorization_decision_id, authorization_policy_version,
            effective_scope_digest, issued_at, correlation_id,
            causation_id, producer_version, recorded_at,
            result_digest, result_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rows.command_id,
            idempotency_namespace,
            command.idempotency_key,
            semantic_request_digest,
            command.command_type,
            command.aggregate_type,
            rows.aggregate_id,
            command.expected_aggregate_version,
            command.payload_schema_version,
            command.payload_digest,
            command.payload_object_ref,
            authentication.principal_id,
            str(authentication.authentication_context_id),
            str(authorization.authorization_decision_id),
            authorization.authorization_policy_version,
            authorization.effective_scope_digest,
            command.issued_at.to_text(),
            command.correlation_id,
            command.causation_id,
            command.producer_version,
            rows.recorded_at,
            rows.result_digest,
            rows.result_bytes,
        ),
    )
    _write_aggregate_head(conn, command=command, rows=rows)
    conn.execute(
        """INSERT INTO authority_aggregate_versions(
            aggregate_type, aggregate_id, aggregate_version, command_id,
            trust_scope, payload_schema_version, payload_digest,
            payload_object_ref, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            command.aggregate_type,
            rows.aggregate_id,
            rows.new_version,
            rows.command_id,
            command.trust_scope.value,
            command.payload_schema_version,
            command.payload_digest,
            command.payload_object_ref,
            rows.recorded_at,
        ),
    )
    conn.execute(
        """INSERT INTO authority_audit_events(
            audit_id, command_id, event_type, principal_id,
            authentication_context_id, authorization_decision_id,
            authorization_policy_version, effective_scope_digest,
            semantic_request_digest, detail_digest, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rows.audit_id,
            rows.command_id,
            "COMMAND_COMMITTED",
            authentication.principal_id,
            str(authentication.authentication_context_id),
            str(authorization.authorization_decision_id),
            authorization.authorization_policy_version,
            authorization.effective_scope_digest,
            semantic_request_digest,
            rows.audit_detail_digest,
            rows.recorded_at,
        ),
    )
    conn.execute(
        """INSERT INTO ledger_events(
            ledger_seq, event_id, event_type, event_schema_version,
            aggregate_type, aggregate_id, aggregate_version, recorded_at,
            command_id, principal_id, authentication_context_id,
            authorization_decision_id, correlation_id, causation_id,
            producer_version, payload_digest, payload_object_ref,
            security_scope, retention_scope, trust_scope
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rows.ledger_seq,
            rows.event_id,
            command.event_type,
            command.event_schema_version,
            command.aggregate_type,
            rows.aggregate_id,
            rows.new_version,
            rows.recorded_at,
            rows.command_id,
            authentication.principal_id,
            str(authentication.authentication_context_id),
            str(authorization.authorization_decision_id),
            command.correlation_id,
            command.causation_id,
            command.producer_version,
            command.payload_digest,
            command.payload_object_ref,
            command.security_scope,
            command.retention_scope,
            command.trust_scope.value,
        ),
    )


def _write_aggregate_head(
    conn: sqlite3.Connection, *, command: SemanticCommand, rows: CommitRows
) -> None:
    if rows.current_version is None:
        conn.execute(
            "INSERT INTO authority_aggregates("
            "aggregate_type, aggregate_id, current_version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                command.aggregate_type,
                rows.aggregate_id,
                rows.new_version,
                rows.recorded_at,
                rows.recorded_at,
            ),
        )
        return
    updated = conn.execute(
        "UPDATE authority_aggregates "
        "SET current_version = ?, updated_at = ? "
        "WHERE aggregate_type = ? AND aggregate_id = ? AND current_version = ?",
        (
            rows.new_version,
            rows.recorded_at,
            command.aggregate_type,
            rows.aggregate_id,
            rows.current_version,
        ),
    )
    if updated.rowcount != 1:
        raise ExpectedVersionConflict("aggregate version changed during fenced command")
