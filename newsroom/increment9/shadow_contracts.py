"""Immutable, effect-free Increment 9A1 shadow-boundary contracts.

The public values in this module describe an isolated shadow.  They neither
construct that authority nor obtain credentials, open a connection, permit
network I/O, deploy resources, execute a campaign, publish, or mutate
production.  Construction remains a private seam for Increment 9A2.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.plan import (
    INCREMENT_9_SHADOW_PLAN,
    INCREMENT_9_SHADOW_PLAN_DIGEST,
)

SHADOW_SCOPE = "newsroom.increment9.shadow-scope.v1"
SHADOW_MANIFEST = "newsroom.increment9.shadow-manifest.v1"
SHADOW_MANIFEST_VERSION = "increment9-shadow-manifest-v1"
MAX_SHADOW_CONTRACT_BYTES = 1_048_576

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class ShadowContractError(ValueError):
    """Untrusted bytes or values failed the exact Increment 9A1 contract."""


class ShadowEffect(StrEnum):
    PRODUCTION_SNAPSHOT_READ_ONCE = "PRODUCTION_SNAPSHOT_READ_ONCE"
    SHADOW_AUTHORITY_WRITE = "SHADOW_AUTHORITY_WRITE"
    PROPOSAL_WORKSPACE_WRITE = "PROPOSAL_WORKSPACE_WRITE"
    PROTECTED_ARTIFACT_WRITE = "PROTECTED_ARTIFACT_WRITE"
    EVALUATION_RECORD_WRITE = "EVALUATION_RECORD_WRITE"


class ProhibitedEffect(StrEnum):
    PUBLICATION = "PUBLICATION"
    DISCORD_OR_PUBLIC_DISPATCH = "DISCORD_OR_PUBLIC_DISPATCH"
    EVIDENCE_INTAKE = "EVIDENCE_INTAKE"
    CANARY = "CANARY"
    PRODUCTION_SQLITE_WRITE = "PRODUCTION_SQLITE_WRITE"
    PRODUCTION_NEO4J_WRITE = "PRODUCTION_NEO4J_WRITE"
    PRODUCTION_AUTHORITY_MUTATION = "PRODUCTION_AUTHORITY_MUTATION"
    PRODUCTION_ACTIVATION = "PRODUCTION_ACTIVATION"
    LEGACY_RETIREMENT = "LEGACY_RETIREMENT"


class ShadowOutcome(StrEnum):
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    RIGHTS_BLOCKED = "RIGHTS_BLOCKED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class DifferenceMateriality(StrEnum):
    MATERIAL = "MATERIAL"
    NON_MATERIAL = "NON_MATERIAL"


class ProtectedArtifactClass(StrEnum):
    AUDIT_LEDGER = "AUDIT_LEDGER"
    BACKUP = "BACKUP"
    CREDENTIAL_METADATA = "CREDENTIAL_METADATA"
    EMBEDDING_INPUT = "EMBEDDING_INPUT"
    GOVERNED_PASSAGE = "GOVERNED_PASSAGE"
    MODEL_INPUT_OUTPUT = "MODEL_INPUT_OUTPUT"
    RAW_HTTP = "RAW_HTTP"
    REVIEW_RESEARCH_BYTES = "REVIEW_RESEARCH_BYTES"
    RIGHTS_RECORD = "RIGHTS_RECORD"


class ClosureReason(StrEnum):
    EXPIRED = "EXPIRED"
    OWNER_STOP = "OWNER_STOP"
    KILL_SWITCH = "KILL_SWITCH"
    RIGHTS_WITHDRAWN = "RIGHTS_WITHDRAWN"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    MANIFEST_SUPERSEDED = "MANIFEST_SUPERSEDED"
    CONTAINMENT_FAILURE = "CONTAINMENT_FAILURE"
    TEARDOWN_COMPLETE = "TEARDOWN_COMPLETE"


class _NoEffect:
    authorises_deployment = False
    authorises_credentials = False
    authorises_external_egress = False
    authorises_spend = False
    authorises_live_request = False
    authorises_shadow_campaign = False
    authorises_evidence_intake = False
    authorises_publication = False
    authorises_canary = False
    authorises_production_mutation = False
    authorises_production_activation = False
    exposes_connection = False


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ShadowContractError(f"duplicate object name: {name}")
        result[name] = value
    return result


def _document(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_SHADOW_CONTRACT_BYTES:
        raise ShadowContractError("shadow contract bytes are not bounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except ShadowContractError:
        raise
    except (UnicodeError, json.JSONDecodeError, CanonicalizationError, RecursionError) as exc:
        raise ShadowContractError("shadow contract bytes are invalid") from exc
    if canonical != raw:
        raise ShadowContractError("shadow contract bytes must be exact canonical JSON")
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(fields)):
        raise ShadowContractError("shadow contract fields differ")
    if value.get("schema_version") != schema:
        raise ShadowContractError("shadow contract schema differs")
    return value


def _text(value: object, field: str, maximum: int = 2048) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value.encode("utf-8", errors="strict")) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ShadowContractError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise ShadowContractError(f"{field} must be a canonical token")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise ShadowContractError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise ShadowContractError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ShadowContractError(f"{field} must be an exact UTC timestamp") from exc
    return value


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ShadowContractError(f"{field} must be a bounded integer")
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    try:
        if type(value) is not str and type(value) is not kind:
            raise ValueError
        return kind(value)
    except ValueError as exc:
        raise ShadowContractError(f"{field} differs") from exc


def _tokens(value: object, field: str, *, maximum: int = 64) -> tuple[str, ...]:
    if type(value) not in (tuple, list) or not value or len(value) > maximum:
        raise ShadowContractError(f"{field} must be a bounded array")
    result = tuple(_token(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise ShadowContractError(f"{field} must be unique and sorted")
    return result


def _enums[T: StrEnum](kind: type[T], value: object, field: str) -> tuple[T, ...]:
    if type(value) not in (tuple, list) or not value or len(value) > 64:
        raise ShadowContractError(f"{field} must be a bounded array")
    result = tuple(_enum(kind, item, field) for item in value)
    if tuple(sorted(set(result), key=str)) != result:
        raise ShadowContractError(f"{field} must be unique and sorted")
    return result


def _mapping(value: object, fields: tuple[str, ...], field: str) -> dict[str, object]:
    if type(value) is not dict or tuple(sorted(value)) != tuple(sorted(fields)):
        raise ShadowContractError(f"{field} fields differ")
    return value


@dataclass(frozen=True, slots=True)
class ProductionAuthorityReference(_NoEffect):
    authority: str
    schema_version: int
    schema_fingerprint: str
    migration_history_digest: str
    snapshot_digest: str
    export_digest: str
    cutoff_at: str
    watermark: str

    def __post_init__(self) -> None:
        _token(self.authority, "authority")
        _integer(self.schema_version, "schema_version", minimum=1)
        for field in (
            "schema_fingerprint",
            "migration_history_digest",
            "snapshot_digest",
            "export_digest",
        ):
            _digest(getattr(self, field), field)
        _timestamp(self.cutoff_at, "cutoff_at")
        _token(self.watermark, "watermark")

    def primitive(self) -> dict[str, object]:
        return {
            "authority": self.authority,
            "cutoff_at": self.cutoff_at,
            "export_digest": self.export_digest,
            "migration_history_digest": self.migration_history_digest,
            "schema_fingerprint": self.schema_fingerprint,
            "schema_version": self.schema_version,
            "snapshot_digest": self.snapshot_digest,
            "watermark": self.watermark,
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        raw = _mapping(value, tuple(cls.__dataclass_fields__), "production_authority")
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ShadowAuthorityIdentity(_NoEffect):
    authority_id: str
    sqlite_identity: str
    neo4j_database: str
    neo4j_namespace: str
    graphiti_workspace: str
    principal_identity_digest: str

    def __post_init__(self) -> None:
        for field in (
            "authority_id",
            "sqlite_identity",
            "neo4j_database",
            "neo4j_namespace",
            "graphiti_workspace",
        ):
            _token(getattr(self, field), field)
        _digest(self.principal_identity_digest, "principal_identity_digest")

    def primitive(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        raw = _mapping(value, tuple(cls.__dataclass_fields__), "shadow_authority")
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ShadowAccessBoundary(_NoEffect):
    purpose_identity: str
    principal_identity_digest: str
    permitted_credential_classes: tuple[str, ...]
    prohibited_credential_classes: tuple[str, ...]
    egress_policy_digest: str
    artefact_policy_digest: str

    def __post_init__(self) -> None:
        _token(self.purpose_identity, "purpose_identity")
        _digest(self.principal_identity_digest, "principal_identity_digest")
        permitted = _tokens(
            self.permitted_credential_classes, "permitted_credential_classes"
        )
        prohibited = _tokens(
            self.prohibited_credential_classes, "prohibited_credential_classes"
        )
        if set(permitted) & set(prohibited):
            raise ShadowContractError("credential class boundaries overlap")
        _digest(self.egress_policy_digest, "egress_policy_digest")
        _digest(self.artefact_policy_digest, "artefact_policy_digest")

    def primitive(self) -> dict[str, object]:
        return {
            "artefact_policy_digest": self.artefact_policy_digest,
            "permitted_credential_classes": list(self.permitted_credential_classes),
            "prohibited_credential_classes": list(self.prohibited_credential_classes),
            "egress_policy_digest": self.egress_policy_digest,
            "principal_identity_digest": self.principal_identity_digest,
            "purpose_identity": self.purpose_identity,
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        fields = tuple(cls.__dataclass_fields__)
        raw = _mapping(value, fields, "access_boundary")
        return cls(
            purpose_identity=raw["purpose_identity"],  # type: ignore[arg-type]
            principal_identity_digest=raw["principal_identity_digest"],  # type: ignore[arg-type]
            permitted_credential_classes=_tokens(
                raw["permitted_credential_classes"], "permitted_credential_classes"
            ),
            prohibited_credential_classes=_tokens(
                raw["prohibited_credential_classes"], "prohibited_credential_classes"
            ),
            egress_policy_digest=raw["egress_policy_digest"],  # type: ignore[arg-type]
            artefact_policy_digest=raw["artefact_policy_digest"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ProductionDifference(_NoEffect):
    difference_id: str
    materiality: DifferenceMateriality
    statement: str
    inference_limit: str

    def __post_init__(self) -> None:
        _token(self.difference_id, "difference_id")
        _enum(DifferenceMateriality, self.materiality, "materiality")
        _text(self.statement, "statement")
        _token(self.inference_limit, "inference_limit")

    def primitive(self) -> dict[str, object]:
        return {
            "difference_id": self.difference_id,
            "inference_limit": self.inference_limit,
            "materiality": str(self.materiality),
            "statement": self.statement,
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        raw = _mapping(value, tuple(cls.__dataclass_fields__), "production_difference")
        return cls(
            difference_id=raw["difference_id"],  # type: ignore[arg-type]
            materiality=_enum(DifferenceMateriality, raw["materiality"], "materiality"),
            statement=raw["statement"],  # type: ignore[arg-type]
            inference_limit=raw["inference_limit"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ProtectedArtifactRule(_NoEffect):
    artifact_class: ProtectedArtifactClass
    lineage_required: bool
    encrypted_at_rest: bool
    retention_days_max: int
    rights_revocation_purge_hours: int

    def __post_init__(self) -> None:
        _enum(ProtectedArtifactClass, self.artifact_class, "artifact_class")
        if type(self.lineage_required) is not bool or type(self.encrypted_at_rest) is not bool:
            raise ShadowContractError("artifact booleans differ")
        if not self.lineage_required or not self.encrypted_at_rest:
            raise ShadowContractError("protected artefacts require lineage and encryption")
        _integer(self.retention_days_max, "retention_days_max", minimum=1)
        _integer(
            self.rights_revocation_purge_hours,
            "rights_revocation_purge_hours",
            minimum=1,
        )

    def primitive(self) -> dict[str, object]:
        return {
            "artifact_class": str(self.artifact_class),
            "encrypted_at_rest": self.encrypted_at_rest,
            "lineage_required": self.lineage_required,
            "retention_days_max": self.retention_days_max,
            "rights_revocation_purge_hours": self.rights_revocation_purge_hours,
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        raw = _mapping(value, tuple(cls.__dataclass_fields__), "protected_artifact")
        return cls(
            artifact_class=_enum(ProtectedArtifactClass, raw["artifact_class"], "artifact_class"),
            lineage_required=raw["lineage_required"],  # type: ignore[arg-type]
            encrypted_at_rest=raw["encrypted_at_rest"],  # type: ignore[arg-type]
            retention_days_max=raw["retention_days_max"],  # type: ignore[arg-type]
            rights_revocation_purge_hours=raw["rights_revocation_purge_hours"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class StopAndClosurePolicy(_NoEffect):
    owner_decision_id: str
    global_kill_authority: str
    scoped_kill_authority: str
    p0_kill_seconds: int
    p0_revoke_seconds: int
    p0_notify_seconds: int
    p0_contain_seconds: int
    p1_stop_seconds: int
    p1_notify_seconds: int
    p1_contain_seconds: int
    closure_reasons: tuple[ClosureReason, ...]
    decision_bearing_later_phase_after_early_stop_allowed: bool
    autonomous_recovery_evidence_after_early_stop_allowed: bool

    def __post_init__(self) -> None:
        if self.owner_decision_id != "OD-014":
            raise ShadowContractError("stop policy owner decision differs")
        _token(self.global_kill_authority, "global_kill_authority")
        _token(self.scoped_kill_authority, "scoped_kill_authority")
        for field in (
            "p0_kill_seconds",
            "p0_revoke_seconds",
            "p0_notify_seconds",
            "p0_contain_seconds",
            "p1_stop_seconds",
            "p1_notify_seconds",
            "p1_contain_seconds",
        ):
            _integer(getattr(self, field), field, minimum=1)
        _enums(ClosureReason, self.closure_reasons, "closure_reasons")
        if self.decision_bearing_later_phase_after_early_stop_allowed is not False:
            raise ShadowContractError("decision-bearing later phases must stop")
        if self.autonomous_recovery_evidence_after_early_stop_allowed is not True:
            raise ShadowContractError("recovery evidence must remain allowed")

    def primitive(self) -> dict[str, object]:
        result = {field: getattr(self, field) for field in self.__dataclass_fields__}
        result["closure_reasons"] = [str(item) for item in self.closure_reasons]
        return result

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        raw = _mapping(value, tuple(cls.__dataclass_fields__), "stop_and_closure")
        return cls(
            **{
                **raw,
                "closure_reasons": _enums(
                    ClosureReason, raw["closure_reasons"], "closure_reasons"
                ),
            }
        )  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ShadowScope(_NoEffect):
    schema_version: ClassVar[str] = SHADOW_SCOPE

    scope_id: str
    plan_digest: str
    production_authority: ProductionAuthorityReference
    shadow_authority: ShadowAuthorityIdentity
    access_boundary: ShadowAccessBoundary
    allowed_effects: tuple[ShadowEffect, ...]
    prohibited_effects: tuple[ProhibitedEffect, ...]
    outcomes: tuple[ShadowOutcome, ...]
    production_differences: tuple[ProductionDifference, ...]
    protected_artifacts: tuple[ProtectedArtifactRule, ...]
    stop_and_closure: StopAndClosurePolicy
    created_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _token(self.scope_id, "scope_id")
        if _digest(self.plan_digest, "plan_digest") != INCREMENT_9_SHADOW_PLAN_DIGEST:
            raise ShadowContractError("scope plan digest differs")
        if type(self.production_authority) is not ProductionAuthorityReference:
            raise ShadowContractError("production authority differs")
        if type(self.shadow_authority) is not ShadowAuthorityIdentity:
            raise ShadowContractError("shadow authority differs")
        if type(self.access_boundary) is not ShadowAccessBoundary:
            raise ShadowContractError("access boundary differs")
        if (
            self.access_boundary.principal_identity_digest
            != self.shadow_authority.principal_identity_digest
        ):
            raise ShadowContractError("shadow principal identities differ")
        _enums(ShadowEffect, self.allowed_effects, "allowed_effects")
        _enums(ProhibitedEffect, self.prohibited_effects, "prohibited_effects")
        _enums(ShadowOutcome, self.outcomes, "outcomes")
        if set(self.prohibited_effects) != set(ProhibitedEffect):
            raise ShadowContractError("prohibited effect closure differs")
        if set(self.outcomes) != set(ShadowOutcome):
            raise ShadowContractError("shadow outcome closure differs")
        if (
            not self.production_differences
            or any(
                type(item) is not ProductionDifference
                for item in self.production_differences
            )
            or tuple(
            sorted(item.difference_id for item in self.production_differences)
            )
            != tuple(item.difference_id for item in self.production_differences)
        ):
            raise ShadowContractError("production differences must be unique and sorted")
        if (
            not self.protected_artifacts
            or any(
                type(item) is not ProtectedArtifactRule
                for item in self.protected_artifacts
            )
            or tuple(
                sorted(
                    (item.artifact_class for item in self.protected_artifacts),
                    key=str,
                )
            )
            != tuple(item.artifact_class for item in self.protected_artifacts)
        ):
            raise ShadowContractError("protected artefacts must be unique and sorted")
        if type(self.stop_and_closure) is not StopAndClosurePolicy:
            raise ShadowContractError("stop and closure policy differs")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.expires_at, "expires_at")
        if _instant(self.created_at) >= _instant(self.expires_at):
            raise ShadowContractError("scope expiry must follow creation")
        validate_scope_against_owner_plan(self)

    def primitive(self) -> dict[str, object]:
        return {
            "access_boundary": self.access_boundary.primitive(),
            "allowed_effects": [str(item) for item in self.allowed_effects],
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "outcomes": [str(item) for item in self.outcomes],
            "plan_digest": self.plan_digest,
            "production_authority": self.production_authority.primitive(),
            "production_differences": [item.primitive() for item in self.production_differences],
            "prohibited_effects": [str(item) for item in self.prohibited_effects],
            "protected_artifacts": [item.primitive() for item in self.protected_artifacts],
            "schema_version": self.schema_version,
            "scope_id": self.scope_id,
            "shadow_authority": self.shadow_authority.primitive(),
            "stop_and_closure": self.stop_and_closure.primitive(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.primitive())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = (
            "access_boundary",
            "allowed_effects",
            "created_at",
            "expires_at",
            "outcomes",
            "plan_digest",
            "production_authority",
            "production_differences",
            "prohibited_effects",
            "protected_artifacts",
            "schema_version",
            "scope_id",
            "shadow_authority",
            "stop_and_closure",
        )
        value = _document(raw, SHADOW_SCOPE, fields)
        return cls(
            scope_id=value["scope_id"],  # type: ignore[arg-type]
            plan_digest=value["plan_digest"],  # type: ignore[arg-type]
            production_authority=ProductionAuthorityReference.from_primitive(value["production_authority"]),
            shadow_authority=ShadowAuthorityIdentity.from_primitive(value["shadow_authority"]),
            access_boundary=ShadowAccessBoundary.from_primitive(value["access_boundary"]),
            allowed_effects=_enums(ShadowEffect, value["allowed_effects"], "allowed_effects"),
            prohibited_effects=_enums(ProhibitedEffect, value["prohibited_effects"], "prohibited_effects"),
            outcomes=_enums(ShadowOutcome, value["outcomes"], "outcomes"),
            production_differences=tuple(
                ProductionDifference.from_primitive(item)
                for item in _sequence(value["production_differences"], "production_differences")
            ),
            protected_artifacts=tuple(
                ProtectedArtifactRule.from_primitive(item)
                for item in _sequence(value["protected_artifacts"], "protected_artifacts")
            ),
            stop_and_closure=StopAndClosurePolicy.from_primitive(value["stop_and_closure"]),
            created_at=value["created_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ShadowManifest(_NoEffect):
    schema_version: ClassVar[str] = SHADOW_MANIFEST

    manifest_id: str
    manifest_version: str
    version_ordinal: int
    previous_manifest_digest: str | None
    scope_digest: str
    plan_digest: str
    effective_manifest_digest: str
    production_snapshot_digest: str
    shadow_authority_id: str
    principal_identity_digest: str
    purpose_identity: str
    egress_policy_digest: str
    artefact_policy_digest: str
    created_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _token(self.manifest_id, "manifest_id")
        if self.manifest_version != SHADOW_MANIFEST_VERSION:
            raise ShadowContractError("manifest version differs")
        _integer(self.version_ordinal, "version_ordinal", minimum=1)
        if self.version_ordinal == 1 and self.previous_manifest_digest is not None:
            raise ShadowContractError("first manifest cannot name a predecessor")
        if self.version_ordinal > 1 and self.previous_manifest_digest is None:
            raise ShadowContractError("later manifest requires a predecessor")
        if self.previous_manifest_digest is not None:
            _digest(self.previous_manifest_digest, "previous_manifest_digest")
        for field in (
            "scope_digest",
            "plan_digest",
            "effective_manifest_digest",
            "production_snapshot_digest",
            "principal_identity_digest",
            "egress_policy_digest",
            "artefact_policy_digest",
        ):
            _digest(getattr(self, field), field)
        if self.plan_digest != INCREMENT_9_SHADOW_PLAN_DIGEST:
            raise ShadowContractError("manifest plan digest differs")
        _token(self.shadow_authority_id, "shadow_authority_id")
        _token(self.purpose_identity, "purpose_identity")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.expires_at, "expires_at")
        if _instant(self.created_at) >= _instant(self.expires_at):
            raise ShadowContractError("manifest expiry must follow creation")

    def primitive(self) -> dict[str, object]:
        return {
            "artefact_policy_digest": self.artefact_policy_digest,
            "created_at": self.created_at,
            "effective_manifest_digest": self.effective_manifest_digest,
            "egress_policy_digest": self.egress_policy_digest,
            "expires_at": self.expires_at,
            "manifest_id": self.manifest_id,
            "manifest_version": self.manifest_version,
            "plan_digest": self.plan_digest,
            "previous_manifest_digest": self.previous_manifest_digest,
            "principal_identity_digest": self.principal_identity_digest,
            "production_snapshot_digest": self.production_snapshot_digest,
            "purpose_identity": self.purpose_identity,
            "schema_version": self.schema_version,
            "scope_digest": self.scope_digest,
            "shadow_authority_id": self.shadow_authority_id,
            "version_ordinal": self.version_ordinal,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.primitive())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = (
            "artefact_policy_digest",
            "created_at",
            "effective_manifest_digest",
            "egress_policy_digest",
            "expires_at",
            "manifest_id",
            "manifest_version",
            "plan_digest",
            "previous_manifest_digest",
            "principal_identity_digest",
            "production_snapshot_digest",
            "purpose_identity",
            "schema_version",
            "scope_digest",
            "shadow_authority_id",
            "version_ordinal",
        )
        value = _document(raw, SHADOW_MANIFEST, fields)
        value.pop("schema_version")
        return cls(**value)  # type: ignore[arg-type]


def _sequence(value: object, field: str) -> list[object]:
    if type(value) is not list or not value or len(value) > 64:
        raise ShadowContractError(f"{field} must be a bounded array")
    return value


def _decisions() -> dict[str, Any]:
    return {
        item.decision_id: item.selection
        for item in INCREMENT_9_SHADOW_PLAN.owner_decisions
    }


def validate_scope_against_owner_plan(scope: ShadowScope) -> ShadowScope:
    """Bind a scope to owner-approved identities without creating an effect."""

    decisions = _decisions()
    od2 = decisions["OD-002"]
    schema = od2["schema_version_and_fingerprint"]
    if (
        scope.production_authority.authority != "SQLITE_AND_GOVERNED_OBJECTS"
        or scope.production_authority.schema_version != schema["schema_version"]
        or scope.production_authority.schema_fingerprint != schema["schema_fingerprint"]
        or scope.production_authority.migration_history_digest
        != od2["migration_history_digest"]
    ):
        raise ShadowContractError("production authority reference differs from OD-002")
    od3 = decisions["OD-003"]["database_and_namespace"]
    od4 = decisions["OD-004"]
    if (
        scope.shadow_authority.sqlite_identity != od2["shadow_copy_identity"]
        or scope.shadow_authority.neo4j_database != od3["database"]
        or scope.shadow_authority.neo4j_namespace != od3["namespace"]
        or scope.shadow_authority.graphiti_workspace
        != od4["proposal_workspace_identity"]
    ):
        raise ShadowContractError("shadow authority identity differs from OD-002/003/004")
    if set(scope.allowed_effects) != set(ShadowEffect):
        raise ShadowContractError("allowed shadow effects differ")
    od13 = decisions["OD-013"]
    expected_differences = set(od13["known_material_differences"]) | set(
        od13["known_non_material_differences"]
    )
    observed_differences = {item.difference_id for item in scope.production_differences}
    if observed_differences != expected_differences:
        raise ShadowContractError("production-equivalence differences differ from OD-013")
    od12 = decisions["OD-012"]
    expected_artifacts = set(od12["protected_artifact_classes"])
    if {str(item.artifact_class) for item in scope.protected_artifacts} != expected_artifacts:
        raise ShadowContractError("protected artefact inventory differs from OD-012")
    expected_credentials = set(
        od12["credential_classes_and_secret_locations"]["classes"]
    )
    permitted_credentials = set(scope.access_boundary.permitted_credential_classes)
    prohibited_credentials = set(scope.access_boundary.prohibited_credential_classes)
    if permitted_credentials | prohibited_credentials != expected_credentials:
        raise ShadowContractError("credential classes differ from OD-012")
    if prohibited_credentials != {"PUBLICATION_TARGET_ADAPTER"}:
        raise ShadowContractError("publication credential must remain prohibited")
    od14 = decisions["OD-014"]["containment_owner_and_deadline"]
    stop = scope.stop_and_closure
    if (
        stop.p0_kill_seconds != od14["p0_kill_seconds"]
        or stop.p0_revoke_seconds != od14["p0_revoke_seconds"]
        or stop.p0_notify_seconds != od14["p0_human_notify_seconds"]
        or stop.p0_contain_seconds != od14["p0_contain_seconds"]
        or stop.p1_stop_seconds != od14["p1_stop_seconds"]
        or stop.p1_notify_seconds != od14["p1_notify_seconds"]
        or stop.p1_contain_seconds != od14["p1_contain_seconds"]
    ):
        raise ShadowContractError("containment deadlines differ from OD-014")
    return scope


def validate_manifest_for_scope(scope: ShadowScope, manifest: ShadowManifest) -> ShadowManifest:
    if manifest.scope_digest != scope.canonical_digest:
        raise ShadowContractError("manifest scope digest differs")
    if manifest.production_snapshot_digest != scope.production_authority.snapshot_digest:
        raise ShadowContractError("manifest production snapshot differs")
    if manifest.shadow_authority_id != scope.shadow_authority.authority_id:
        raise ShadowContractError("manifest shadow authority differs")
    if manifest.principal_identity_digest != scope.shadow_authority.principal_identity_digest:
        raise ShadowContractError("manifest principal differs")
    if (
        manifest.purpose_identity != scope.access_boundary.purpose_identity
        or manifest.egress_policy_digest != scope.access_boundary.egress_policy_digest
        or manifest.artefact_policy_digest
        != scope.access_boundary.artefact_policy_digest
    ):
        raise ShadowContractError("manifest access policy identities differ")
    if not (_instant(scope.created_at) <= _instant(manifest.created_at)):
        raise ShadowContractError("manifest predates scope")
    if _instant(manifest.expires_at) > _instant(scope.expires_at):
        raise ShadowContractError("manifest exceeds scope expiry")
    return manifest


def validate_manifest_chain(
    scope: ShadowScope, manifests: tuple[ShadowManifest, ...]
) -> tuple[ShadowManifest, ...]:
    if type(manifests) is not tuple or not manifests:
        raise ShadowContractError("manifest chain must be a non-empty tuple")
    previous: ShadowManifest | None = None
    for ordinal, manifest in enumerate(manifests, 1):
        if type(manifest) is not ShadowManifest:
            raise ShadowContractError("manifest chain contains an invalid record")
        validate_manifest_for_scope(scope, manifest)
        if manifest.version_ordinal != ordinal:
            raise ShadowContractError("manifest ordinal is not contiguous")
        expected = None if previous is None else previous.canonical_digest
        if manifest.previous_manifest_digest != expected:
            raise ShadowContractError("manifest predecessor differs")
        if previous is not None and _instant(manifest.created_at) <= _instant(previous.created_at):
            raise ShadowContractError("manifest chronology differs")
        previous = manifest
    return manifests


@dataclass(frozen=True, slots=True)
class _DeploymentConstructionPermit(_NoEffect):
    """Private 9A2 hand-off; it carries identities, never authority or secrets."""

    manifest_digest: str
    shadow_authority_id: str
    construction_module: str = "newsroom.increment9.deployment"

    def __post_init__(self) -> None:
        _digest(self.manifest_digest, "manifest_digest")
        _token(self.shadow_authority_id, "shadow_authority_id")
        if self.construction_module != "newsroom.increment9.deployment":
            raise ShadowContractError("construction module differs")


def _admit_for_later_deployment(
    scope: ShadowScope, manifest: ShadowManifest
) -> _DeploymentConstructionPermit:
    """Return an inert identity receipt for the private 9A2 construction seam."""

    validate_manifest_for_scope(scope, manifest)
    return _DeploymentConstructionPermit(
        manifest_digest=manifest.canonical_digest,
        shadow_authority_id=manifest.shadow_authority_id,
    )
