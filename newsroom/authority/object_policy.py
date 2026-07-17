from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Iterable, Mapping

from .canonical import digest_canonical
from .objects import (
    AdmissionState,
    ImmutableBlobIdentity,
    ObjectAdmissionDefinition,
    ObjectAdmissionDenied,
    ObjectAdmissionReceipt,
    ObjectAdmissionRequest,
    ObjectPolicyError,
    RightsDecision,
)
from .types import (
    AuthenticationContextId,
    AuthorizationDecisionId,
    ObjectAdmissionId,
    RightsDecisionId,
    UtcTimestamp,
    require_token,
)


class UnknownObjectAdmissionDefinition(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectAdmissionRegistry:
    """Immutable retained registry of server-owned object-use definitions."""

    _by_key: Mapping[tuple[str, str], ObjectAdmissionDefinition]
    _current_versions: Mapping[str, str]

    def __init__(
        self,
        definitions: Iterable[ObjectAdmissionDefinition],
        *,
        current_versions: Mapping[str, str] | None = None,
    ) -> None:
        by_key: dict[tuple[str, str], ObjectAdmissionDefinition] = {}
        versions_by_type: dict[str, list[str]] = {}
        for definition in definitions:
            if not isinstance(definition, ObjectAdmissionDefinition):
                raise ObjectPolicyError(
                    "object admission registry accepts typed definitions only"
                )
            key = (definition.admission_type, definition.definition_version)
            if key in by_key:
                raise ObjectPolicyError(
                    "duplicate object admission definition: "
                    f"{definition.admission_type}/{definition.definition_version}"
                )
            by_key[key] = definition
            versions_by_type.setdefault(definition.admission_type, []).append(
                definition.definition_version
            )
        if not by_key:
            raise ObjectPolicyError("object admission registry cannot be empty")

        requested = dict(current_versions or {})
        selected: dict[str, str] = {}
        for admission_type, versions in versions_by_type.items():
            if admission_type in requested:
                version = requested.pop(admission_type)
            elif len(versions) == 1:
                version = versions[0]
            else:
                raise ObjectPolicyError(
                    "multiple admission-definition versions require an explicit "
                    f"current version: {admission_type}"
                )
            if (admission_type, version) not in by_key:
                raise ObjectPolicyError(
                    f"unknown current admission definition: {admission_type}/{version}"
                )
            selected[admission_type] = version
        if requested:
            raise ObjectPolicyError(
                "current version declared for unknown admission types: "
                f"{sorted(requested)}"
            )
        object.__setattr__(self, "_by_key", MappingProxyType(dict(by_key)))
        object.__setattr__(
            self, "_current_versions", MappingProxyType(dict(selected))
        )

    def resolve(
        self,
        admission_type: str,
        definition_version: str | None = None,
    ) -> ObjectAdmissionDefinition:
        require_token(admission_type, field="admission_type")
        version = (
            self._current_versions.get(admission_type)
            if definition_version is None
            else definition_version
        )
        if version is None:
            raise UnknownObjectAdmissionDefinition(admission_type)
        try:
            return self._by_key[(admission_type, version)]
        except KeyError as exc:
            raise UnknownObjectAdmissionDefinition(
                f"{admission_type}/{version}"
            ) from exc

    def resolve_exact(
        self,
        admission_type: str,
        definition_version: str,
        definition_digest: str,
    ) -> ObjectAdmissionDefinition:
        definition = self.resolve(admission_type, definition_version)
        if definition.digest != definition_digest:
            raise UnknownObjectAdmissionDefinition(
                "retained object admission definition digest mismatch"
            )
        return definition

    def definitions(self) -> tuple[ObjectAdmissionDefinition, ...]:
        return tuple(self._by_key[key] for key in sorted(self._by_key))


@dataclass(frozen=True, slots=True)
class StaticRightsRule:
    """Deterministic test/local rule; never caller-owned rights authority."""

    policy_version: str
    allowed: bool
    reason_code: str
    validity_seconds: int | None = None

    def __post_init__(self) -> None:
        require_token(self.policy_version, field="rights_policy_version")
        if not isinstance(self.allowed, bool):
            raise ObjectPolicyError("rights rule allowed value must be boolean")
        require_token(self.reason_code, field="rights_reason_code")
        if self.validity_seconds is not None and (
            isinstance(self.validity_seconds, bool)
            or not isinstance(self.validity_seconds, int)
            or self.validity_seconds <= 0
        ):
            raise ObjectPolicyError(
                "rights validity_seconds must be positive when set"
            )


@dataclass(frozen=True, slots=True)
class RightsPreflight:
    definition_digest: str
    policy_version: str
    principal_id: str
    authority_domain: str
    allowed: bool
    reason_code: str
    checked_at: UtcTimestamp

    def __post_init__(self) -> None:
        require_token(self.policy_version, field="rights_policy_version")
        require_token(self.principal_id, field="principal_id")
        require_token(self.authority_domain, field="authority_domain")
        require_token(self.reason_code, field="rights_reason_code")
        if not isinstance(self.allowed, bool):
            raise ObjectPolicyError("rights preflight result must be boolean")
        if not isinstance(self.checked_at, UtcTimestamp):
            raise ObjectPolicyError("rights preflight time must be typed UTC")

    def require_allowed(self) -> None:
        if not self.allowed:
            raise ObjectAdmissionDenied(self.reason_code)

    @property
    def digest(self) -> str:
        return digest_canonical(
            {
                "definition_digest": self.definition_digest,
                "policy_version": self.policy_version,
                "principal_id": self.principal_id,
                "authority_domain": self.authority_domain,
                "allowed": self.allowed,
                "reason_code": self.reason_code,
                "checked_at": self.checked_at.to_text(),
            }
        )


@dataclass(frozen=True, slots=True)
class AdmissionPreflight:
    """No bytes or digest are accepted at this known-denial boundary."""

    request: ObjectAdmissionRequest
    definition: ObjectAdmissionDefinition
    rights: RightsPreflight

    def __post_init__(self) -> None:
        if not isinstance(self.request, ObjectAdmissionRequest):
            raise ObjectPolicyError("preflight request must be typed")
        if not isinstance(self.definition, ObjectAdmissionDefinition):
            raise ObjectPolicyError("preflight definition must be typed")
        if not isinstance(self.rights, RightsPreflight):
            raise ObjectPolicyError("preflight rights result must be typed")
        if self.request.admission_type != self.definition.admission_type:
            raise ObjectPolicyError("request and definition admission type mismatch")
        if self.rights.definition_digest != self.definition.digest:
            raise ObjectPolicyError("rights preflight definition digest mismatch")

    @property
    def required_write_scope(self) -> str:
        return self.definition.required_write_scope

    def require_allowed(self) -> None:
        self.rights.require_allowed()


class StaticRightsResolver:
    """Server-owned deterministic rights resolver for tests/local integration."""

    def __init__(self, rules: Mapping[str, StaticRightsRule]) -> None:
        if not isinstance(rules, Mapping) or not rules:
            raise ObjectPolicyError("rights resolver requires server-side rules")
        copied: dict[str, StaticRightsRule] = {}
        for key, rule in rules.items():
            require_token(key, field="rights_policy_key")
            if not isinstance(rule, StaticRightsRule):
                raise ObjectPolicyError("rights resolver rules must be typed")
            copied[key] = rule
        self._rules = MappingProxyType(dict(sorted(copied.items())))

    def rule_for(self, rights_policy_key: str) -> StaticRightsRule:
        try:
            return self._rules[rights_policy_key]
        except KeyError as exc:
            raise ObjectPolicyError(
                f"unknown rights policy key: {rights_policy_key}"
            ) from exc

    def preflight(
        self,
        definition: ObjectAdmissionDefinition,
        *,
        principal_id: str,
        authority_domain: str,
        now: UtcTimestamp,
    ) -> RightsPreflight:
        """Return known policy outcome without accepting bytes or a digest."""

        if not isinstance(definition, ObjectAdmissionDefinition):
            raise ObjectPolicyError("rights preflight requires a typed definition")
        require_token(principal_id, field="principal_id")
        require_token(authority_domain, field="authority_domain")
        if not isinstance(now, UtcTimestamp):
            raise ObjectPolicyError("rights preflight time must be typed UTC")
        rule = self.rule_for(definition.rights_policy_key)
        return RightsPreflight(
            definition_digest=definition.digest,
            policy_version=rule.policy_version,
            principal_id=principal_id,
            authority_domain=authority_domain,
            allowed=rule.allowed,
            reason_code=rule.reason_code,
            checked_at=now,
        )

    def decide(
        self,
        definition: ObjectAdmissionDefinition,
        *,
        blob: ImmutableBlobIdentity,
        principal_id: str,
        authority_domain: str,
        authentication_context_id: AuthenticationContextId,
        authorization_request_digest: str,
        authorization_decision_id: AuthorizationDecisionId,
        now: UtcTimestamp,
    ) -> RightsDecision:
        if not isinstance(blob, ImmutableBlobIdentity):
            raise ObjectPolicyError("rights decision requires immutable blob identity")
        preflight = self.preflight(
            definition,
            principal_id=principal_id,
            authority_domain=authority_domain,
            now=now,
        )
        rule = self.rule_for(definition.rights_policy_key)
        valid_until = (
            None
            if rule.validity_seconds is None
            else UtcTimestamp(now.value + timedelta(seconds=rule.validity_seconds))
        )
        rights_request_digest = digest_canonical(
            {
                "definition_digest": definition.digest,
                "blob": blob.canonical_value(),
                "principal_id": principal_id,
                "authority_domain": authority_domain,
                "authentication_context_id": str(authentication_context_id),
                "authorization_request_digest": authorization_request_digest,
                "authorization_decision_id": str(authorization_decision_id),
                "preflight_digest": preflight.digest,
            }
        )
        return RightsDecision(
            rights_decision_id=RightsDecisionId.new(),
            authentication_context_id=authentication_context_id,
            authorization_request_digest=authorization_request_digest,
            authorization_decision_id=authorization_decision_id,
            rights_request_digest=rights_request_digest,
            policy_version=rule.policy_version,
            admission_definition_digest=definition.digest,
            blob_digest=blob.blob_digest,
            size_bytes=blob.size_bytes,
            object_class=definition.object_class,
            allowed_use=definition.allowed_use,
            security_scope=definition.security_scope,
            retention_scope=definition.retention_scope,
            allowed=rule.allowed,
            reason_code=rule.reason_code,
            valid_from=now,
            valid_until=valid_until,
            decided_at=now,
        )


def prepare_admission(
    *,
    registry: ObjectAdmissionRegistry,
    rights_resolver: StaticRightsResolver,
    request: ObjectAdmissionRequest,
    principal_id: str,
    authority_domain: str,
    now: UtcTimestamp,
) -> AdmissionPreflight:
    """Resolve exact server semantics before any large staging operation."""

    definition = registry.resolve(request.admission_type)
    rights = rights_resolver.preflight(
        definition,
        principal_id=principal_id,
        authority_domain=authority_domain,
        now=now,
    )
    return AdmissionPreflight(
        request=request,
        definition=definition,
        rights=rights,
    )


def activate_admission_contract(
    *,
    definition: ObjectAdmissionDefinition,
    blob: ImmutableBlobIdentity,
    rights: RightsDecision,
    now: UtcTimestamp,
) -> ObjectAdmissionReceipt:
    """Construct the immutable activation contract after authoritative commit.

    SQLite/CAS mutation and the ordered activation event are intentionally not
    implemented by this initial Draft slice; the future store supplies the event
    identity when the atomic commit path lands.
    """

    rights.require_current(now)
    if rights.admission_definition_digest != definition.digest:
        raise ObjectPolicyError("rights decision uses another admission definition")
    if rights.blob_digest != blob.blob_digest or rights.size_bytes != blob.size_bytes:
        raise ObjectPolicyError("rights decision uses another immutable blob")
    expected = (
        rights.object_class == definition.object_class
        and rights.allowed_use == definition.allowed_use
        and rights.security_scope == definition.security_scope
        and rights.retention_scope == definition.retention_scope
    )
    if not expected:
        raise ObjectPolicyError("rights decision use semantics do not match definition")
    return ObjectAdmissionReceipt(
        admission_id=ObjectAdmissionId.new(),
        admission_type=definition.admission_type,
        definition_version=definition.definition_version,
        definition_digest=definition.digest,
        blob=blob,
        object_class=definition.object_class,
        allowed_use=definition.allowed_use,
        security_scope=definition.security_scope,
        retention_scope=definition.retention_scope,
        rights_decision_id=rights.rights_decision_id,
        rights_decision_digest=rights.digest,
        valid_from=rights.valid_from,
        valid_until=rights.valid_until,
        state=AdmissionState.ACTIVE,
        activation_event_id=None,
    )
