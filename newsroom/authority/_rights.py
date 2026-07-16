from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .canonical import digest_canonical, validate_sha256_digest
from .objects import (
    ObjectAdmissionDefinition,
    StaticRightsResolver,
)
from .types import RightsDecisionId, UtcTimestamp, require_scope, require_token


@dataclass(frozen=True, slots=True)
class _RightsDecision:
    rights_decision_id: RightsDecisionId
    authentication_context_id: str
    authorization_decision_id: str
    request_digest: str
    policy_version: str
    allowed: bool
    reason_code: str
    blob_digest: str
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp | None
    decided_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.rights_decision_id, RightsDecisionId):
            raise ValueError("rights decision identity must be typed")
        require_token(self.authentication_context_id, field="authentication_context_id")
        require_token(self.authorization_decision_id, field="authorization_decision_id")
        validate_sha256_digest(self.request_digest, field="rights_request_digest")
        require_token(self.policy_version, field="rights_policy_version")
        if not isinstance(self.allowed, bool):
            raise ValueError("rights allowed value must be boolean")
        require_token(self.reason_code, field="rights_reason_code")
        validate_sha256_digest(self.blob_digest, field="blob_digest")
        require_token(self.object_class, field="object_class")
        require_token(self.allowed_use, field="allowed_use")
        require_scope(self.security_scope, field="security_scope")
        require_scope(self.retention_scope, field="retention_scope")
        if not isinstance(self.valid_from, UtcTimestamp):
            raise ValueError("rights valid_from must be typed UTC")
        if self.valid_until is not None:
            if not isinstance(self.valid_until, UtcTimestamp):
                raise ValueError("rights valid_until must be typed UTC")
            if self.valid_until.value <= self.valid_from.value:
                raise ValueError("rights validity must end after it starts")
        if not isinstance(self.decided_at, UtcTimestamp):
            raise ValueError("rights decision time must be typed UTC")

    def canonical_value(self) -> dict[str, Any]:
        return {
            "rights_decision_id": str(self.rights_decision_id),
            "authentication_context_id": self.authentication_context_id,
            "authorization_decision_id": self.authorization_decision_id,
            "request_digest": self.request_digest,
            "policy_version": self.policy_version,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "blob_digest": self.blob_digest,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "valid_from": self.valid_from.to_text(),
            "valid_until": (
                None if self.valid_until is None else self.valid_until.to_text()
            ),
            "decided_at": self.decided_at.to_text(),
        }

    @property
    def digest(self) -> str:
        return digest_canonical(self.canonical_value())

    def require_current(self, now: UtcTimestamp) -> None:
        if not self.allowed:
            raise PermissionError(self.reason_code)
        if now.value < self.valid_from.value:
            raise PermissionError("RIGHTS_NOT_YET_VALID")
        if self.valid_until is not None and now.value >= self.valid_until.value:
            raise PermissionError("RIGHTS_EXPIRED")


def resolve_rights(
    resolver: StaticRightsResolver,
    definition: ObjectAdmissionDefinition,
    *,
    blob_digest: str,
    authentication_context_id: str,
    authorization_decision_id: str,
    principal_id: str,
    authority_domain: str,
    now: UtcTimestamp,
) -> _RightsDecision:
    rule = resolver.rule_for(definition.rights_policy_key)
    request_value = {
        "rights_policy_key": definition.rights_policy_key,
        "admission_type": definition.admission_type,
        "definition_version": definition.definition_version,
        "blob_digest": blob_digest,
        "object_class": definition.object_class,
        "allowed_use": definition.allowed_use,
        "security_scope": definition.security_scope,
        "retention_scope": definition.retention_scope,
        "principal_id": principal_id,
        "authority_domain": authority_domain,
        "authentication_context_id": authentication_context_id,
        "authorization_decision_id": authorization_decision_id,
    }
    valid_from, valid_until = resolver.validity_window(rule, now=now)
    return _RightsDecision(
        rights_decision_id=RightsDecisionId.new(),
        authentication_context_id=authentication_context_id,
        authorization_decision_id=authorization_decision_id,
        request_digest=digest_canonical(request_value),
        policy_version=rule.policy_version,
        allowed=rule.allowed,
        reason_code=rule.reason_code,
        blob_digest=blob_digest,
        object_class=definition.object_class,
        allowed_use=definition.allowed_use,
        security_scope=definition.security_scope,
        retention_scope=definition.retention_scope,
        valid_from=valid_from,
        valid_until=valid_until,
        decided_at=now,
    )
