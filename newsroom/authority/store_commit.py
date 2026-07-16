from __future__ import annotations

from .auth import AuthorizationDecision, VerifiedAuthenticationContext
from .canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from .models import CommittedCommand, SemanticCommand
from .store_base import (
    ExpectedVersionConflict,
    IdempotencyConflict,
    UnknownObjectReference,
)
from .store_command_write import CommitRows, persist_commit
from .types import AggregateVersion, AuditId, CommandId, EventId


class AuthorityStoreCommitMixin:
    def commit_command(
        self,
        *,
        command: SemanticCommand,
        authentication: VerifiedAuthenticationContext,
        authorization: AuthorizationDecision,
        idempotency_namespace: str,
        semantic_request_digest: str,
    ) -> CommittedCommand:
        authorization.require_allowed()
        validate_sha256_digest(idempotency_namespace, field="idempotency_namespace")
        validate_sha256_digest(
            semantic_request_digest, field="semantic_request_digest"
        )
        with self._write_transaction():
            replay = self._find_replay(
                namespace=idempotency_namespace,
                key=command.idempotency_key,
                request_digest=semantic_request_digest,
            )
            if replay is not None:
                return replay
            self._require_registered_object(command.payload_object_ref)
            aggregate_id = str(command.aggregate_id)
            current_version, new_version = self._resolve_version(
                command, aggregate_id=aggregate_id
            )
            rows = self._prepare_rows(
                command=command,
                authentication=authentication,
                authorization=authorization,
                aggregate_id=aggregate_id,
                current_version=current_version,
                new_version=new_version,
                semantic_request_digest=semantic_request_digest,
            )
            persist_commit(
                self._conn,
                command=command,
                authentication=authentication,
                authorization=authorization,
                idempotency_namespace=idempotency_namespace,
                semantic_request_digest=semantic_request_digest,
                rows=rows,
            )
            return CommittedCommand(
                command_id=rows.command_id,
                aggregate_type=command.aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_version=AggregateVersion(new_version),
                ledger_seq=rows.ledger_seq,
                event_id=rows.event_id,
                result_digest=rows.result_digest,
                replayed=False,
            )

    def _find_replay(
        self, *, namespace: str, key: str, request_digest: str
    ) -> CommittedCommand | None:
        existing = self._conn.execute(
            "SELECT semantic_request_digest, result_digest, result_bytes "
            "FROM authority_commands "
            "WHERE idempotency_namespace = ? AND idempotency_key = ?",
            (namespace, key),
        ).fetchone()
        if existing is None:
            return None
        if str(existing["semantic_request_digest"]) != request_digest:
            raise IdempotencyConflict(
                "idempotency identity was reused for a different semantic request"
            )
        return self._decode_result(
            bytes(existing["result_bytes"]),
            str(existing["result_digest"]),
            replayed=True,
        )

    def _require_registered_object(self, object_ref: str | None) -> None:
        if object_ref is None:
            return
        object_row = self._conn.execute(
            "SELECT 1 FROM governed_objects WHERE digest = ?", (object_ref,)
        ).fetchone()
        if object_row is None:
            raise UnknownObjectReference(
                "command references an unregistered governed object"
            )

    def _resolve_version(
        self, command: SemanticCommand, *, aggregate_id: str
    ) -> tuple[int | None, int]:
        row = self._conn.execute(
            "SELECT current_version FROM authority_aggregates "
            "WHERE aggregate_type = ? AND aggregate_id = ?",
            (command.aggregate_type, aggregate_id),
        ).fetchone()
        current = None if row is None else int(row["current_version"])
        if current is None:
            if command.expected_aggregate_version != 0:
                raise ExpectedVersionConflict(
                    "create command requires expected aggregate version 0"
                )
            return None, 1
        if command.expected_aggregate_version != current:
            raise ExpectedVersionConflict(
                f"expected aggregate version {command.expected_aggregate_version}, "
                f"current is {current}"
            )
        return current, current + 1

    def _prepare_rows(
        self,
        *,
        command: SemanticCommand,
        authentication: VerifiedAuthenticationContext,
        authorization: AuthorizationDecision,
        aggregate_id: str,
        current_version: int | None,
        new_version: int,
        semantic_request_digest: str,
    ) -> CommitRows:
        command_id = str(CommandId.new())
        event_id = str(EventId.new())
        recorded_at = self._clock().to_text()
        ledger_seq = self._next_ledger_seq()
        result_bytes = canonical_json_bytes(
            {
                "command_id": command_id,
                "aggregate_type": command.aggregate_type,
                "aggregate_id": aggregate_id,
                "aggregate_version": new_version,
                "ledger_seq": ledger_seq,
                "event_id": event_id,
            }
        )
        return CommitRows(
            command_id=command_id,
            event_id=event_id,
            audit_id=str(AuditId.new()),
            aggregate_id=aggregate_id,
            current_version=current_version,
            new_version=new_version,
            ledger_seq=ledger_seq,
            recorded_at=recorded_at,
            result_digest=digest_bytes(result_bytes),
            result_bytes=result_bytes,
            audit_detail_digest=digest_canonical(
                {
                    "command_type": command.command_type,
                    "aggregate_type": command.aggregate_type,
                    "aggregate_id": aggregate_id,
                    "expected_aggregate_version": command.expected_aggregate_version,
                    "payload_schema_version": command.payload_schema_version,
                    "payload_digest": command.payload_digest,
                    "payload_object_ref": command.payload_object_ref,
                    "principal_id": authentication.principal_id,
                    "authentication_context_id": str(
                        authentication.authentication_context_id
                    ),
                    "authorization_decision_id": str(
                        authorization.authorization_decision_id
                    ),
                    "authorization_policy_version": (
                        authorization.authorization_policy_version
                    ),
                    "effective_scope_digest": authorization.effective_scope_digest,
                    "semantic_request_digest": semantic_request_digest,
                }
            ),
        )
