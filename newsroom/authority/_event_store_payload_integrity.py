from __future__ import annotations

import sqlite3

from .canonical import digest_bytes, validate_sha256_digest
from .persistence import (
    AuthorityPersistenceError,
    PayloadId,
    UnsupportedPayloadMode,
)
from .types import (
    AggregateId,
    AuthenticationContextId,
    AuthorizationDecisionId,
    CausationKind,
    CausationRef,
    CommandId,
    CorrelationId,
    EventId,
    PayloadMode,
    TrustScope,
    UtcTimestamp,
    require_scope,
    require_token,
)


class _PayloadAndEnvelopeIntegrity:
    """Rehash retained payloads and validate typed event routing values."""

    def _validate_immutable_records(
        self, conn: sqlite3.Connection
    ) -> None:
        super()._validate_immutable_records(conn)  # type: ignore[misc]
        for row in conn.execute(
            "SELECT * FROM authority_payloads"
        ).fetchall():
            PayloadId.parse(str(row["payload_id"]))
            mode = PayloadMode(str(row["mode"]))
            if mode is PayloadMode.OBJECT_ADMISSION:
                raise UnsupportedPayloadMode(
                    "object-admission authority belongs to Increment 1A2b"
                )
            if row["payload_bytes"] is None:
                raise AuthorityPersistenceError(
                    "A2a retained payload bytes are missing"
                )
            data = bytes(row["payload_bytes"])
            expected_digest = str(row["payload_digest"])
            validate_sha256_digest(
                expected_digest, field="payload_digest"
            )
            if digest_bytes(data) != expected_digest:
                raise AuthorityPersistenceError(
                    "retained payload digest does not match exact bytes"
                )
            if mode is PayloadMode.NO_PAYLOAD and data != b"":
                raise AuthorityPersistenceError(
                    "NO_PAYLOAD authority must retain exact empty bytes"
                )
            if mode is PayloadMode.INLINE and not data:
                raise AuthorityPersistenceError(
                    "INLINE authority cannot retain an empty payload"
                )
            contract = conn.execute(
                "SELECT * FROM payload_schema_contracts "
                "WHERE contract_digest=?",
                (str(row["schema_contract_digest"]),),
            ).fetchone()
            if contract is None:
                raise AuthorityPersistenceError(
                    "payload schema contract is missing"
                )
            if (
                str(contract["schema_version"])
                != str(row["schema_version"])
                or str(contract["payload_mode"]) != mode.value
                or str(contract["contract_version"])
                != str(row["schema_contract_version"])
                or str(
                    contract["canonicalizer_implementation_version"]
                )
                != str(row["canonicalizer_implementation_version"])
            ):
                raise AuthorityPersistenceError(
                    "payload does not match its immutable schema contract"
                )

        for row in conn.execute(
            "SELECT * FROM ledger_events ORDER BY ledger_seq"
        ).fetchall():
            self._validate_event_types(row)

    @staticmethod
    def _validate_event_types(row: sqlite3.Row) -> None:
        ledger_seq = int(row["ledger_seq"])
        aggregate_version = int(row["aggregate_version"])
        event_schema_version = int(row["event_schema_version"])
        if ledger_seq <= 0 or aggregate_version <= 0 or event_schema_version <= 0:
            raise AuthorityPersistenceError(
                "event sequence and versions must be positive"
            )
        EventId.parse(str(row["event_id"]))
        CommandId.parse(str(row["command_id"]))
        PayloadId.parse(str(row["payload_id"]))
        AggregateId.parse(str(row["aggregate_id"]))
        AuthenticationContextId.parse(
            str(row["authentication_context_id"])
        )
        AuthorizationDecisionId.parse(
            str(row["authorization_decision_id"])
        )
        UtcTimestamp.parse(str(row["recorded_at"]))
        for field in (
            "event_type",
            "aggregate_type",
            "producer_version",
            "command_definition_version",
            "payload_schema_version",
            "payload_schema_contract_version",
            "payload_canonicalizer_version",
            "principal_id",
        ):
            require_token(str(row[field]), field=field)
        for field in ("security_scope", "retention_scope"):
            require_scope(str(row[field]), field=field)
        TrustScope(str(row["trust_scope"]))
        PayloadMode(str(row["payload_mode"]))
        for field in (
            "command_definition_digest",
            "payload_schema_contract_digest",
            "payload_digest",
            "authorization_request_digest",
        ):
            validate_sha256_digest(str(row[field]), field=field)
        if row["correlation_id"] is not None:
            CorrelationId.parse(str(row["correlation_id"]))
        if row["causation_kind"] is not None:
            CausationRef(
                kind=CausationKind(str(row["causation_kind"])),
                identifier=str(row["causation_identifier"]),
                external_system=(
                    None
                    if row["causation_external_system"] is None
                    else str(row["causation_external_system"])
                ),
            )
