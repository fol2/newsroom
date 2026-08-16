"""Isolated Increment 9A2 deployment and readiness evidence boundary.

Construction and qualification are limited to the shadow authority and bounded
readiness probes.  No object in this module grants campaign, publication,
Evidence Intake, canary or production authority.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sqlite3
import stat
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Mapping, Self
from urllib.parse import urlsplit

from newsroom.authority import migrations as production_migrations
from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.increment9_shadow_migrations import (
    INCREMENT9_SHADOW_MIGRATION_CHECKSUM,
    INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
    INCREMENT9_SHADOW_SCHEMA_VERSION,
    install_increment9_shadow_schema,
    verify_increment9_shadow_schema,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST
from newsroom.increment9.shadow_contracts import (
    ProtectedArtifactClass,
    ShadowManifest,
    ShadowScope,
    _admit_for_later_deployment,
)

MAX_RECORD_BYTES = 4_194_304
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class DeploymentError(ValueError):
    """Deployment or readiness evidence differs from 9A2 authority."""


class ProbeOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"


class ServiceClass(StrEnum):
    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"
    ACTUAL_ISOLATED_HOST = "ACTUAL_ISOLATED_HOST"
    ACTUAL_ISOLATED_SERVICE = "ACTUAL_ISOLATED_SERVICE"


class ReadinessDisposition(StrEnum):
    READY_FOR_9B2_CONTROLLER_QUALIFICATION = "READY_FOR_9B2_CONTROLLER_QUALIFICATION"
    NOT_READY = "NOT_READY"


EXPECTED_CREDENTIAL_CLASSES = (
    "ANTHROPIC_AGENT_SDK",
    "GOOGLE_GEMINI_API",
    "NEO4J_SHADOW_WRITER",
    "OPENAI_CODEX_LOGIN",
    "OPENAI_EMBEDDINGS_API",
    "SOURCE_OWNER_PROVISIONED",
    "XAI_GROK_BUILD_LOGIN",
)
PROHIBITED_CREDENTIAL_CLASSES = ("PUBLICATION_TARGET_ADAPTER",)
EXPECTED_EGRESS_DESTINATIONS = (
    "ANTHROPIC_AGENT_SDK",
    "APPROVED_REVIEW_RESEARCH",
    "GOOGLE_GEMINI_API",
    "INTEGRATED_NEWSROOM_TARGET",
    "OPENAI_CODEX",
    "OPENAI_EMBEDDINGS",
    "TEN_APPROVED_SOURCE_ENDPOINTS",
    "XAI_GROK_BUILD",
)
READINESS_ONLY_DESTINATIONS = ("LOCAL_FILESYSTEM", "LOCAL_NEO4J")
ISOLATED_DIRECTORY_INVENTORY = (
    "authority",
    "backups",
    "evidence",
    "graphiti",
    "graphiti/increment9-graphiti-proposal-workspace-v1",
    "objects",
)
ISOLATED_FILE_INVENTORY = (
    "authority/epoch.sqlite3",
    "authority/production-snapshot.sqlite3",
    "backups/epoch.sqlite3",
    "backups/production-snapshot.sqlite3",
    "deployment-plan.json",
    "egress-policy.json",
)
PRODUCTION_SCHEMA_VERSION = 32
PRODUCTION_SCHEMA_FINGERPRINT = (
    "sha256:3439b82ec6d212116e54765d50cace4d7f147b6ecc3e6ff84146b523c6fd5676"
)
PRODUCTION_MIGRATION_HISTORY_DIGEST = (
    "sha256:5a48fd76cd11f266e19a4b48174d0c009f320a8d00d3eeb281a558fc2d561910"
)
EXPECTED_COMPONENT_LOCKS = MappingProxyType(
    {
        "embedding_dimensions": "1024",
        "embedding_model": "text-embedding-3-large",
        "embedding_sdk": "3.1.0",
        "epoch_sqlite_migration_checksum": INCREMENT9_SHADOW_MIGRATION_CHECKSUM,
        "epoch_sqlite_schema_fingerprint": INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
        "epoch_sqlite_schema_version": str(INCREMENT9_SHADOW_SCHEMA_VERSION),
        "graphiti_package": "graphiti-core==0.29.3",
        "graphiti_wheel_sha256": "0210510e8043b5b4fa57aa038934e849b2e61d31d298200b0074faf7ca793ed5",
        "neo4j_arm64_digest": "sha256:a731d66b956a4155333eb09badfb3b17ad51d1aedaaf2c1530e24fd24e5559a9",
        "neo4j_driver": "neo4j==6.2.0",
        "neo4j_driver_wheel_sha256": "b87abdd13a5cc2e3bd51026926c2f20ac38fa3febe98c340520dce19e97388d0",
        "neo4j_image": "neo4j:5.26.2",
        "neo4j_index_digest": "sha256:099b9f74968c123209972835417985ed2a1cc19c0422c0753a313e26a736c365",
        "ontology": "INCREMENT4_GOVERNED_ONTOLOGY_V1",
        "projection_mapping": "INCREMENT4_PROJECTION_V1",
        "projector": "ADMITTED_GENERATION_ONLY",
        "production_sqlite_migration_history_digest": PRODUCTION_MIGRATION_HISTORY_DIGEST,
        "production_sqlite_schema_fingerprint": PRODUCTION_SCHEMA_FINGERPRINT,
        "production_sqlite_schema_version": str(PRODUCTION_SCHEMA_VERSION),
        "vector_similarity": "COSINE",
    }
)
EXPECTED_EFFECTIVE_IDENTITIES = (
    "controller_code",
    "controller_config",
    "graphiti_adapter_code",
    "ontology_mapping_code",
    "projector_code",
)
EXPECTED_PROBES = (
    "ARTIFACT_ENCRYPTION_ACCESS_AUDIT",
    "BACKUP_RESTORE_RECONCILIATION",
    "CAPACITY_MACM4",
    "CREDENTIAL_VALUES_ABSENT",
    "DNS_TLS_REDIRECT_BODY_TIMEOUT_RATE_BOUNDS",
    "EGRESS_ALLOWLIST_BOUNDED",
    "EGRESS_DEFAULT_DENY",
    "EVIDENCE_INTAKE_PATH_DENIED",
    "EXACT_COMPONENT_IDENTITIES",
    "FILESYSTEM_SEPARATION",
    "FULLTEXT_GENERATION_SCOPED",
    "GRAPHITI_PROPOSAL_ONLY",
    "KILL_SWITCH_AND_CONTAINMENT",
    "NEO4J_AUTHENTICATED",
    "NEO4J_DATABASE_NAMESPACE",
    "PRODUCTION_CREDENTIAL_DENIED",
    "PRODUCTION_NEO4J_DENIED",
    "PRODUCTION_NONMUTATION",
    "PRODUCTION_SQLITE_WRITE_DENIED",
    "PUBLICATION_PATH_DENIED",
    "PURGE_NO_RESURRECTION",
    "RESTART_RECONCILIATION",
    "SQLITE_ISOLATED_SCHEMA",
    "TEARDOWN_ZERO_ORPHANS",
    "VECTOR_GENERATION_1024_COSINE",
)
ACTUAL_SERVICE_PROBES = frozenset(
    {
        "FULLTEXT_GENERATION_SCOPED",
        "NEO4J_AUTHENTICATED",
        "NEO4J_DATABASE_NAMESPACE",
        "RESTART_RECONCILIATION",
        "TEARDOWN_ZERO_ORPHANS",
        "VECTOR_GENERATION_1024_COSINE",
    }
)
ACTUAL_HOST_PROBES = frozenset(
    {
        "ARTIFACT_ENCRYPTION_ACCESS_AUDIT",
        "BACKUP_RESTORE_RECONCILIATION",
        "CAPACITY_MACM4",
        "CREDENTIAL_VALUES_ABSENT",
        "EGRESS_ALLOWLIST_BOUNDED",
        "EGRESS_DEFAULT_DENY",
        "EVIDENCE_INTAKE_PATH_DENIED",
        "EXACT_COMPONENT_IDENTITIES",
        "FILESYSTEM_SEPARATION",
        "GRAPHITI_PROPOSAL_ONLY",
        "KILL_SWITCH_AND_CONTAINMENT",
        "PRODUCTION_CREDENTIAL_DENIED",
        "PRODUCTION_NEO4J_DENIED",
        "PRODUCTION_NONMUTATION",
        "PRODUCTION_SQLITE_WRITE_DENIED",
        "PUBLICATION_PATH_DENIED",
        "PURGE_NO_RESURRECTION",
        "SQLITE_ISOLATED_SCHEMA",
    }
)


class _NoPublicEffect:
    authorises_campaign = False
    authorises_decision_bearing_evidence = False
    authorises_source_portfolio_io = False
    authorises_provider_or_model_call = False
    authorises_publication = False
    authorises_evidence_intake = False
    authorises_canary = False
    authorises_production_mutation = False
    authorises_production_activation = False
    authorises_readiness_local_neo4j = True
    authorises_readiness_shadow_credentials = True


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DeploymentError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _text(value: object, field: str, maximum: int = 2048) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value.encode("utf-8", errors="strict")) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DeploymentError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise DeploymentError(f"{field} must be a canonical token")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise DeploymentError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise DeploymentError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise DeploymentError(f"{field} must be an exact UTC timestamp") from exc
    return value


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise DeploymentError(f"{field} must be a bounded integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise DeploymentError(f"{field} must be a boolean")
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    try:
        if type(value) is not str and type(value) is not kind:
            raise ValueError
        return kind(value)
    except ValueError as exc:
        raise DeploymentError(f"{field} differs") from exc


def _mapping(value: object, fields: frozenset[str], field: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise DeploymentError(f"{field} fields differ")
    return value


def _tokens(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if type(value) not in (list, tuple) or (not value and not allow_empty) or len(value) > 256:
        raise DeploymentError(f"{field} must be a bounded array")
    result = tuple(_token(item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise DeploymentError(f"{field} must be unique and sorted")
    return result


def _document(raw: bytes, schema: str, fields: frozenset[str]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RECORD_BYTES:
        raise DeploymentError("deployment record bytes are not bounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except DeploymentError:
        raise
    except (UnicodeError, json.JSONDecodeError, CanonicalizationError, RecursionError) as exc:
        raise DeploymentError("deployment record bytes are invalid") from exc
    if canonical != raw:
        raise DeploymentError("deployment record bytes must be exact canonical JSON")
    value = _mapping(value, fields | {"schema_version"}, "deployment record")
    if value.pop("schema_version") != schema:
        raise DeploymentError("deployment record schema differs")
    return value


@dataclass(frozen=True, slots=True)
class _Record(_NoPublicEffect):
    schema_version: ClassVar[str]

    def primitive(self) -> dict[str, object]:
        raise NotImplementedError

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.primitive())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class EgressPolicy(_NoPublicEffect):
    configured_destinations: tuple[str, ...] = EXPECTED_EGRESS_DESTINATIONS
    readiness_destinations: tuple[str, ...] = READINESS_ONLY_DESTINATIONS
    default_deny: bool = True
    dns_pinned_per_request: bool = True
    tls_minimum: str = "TLS_1_3"
    redirects_max: int = 0
    response_body_bytes_max: int = 8_388_608
    timeout_seconds: int = 30
    source_requests_per_day_max: int = 36

    def __post_init__(self) -> None:
        if type(self.configured_destinations) is not tuple or type(self.readiness_destinations) is not tuple:
            raise DeploymentError("egress destination collections must be tuples")
        if tuple(self.configured_destinations) != EXPECTED_EGRESS_DESTINATIONS:
            raise DeploymentError("configured egress destinations differ from OD-012")
        if tuple(self.readiness_destinations) != READINESS_ONLY_DESTINATIONS:
            raise DeploymentError("readiness egress must remain local-only")
        _boolean(self.default_deny, "default_deny")
        _boolean(self.dns_pinned_per_request, "dns_pinned_per_request")
        if (self.default_deny, self.dns_pinned_per_request) != (True, True):
            raise DeploymentError("egress default-deny boundary differs")
        if self.tls_minimum != "TLS_1_3":
            raise DeploymentError("TLS minimum differs")
        for field in (
            "redirects_max",
            "response_body_bytes_max",
            "timeout_seconds",
            "source_requests_per_day_max",
        ):
            _integer(getattr(self, field), field)
        if (
            self.redirects_max,
            self.response_body_bytes_max,
            self.timeout_seconds,
            self.source_requests_per_day_max,
        ) != (0, 8_388_608, 30, 36):
            raise DeploymentError("egress request bounds differ")

    def primitive(self) -> dict[str, object]:
        return {
            "configured_destinations": list(self.configured_destinations),
            "default_deny": self.default_deny,
            "dns_pinned_per_request": self.dns_pinned_per_request,
            "readiness_destinations": list(self.readiness_destinations),
            "redirects_max": self.redirects_max,
            "response_body_bytes_max": self.response_body_bytes_max,
            "source_requests_per_day_max": self.source_requests_per_day_max,
            "timeout_seconds": self.timeout_seconds,
            "tls_minimum": self.tls_minimum,
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        value = _mapping(value, frozenset(cls.__dataclass_fields__), "egress_policy")
        value["configured_destinations"] = tuple(value["configured_destinations"])  # type: ignore[arg-type]
        value["readiness_destinations"] = tuple(value["readiness_destinations"])  # type: ignore[arg-type]
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class DeploymentPlan(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.deployment-plan.v1"
    deployment_id: str
    owner_plan_digest: str
    scope_digest: str
    manifest_digest: str
    effective_manifest_digest: str
    production_snapshot_digest: str
    principal_identity_digest: str
    sqlite_identity: str
    neo4j_database: str
    neo4j_namespace: str
    graphiti_workspace: str
    component_locks: Mapping[str, str]
    effective_identity_digests: Mapping[str, str]
    credential_classes: tuple[str, ...]
    prohibited_credential_classes: tuple[str, ...]
    egress_policy: EgressPolicy
    protected_artifact_classes: tuple[ProtectedArtifactClass, ...]
    created_at: str
    expires_at: str
    production_reads_after_snapshot: int = 0
    production_writer_capability: bool = False
    public_effect_adapter_present: bool = False
    evidence_intake_adapter_present: bool = False
    decisions_bearing_campaign_allowed: bool = False

    def __post_init__(self) -> None:
        _token(self.deployment_id, "deployment_id")
        for field in (
            "owner_plan_digest",
            "scope_digest",
            "manifest_digest",
            "effective_manifest_digest",
            "production_snapshot_digest",
            "principal_identity_digest",
        ):
            _digest(getattr(self, field), field)
        if self.owner_plan_digest != INCREMENT_9_SHADOW_PLAN_DIGEST:
            raise DeploymentError("owner plan digest differs")
        for field in (
            "sqlite_identity",
            "neo4j_database",
            "neo4j_namespace",
            "graphiti_workspace",
        ):
            _token(getattr(self, field), field)
        if self.sqlite_identity != "increment9-schema-v32-isolated-shadow-authority":
            raise DeploymentError("SQLite identity differs")
        if (self.neo4j_database, self.neo4j_namespace) != (
            "increment9",
            "increment9_shadow",
        ):
            raise DeploymentError("Neo4j identity differs")
        if self.graphiti_workspace != "increment9-graphiti-proposal-workspace-v1":
            raise DeploymentError("Graphiti workspace differs")
        if dict(self.component_locks) != dict(EXPECTED_COMPONENT_LOCKS):
            raise DeploymentError("component locks differ")
        object.__setattr__(self, "component_locks", MappingProxyType(dict(sorted(self.component_locks.items()))))
        if set(self.effective_identity_digests) != set(EXPECTED_EFFECTIVE_IDENTITIES):
            raise DeploymentError("Effective Manifest identities differ")
        identities = {
            key: _digest(value, f"effective_identity_digests.{key}")
            for key, value in self.effective_identity_digests.items()
        }
        object.__setattr__(self, "effective_identity_digests", MappingProxyType(dict(sorted(identities.items()))))
        if type(self.credential_classes) is not tuple or tuple(self.credential_classes) != EXPECTED_CREDENTIAL_CLASSES:
            raise DeploymentError("credential classes differ")
        if (
            type(self.prohibited_credential_classes) is not tuple
            or tuple(self.prohibited_credential_classes) != PROHIBITED_CREDENTIAL_CLASSES
        ):
            raise DeploymentError("prohibited credential boundary differs")
        if type(self.egress_policy) is not EgressPolicy:
            raise DeploymentError("egress policy type differs")
        expected_artifacts = tuple(sorted(ProtectedArtifactClass, key=str))
        if (
            type(self.protected_artifact_classes) is not tuple
            or tuple(self.protected_artifact_classes) != expected_artifacts
        ):
            raise DeploymentError("protected artifact inventory differs")
        _timestamp(self.created_at, "created_at")
        _timestamp(self.expires_at, "expires_at")
        if _instant(self.created_at) >= _instant(self.expires_at):
            raise DeploymentError("deployment chronology differs")
        _integer(self.production_reads_after_snapshot, "production_reads_after_snapshot")
        if self.production_reads_after_snapshot != 0:
            raise DeploymentError("production reads after snapshot are prohibited")
        for field in (
            "production_writer_capability",
            "public_effect_adapter_present",
            "evidence_intake_adapter_present",
            "decisions_bearing_campaign_allowed",
        ):
            _boolean(getattr(self, field), field)
        if any(
            (
                self.production_writer_capability,
                self.public_effect_adapter_present,
                self.evidence_intake_adapter_present,
                self.decisions_bearing_campaign_allowed,
            )
        ):
            raise DeploymentError("deployment non-effect boundary differs")

    def primitive(self) -> dict[str, object]:
        return {
            "component_locks": dict(self.component_locks),
            "created_at": self.created_at,
            "credential_classes": list(self.credential_classes),
            "decisions_bearing_campaign_allowed": self.decisions_bearing_campaign_allowed,
            "deployment_id": self.deployment_id,
            "effective_identity_digests": dict(self.effective_identity_digests),
            "effective_manifest_digest": self.effective_manifest_digest,
            "egress_policy": self.egress_policy.primitive(),
            "evidence_intake_adapter_present": self.evidence_intake_adapter_present,
            "expires_at": self.expires_at,
            "graphiti_workspace": self.graphiti_workspace,
            "manifest_digest": self.manifest_digest,
            "neo4j_database": self.neo4j_database,
            "neo4j_namespace": self.neo4j_namespace,
            "owner_plan_digest": self.owner_plan_digest,
            "principal_identity_digest": self.principal_identity_digest,
            "production_reads_after_snapshot": self.production_reads_after_snapshot,
            "production_snapshot_digest": self.production_snapshot_digest,
            "production_writer_capability": self.production_writer_capability,
            "prohibited_credential_classes": list(self.prohibited_credential_classes),
            "protected_artifact_classes": [str(item) for item in self.protected_artifact_classes],
            "public_effect_adapter_present": self.public_effect_adapter_present,
            "schema_version": self.schema_version,
            "scope_digest": self.scope_digest,
            "sqlite_identity": self.sqlite_identity,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        value["egress_policy"] = EgressPolicy.from_primitive(value["egress_policy"])
        value["credential_classes"] = tuple(value["credential_classes"])  # type: ignore[arg-type]
        value["prohibited_credential_classes"] = tuple(
            value["prohibited_credential_classes"]  # type: ignore[arg-type]
        )
        value["protected_artifact_classes"] = tuple(
            _enum(ProtectedArtifactClass, item, "protected_artifact_classes")
            for item in value["protected_artifact_classes"]  # type: ignore[union-attr]
        )
        return cls(**value)  # type: ignore[arg-type]


def build_deployment_plan(
    scope: ShadowScope,
    manifest: ShadowManifest,
    *,
    deployment_id: str,
    effective_identity_digests: Mapping[str, str],
    created_at: str,
) -> DeploymentPlan:
    """Consume 9A1's inert construction seam and bind the exact deployment."""

    if type(scope) is not ShadowScope or type(manifest) is not ShadowManifest:
        raise DeploymentError("scope or manifest type differs")
    permit = _admit_for_later_deployment(scope, manifest)
    if permit.construction_module != "newsroom.increment9.deployment":
        raise DeploymentError("9A1 construction permit differs")
    _timestamp(created_at, "created_at")
    if not (_instant(manifest.created_at) <= _instant(created_at) < _instant(manifest.expires_at)):
        raise DeploymentError("deployment creation is outside the manifest window")
    return DeploymentPlan(
        deployment_id=deployment_id,
        owner_plan_digest=scope.plan_digest,
        scope_digest=scope.canonical_digest,
        manifest_digest=manifest.canonical_digest,
        effective_manifest_digest=manifest.effective_manifest_digest,
        production_snapshot_digest=manifest.production_snapshot_digest,
        principal_identity_digest=manifest.principal_identity_digest,
        sqlite_identity=scope.shadow_authority.sqlite_identity,
        neo4j_database=scope.shadow_authority.neo4j_database,
        neo4j_namespace=scope.shadow_authority.neo4j_namespace,
        graphiti_workspace=scope.shadow_authority.graphiti_workspace,
        component_locks=EXPECTED_COMPONENT_LOCKS,
        effective_identity_digests=effective_identity_digests,
        credential_classes=scope.access_boundary.permitted_credential_classes,
        prohibited_credential_classes=scope.access_boundary.prohibited_credential_classes,
        egress_policy=EgressPolicy(),
        protected_artifact_classes=tuple(sorted(ProtectedArtifactClass, key=str)),
        created_at=created_at,
        expires_at=manifest.expires_at,
    )


@dataclass(frozen=True, slots=True)
class ProbeEvidence(_NoPublicEffect):
    probe_id: str
    outcome: ProbeOutcome
    service_class: ServiceClass
    evidence_digest: str
    observed_identity_digest: str
    started_at: str
    completed_at: str
    secret_value_count: int = 0
    production_mutation_count: int = 0
    public_effect_count: int = 0
    orphan_resource_count: int = 0

    def __post_init__(self) -> None:
        _token(self.probe_id, "probe_id")
        if self.probe_id not in EXPECTED_PROBES:
            raise DeploymentError("probe identity differs")
        object.__setattr__(self, "outcome", _enum(ProbeOutcome, self.outcome, "outcome"))
        object.__setattr__(self, "service_class", _enum(ServiceClass, self.service_class, "service_class"))
        _digest(self.evidence_digest, "evidence_digest")
        _digest(self.observed_identity_digest, "observed_identity_digest")
        _timestamp(self.started_at, "started_at")
        _timestamp(self.completed_at, "completed_at")
        if _instant(self.started_at) > _instant(self.completed_at):
            raise DeploymentError("probe chronology differs")
        for field in (
            "secret_value_count",
            "production_mutation_count",
            "public_effect_count",
            "orphan_resource_count",
        ):
            _integer(getattr(self, field), field)

    def primitive(self) -> dict[str, object]:
        return {
            "completed_at": self.completed_at,
            "evidence_digest": self.evidence_digest,
            "observed_identity_digest": self.observed_identity_digest,
            "orphan_resource_count": self.orphan_resource_count,
            "outcome": str(self.outcome),
            "probe_id": self.probe_id,
            "production_mutation_count": self.production_mutation_count,
            "public_effect_count": self.public_effect_count,
            "secret_value_count": self.secret_value_count,
            "service_class": str(self.service_class),
            "started_at": self.started_at,
        }

    @classmethod
    def from_primitive(cls, value: object) -> Self:
        value = _mapping(value, frozenset(cls.__dataclass_fields__), "probe")
        value["outcome"] = _enum(ProbeOutcome, value["outcome"], "outcome")
        value["service_class"] = _enum(ServiceClass, value["service_class"], "service_class")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ReadinessEvidenceBundle(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.readiness-evidence-bundle.v1"
    bundle_id: str
    deployment_plan_digest: str
    scope_digest: str
    manifest_digest: str
    production_before_digest: str
    production_after_digest: str
    probes: tuple[ProbeEvidence, ...]
    sealed_at: str
    source_campaign_attempt_count: int = 0
    decision_bearing_case_count: int = 0

    def __post_init__(self) -> None:
        _token(self.bundle_id, "bundle_id")
        for field in (
            "deployment_plan_digest",
            "scope_digest",
            "manifest_digest",
            "production_before_digest",
            "production_after_digest",
        ):
            _digest(getattr(self, field), field)
        if type(self.probes) is not tuple or any(type(item) is not ProbeEvidence for item in self.probes):
            raise DeploymentError("probe bundle type differs")
        if tuple(item.probe_id for item in self.probes) != EXPECTED_PROBES:
            raise DeploymentError("probe inventory must be exact and ordered")
        _timestamp(self.sealed_at, "sealed_at")
        if any(_instant(item.completed_at) > _instant(self.sealed_at) for item in self.probes):
            raise DeploymentError("bundle predates a probe")
        _integer(self.source_campaign_attempt_count, "source_campaign_attempt_count")
        _integer(self.decision_bearing_case_count, "decision_bearing_case_count")
        if self.source_campaign_attempt_count != 0 or self.decision_bearing_case_count != 0:
            raise DeploymentError("readiness evidence contains campaign work")

    def primitive(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "decision_bearing_case_count": self.decision_bearing_case_count,
            "deployment_plan_digest": self.deployment_plan_digest,
            "manifest_digest": self.manifest_digest,
            "probes": [item.primitive() for item in self.probes],
            "production_after_digest": self.production_after_digest,
            "production_before_digest": self.production_before_digest,
            "schema_version": self.schema_version,
            "scope_digest": self.scope_digest,
            "sealed_at": self.sealed_at,
            "source_campaign_attempt_count": self.source_campaign_attempt_count,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        probes = value["probes"]
        if type(probes) is not list:
            raise DeploymentError("probes must be an array")
        value["probes"] = tuple(ProbeEvidence.from_primitive(item) for item in probes)
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class DeploymentReadinessReceipt(_Record):
    schema_version: ClassVar[str] = "newsroom.increment9.deployment-readiness-receipt.v1"
    receipt_id: str
    deployment_plan_digest: str
    evidence_bundle_digest: str
    disposition: ReadinessDisposition
    reason: str
    actual_service_probe_ids: tuple[str, ...]
    actual_host_probe_ids: tuple[str, ...]
    production_nonmutation_proved: bool
    teardown_complete: bool
    completed_at: str
    runtime_campaign_authority_still_required: bool = True

    def __post_init__(self) -> None:
        _token(self.receipt_id, "receipt_id")
        _digest(self.deployment_plan_digest, "deployment_plan_digest")
        _digest(self.evidence_bundle_digest, "evidence_bundle_digest")
        object.__setattr__(self, "disposition", _enum(ReadinessDisposition, self.disposition, "disposition"))
        _token(self.reason, "reason")
        actual = _tokens(self.actual_service_probe_ids, "actual_service_probe_ids", allow_empty=True)
        object.__setattr__(self, "actual_service_probe_ids", actual)
        actual_host = _tokens(
            self.actual_host_probe_ids, "actual_host_probe_ids", allow_empty=True
        )
        object.__setattr__(self, "actual_host_probe_ids", actual_host)
        _boolean(self.production_nonmutation_proved, "production_nonmutation_proved")
        _boolean(self.teardown_complete, "teardown_complete")
        _timestamp(self.completed_at, "completed_at")
        if self.runtime_campaign_authority_still_required is not True:
            raise DeploymentError("9A2 cannot grant campaign authority")
        ready = self.disposition is ReadinessDisposition.READY_FOR_9B2_CONTROLLER_QUALIFICATION
        if ready and (
            set(actual) != ACTUAL_SERVICE_PROBES
            or set(actual_host) != ACTUAL_HOST_PROBES
            or not self.production_nonmutation_proved
            or not self.teardown_complete
            or self.reason != "ALL_READINESS_PROBES_PASS"
        ):
            raise DeploymentError("ready receipt evidence differs")
        if not ready and self.reason != "READINESS_EVIDENCE_INCOMPLETE_OR_FAILED":
            raise DeploymentError("not-ready receipt reason differs")

    def primitive(self) -> dict[str, object]:
        return {
            "actual_host_probe_ids": list(self.actual_host_probe_ids),
            "actual_service_probe_ids": list(self.actual_service_probe_ids),
            "completed_at": self.completed_at,
            "deployment_plan_digest": self.deployment_plan_digest,
            "disposition": str(self.disposition),
            "evidence_bundle_digest": self.evidence_bundle_digest,
            "production_nonmutation_proved": self.production_nonmutation_proved,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "runtime_campaign_authority_still_required": self.runtime_campaign_authority_still_required,
            "schema_version": self.schema_version,
            "teardown_complete": self.teardown_complete,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        value["disposition"] = _enum(ReadinessDisposition, value["disposition"], "disposition")
        value["actual_host_probe_ids"] = tuple(value["actual_host_probe_ids"])  # type: ignore[arg-type]
        value["actual_service_probe_ids"] = tuple(value["actual_service_probe_ids"])  # type: ignore[arg-type]
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class IsolatedDeploymentReceipt(_Record):
    """Immutable identity of one materialised local shadow authority."""

    schema_version: ClassVar[str] = "newsroom.increment9.isolated-deployment-receipt.v1"
    receipt_id: str
    deployment_plan_digest: str
    root_identity_digest: str
    directory_inventory: tuple[str, ...]
    protected_file_digests: Mapping[str, str]
    epoch_schema_version: int
    epoch_schema_fingerprint: str
    epoch_backup_restore_digest: str
    production_snapshot_digest: str
    production_snapshot_schema_version: int
    production_snapshot_schema_fingerprint: str
    production_snapshot_migration_history_digest: str
    production_snapshot_backup_restore_digest: str
    graphiti_workspace: str
    neo4j_database: str
    neo4j_namespace: str
    created_at: str
    secret_value_count: int = 0
    production_path_count: int = 0
    public_effect_adapter_count: int = 0
    encryption_access_audit_still_required: bool = True

    def __post_init__(self) -> None:
        _token(self.receipt_id, "receipt_id")
        for field in (
            "deployment_plan_digest",
            "root_identity_digest",
            "epoch_schema_fingerprint",
            "epoch_backup_restore_digest",
            "production_snapshot_digest",
            "production_snapshot_schema_fingerprint",
            "production_snapshot_migration_history_digest",
            "production_snapshot_backup_restore_digest",
        ):
            _digest(getattr(self, field), field)
        if type(self.directory_inventory) is not tuple or self.directory_inventory != ISOLATED_DIRECTORY_INVENTORY:
            raise DeploymentError("isolated directory inventory differs")
        if type(self.protected_file_digests) is not dict:
            raise DeploymentError("protected file inventory type differs")
        if tuple(sorted(self.protected_file_digests)) != ISOLATED_FILE_INVENTORY:
            raise DeploymentError("protected file inventory differs")
        files = {
            _text(path, "protected_file_path", 256): _digest(value, f"protected_file_digests.{path}")
            for path, value in self.protected_file_digests.items()
        }
        object.__setattr__(self, "protected_file_digests", MappingProxyType(dict(sorted(files.items()))))
        _integer(self.epoch_schema_version, "epoch_schema_version")
        if (
            self.epoch_schema_version != INCREMENT9_SHADOW_SCHEMA_VERSION
            or self.epoch_schema_fingerprint != INCREMENT9_SHADOW_SCHEMA_FINGERPRINT
        ):
            raise DeploymentError("materialised Epoch SQLite identity differs")
        _integer(
            self.production_snapshot_schema_version,
            "production_snapshot_schema_version",
        )
        if (
            self.production_snapshot_schema_version != PRODUCTION_SCHEMA_VERSION
            or self.production_snapshot_schema_fingerprint
            != PRODUCTION_SCHEMA_FINGERPRINT
            or self.production_snapshot_migration_history_digest
            != PRODUCTION_MIGRATION_HISTORY_DIGEST
        ):
            raise DeploymentError("materialised production snapshot identity differs")
        if (
            self.graphiti_workspace != "increment9-graphiti-proposal-workspace-v1"
            or self.neo4j_database != "increment9"
            or self.neo4j_namespace != "increment9_shadow"
        ):
            raise DeploymentError("materialised workspace identity differs")
        _timestamp(self.created_at, "created_at")
        for field in (
            "secret_value_count",
            "production_path_count",
            "public_effect_adapter_count",
        ):
            _integer(getattr(self, field), field)
            if getattr(self, field) != 0:
                raise DeploymentError("materialised deployment crosses isolation boundary")
        if self.encryption_access_audit_still_required is not True:
            raise DeploymentError("storage audit cannot be inferred from materialisation")

    def primitive(self) -> dict[str, object]:
        return {
            "created_at": self.created_at,
            "deployment_plan_digest": self.deployment_plan_digest,
            "directory_inventory": list(self.directory_inventory),
            "encryption_access_audit_still_required": self.encryption_access_audit_still_required,
            "epoch_backup_restore_digest": self.epoch_backup_restore_digest,
            "epoch_schema_fingerprint": self.epoch_schema_fingerprint,
            "epoch_schema_version": self.epoch_schema_version,
            "graphiti_workspace": self.graphiti_workspace,
            "neo4j_database": self.neo4j_database,
            "neo4j_namespace": self.neo4j_namespace,
            "production_path_count": self.production_path_count,
            "production_snapshot_backup_restore_digest": self.production_snapshot_backup_restore_digest,
            "production_snapshot_digest": self.production_snapshot_digest,
            "production_snapshot_migration_history_digest": self.production_snapshot_migration_history_digest,
            "production_snapshot_schema_fingerprint": self.production_snapshot_schema_fingerprint,
            "production_snapshot_schema_version": self.production_snapshot_schema_version,
            "protected_file_digests": dict(self.protected_file_digests),
            "public_effect_adapter_count": self.public_effect_adapter_count,
            "receipt_id": self.receipt_id,
            "root_identity_digest": self.root_identity_digest,
            "schema_version": self.schema_version,
            "secret_value_count": self.secret_value_count,
        }

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        fields = frozenset(name for name in cls.__dataclass_fields__ if name != "schema_version")
        value = _document(raw, cls.schema_version, fields)
        value["directory_inventory"] = tuple(value["directory_inventory"])  # type: ignore[arg-type]
        return cls(**value)  # type: ignore[arg-type]


def qualify_deployment(
    plan: DeploymentPlan,
    bundle: ReadinessEvidenceBundle,
    *,
    receipt_id: str,
) -> DeploymentReadinessReceipt:
    """Produce a readiness-only receipt from one closed-world evidence bundle."""

    if type(plan) is not DeploymentPlan or type(bundle) is not ReadinessEvidenceBundle:
        raise DeploymentError("deployment qualification types differ")
    exact = (
        bundle.deployment_plan_digest == plan.canonical_digest,
        bundle.scope_digest == plan.scope_digest,
        bundle.manifest_digest == plan.manifest_digest,
        bundle.production_before_digest == plan.production_snapshot_digest,
        _instant(bundle.sealed_at) <= _instant(plan.expires_at),
        all(
            _instant(plan.created_at) <= _instant(item.started_at)
            and _instant(item.completed_at) <= _instant(bundle.sealed_at)
            for item in bundle.probes
        ),
        all(
            item.observed_identity_digest
            == expected_probe_identity_digest(plan, item.probe_id, item.service_class)
            for item in bundle.probes
        ),
    )
    actual = tuple(
        item.probe_id
        for item in bundle.probes
        if item.service_class is ServiceClass.ACTUAL_ISOLATED_SERVICE
    )
    actual_host = tuple(
        item.probe_id
        for item in bundle.probes
        if item.service_class is ServiceClass.ACTUAL_ISOLATED_HOST
    )
    observations_clean = all(
        item.outcome is ProbeOutcome.PASS
        and item.secret_value_count == 0
        and item.production_mutation_count == 0
        and item.public_effect_count == 0
        and item.orphan_resource_count == 0
        for item in bundle.probes
    )
    production_clean = bundle.production_before_digest == bundle.production_after_digest
    actual_complete = set(actual) == ACTUAL_SERVICE_PROBES
    host_complete = {
        item.probe_id
        for item in bundle.probes
        if item.service_class is ServiceClass.ACTUAL_ISOLATED_HOST
    } == ACTUAL_HOST_PROBES
    service_classes_exact = all(
        (
            item.service_class is ServiceClass.ACTUAL_ISOLATED_SERVICE
            if item.probe_id in ACTUAL_SERVICE_PROBES
            else item.service_class is ServiceClass.ACTUAL_ISOLATED_HOST
            if item.probe_id in ACTUAL_HOST_PROBES
            else item.service_class is ServiceClass.DETERMINISTIC_FIXTURE
        )
        for item in bundle.probes
    )
    passed = (
        all(exact)
        and observations_clean
        and production_clean
        and actual_complete
        and host_complete
        and service_classes_exact
    )
    reason = "ALL_READINESS_PROBES_PASS" if passed else "READINESS_EVIDENCE_INCOMPLETE_OR_FAILED"
    return DeploymentReadinessReceipt(
        receipt_id=receipt_id,
        deployment_plan_digest=plan.canonical_digest,
        evidence_bundle_digest=bundle.canonical_digest,
        disposition=(
            ReadinessDisposition.READY_FOR_9B2_CONTROLLER_QUALIFICATION
            if passed
            else ReadinessDisposition.NOT_READY
        ),
        reason=reason,
        actual_host_probe_ids=tuple(sorted(actual_host)),
        actual_service_probe_ids=tuple(sorted(actual)),
        production_nonmutation_proved=production_clean,
        teardown_complete=all(item.orphan_resource_count == 0 for item in bundle.probes),
        completed_at=bundle.sealed_at,
    )


def expected_probe_identity_digest(
    plan: DeploymentPlan,
    probe_id: str,
    service_class: ServiceClass,
) -> str:
    """Bind one readiness observation to the immutable deployment identity."""

    if type(plan) is not DeploymentPlan or probe_id not in EXPECTED_PROBES:
        raise DeploymentError("probe identity binding differs")
    service_class = _enum(ServiceClass, service_class, "service_class")
    return digest_bytes(
        canonical_json_bytes(
            {
                "deployment_plan_digest": plan.canonical_digest,
                "effective_manifest_digest": plan.effective_manifest_digest,
                "probe_id": probe_id,
                "service_class": str(service_class),
            }
        )
    )


def _root_identity_digest(root: str | os.PathLike[str]) -> str:
    resolved = os.path.realpath(os.fspath(root))
    return digest_bytes(canonical_json_bytes({"isolated_root": resolved}))


def _require_private_directory(path: str | os.PathLike[str], field: str) -> None:
    value = os.fspath(path)
    if not os.path.isdir(value) or os.path.islink(value):
        raise DeploymentError(f"{field} must be a real directory")
    if stat.S_IMODE(os.stat(value).st_mode) & 0o077:
        raise DeploymentError(f"{field} must deny group and public access")


def _write_protected_bytes(path: str | os.PathLike[str], payload: bytes) -> None:
    value = os.fspath(path)
    descriptor = os.open(value, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            os.unlink(value)
        except FileNotFoundError:
            pass
        raise


def _copy_protected_file(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
    source_text = os.fspath(source)
    target_text = os.fspath(target)
    if (
        os.path.islink(source_text)
        or not os.path.isfile(source_text)
        or os.path.exists(source_text + "-wal")
        or os.path.exists(source_text + "-shm")
    ):
        raise DeploymentError("production snapshot export must be a regular file")
    descriptor = os.open(target_text, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with open(source_text, "rb") as reader, os.fdopen(descriptor, "wb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
    except Exception:
        try:
            os.unlink(target_text)
        except FileNotFoundError:
            pass
        raise


def _file_digest(path: str | os.PathLike[str]) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sqlite_read_only_uri(path: str | os.PathLike[str]) -> str:
    return Path(os.path.abspath(os.fspath(path))).as_uri() + "?mode=ro&immutable=1"


def _verify_production_snapshot(path: str | os.PathLike[str]) -> str:
    connection = sqlite3.connect(_sqlite_read_only_uri(path), uri=True, isolation_level=None)
    try:
        history = connection.execute(
            "SELECT version,name,checksum FROM authority_migrations ORDER BY version"
        ).fetchall()
        history_digest = digest_bytes(canonical_json_bytes(history))
        if (
            connection.execute("PRAGMA user_version").fetchone()[0]
            != PRODUCTION_SCHEMA_VERSION
            or production_migrations.schema_fingerprint(connection)
            != PRODUCTION_SCHEMA_FINGERPRINT
            or history_digest != PRODUCTION_MIGRATION_HISTORY_DIGEST
            or connection.execute("PRAGMA quick_check").fetchone()[0] != "ok"
        ):
            raise DeploymentError("frozen production snapshot identity differs")
        return history_digest
    except sqlite3.Error as exc:
        raise DeploymentError("frozen production snapshot is unreadable") from exc
    finally:
        connection.close()


def _isolated_inventory(root: str | os.PathLike[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    root_text = os.fspath(root)
    directories: list[str] = []
    files: list[str] = []
    for current, names, filenames in os.walk(root_text, followlinks=False):
        if os.path.islink(current):
            raise DeploymentError("isolated deployment contains a symlink")
        if stat.S_IMODE(os.stat(current).st_mode) != 0o700:
            raise DeploymentError("isolated directory mode differs")
        for name in names:
            candidate = os.path.join(current, name)
            if os.path.islink(candidate):
                raise DeploymentError("isolated deployment contains a symlink")
            directories.append(os.path.relpath(candidate, root_text))
        for name in filenames:
            candidate = os.path.join(current, name)
            if os.path.islink(candidate) or not os.path.isfile(candidate):
                raise DeploymentError("isolated deployment contains a non-regular file")
            files.append(os.path.relpath(candidate, root_text))
    return tuple(sorted(directories)), tuple(sorted(files))


def materialise_isolated_deployment(
    plan: DeploymentPlan,
    *,
    root: str | os.PathLike[str],
    production_snapshot: str | os.PathLike[str],
    receipt_id: str,
    created_at: str,
) -> IsolatedDeploymentReceipt:
    """Create one empty, private and production-disconnected shadow authority."""

    if type(plan) is not DeploymentPlan:
        raise DeploymentError("deployment plan type differs")
    _timestamp(created_at, "created_at")
    if not (_instant(plan.created_at) <= _instant(created_at) <= _instant(plan.expires_at)):
        raise DeploymentError("materialisation is outside the deployment window")
    root_text = os.path.abspath(os.fspath(root))
    if os.path.basename(root_text) != plan.deployment_id or os.path.lexists(root_text):
        raise DeploymentError("isolated root identity differs or already exists")
    parent = os.path.dirname(root_text)
    _require_private_directory(parent, "isolated root parent")
    os.mkdir(root_text, 0o700)
    try:
        for relative in ISOLATED_DIRECTORY_INVENTORY:
            os.mkdir(os.path.join(root_text, relative), 0o700)
        _write_protected_bytes(
            os.path.join(root_text, "deployment-plan.json"), plan.canonical_bytes
        )
        _write_protected_bytes(
            os.path.join(root_text, "egress-policy.json"),
            canonical_json_bytes(plan.egress_policy.primitive()),
        )
        snapshot_path = os.path.join(
            root_text, "authority", "production-snapshot.sqlite3"
        )
        _copy_protected_file(production_snapshot, snapshot_path)
        snapshot_digest = _file_digest(snapshot_path)
        if snapshot_digest != plan.production_snapshot_digest:
            raise DeploymentError("frozen production snapshot digest differs")
        snapshot_history_digest = _verify_production_snapshot(snapshot_path)
        snapshot_backup_path = os.path.join(
            root_text, "backups", "production-snapshot.sqlite3"
        )
        descriptor = os.open(
            snapshot_backup_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(descriptor)
        snapshot_source = sqlite3.connect(
            _sqlite_read_only_uri(snapshot_path), uri=True, isolation_level=None
        )
        snapshot_backup = sqlite3.connect(snapshot_backup_path, isolation_level=None)
        try:
            snapshot_source.backup(snapshot_backup)
        finally:
            snapshot_backup.close()
            snapshot_source.close()
        os.chmod(snapshot_backup_path, 0o600)
        _verify_production_snapshot(snapshot_backup_path)

        epoch_path = os.path.join(root_text, "authority", "epoch.sqlite3")
        descriptor = os.open(epoch_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        database = sqlite3.connect(epoch_path)
        try:
            install_increment9_shadow_schema(database)
            verify_increment9_shadow_schema(database)
            database.commit()
        finally:
            database.close()
        os.chmod(epoch_path, 0o600)
        epoch_backup_path = os.path.join(root_text, "backups", "epoch.sqlite3")
        descriptor = os.open(
            epoch_backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        os.close(descriptor)
        source = sqlite3.connect(_sqlite_read_only_uri(epoch_path), uri=True)
        backup = sqlite3.connect(epoch_backup_path)
        try:
            source.backup(backup)
            verify_increment9_shadow_schema(backup)
            backup.commit()
        finally:
            backup.close()
            source.close()
        os.chmod(epoch_backup_path, 0o600)
        directories, files = _isolated_inventory(root_text)
        if directories != ISOLATED_DIRECTORY_INVENTORY or files != ISOLATED_FILE_INVENTORY:
            raise DeploymentError("materialised isolated inventory differs")
        file_digests: dict[str, str] = {}
        for relative in files:
            candidate = os.path.join(root_text, relative)
            if stat.S_IMODE(os.stat(candidate).st_mode) != 0o600:
                raise DeploymentError("protected file mode differs")
            with open(candidate, "rb") as stream:
                file_digests[relative] = digest_bytes(stream.read())
        epoch_backup_restore_digest = digest_bytes(
            canonical_json_bytes(
                {
                    "authority_digest": file_digests["authority/epoch.sqlite3"],
                    "backup_digest": file_digests["backups/epoch.sqlite3"],
                    "schema_fingerprint": INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
                    "schema_version": INCREMENT9_SHADOW_SCHEMA_VERSION,
                }
            )
        )
        production_backup_restore_digest = digest_bytes(
            canonical_json_bytes(
                {
                    "authority_digest": snapshot_digest,
                    "backup_digest": file_digests[
                        "backups/production-snapshot.sqlite3"
                    ],
                    "migration_history_digest": snapshot_history_digest,
                    "schema_fingerprint": PRODUCTION_SCHEMA_FINGERPRINT,
                    "schema_version": PRODUCTION_SCHEMA_VERSION,
                }
            )
        )
        receipt = IsolatedDeploymentReceipt(
            receipt_id=receipt_id,
            deployment_plan_digest=plan.canonical_digest,
            root_identity_digest=_root_identity_digest(root_text),
            directory_inventory=directories,
            protected_file_digests=file_digests,
            epoch_schema_version=INCREMENT9_SHADOW_SCHEMA_VERSION,
            epoch_schema_fingerprint=INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
            epoch_backup_restore_digest=epoch_backup_restore_digest,
            production_snapshot_digest=snapshot_digest,
            production_snapshot_schema_version=PRODUCTION_SCHEMA_VERSION,
            production_snapshot_schema_fingerprint=PRODUCTION_SCHEMA_FINGERPRINT,
            production_snapshot_migration_history_digest=snapshot_history_digest,
            production_snapshot_backup_restore_digest=production_backup_restore_digest,
            graphiti_workspace=plan.graphiti_workspace,
            neo4j_database=plan.neo4j_database,
            neo4j_namespace=plan.neo4j_namespace,
            created_at=created_at,
        )
        verify_materialised_deployment(plan, receipt, root=root_text)
        return receipt
    except Exception:
        shutil.rmtree(root_text, ignore_errors=True)
        raise


def verify_materialised_deployment(
    plan: DeploymentPlan,
    receipt: IsolatedDeploymentReceipt,
    *,
    root: str | os.PathLike[str],
) -> str:
    """Verify exact files, modes, schema and digests without altering state."""

    if type(plan) is not DeploymentPlan or type(receipt) is not IsolatedDeploymentReceipt:
        raise DeploymentError("materialised verification types differ")
    root_text = os.path.abspath(os.fspath(root))
    _require_private_directory(root_text, "isolated root")
    if (
        os.path.basename(root_text) != plan.deployment_id
        or receipt.deployment_plan_digest != plan.canonical_digest
        or receipt.root_identity_digest != _root_identity_digest(root_text)
    ):
        raise DeploymentError("materialised deployment binding differs")
    directories, files = _isolated_inventory(root_text)
    if directories != receipt.directory_inventory or files != ISOLATED_FILE_INVENTORY:
        raise DeploymentError("materialised isolated inventory differs")
    observed: dict[str, str] = {}
    for relative in files:
        candidate = os.path.join(root_text, relative)
        if stat.S_IMODE(os.stat(candidate).st_mode) != 0o600:
            raise DeploymentError("protected file mode differs")
        with open(candidate, "rb") as stream:
            observed[relative] = digest_bytes(stream.read())
    if observed != dict(receipt.protected_file_digests):
        raise DeploymentError("protected file digest differs")
    if (
        receipt.production_snapshot_digest != plan.production_snapshot_digest
        or observed["authority/production-snapshot.sqlite3"]
        != plan.production_snapshot_digest
    ):
        raise DeploymentError("production snapshot binding differs")
    with open(os.path.join(root_text, "deployment-plan.json"), "rb") as stream:
        materialised_plan = stream.read()
    if materialised_plan != plan.canonical_bytes:
        raise DeploymentError("materialised deployment plan differs")
    database = sqlite3.connect(
        _sqlite_read_only_uri(os.path.join(root_text, "authority", "epoch.sqlite3")),
        uri=True,
    )
    backup = sqlite3.connect(
        _sqlite_read_only_uri(os.path.join(root_text, "backups", "epoch.sqlite3")),
        uri=True,
    )
    try:
        verify_increment9_shadow_schema(database)
        verify_increment9_shadow_schema(backup)
    finally:
        backup.close()
        database.close()
    history = _verify_production_snapshot(
        os.path.join(root_text, "authority", "production-snapshot.sqlite3")
    )
    backup_history = _verify_production_snapshot(
        os.path.join(root_text, "backups", "production-snapshot.sqlite3")
    )
    if (
        history != receipt.production_snapshot_migration_history_digest
        or backup_history != history
    ):
        raise DeploymentError("production snapshot restore identity differs")
    expected_epoch_backup = digest_bytes(
        canonical_json_bytes(
            {
                "authority_digest": observed["authority/epoch.sqlite3"],
                "backup_digest": observed["backups/epoch.sqlite3"],
                "schema_fingerprint": INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
                "schema_version": INCREMENT9_SHADOW_SCHEMA_VERSION,
            }
        )
    )
    expected_production_backup = digest_bytes(
        canonical_json_bytes(
            {
                "authority_digest": observed[
                    "authority/production-snapshot.sqlite3"
                ],
                "backup_digest": observed[
                    "backups/production-snapshot.sqlite3"
                ],
                "migration_history_digest": history,
                "schema_fingerprint": PRODUCTION_SCHEMA_FINGERPRINT,
                "schema_version": PRODUCTION_SCHEMA_VERSION,
            }
        )
    )
    if (
        receipt.epoch_backup_restore_digest != expected_epoch_backup
        or receipt.production_snapshot_backup_restore_digest
        != expected_production_backup
    ):
        raise DeploymentError("backup and restore receipt differs")
    return digest_bytes(
        canonical_json_bytes(
            {
                "deployment_plan_digest": plan.canonical_digest,
                "isolated_deployment_receipt_digest": receipt.canonical_digest,
                "verified_file_digests": observed,
            }
        )
    )


def teardown_isolated_deployment(
    plan: DeploymentPlan,
    receipt: IsolatedDeploymentReceipt,
    *,
    root: str | os.PathLike[str],
) -> str:
    """Remove an exactly verified isolated authority and prove no resurrection."""

    root_text = os.path.abspath(os.fspath(root))
    verification_digest = verify_materialised_deployment(plan, receipt, root=root_text)
    shutil.rmtree(root_text)
    if os.path.lexists(root_text):
        raise DeploymentError("isolated teardown left an orphan")
    parent_descriptor = os.open(os.path.dirname(root_text), os.O_RDONLY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    return digest_bytes(
        canonical_json_bytes(
            {
                "isolated_deployment_receipt_digest": receipt.canonical_digest,
                "purged": True,
                "verification_digest": verification_digest,
            }
        )
    )


def admit_readiness_egress(uri: str) -> str:
    """Enforce the 9A2 local-only readiness egress boundary."""

    if type(uri) is not str:
        raise DeploymentError("readiness egress URI differs")
    parsed = urlsplit(uri)
    if (
        parsed.scheme not in {"bolt", "neo4j"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise DeploymentError("readiness egress is default-denied")
    return "LOCAL_NEO4J"


def verify_isolated_sqlite_backup_restore() -> str:
    """Exercise the standalone shadow schema and SQLite backup/restore in memory."""

    source = sqlite3.connect(":memory:")
    restored = sqlite3.connect(":memory:")
    try:
        install_increment9_shadow_schema(source)
        verify_increment9_shadow_schema(source)
        source.backup(restored)
        verify_increment9_shadow_schema(restored)
        identity = {
            "schema_version": INCREMENT9_SHADOW_SCHEMA_VERSION,
            "schema_fingerprint": INCREMENT9_SHADOW_SCHEMA_FINGERPRINT,
            "integrity": source.execute("PRAGMA integrity_check").fetchone()[0],
            "restored_integrity": restored.execute("PRAGMA integrity_check").fetchone()[0],
        }
        return digest_bytes(canonical_json_bytes(identity))
    finally:
        restored.close()
        source.close()


def probe_macm4_capacity(*, root: str = "/") -> Mapping[str, object]:
    """Observe the approved Mac M4 host identity without changing host state."""

    if type(root) is not str or not os.path.isabs(root):
        raise DeploymentError("capacity root must be absolute")
    memory_bytes = int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    values: dict[str, object] = {
        "architecture": platform.machine(),
        "logical_cores": os.cpu_count(),
        "machine_model": platform.machine(),
        "memory_bytes": memory_bytes,
        "root_available_bytes": shutil.disk_usage(root).free,
        "secret_value_count": 0,
    }
    # macOS reports the Apple model separately from the CPU architecture.
    try:
        import subprocess

        result = subprocess.run(
            [
                "/usr/sbin/sysctl",
                "-n",
                "hw.model",
                "machdep.cpu.brand_string",
                "hw.physicalcpu",
                "hw.logicalcpu",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.splitlines()
        if len(lines) == 4:
            values["machine_model"], values["chip"] = lines[:2]
            values["physical_cores"] = int(lines[2])
            values["reported_logical_cores"] = int(lines[3])
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        values["chip"] = "UNAVAILABLE"
    values["matches_od003"] = (
        values.get("architecture") == "arm64"
        and values.get("logical_cores") == 10
        and values.get("machine_model") == "Mac16,10"
        and values.get("chip") == "Apple M4"
        and values.get("physical_cores") == 10
        and values.get("reported_logical_cores") == 10
        and memory_bytes >= 17_179_869_184
        and int(values["root_available_bytes"]) >= 10_240 * 1024 * 1024
    )
    values["evidence_digest"] = digest_bytes(canonical_json_bytes(values))
    return MappingProxyType(values)


def probe_increment9_neo4j(
    *,
    uri: str,
    username: str,
    password: str,
    database: str = "increment9",
    namespace: str = "increment9_shadow",
) -> Mapping[str, object]:
    """Run a bounded, self-cleaning actual-service readiness probe.

    The caller owns credential acquisition. Secret values are never returned.
    The probe writes only its unique namespace and removes all created state.
    """

    if database != "increment9" or namespace != "increment9_shadow":
        raise DeploymentError("actual-service namespace differs")
    if type(uri) is not str or type(username) is not str or type(password) is not str:
        raise DeploymentError("actual-service connection inputs differ")
    try:
        admit_readiness_egress(uri)
    except DeploymentError:
        raise DeploymentError(
            "actual-service connection must be local and credential-separated"
        ) from None
    if not username or not password:
        raise DeploymentError("actual-service connection inputs differ")
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:  # pragma: no cover - locked dependency in qualification
        raise DeploymentError("neo4j driver is unavailable") from exc
    nonce = uuid.uuid4().hex
    fulltext = f"i9_readiness_fulltext_{nonce}"
    vector = f"i9_readiness_vector_{nonce}"
    driver = GraphDatabase.driver(uri, auth=(username, password))
    observed: dict[str, object] = {}
    probe_failed = False
    cleanup_failed = False
    try:
        try:
            driver.verify_connectivity()
            with driver.session(database=database) as session:
                component = session.run(
                    "CALL dbms.components() YIELD name, versions, edition "
                    "RETURN name, versions[0] AS version, edition"
                ).single(strict=True)
                observed.update(
                    server_name=str(component["name"]),
                    server_version=str(component["version"]),
                    edition=str(component["edition"]),
                    database=database,
                    namespace=namespace,
                )
                session.run(
                    f"CREATE FULLTEXT INDEX `{fulltext}` "
                    "FOR (n:Increment9ReadinessProbe) ON EACH [n.text]"
                ).consume()
                session.run(
                    f"CREATE VECTOR INDEX `{vector}` "
                    "FOR (n:Increment9ReadinessProbe) ON (n.embedding) "
                    "OPTIONS {indexConfig: {`vector.dimensions`: 1024, "
                    "`vector.similarity_function`: 'cosine'}}"
                ).consume()
                session.run(
                    "CREATE (n:Increment9ReadinessProbe "
                    "{namespace:$namespace, nonce:$nonce, text:'fixture', "
                    "embedding:$embedding})",
                    namespace=namespace,
                    nonce=nonce,
                    embedding=[0.0] * 1024,
                ).consume()
                session.run("CALL db.awaitIndexes(30)").consume()
                observed["round_trip_count"] = int(
                    session.run(
                        "MATCH (n:Increment9ReadinessProbe "
                        "{namespace:$namespace, nonce:$nonce}) "
                        "RETURN count(n) AS count",
                        namespace=namespace,
                        nonce=nonce,
                    ).single(strict=True)["count"]
                )
                observed["indexes"] = session.run(
                    "SHOW INDEXES YIELD name, type, state "
                    "WHERE name = $fulltext OR name = $vector "
                    "RETURN name, type, state ORDER BY name",
                    fulltext=fulltext,
                    vector=vector,
                ).data()
        except Exception:
            probe_failed = True
        finally:
            try:
                with driver.session(database=database) as cleanup:
                    cleanup.run(
                        "MATCH (n:Increment9ReadinessProbe "
                        "{namespace:$namespace, nonce:$nonce}) DETACH DELETE n",
                        namespace=namespace,
                        nonce=nonce,
                    ).consume()
                    cleanup.run(f"DROP INDEX `{fulltext}` IF EXISTS").consume()
                    cleanup.run(f"DROP INDEX `{vector}` IF EXISTS").consume()
                    observed["remaining_probe_nodes"] = int(
                        cleanup.run(
                            "MATCH (n:Increment9ReadinessProbe "
                            "{namespace:$namespace, nonce:$nonce}) "
                            "RETURN count(n) AS count",
                            namespace=namespace,
                            nonce=nonce,
                        ).single(strict=True)["count"]
                    )
                    observed["remaining_probe_indexes"] = len(
                        cleanup.run(
                            "SHOW INDEXES YIELD name "
                            "WHERE name = $fulltext OR name = $vector RETURN name",
                            fulltext=fulltext,
                            vector=vector,
                        ).data()
                    )
            except Exception:
                cleanup_failed = True
    finally:
        driver.close()
    if probe_failed:
        raise DeploymentError("Neo4j readiness probe failed") from None
    if cleanup_failed:
        raise DeploymentError("Neo4j readiness teardown failed") from None
    if (
        observed.get("server_version") != "5.26.2"
        or str(observed.get("edition", "")).lower() != "community"
    ):
        raise DeploymentError("Neo4j runtime identity differs")
    if (
        observed.get("round_trip_count") != 1
        or observed.get("remaining_probe_nodes") != 0
        or observed.get("remaining_probe_indexes") != 0
    ):
        raise DeploymentError("Neo4j readiness round trip or teardown differs")
    indexes = observed.get("indexes")
    if (
        not isinstance(indexes, list)
        or sorted(str(item.get("type")) for item in indexes)
        != ["FULLTEXT", "VECTOR"]
        or any(item.get("state") != "ONLINE" for item in indexes)
    ):
        raise DeploymentError("Neo4j readiness indexes differ")
    observed["secret_value_count"] = 0
    observed["evidence_digest"] = digest_bytes(canonical_json_bytes(observed))
    return MappingProxyType(observed)
