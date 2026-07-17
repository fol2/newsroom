from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
from typing import Any

from ._security import (
    _AuthorizationDecision,
    _AuthorizationRequest,
    _VerifiedAuthenticationContext,
    _effective_scope_digest,
)
from .canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from .models import CommandDefinition
from .policy import CommandRegistry, PayloadSchemaRegistry
from .types import AggregateId, ObjectAdmissionId, PayloadMode


class InvalidCommitCapability(PermissionError):
    """Raised when persistence receives a fabricated or mismatched commit grant."""


@dataclass(frozen=True, slots=True)
class _ResolvedPayload:
    kind: str
    schema_version: str
    schema_contract_version: str
    schema_contract_digest: str
    canonicalizer_version: str
    digest: str
    inline_bytes: bytes | None
    object_admission_id: ObjectAdmissionId | None
    blob_digest: str | None
    object_class: str | None
    allowed_use: str | None

    def canonical_value(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "schema_version": self.schema_version,
            "schema_contract_version": self.schema_contract_version,
            "schema_contract_digest": self.schema_contract_digest,
            "canonicalizer_version": self.canonicalizer_version,
            "digest": self.digest,
            "inline_digest": (
                None
                if self.inline_bytes is None
                else digest_bytes(self.inline_bytes)
            ),
            "object_admission_id": (
                None
                if self.object_admission_id is None
                else str(self.object_admission_id)
            ),
            "blob_digest": self.blob_digest,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
        }


@dataclass(frozen=True, slots=True)
class _AuthorizedCommandGrant:
    command_type: str
    aggregate_id: str
    expected_aggregate_version: int
    definition: CommandDefinition
    payload: _ResolvedPayload
    authentication: _VerifiedAuthenticationContext
    authorization_request: _AuthorizationRequest
    authorization: _AuthorizationDecision
    idempotency_namespace: str
    idempotency_key: str
    stable_semantic_request_digest: str
    correlation_id: str | None
    causation_kind: str | None
    causation_identifier: str | None
    causation_external_system: str | None
    signature: str
    replay_of_command_id: str | None = None

    def unsigned_value(self) -> dict[str, Any]:
        return {
            "operation": "COMMAND_COMMIT",
            "command_type": self.command_type,
            "aggregate_id": self.aggregate_id,
            "expected_aggregate_version": self.expected_aggregate_version,
            "definition_digest": self.definition.digest,
            "definition_version": self.definition.definition_version,
            "payload": self.payload.canonical_value(),
            "authentication_context_digest": self.authentication.digest,
            "authorization_request_record_digest": (
                self.authorization_request.digest
            ),
            "authorization_request_digest": (
                self.authorization_request.request_digest
            ),
            "authorization_decision_digest": self.authorization.digest,
            "idempotency_namespace": self.idempotency_namespace,
            "idempotency_key": self.idempotency_key,
            "stable_semantic_request_digest": (
                self.stable_semantic_request_digest
            ),
            "correlation_id": self.correlation_id,
            "causation_kind": self.causation_kind,
            "causation_identifier": self.causation_identifier,
            "causation_external_system": self.causation_external_system,
            "replay_of_command_id": self.replay_of_command_id,
        }


def _derive_idempotency_namespace(
    authentication: _VerifiedAuthenticationContext,
    definition: CommandDefinition,
) -> str:
    return digest_canonical(
        {
            "authority_domain": authentication.authority_domain,
            "principal_id": authentication.principal_id,
            "command_type": definition.command_type,
        }
    )


def _derive_stable_semantic_request_digest(
    *,
    definition: CommandDefinition,
    aggregate_id: str,
    expected_aggregate_version: int,
    payload: _ResolvedPayload,
) -> str:
    return digest_canonical(
        {
            "command_type": definition.command_type,
            "command_definition_version": definition.definition_version,
            "command_definition_digest": definition.digest,
            "aggregate_type": definition.aggregate_type,
            "aggregate_id": aggregate_id,
            "expected_aggregate_version": expected_aggregate_version,
            "payload": payload.canonical_value(),
        }
    )


def _validate_resolved_payload(
    payload: _ResolvedPayload, definition: CommandDefinition
) -> None:
    if not isinstance(payload, _ResolvedPayload):
        raise InvalidCommitCapability("commit payload must be resolved")
    validate_sha256_digest(payload.digest, field="payload_digest")
    validate_sha256_digest(
        payload.schema_contract_digest,
        field="payload_schema_contract_digest",
    )
    if (
        payload.kind != definition.payload_mode.value
        or payload.schema_version != definition.payload_schema_version
        or payload.schema_contract_version
        != definition.payload_schema_contract_version
        or payload.schema_contract_digest
        != definition.payload_schema_contract_digest
        or payload.canonicalizer_version
        != definition.payload_canonicalizer_version
    ):
        raise InvalidCommitCapability(
            "resolved payload schema identity does not match server definition"
        )

    object_fields = (
        payload.object_admission_id,
        payload.blob_digest,
        payload.object_class,
        payload.allowed_use,
    )
    if definition.payload_mode is PayloadMode.INLINE:
        if not isinstance(payload.inline_bytes, bytes):
            raise InvalidCommitCapability(
                "inline payload must retain immutable canonical bytes"
            )
        if any(value is not None for value in object_fields):
            raise InvalidCommitCapability(
                "inline payload cannot carry object-admission fields"
            )
        if digest_bytes(payload.inline_bytes) != payload.digest:
            raise InvalidCommitCapability(
                "inline payload digest does not match retained bytes"
            )
        if len(payload.inline_bytes) > definition.max_inline_bytes:
            raise InvalidCommitCapability(
                "inline payload exceeds server definition limit"
            )
        return

    if definition.payload_mode is PayloadMode.NO_PAYLOAD:
        if payload.inline_bytes != b"":
            raise InvalidCommitCapability(
                "NO_PAYLOAD must retain the exact empty payload"
            )
        if any(value is not None for value in object_fields):
            raise InvalidCommitCapability(
                "NO_PAYLOAD cannot carry object-admission fields"
            )
        if digest_bytes(b"") != payload.digest:
            raise InvalidCommitCapability("NO_PAYLOAD digest is not empty")
        return

    if payload.inline_bytes is not None:
        raise InvalidCommitCapability(
            "object-admission payload cannot carry inline bytes"
        )
    if not isinstance(payload.object_admission_id, ObjectAdmissionId):
        raise InvalidCommitCapability(
            "object-admission payload requires typed admission identity"
        )
    if payload.blob_digest is None:
        raise InvalidCommitCapability(
            "object-admission payload requires blob digest"
        )
    normalized = validate_sha256_digest(
        payload.blob_digest, field="blob_digest"
    )
    if normalized != payload.blob_digest or payload.digest != payload.blob_digest:
        raise InvalidCommitCapability(
            "object-admission payload digest is inconsistent"
        )
    if (
        payload.object_class != definition.required_object_class
        or payload.allowed_use != definition.required_allowed_use
    ):
        raise InvalidCommitCapability(
            "object-admission payload class/use does not match server definition"
        )


class _CapabilityIssuer:
    """Issues and verifies grants against an immutable server contract snapshot."""

    def __init__(
        self,
        secret: bytes | None = None,
        *,
        command_registry: CommandRegistry | None = None,
        payload_schemas: PayloadSchemaRegistry | None = None,
    ) -> None:
        self._secret = secret or secrets.token_bytes(32)
        if len(self._secret) < 32:
            raise ValueError("capability secret must be at least 256 bits")
        self._definition_snapshot: dict[
            tuple[str, str, str], CommandDefinition
        ] | None = None
        self._schema_snapshot: frozenset[
            tuple[str, str, str, str, str]
        ] | None = None
        if command_registry is not None or payload_schemas is not None:
            if command_registry is None or payload_schemas is None:
                raise ValueError(
                    "capability contract binding requires both registries"
                )
            self.bind_contracts(command_registry, payload_schemas)

    def bind_contracts(
        self,
        command_registry: CommandRegistry,
        payload_schemas: PayloadSchemaRegistry,
    ) -> None:
        definitions = {
            (
                definition.command_type,
                definition.definition_version,
                definition.digest,
            ): definition
            for definition in command_registry.definitions()
        }
        schemas = frozenset(
            (
                contract.schema_version,
                contract.payload_mode.value,
                contract.contract_version,
                contract.contract_digest,
                contract.canonicalizer_implementation_version,
            )
            for contract in payload_schemas.contracts()
        )
        if not definitions or not schemas:
            raise ValueError(
                "capability contract snapshot cannot be empty"
            )
        if self._definition_snapshot is not None:
            previous = {
                key: value.canonical_value()
                for key, value in self._definition_snapshot.items()
            }
            current = {
                key: value.canonical_value()
                for key, value in definitions.items()
            }
            if previous != current or self._schema_snapshot != schemas:
                raise ValueError(
                    "capability issuer is already bound to different contracts"
                )
            return
        self._definition_snapshot = definitions
        self._schema_snapshot = schemas

    def _require_registered_contracts(
        self, definition: CommandDefinition
    ) -> None:
        if self._definition_snapshot is None or self._schema_snapshot is None:
            raise InvalidCommitCapability(
                "capability issuer is not bound to the server contract registry"
            )
        key = (
            definition.command_type,
            definition.definition_version,
            definition.digest,
        )
        registered = self._definition_snapshot.get(key)
        if (
            registered is None
            or registered.canonical_value() != definition.canonical_value()
        ):
            raise InvalidCommitCapability(
                "commit definition is not an exact registered server contract"
            )
        schema_key = (
            definition.payload_schema_version,
            definition.payload_mode.value,
            definition.payload_schema_contract_version,
            definition.payload_schema_contract_digest,
            definition.payload_canonicalizer_version,
        )
        if schema_key not in self._schema_snapshot:
            raise InvalidCommitCapability(
                "commit payload schema is not an exact registered server contract"
            )

    def _signature(self, value: dict[str, Any]) -> str:
        mac = hmac.new(
            self._secret, canonical_json_bytes(value), hashlib.sha256
        )
        return f"hmac-sha256:{mac.hexdigest()}"

    def issue(self, **kwargs: Any) -> _AuthorizedCommandGrant:
        provisional = _AuthorizedCommandGrant(signature="", **kwargs)
        return _AuthorizedCommandGrant(
            signature=self._signature(provisional.unsigned_value()), **kwargs
        )

    def verify(self, grant: _AuthorizedCommandGrant) -> None:
        if not isinstance(grant, _AuthorizedCommandGrant):
            raise InvalidCommitCapability(
                "commit requires an authorised command grant"
            )
        expected = self._signature(grant.unsigned_value())
        if not hmac.compare_digest(expected, grant.signature):
            raise InvalidCommitCapability(
                "commit capability signature mismatch"
            )

        request = grant.authorization_request
        definition = grant.definition
        self._require_registered_contracts(definition)
        authentication = grant.authentication
        authorization = grant.authorization

        AggregateId.parse(grant.aggregate_id)
        if (
            isinstance(grant.expected_aggregate_version, bool)
            or not isinstance(grant.expected_aggregate_version, int)
            or grant.expected_aggregate_version < 0
        ):
            raise InvalidCommitCapability(
                "grant expected version must be a non-negative integer"
            )
        if (
            not isinstance(grant.idempotency_key, str)
            or not grant.idempotency_key.strip()
            or len(grant.idempotency_key.encode("utf-8")) > 256
        ):
            raise InvalidCommitCapability("grant idempotency key is invalid")

        authentication.require_current(authorization.decided_at)
        if request.request_digest != request.computed_digest:
            raise InvalidCommitCapability(
                "authorization request digest changed"
            )
        if (
            request.authentication_context_id
            != authentication.authentication_context_id
            or request.principal_id != authentication.principal_id
            or request.authority_domain != authentication.authority_domain
        ):
            raise InvalidCommitCapability(
                "authorization request is not bound to authentication context"
            )
        if (
            authorization.authentication_context_id
            != authentication.authentication_context_id
        ):
            raise InvalidCommitCapability(
                "authorization decision is not bound to authentication context"
            )
        if (
            authorization.authorization_request_digest
            != request.request_digest
        ):
            raise InvalidCommitCapability(
                "authorization decision is not bound to exact request"
            )
        if authorization.effective_scope_digest != _effective_scope_digest(
            authentication, authorization.effective_scopes
        ):
            raise InvalidCommitCapability(
                "authorization scopes are not bound to authentication provenance"
            )
        if not authorization.allowed:
            raise InvalidCommitCapability(
                "denied authorization cannot create a grant"
            )

        _validate_resolved_payload(grant.payload, definition)
        expected_namespace = _derive_idempotency_namespace(
            authentication, definition
        )
        expected_semantic_digest = _derive_stable_semantic_request_digest(
            definition=definition,
            aggregate_id=grant.aggregate_id,
            expected_aggregate_version=grant.expected_aggregate_version,
            payload=grant.payload,
        )
        expected_operation = f"command:{definition.command_type}"

        if grant.idempotency_namespace != expected_namespace:
            raise InvalidCommitCapability(
                "idempotency namespace was not server-derived"
            )
        if (
            grant.stable_semantic_request_digest
            != expected_semantic_digest
        ):
            raise InvalidCommitCapability(
                "stable semantic request digest was not server-derived"
            )
        expected_semantics = (
            grant.command_type == definition.command_type
            and request.operation_type == expected_operation
            and request.required_scope == definition.required_scope
            and request.command_definition_digest == definition.digest
            and request.stable_semantic_request_digest
            == expected_semantic_digest
            and request.aggregate_type == definition.aggregate_type
            and request.aggregate_id == grant.aggregate_id
            and request.event_type == definition.event_type
            and request.event_schema_version
            == definition.event_schema_version
            and request.payload_mode == definition.payload_mode.value
            and request.payload_schema_version
            == definition.payload_schema_version
            and request.payload_schema_contract_version
            == definition.payload_schema_contract_version
            and request.payload_schema_contract_digest
            == definition.payload_schema_contract_digest
            and request.payload_canonicalizer_version
            == definition.payload_canonicalizer_version
            and request.trust_scope == definition.trust_scope.value
            and request.security_scope == definition.security_scope
            and request.retention_scope == definition.retention_scope
            and request.object_class == definition.required_object_class
            and request.allowed_use == definition.required_allowed_use
        )
        if not expected_semantics:
            raise InvalidCommitCapability(
                "commit grant semantics do not match authorised server definition"
            )
