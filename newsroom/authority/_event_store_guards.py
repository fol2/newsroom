from __future__ import annotations

import sqlite3

from ._capability import _AuthorizedCommandGrant
from .canonical import canonical_json_bytes, digest_bytes, digest_canonical
from .persistence import (
    AuthorityPersistenceError,
    CommandDefinitionRecord,
    EventProvenanceRecord,
    EventReadPolicy,
)
from .types import UtcTimestamp


class _ExactAuthorityGuards:
    """Cross-record checks that cannot be expressed by IDs or FKs alone."""

    def _definition_record_from_row(
        self, row: sqlite3.Row
    ) -> CommandDefinitionRecord:
        data = bytes(row["canonical_bytes"])
        value = self._decode_canonical(data)  # type: ignore[attr-defined]
        digest = str(row["definition_digest"])
        schema_digest = str(row["payload_schema_contract_digest"])
        if digest_bytes(data) != digest:
            raise AuthorityPersistenceError(
                "stored command definition digest mismatch"
            )
        if (
            not isinstance(value, dict)
            or value.get("command_type") != str(row["command_type"])
            or value.get("definition_version")
            != str(row["definition_version"])
            or value.get("payload_schema_contract_digest")
            != schema_digest
        ):
            raise AuthorityPersistenceError(
                "stored command definition fields mismatch"
            )
        return CommandDefinitionRecord(
            definition_digest=digest,
            command_type=str(row["command_type"]),
            definition_version=str(row["definition_version"]),
            payload_schema_contract_digest=schema_digest,
            canonical_bytes=data,
        )

    def _persist_security_records(
        self,
        conn: sqlite3.Connection,
        *,
        authentication: object,
        request: object,
        decision: object,
        recorded_at: str,
    ) -> None:
        super()._persist_security_records(  # type: ignore[misc]
            conn,
            authentication=authentication,
            request=request,
            decision=decision,
            recorded_at=recorded_at,
        )
        expected = (
            (
                "authentication_contexts",
                "authentication_context_id",
                str(authentication.authentication_context_id),  # type: ignore[attr-defined]
                canonical_json_bytes(authentication.canonical_value()),  # type: ignore[attr-defined]
                authentication.digest,  # type: ignore[attr-defined]
                "canonical_digest",
            ),
            (
                "authorization_requests",
                "request_digest",
                request.request_digest,  # type: ignore[attr-defined]
                canonical_json_bytes(request.canonical_value()),  # type: ignore[attr-defined]
                request.digest,  # type: ignore[attr-defined]
                "canonical_record_digest",
            ),
            (
                "authorization_decisions",
                "authorization_decision_id",
                str(decision.authorization_decision_id),  # type: ignore[attr-defined]
                canonical_json_bytes(decision.canonical_value()),  # type: ignore[attr-defined]
                decision.digest,  # type: ignore[attr-defined]
                "canonical_digest",
            ),
        )
        for (
            table,
            identity_column,
            identity,
            expected_bytes,
            expected_digest,
            digest_column,
        ) in expected:
            row = conn.execute(
                f"SELECT canonical_bytes,{digest_column} FROM {table} "
                f"WHERE {identity_column}=?",
                (identity,),
            ).fetchone()
            if (
                row is None
                or bytes(row["canonical_bytes"]) != expected_bytes
                or str(row[digest_column]) != expected_digest
            ):
                raise AuthorityPersistenceError(
                    f"{table} identity already belongs to different provenance"
                )

    @staticmethod
    def _validate_relational_invariants(
        conn: sqlite3.Connection,
    ) -> None:
        # Preserve the base exact-head, one-version/audit/event and envelope checks.
        from ._event_store_base import _EventStoreBase

        _EventStoreBase._validate_relational_invariants(conn)
        mismatch = conn.execute(
            "SELECT e.event_id FROM ledger_events e "
            "JOIN authentication_contexts a "
            "ON a.authentication_context_id=e.authentication_context_id "
            "JOIN authorization_requests r "
            "ON r.request_digest=e.authorization_request_digest "
            "JOIN authorization_decisions z "
            "ON z.authorization_decision_id=e.authorization_decision_id "
            "JOIN command_definitions d "
            "ON d.definition_digest=e.command_definition_digest "
            "WHERE e.principal_id != a.principal_id "
            "OR r.authentication_context_id != e.authentication_context_id "
            "OR r.principal_id != a.principal_id "
            "OR r.authority_domain != a.authority_domain "
            "OR z.authentication_context_id != e.authentication_context_id "
            "OR z.authorization_request_digest != "
            "e.authorization_request_digest "
            "OR z.allowed != 1 "
            "OR d.payload_schema_contract_digest != "
            "e.payload_schema_contract_digest LIMIT 1"
        ).fetchone()
        if mismatch is not None:
            raise AuthorityPersistenceError(
                "event security or definition provenance is inconsistent"
            )

    def event_provenance(
        self, *, event_id: str, policy: EventReadPolicy
    ) -> EventProvenanceRecord:
        provenance = super().event_provenance(  # type: ignore[misc]
            event_id=event_id, policy=policy
        )
        event = provenance.event
        authentication = provenance.authentication
        request = provenance.authorization_request
        decision = provenance.authorization_decision
        definition = provenance.command_definition

        if (
            request.principal_id != authentication.principal_id
            or request.authority_domain != authentication.authority_domain
        ):
            raise AuthorityPersistenceError(
                "authorization request is not bound to authentication provenance"
            )
        expected_scope_digest = digest_canonical(
            {
                "authentication_context_digest": (
                    authentication.canonical_digest
                ),
                "effective_scopes": list(decision.effective_scopes),
            }
        )
        if decision.effective_scope_digest != expected_scope_digest:
            raise AuthorityPersistenceError(
                "authorization scopes are not bound to authentication provenance"
            )
        if not decision.allowed:
            raise AuthorityPersistenceError(
                "a committed event cannot reference a denied decision"
            )
        authenticated_at = UtcTimestamp.parse(
            authentication.authenticated_at
        )
        expires_at = UtcTimestamp.parse(authentication.expires_at)
        decided_at = UtcTimestamp.parse(decision.decided_at)
        if not (
            authenticated_at.value
            <= decided_at.value
            < expires_at.value
        ):
            raise AuthorityPersistenceError(
                "authorization decision is outside authentication validity"
            )
        if (
            definition.payload_schema_contract_digest
            != event.payload_schema_contract_digest
        ):
            raise AuthorityPersistenceError(
                "event schema contract differs from command definition"
            )

        request_value = self._decode_canonical(  # type: ignore[attr-defined]
            request.canonical_bytes
        )
        expected_request_fields = {
            "command_definition_digest": event.command_definition_digest,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "event_type": event.event_type,
            "event_schema_version": event.event_schema_version,
            "payload_mode": event.payload_mode,
            "payload_schema_version": event.payload_schema_version,
            "payload_schema_contract_version": (
                event.payload_schema_contract_version
            ),
            "payload_schema_contract_digest": (
                event.payload_schema_contract_digest
            ),
            "payload_canonicalizer_version": (
                event.payload_canonicalizer_version
            ),
            "trust_scope": event.trust_scope,
            "security_scope": event.security_scope,
            "retention_scope": event.retention_scope,
        }
        if not isinstance(request_value, dict) or any(
            request_value.get(field) != value
            for field, value in expected_request_fields.items()
        ):
            raise AuthorityPersistenceError(
                "event routing metadata differs from exact authorization request"
            )
        return provenance
