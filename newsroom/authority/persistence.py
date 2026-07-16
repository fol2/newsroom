from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .auth import AuthenticationProof
from .models import SemanticCommand


class AuthorityPersistenceError(RuntimeError):
    pass


class AuthoritySchemaError(AuthorityPersistenceError):
    pass


class AuthorityWriterBusy(AuthorityPersistenceError):
    pass


class ExpectedVersionConflict(AuthorityPersistenceError):
    pass


class IdempotencyConflict(AuthorityPersistenceError):
    pass


class UnknownCausation(AuthorityPersistenceError):
    pass


class UnsupportedPayloadMode(AuthorityPersistenceError):
    pass


@dataclass(frozen=True, slots=True)
class CommittedCommand:
    command_id: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    ledger_seq: int
    event_id: str
    result_digest: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class CommandResultRecord:
    command_id: str
    result_digest: str
    result_bytes: bytes


@dataclass(frozen=True, slots=True)
class LedgerEventRecord:
    ledger_seq: int
    event_id: str
    event_type: str
    event_schema_version: int
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    command_id: str
    payload_id: str
    principal_id: str
    authentication_context_id: str
    authorization_request_digest: str
    authorization_decision_id: str
    command_definition_version: str
    command_definition_digest: str
    correlation_id: str | None
    causation_kind: str | None
    causation_identifier: str | None
    causation_external_system: str | None
    security_scope: str
    retention_scope: str
    trust_scope: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class AuthenticationContextRecord:
    authentication_context_id: str
    principal_id: str
    authority_domain: str
    authentication_method: str
    assurance_class: str
    credential_binding_digest: str
    authenticated_at: str
    expires_at: str
    canonical_digest: str


@dataclass(frozen=True, slots=True)
class AuthorizationDecisionRecord:
    authorization_decision_id: str
    authentication_context_id: str
    authorization_request_digest: str
    authorization_policy_version: str
    effective_scopes: tuple[str, ...]
    effective_scope_digest: str
    allowed: bool
    reason_code: str
    decided_at: str
    canonical_digest: str


@dataclass(frozen=True, slots=True)
class EventProvenanceRecord:
    event: LedgerEventRecord
    authentication: AuthenticationContextRecord
    authorization: AuthorizationDecisionRecord


class AuthorityCommands:
    """Public command facade; no persistence object is exposed."""

    __slots__ = ("__execute",)

    def __init__(
        self,
        execute: Callable[[SemanticCommand, AuthenticationProof], CommittedCommand],
    ) -> None:
        self.__execute = execute

    def execute(
        self, command: SemanticCommand, *, proof: AuthenticationProof
    ) -> CommittedCommand:
        return self.__execute(command, proof)


class AuthorityEvents:
    """Authenticated metadata reader; it never hydrates payload bytes."""

    __slots__ = ("__read", "__provenance", "__result")

    def __init__(
        self,
        read: Callable[[int, int, AuthenticationProof], tuple[LedgerEventRecord, ...]],
        provenance: Callable[[str, AuthenticationProof], EventProvenanceRecord],
        result: Callable[[str, AuthenticationProof], CommandResultRecord],
    ) -> None:
        self.__read = read
        self.__provenance = provenance
        self.__result = result

    def after(
        self,
        ledger_seq: int,
        *,
        limit: int = 100,
        proof: AuthenticationProof,
    ) -> tuple[LedgerEventRecord, ...]:
        return self.__read(ledger_seq, limit, proof)

    def provenance(
        self, event_id: str, *, proof: AuthenticationProof
    ) -> EventProvenanceRecord:
        return self.__provenance(event_id, proof)

    def command_result(
        self, command_id: str, *, proof: AuthenticationProof
    ) -> CommandResultRecord:
        return self.__result(command_id, proof)
