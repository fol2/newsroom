from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
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
from .canonical import canonical_json_bytes, digest_canonical
from .models import CommandDefinition
from .object_policy import (
    HydrationPolicyRegistry,
    ObjectAdmissionRegistry,
    RightsPolicyRegistry,
)
from .objects import (
    BlobIdentity,
    HydrationPolicyContract,
    HydrationRequest,
    ObjectAdmissionDefinition,
    ObjectAdmissionRequest,
    ObjectOperationId,
    ObjectPolicyError,
    ObjectPreflightId,
    RightsPolicyContract,
)
from .policy import CommandRegistry
from .types import UtcTimestamp, require_token


class InvalidObjectCapability(PermissionError):
    """An object authority grant was fabricated, stale, or semantically altered."""


@dataclass(frozen=True, slots=True)
class _RightsProposal:
    policy_contract_digest: str
    admission_definition_digest: str
    blob: BlobIdentity
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    allowed: bool
    reason_code: str
    decided_at: UtcTimestamp
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp | None
    rights_request_digest: str

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_contract_digest": self.policy_contract_digest,
            "admission_definition_digest": self.admission_definition_digest,
            "blob": self.blob.canonical_value(),
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "decided_at": self.decided_at.to_text(),
            "valid_from": self.valid_from.to_text(),
            "valid_until": (
                None if self.valid_until is None else self.valid_until.to_text()
            ),
            "rights_request_digest": self.rights_request_digest,
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def require_current(self, now: UtcTimestamp) -> None:
        if not self.allowed:
            raise InvalidObjectCapability(self.reason_code)
        if now.value < self.decided_at.value:
            raise InvalidObjectCapability("rights decision is not yet effective")
        if now.value < self.valid_from.value:
            raise InvalidObjectCapability("rights validity has not begun")
        if self.valid_until is not None and now.value >= self.valid_until.value:
            raise InvalidObjectCapability("rights decision has expired")


@dataclass(frozen=True, slots=True)
class _AdmissionPreflightGrant:
    preflight_id: ObjectPreflightId
    request: ObjectAdmissionRequest
    definition: ObjectAdmissionDefinition
    rights_policy: RightsPolicyContract
    authentication: _VerifiedAuthenticationContext
    authorization_request: _AuthorizationRequest
    authorization: _AuthorizationDecision
    idempotency_namespace: str
    stable_semantic_request_digest: str
    checked_at: UtcTimestamp
    expires_at: UtcTimestamp
    signature: str

    def unsigned_value(self) -> dict[str, object]:
        return {
            "grant_type": "OBJECT_ADMISSION_PREFLIGHT",
            "preflight_id": str(self.preflight_id),
            "request": {
                "admission_type": self.request.admission_type,
                "idempotency_key": self.request.idempotency_key,
            },
            "definition_digest": self.definition.digest,
            "rights_policy_contract_digest": (
                self.rights_policy.contract_digest
            ),
            "authentication_context_digest": self.authentication.digest,
            "authorization_request_record_digest": (
                self.authorization_request.digest
            ),
            "authorization_request_digest": (
                self.authorization_request.request_digest
            ),
            "authorization_decision_digest": self.authorization.digest,
            "idempotency_namespace": self.idempotency_namespace,
            "stable_semantic_request_digest": (
                self.stable_semantic_request_digest
            ),
            "checked_at": self.checked_at.to_text(),
            "expires_at": self.expires_at.to_text(),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.unsigned_value())


@dataclass(frozen=True, slots=True)
class _AdmissionCommitGrant:
    operation_id: ObjectOperationId
    preflight: _AdmissionPreflightGrant
    blob: BlobIdentity
    stage_id: str
    staged_name: str
    authentication: _VerifiedAuthenticationContext
    authorization_request: _AuthorizationRequest
    authorization: _AuthorizationDecision
    rights: _RightsProposal
    stable_semantic_request_digest: str
    signature: str

    def unsigned_value(self) -> dict[str, object]:
        return {
            "grant_type": "OBJECT_ADMISSION_COMMIT",
            "operation_id": str(self.operation_id),
            "preflight_digest": self.preflight.digest,
            "blob": self.blob.canonical_value(),
            "stage_id": self.stage_id,
            "staged_name": self.staged_name,
            "authentication_context_digest": self.authentication.digest,
            "authorization_request_record_digest": (
                self.authorization_request.digest
            ),
            "authorization_request_digest": (
                self.authorization_request.request_digest
            ),
            "authorization_decision_digest": self.authorization.digest,
            "rights_proposal_digest": self.rights.digest,
            "stable_semantic_request_digest": (
                self.stable_semantic_request_digest
            ),
        }


@dataclass(frozen=True, slots=True)
class _MaintenanceGrant:
    operation_id: ObjectOperationId
    operation_type: str
    target_identity: str
    reason_code: str
    lifecycle_definition: CommandDefinition
    authentication: _VerifiedAuthenticationContext
    authorization_request: _AuthorizationRequest
    authorization: _AuthorizationDecision
    idempotency_key: str
    idempotency_namespace: str
    stable_semantic_request_digest: str
    decided_at: UtcTimestamp
    signature: str

    def unsigned_value(self) -> dict[str, object]:
        return {
            "grant_type": "OBJECT_MAINTENANCE",
            "operation_id": str(self.operation_id),
            "operation_type": self.operation_type,
            "target_identity": self.target_identity,
            "reason_code": self.reason_code,
            "lifecycle_definition_digest": self.lifecycle_definition.digest,
            "authentication_context_digest": self.authentication.digest,
            "authorization_request_record_digest": (
                self.authorization_request.digest
            ),
            "authorization_request_digest": (
                self.authorization_request.request_digest
            ),
            "authorization_decision_digest": self.authorization.digest,
            "idempotency_key": self.idempotency_key,
            "idempotency_namespace": self.idempotency_namespace,
            "stable_semantic_request_digest": (
                self.stable_semantic_request_digest
            ),
            "decided_at": self.decided_at.to_text(),
        }


@dataclass(frozen=True, slots=True)
class _HydrationGrant:
    operation_id: ObjectOperationId
    request: HydrationRequest
    policy: HydrationPolicyContract
    authentication: _VerifiedAuthenticationContext
    authorization_request: _AuthorizationRequest
    authorization: _AuthorizationDecision
    stable_semantic_request_digest: str
    decided_at: UtcTimestamp
    signature: str

    def unsigned_value(self) -> dict[str, object]:
        return {
            "grant_type": "OBJECT_HYDRATION",
            "operation_id": str(self.operation_id),
            "request": {
                "admission_id": str(self.request.admission_id),
                "purpose": self.request.purpose,
                "offset": self.request.offset,
                "length": self.request.length,
            },
            "hydration_policy_contract_digest": self.policy.contract_digest,
            "authentication_context_digest": self.authentication.digest,
            "authorization_request_record_digest": (
                self.authorization_request.digest
            ),
            "authorization_request_digest": (
                self.authorization_request.request_digest
            ),
            "authorization_decision_digest": self.authorization.digest,
            "stable_semantic_request_digest": (
                self.stable_semantic_request_digest
            ),
            "decided_at": self.decided_at.to_text(),
        }


class _ObjectCapabilityIssuer:
    """Issues and independently verifies object grants against retained registries."""

    def __init__(
        self,
        *,
        admission_registry: ObjectAdmissionRegistry,
        rights_policies: RightsPolicyRegistry,
        hydration_policies: HydrationPolicyRegistry,
        command_registry: CommandRegistry,
        secret: bytes | None = None,
    ) -> None:
        self._secret = secret or secrets.token_bytes(32)
        if len(self._secret) < 32:
            raise ValueError("object capability secret must be at least 256 bits")
        self._admission_registry = admission_registry
        self._rights_policies = rights_policies
        self._hydration_policies = hydration_policies
        self._command_registry = command_registry
        self._definition_snapshot = {
            item.digest: item.canonical_value()
            for item in admission_registry.definitions()
        }
        self._rights_snapshot = {
            item.contract_digest: item.canonical_value()
            for item in rights_policies.contracts()
        }
        self._hydration_snapshot = {
            item.contract_digest: item.canonical_value()
            for item in hydration_policies.contracts()
        }

    def _signature(self, value: dict[str, object]) -> str:
        mac = hmac.new(
            self._secret, canonical_json_bytes(value), hashlib.sha256
        )
        return f"hmac-sha256:{mac.hexdigest()}"

    def issue_preflight(self, **kwargs: Any) -> _AdmissionPreflightGrant:
        provisional = _AdmissionPreflightGrant(signature="", **kwargs)
        return _AdmissionPreflightGrant(
            signature=self._signature(provisional.unsigned_value()), **kwargs
        )

    def issue_admission(self, **kwargs: Any) -> _AdmissionCommitGrant:
        provisional = _AdmissionCommitGrant(signature="", **kwargs)
        return _AdmissionCommitGrant(
            signature=self._signature(provisional.unsigned_value()), **kwargs
        )

    def issue_maintenance(self, **kwargs: Any) -> _MaintenanceGrant:
        provisional = _MaintenanceGrant(signature="", **kwargs)
        return _MaintenanceGrant(
            signature=self._signature(provisional.unsigned_value()), **kwargs
        )

    def issue_hydration(self, **kwargs: Any) -> _HydrationGrant:
        provisional = _HydrationGrant(signature="", **kwargs)
        return _HydrationGrant(
            signature=self._signature(provisional.unsigned_value()), **kwargs
        )

    def _verify_signature(self, grant: Any) -> None:
        expected = self._signature(grant.unsigned_value())
        if not hmac.compare_digest(expected, grant.signature):
            raise InvalidObjectCapability("object capability signature mismatch")

    @staticmethod
    def _verify_security(
        authentication: _VerifiedAuthenticationContext,
        request: _AuthorizationRequest,
        decision: _AuthorizationDecision,
        *,
        expected_operation: str,
        expected_scope: str,
        expected_stable_digest: str,
        expected_definition_digest: str,
        now: UtcTimestamp,
    ) -> None:
        authentication.require_current(now)
        if request.request_digest != request.computed_digest:
            raise InvalidObjectCapability("authorization request digest changed")
        if (
            request.authentication_context_id
            != authentication.authentication_context_id
            or request.principal_id != authentication.principal_id
            or request.authority_domain != authentication.authority_domain
        ):
            raise InvalidObjectCapability(
                "authorization request is not bound to authentication"
            )
        if (
            decision.authentication_context_id
            != authentication.authentication_context_id
            or decision.authorization_request_digest != request.request_digest
        ):
            raise InvalidObjectCapability(
                "authorization decision is not bound to exact request"
            )
        if decision.effective_scope_digest != _effective_scope_digest(
            authentication, decision.effective_scopes
        ):
            raise InvalidObjectCapability(
                "effective scopes are not bound to authentication provenance"
            )
        if not decision.allowed or expected_scope not in decision.effective_scopes:
            raise InvalidObjectCapability("allowing required scope is absent")
        if request.operation_type != expected_operation:
            raise InvalidObjectCapability("object operation type was not server-derived")
        if request.required_scope != expected_scope:
            raise InvalidObjectCapability("object required scope was not server-derived")
        if request.stable_semantic_request_digest != expected_stable_digest:
            raise InvalidObjectCapability("object semantic digest was not server-derived")
        if request.command_definition_digest != expected_definition_digest:
            raise InvalidObjectCapability("object policy identity differs from request")
        if decision.decided_at.value > now.value:
            raise InvalidObjectCapability("authorization decision is future-dated")

    def verify_preflight(self, grant: _AdmissionPreflightGrant, *, now: UtcTimestamp) -> None:
        if not isinstance(grant, _AdmissionPreflightGrant):
            raise InvalidObjectCapability("admission preflight grant is required")
        self._verify_signature(grant)
        definition = self._admission_registry.resolve_exact(
            grant.definition.admission_type,
            grant.definition.definition_version,
            grant.definition.digest,
        )
        policy = self._rights_policies.resolve_digest(
            grant.rights_policy.contract_digest
        )
        if (
            self._definition_snapshot.get(definition.digest)
            != definition.canonical_value()
            or self._rights_snapshot.get(policy.contract_digest)
            != policy.canonical_value()
        ):
            raise InvalidObjectCapability("object policy registry snapshot changed")
        if definition.rights_policy_contract_digest != policy.contract_digest:
            raise InvalidObjectCapability(
                "admission definition names another rights-policy contract"
            )
        if grant.request.admission_type != definition.admission_type:
            raise InvalidObjectCapability(
                "preflight request does not match retained admission definition"
            )
        expected_namespace = digest_canonical(
            {
                "authority_domain": grant.authentication.authority_domain,
                "principal_id": grant.authentication.principal_id,
                "operation": "object_admission",
                "admission_type": definition.admission_type,
            }
        )
        expected_semantic = digest_canonical(
            {
                "admission_type": grant.request.admission_type,
                "definition_digest": definition.digest,
                "rights_policy_contract_digest": policy.contract_digest,
                "idempotency_key": grant.request.idempotency_key,
            }
        )
        if grant.idempotency_namespace != expected_namespace:
            raise InvalidObjectCapability("preflight namespace was not server-derived")
        if grant.stable_semantic_request_digest != expected_semantic:
            raise InvalidObjectCapability("preflight semantic digest changed")
        self._verify_security(
            grant.authentication,
            grant.authorization_request,
            grant.authorization,
            expected_operation=(
                f"object:admission:preflight:{definition.admission_type}"
            ),
            expected_scope=definition.required_write_scope,
            expected_stable_digest=expected_semantic,
            expected_definition_digest=definition.digest,
            now=grant.checked_at,
        )
        if grant.checked_at != grant.authorization.decided_at:
            raise InvalidObjectCapability(
                "preflight issue time differs from exact authorization decision"
            )
        expected_expiry = UtcTimestamp(
            grant.checked_at.value
            + timedelta(
                seconds=policy.preflight_ttl_seconds
            )
        )
        if grant.expires_at != expected_expiry:
            raise InvalidObjectCapability(
                "preflight expiry was not derived from retained rights policy"
            )
        if now.value >= grant.expires_at.value:
            raise InvalidObjectCapability("admission preflight capability expired")
        if not policy.preflight_allowed:
            raise InvalidObjectCapability("known-denied rights cannot issue preflight")

    def verify_admission(self, grant: _AdmissionCommitGrant, *, now: UtcTimestamp) -> None:
        if not isinstance(grant, _AdmissionCommitGrant):
            raise InvalidObjectCapability("admission commit grant is required")
        self._verify_signature(grant)
        self.verify_preflight(grant.preflight, now=now)
        definition = grant.preflight.definition
        policy = grant.preflight.rights_policy
        expected_semantic = digest_canonical(
            {
                "preflight_digest": grant.preflight.digest,
                "blob": grant.blob.canonical_value(),
                "stage_id": grant.stage_id,
                "staged_name": grant.staged_name,
            }
        )
        if grant.stable_semantic_request_digest != expected_semantic:
            raise InvalidObjectCapability("admission semantic digest changed")
        self._verify_security(
            grant.authentication,
            grant.authorization_request,
            grant.authorization,
            expected_operation=(
                f"object:admission:commit:{definition.admission_type}"
            ),
            expected_scope=definition.required_write_scope,
            expected_stable_digest=expected_semantic,
            expected_definition_digest=definition.digest,
            now=now,
        )
        rights = grant.rights
        expected_rights_request = digest_canonical(
            {
                "preflight_digest": grant.preflight.digest,
                "blob": grant.blob.canonical_value(),
                "final_authentication_context_digest": grant.authentication.digest,
                "final_authorization_request_digest": (
                    grant.authorization_request.request_digest
                ),
                "final_authorization_decision_digest": grant.authorization.digest,
                "rights_policy_contract_digest": policy.contract_digest,
            }
        )
        if rights.rights_request_digest != expected_rights_request:
            raise InvalidObjectCapability("rights request digest changed")
        expected_rights = (
            rights.policy_contract_digest == policy.contract_digest
            and rights.admission_definition_digest == definition.digest
            and rights.blob == grant.blob
            and rights.object_class == definition.object_class
            and rights.allowed_use == definition.allowed_use
            and rights.security_scope == definition.security_scope
            and rights.retention_scope == definition.retention_scope
            and rights.allowed == policy.preflight_allowed
            and rights.reason_code == policy.reason_code
        )
        if not expected_rights:
            raise InvalidObjectCapability(
                "rights proposal differs from retained exact policy contracts"
            )
        if rights.decided_at != grant.authorization.decided_at:
            raise InvalidObjectCapability(
                "rights decision time differs from exact authorization decision"
            )
        expected_valid_from = UtcTimestamp(
            rights.decided_at.value
            + timedelta(
                seconds=policy.valid_from_delay_seconds
            )
        )
        expected_valid_until = (
            None
            if policy.validity_seconds is None
            else UtcTimestamp(
                expected_valid_from.value
                + timedelta(
                    seconds=policy.validity_seconds
                )
            )
        )
        if rights.valid_from != expected_valid_from:
            raise InvalidObjectCapability(
                "rights valid_from was not derived from retained policy"
            )
        if rights.valid_until != expected_valid_until:
            raise InvalidObjectCapability(
                "rights valid_until was not derived from retained policy"
            )
        rights.require_current(now)

    def verify_maintenance(self, grant: _MaintenanceGrant, *, now: UtcTimestamp) -> None:
        if not isinstance(grant, _MaintenanceGrant):
            raise InvalidObjectCapability("maintenance grant is required")
        self._verify_signature(grant)
        require_token(grant.operation_type, field="object_maintenance_operation")
        require_token(grant.reason_code, field="object_maintenance_reason")
        definition = self._command_registry.resolve_exact(
            grant.lifecycle_definition.command_type,
            grant.lifecycle_definition.definition_version,
            grant.lifecycle_definition.digest,
        )
        expected_semantic = digest_canonical(
            {
                "operation_type": grant.operation_type,
                "target_identity": grant.target_identity,
                "reason_code": grant.reason_code,
                "lifecycle_definition_digest": definition.digest,
                "idempotency_key": grant.idempotency_key,
            }
        )
        expected_namespace = digest_canonical(
            {
                "authority_domain": grant.authentication.authority_domain,
                "principal_id": grant.authentication.principal_id,
                "operation_type": grant.operation_type,
            }
        )
        if grant.stable_semantic_request_digest != expected_semantic:
            raise InvalidObjectCapability("maintenance semantic digest changed")
        if grant.idempotency_namespace != expected_namespace:
            raise InvalidObjectCapability("maintenance namespace changed")
        self._verify_security(
            grant.authentication,
            grant.authorization_request,
            grant.authorization,
            expected_operation=f"object:maintenance:{grant.operation_type}",
            expected_scope=definition.required_scope,
            expected_stable_digest=expected_semantic,
            expected_definition_digest=definition.digest,
            now=now,
        )
        if grant.decided_at != grant.authorization.decided_at:
            raise InvalidObjectCapability("maintenance time differs from authorization")

    def verify_hydration(self, grant: _HydrationGrant, *, now: UtcTimestamp) -> None:
        if not isinstance(grant, _HydrationGrant):
            raise InvalidObjectCapability("hydration grant is required")
        self._verify_signature(grant)
        policy = self._hydration_policies.resolve_exact(
            grant.policy.policy_id,
            grant.policy.contract_version,
            grant.policy.contract_digest,
        )
        if self._hydration_snapshot.get(policy.contract_digest) != policy.canonical_value():
            raise InvalidObjectCapability("hydration policy snapshot changed")
        expected_semantic = digest_canonical(
            {
                "policy_contract_digest": policy.contract_digest,
                "admission_id": str(grant.request.admission_id),
                "purpose": grant.request.purpose,
                "offset": grant.request.offset,
                "length": grant.request.length,
            }
        )
        if grant.stable_semantic_request_digest != expected_semantic:
            raise InvalidObjectCapability("hydration semantic digest changed")
        self._verify_security(
            grant.authentication,
            grant.authorization_request,
            grant.authorization,
            expected_operation=f"object:hydrate:{policy.purpose}",
            expected_scope=policy.required_scope,
            expected_stable_digest=expected_semantic,
            expected_definition_digest=policy.contract_digest,
            now=now,
        )
        if grant.decided_at != grant.authorization.decided_at:
            raise InvalidObjectCapability("hydration time differs from authorization")


__all__ = [
    "InvalidObjectCapability",
    "_AdmissionCommitGrant",
    "_AdmissionPreflightGrant",
    "_HydrationGrant",
    "_MaintenanceGrant",
    "_ObjectCapabilityIssuer",
    "_RightsProposal",
]
