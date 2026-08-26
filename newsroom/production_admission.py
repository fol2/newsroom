"""Fail-closed production Operational Admission inspection and minting.

Readiness inspection is a deterministic, provider-free and publication-free
operation.  Production Operational Admission remains distinct from fixture
admission, Increment 11R authority, activation and publication authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)


class ProductionAdmissionError(ValueError):
    """Production readiness or admission evidence failed closed."""


class ReadinessStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


class ProductionGateId(StrEnum):
    RELATIONAL_SCHEMA_CURRENT = "RELATIONAL_SCHEMA_CURRENT"
    OPERATIONAL_PROFILE_CURRENT = "OPERATIONAL_PROFILE_CURRENT"
    GRAPHRAG_DEPLOYMENT_CURRENT = "GRAPHRAG_DEPLOYMENT_CURRENT"
    RETRIEVAL_CONTRACT_CURRENT = "RETRIEVAL_CONTRACT_CURRENT"
    LIVE_EVIDENCE_INTAKE_CURRENT = "LIVE_EVIDENCE_INTAKE_CURRENT"
    PUBLICATION_ADAPTERS_CURRENT = "PUBLICATION_ADAPTERS_CURRENT"
    HANDOFF_NON_EFFECT_IDENTITIES_CURRENT = "HANDOFF_NON_EFFECT_IDENTITIES_CURRENT"
    EFFECTIVE_REVISION_COVERAGE_CURRENT = "EFFECTIVE_REVISION_COVERAGE_CURRENT"
    SPEND_ACCOUNTING_RECONCILED = "SPEND_ACCOUNTING_RECONCILED"
    RIGHTS_TERMS_CREDENTIALS_EGRESS_CURRENT = "RIGHTS_TERMS_CREDENTIALS_EGRESS_CURRENT"
    HERMES_RUNTIME_CONTROLS_CURRENT = "HERMES_RUNTIME_CONTROLS_CURRENT"
    STORAGE_BACKUP_RESTORE_ROLLBACK_CURRENT = "STORAGE_BACKUP_RESTORE_ROLLBACK_CURRENT"
    PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED = (
        "PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED"
    )
    CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND = "CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND"
    SDLC_CORE_SERVICE_CURRENT = "SDLC_CORE_SERVICE_CURRENT"
    READINESS_INSPECTION_NON_EFFECT = "READINESS_INSPECTION_NON_EFFECT"


PRODUCTION_GATE_IDS = tuple(ProductionGateId)

PUBLICATION_SPEC_PATHS = tuple(
    sorted(
        (
            "docs/specs/editorial-automation/autonomy-and-publication-control.md",
            "docs/specs/editorial-automation/content-generation-and-presentation.md",
            "docs/specs/editorial-automation/publication-engineering-and-projection-control.md",
            "docs/specs/editorial-automation/publication-lifecycle-and-audit.md",
            "docs/specs/editorial-automation/quality-evaluation-and-change-control.md",
            "docs/specs/editorial-automation/rights-and-visuals.md",
            "docs/specs/editorial-automation/sensitive-content-and-escalation.md",
            "docs/specs/editorial-automation/story-eligibility-and-evidence.md",
        )
    )
)

_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_NON_INSTRUCTION_ISSUES = frozenset({599, 760})


def _git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise ProductionAdmissionError(f"{field} must be a lowercase Git SHA")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ProductionAdmissionError(f"{field} must be a canonical digest") from exc


def _optional_digest(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _digest(value, field)


def _token(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 256
        or re.fullmatch(r"[A-Za-z0-9._:/-]+", value) is None
    ):
        raise ProductionAdmissionError(f"{field} must be bounded canonical text")
    return value


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProductionAdmissionError(f"{field} must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ProductionAdmissionError(f"{field} must be canonical UTC text") from exc
    if (
        parsed.tzinfo is None
        or parsed.astimezone(UTC).utcoffset() != parsed.utcoffset()
    ):
        raise ProductionAdmissionError(f"{field} must be UTC")
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ProductionAdmissionError(f"{field} must be boolean")
    return value


def _nonnegative_integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ProductionAdmissionError(f"{field} must be a non-negative integer")
    return value


def _positive_integer(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ProductionAdmissionError(f"{field} must be a positive integer")
    return value


def _seal(unsigned: Mapping[str, object], secret: bytes) -> str:
    return (
        "hmac-sha256:"
        + hmac.new(
            secret,
            canonical_json_bytes(unsigned),
            hashlib.sha256,
        ).hexdigest()
    )


def _verify_seal(
    value: Mapping[str, object], *, secret: bytes, field: str = "seal"
) -> None:
    presented = value.get(field)
    if not isinstance(presented, str) or not presented.startswith("hmac-sha256:"):
        raise ProductionAdmissionError(f"{field} is invalid")
    unsigned = {name: item for name, item in value.items() if name != field}
    if not hmac.compare_digest(presented, _seal(unsigned, secret)):
        raise ProductionAdmissionError(f"{field} is invalid")


def _canonical_document(raw: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionAdmissionError("record is not canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ProductionAdmissionError("record is not canonical JSON")
    return MappingProxyType(value)


def _publication_spec_digests(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(PUBLICATION_SPEC_PATHS):
        raise ProductionAdmissionError("publication spec inventory differs")
    return MappingProxyType(
        {
            path: _digest(value[path], f"accepted_publication_spec_digests.{path}")
            for path in PUBLICATION_SPEC_PATHS
        }
    )


@dataclass(frozen=True, slots=True)
class FreezeIdentity:
    exact_main_sha: str
    exact_main_tree: str

    def __post_init__(self) -> None:
        _git_sha(self.exact_main_sha, "exact_main_sha")
        _git_sha(self.exact_main_tree, "exact_main_tree")

    def canonical_value(self) -> dict[str, str]:
        return {
            "exact_main_sha": self.exact_main_sha,
            "exact_main_tree": self.exact_main_tree,
        }


class KeyClass(StrEnum):
    EVIDENCE_AUTHORITY = "EVIDENCE_AUTHORITY"
    HUMAN_ACCOUNTABLE_OWNER = "HUMAN_ACCOUNTABLE_OWNER"
    PRODUCTION_OPERATIONAL_ADMISSION = "PRODUCTION_OPERATIONAL_ADMISSION"


@dataclass(frozen=True, slots=True)
class AuthenticationKey:
    """An injected key reference; secret bytes never enter canonical records."""

    key_id: str
    key_class: KeyClass
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _token(self.key_id, "key_id")
        if not isinstance(self.key_class, KeyClass):
            raise ProductionAdmissionError("key_class differs")
        if not isinstance(self.secret, bytes) or len(self.secret) < 32:
            raise ProductionAdmissionError("authentication key is too short")


class IdentityClass(StrEnum):
    RELATIONAL_SCHEMA = "RELATIONAL_SCHEMA"
    OPERATIONAL_PROFILE = "OPERATIONAL_PROFILE"
    GRAPHRAG_DEPLOYMENT = "GRAPHRAG_DEPLOYMENT"
    RETRIEVAL_CONTRACT = "RETRIEVAL_CONTRACT"
    LIVE_EVIDENCE_INTAKE = "LIVE_EVIDENCE_INTAKE"
    PUBLICATION_ADAPTERS = "PUBLICATION_ADAPTERS"
    HANDOFF_NON_EFFECT = "HANDOFF_NON_EFFECT"

    @property
    def gate_id(self) -> ProductionGateId:
        return {
            IdentityClass.RELATIONAL_SCHEMA: (
                ProductionGateId.RELATIONAL_SCHEMA_CURRENT
            ),
            IdentityClass.OPERATIONAL_PROFILE: (
                ProductionGateId.OPERATIONAL_PROFILE_CURRENT
            ),
            IdentityClass.GRAPHRAG_DEPLOYMENT: (
                ProductionGateId.GRAPHRAG_DEPLOYMENT_CURRENT
            ),
            IdentityClass.RETRIEVAL_CONTRACT: (
                ProductionGateId.RETRIEVAL_CONTRACT_CURRENT
            ),
            IdentityClass.LIVE_EVIDENCE_INTAKE: (
                ProductionGateId.LIVE_EVIDENCE_INTAKE_CURRENT
            ),
            IdentityClass.PUBLICATION_ADAPTERS: (
                ProductionGateId.PUBLICATION_ADAPTERS_CURRENT
            ),
            IdentityClass.HANDOFF_NON_EFFECT: (
                ProductionGateId.HANDOFF_NON_EFFECT_IDENTITIES_CURRENT
            ),
        }[self]


@dataclass(frozen=True, slots=True)
class EvaluatedIdentity:
    identity_class: IdentityClass
    identity_digest: str
    evaluation_evidence_digest: str
    evaluated_sha: str
    evaluated_tree: str
    operational_manifest_digest: str
    production_scope: bool

    def __post_init__(self) -> None:
        if not isinstance(self.identity_class, IdentityClass):
            raise ProductionAdmissionError("identity class differs")
        _digest(self.identity_digest, "identity_digest")
        _digest(self.evaluation_evidence_digest, "evaluation_evidence_digest")
        _git_sha(self.evaluated_sha, "evaluated_sha")
        _git_sha(self.evaluated_tree, "evaluated_tree")
        _digest(self.operational_manifest_digest, "operational_manifest_digest")
        _boolean(self.production_scope, "production_scope")

    @classmethod
    def from_value(cls, value: object) -> EvaluatedIdentity:
        required = {
            "identity_class",
            "identity_digest",
            "evaluation_evidence_digest",
            "evaluated_sha",
            "evaluated_tree",
            "operational_manifest_digest",
            "production_scope",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ProductionAdmissionError("evaluated identity fields differ")
        try:
            identity_class = IdentityClass(value["identity_class"])
        except (TypeError, ValueError) as exc:
            raise ProductionAdmissionError("identity class differs") from exc
        return cls(
            identity_class,
            _digest(value["identity_digest"], "identity_digest"),
            _digest(
                value["evaluation_evidence_digest"],
                "evaluation_evidence_digest",
            ),
            _git_sha(value["evaluated_sha"], "evaluated_sha"),
            _git_sha(value["evaluated_tree"], "evaluated_tree"),
            _digest(
                value["operational_manifest_digest"],
                "operational_manifest_digest",
            ),
            _boolean(value["production_scope"], "production_scope"),
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "identity_class": self.identity_class.value,
            "identity_digest": self.identity_digest,
            "evaluation_evidence_digest": self.evaluation_evidence_digest,
            "evaluated_sha": self.evaluated_sha,
            "evaluated_tree": self.evaluated_tree,
            "operational_manifest_digest": self.operational_manifest_digest,
            "production_scope": self.production_scope,
        }


@dataclass(frozen=True, slots=True)
class ProductionIdentitySet:
    freeze: FreezeIdentity
    operational_manifest_digest: str
    deployment_bytes_digest: str
    relational_schema_version: int
    migration_history_digest: str
    schema_fingerprint: str
    projection_generation_digest: str
    contiguous_projection_watermark: int
    handoff_max_attempts: int
    identities: tuple[EvaluatedIdentity, ...]
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        freeze: FreezeIdentity,
        operational_manifest_digest: str,
        deployment_bytes_digest: str,
        relational_schema_version: int,
        migration_history_digest: str,
        schema_fingerprint: str,
        projection_generation_digest: str,
        contiguous_projection_watermark: int,
        handoff_max_attempts: int,
        identities: Sequence[EvaluatedIdentity],
    ) -> ProductionIdentitySet:
        checked = tuple(sorted(identities, key=lambda item: item.identity_class.value))
        if len({item.identity_class for item in checked}) != len(checked):
            raise ProductionAdmissionError("production identity classes must be unique")
        operational_digest = _digest(
            operational_manifest_digest, "operational_manifest_digest"
        )
        deployment_digest = _digest(deployment_bytes_digest, "deployment_bytes_digest")
        checked_schema_version = _positive_integer(
            relational_schema_version, "relational_schema_version"
        )
        checked_watermark = _positive_integer(
            contiguous_projection_watermark,
            "contiguous_projection_watermark",
        )
        checked_max_attempts = _positive_integer(
            handoff_max_attempts, "handoff_max_attempts"
        )
        value = {
            "schema_version": "newsroom.production-identity-set.v1",
            **freeze.canonical_value(),
            "operational_manifest_digest": operational_digest,
            "deployment_bytes_digest": deployment_digest,
            "relational_schema_version": checked_schema_version,
            "migration_history_digest": _digest(
                migration_history_digest, "migration_history_digest"
            ),
            "schema_fingerprint": _digest(schema_fingerprint, "schema_fingerprint"),
            "projection_generation_digest": _digest(
                projection_generation_digest, "projection_generation_digest"
            ),
            "contiguous_projection_watermark": checked_watermark,
            "handoff_max_attempts": checked_max_attempts,
            "identities": [item.canonical_value() for item in checked],
        }
        raw = canonical_json_bytes(value)
        return cls(
            freeze,
            operational_digest,
            deployment_digest,
            checked_schema_version,
            str(value["migration_history_digest"]),
            str(value["schema_fingerprint"]),
            str(value["projection_generation_digest"]),
            checked_watermark,
            checked_max_attempts,
            checked,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> ProductionIdentitySet:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "exact_main_sha",
            "exact_main_tree",
            "operational_manifest_digest",
            "deployment_bytes_digest",
            "relational_schema_version",
            "migration_history_digest",
            "schema_fingerprint",
            "projection_generation_digest",
            "contiguous_projection_watermark",
            "handoff_max_attempts",
            "identities",
        }
        identities = value.get("identities")
        if (
            set(value) != required
            or value["schema_version"] != "newsroom.production-identity-set.v1"
            or not isinstance(identities, list)
        ):
            raise ProductionAdmissionError("production identity set fields differ")
        rebuilt = cls.build(
            freeze=FreezeIdentity(
                _git_sha(value["exact_main_sha"], "exact_main_sha"),
                _git_sha(value["exact_main_tree"], "exact_main_tree"),
            ),
            operational_manifest_digest=_digest(
                value["operational_manifest_digest"],
                "operational_manifest_digest",
            ),
            deployment_bytes_digest=_digest(
                value["deployment_bytes_digest"], "deployment_bytes_digest"
            ),
            relational_schema_version=_positive_integer(
                value["relational_schema_version"],
                "relational_schema_version",
            ),
            migration_history_digest=_digest(
                value["migration_history_digest"], "migration_history_digest"
            ),
            schema_fingerprint=_digest(
                value["schema_fingerprint"], "schema_fingerprint"
            ),
            projection_generation_digest=_digest(
                value["projection_generation_digest"],
                "projection_generation_digest",
            ),
            contiguous_projection_watermark=_positive_integer(
                value["contiguous_projection_watermark"],
                "contiguous_projection_watermark",
            ),
            handoff_max_attempts=_positive_integer(
                value["handoff_max_attempts"], "handoff_max_attempts"
            ),
            identities=tuple(EvaluatedIdentity.from_value(item) for item in identities),
        )
        if rebuilt.canonical_bytes != raw:
            raise ProductionAdmissionError("production identity set is non-canonical")
        return rebuilt

    def canonical_value(self) -> Mapping[str, object]:
        return _canonical_document(self.canonical_bytes)


class BoundArtifactRole(StrEnum):
    SHADOW_CLOSEOUT = "SHADOW_CLOSEOUT"
    LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT = "LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT"
    BACKUP = "BACKUP"
    RESTORE = "RESTORE"
    ROLLBACK = "ROLLBACK"


_BOUND_OUTCOMES = {
    BoundArtifactRole.SHADOW_CLOSEOUT: "SCOPED_OPERATIONAL_ELIGIBILITY",
    BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT: (
        "ELIGIBLE_FOR_ACTIVATION_PLANNING"
    ),
    BoundArtifactRole.BACKUP: "PASS",
    BoundArtifactRole.RESTORE: "PASS",
    BoundArtifactRole.ROLLBACK: "PASS",
}


@dataclass(frozen=True, slots=True)
class BoundArtifact:
    role: BoundArtifactRole
    artifact_digest: str
    freeze: FreezeIdentity
    operational_manifest_digest: str
    identity_set_digest: str
    deployment_bytes_digest: str
    store_identity_digest: str
    stop_conditions_digest: str
    reconciliation_procedure_digest: str
    outcome: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, BoundArtifactRole):
            raise ProductionAdmissionError("bound artifact role differs")
        _digest(self.artifact_digest, "artifact_digest")
        _digest(self.operational_manifest_digest, "operational_manifest_digest")
        _digest(self.identity_set_digest, "identity_set_digest")
        _digest(self.deployment_bytes_digest, "deployment_bytes_digest")
        _digest(self.store_identity_digest, "store_identity_digest")
        _digest(self.stop_conditions_digest, "stop_conditions_digest")
        _digest(
            self.reconciliation_procedure_digest,
            "reconciliation_procedure_digest",
        )
        _token(self.outcome, "outcome")

    @classmethod
    def build(
        cls,
        *,
        role: BoundArtifactRole,
        artifact_digest: str,
        freeze: FreezeIdentity,
        operational_manifest_digest: str,
        identity_set_digest: str,
        deployment_bytes_digest: str,
        store_identity_digest: str,
        stop_conditions_digest: str,
        reconciliation_procedure_digest: str,
        outcome: str,
    ) -> BoundArtifact:
        if not isinstance(role, BoundArtifactRole):
            raise ProductionAdmissionError("bound artifact role differs")
        return cls(
            role,
            _digest(artifact_digest, "artifact_digest"),
            freeze,
            _digest(operational_manifest_digest, "operational_manifest_digest"),
            _digest(identity_set_digest, "identity_set_digest"),
            _digest(deployment_bytes_digest, "deployment_bytes_digest"),
            _digest(store_identity_digest, "store_identity_digest"),
            _digest(stop_conditions_digest, "stop_conditions_digest"),
            _digest(
                reconciliation_procedure_digest,
                "reconciliation_procedure_digest",
            ),
            _token(outcome, "outcome"),
        )

    @classmethod
    def from_value(cls, value: object) -> BoundArtifact:
        required = {
            "role",
            "artifact_digest",
            "exact_main_sha",
            "exact_main_tree",
            "operational_manifest_digest",
            "identity_set_digest",
            "deployment_bytes_digest",
            "store_identity_digest",
            "stop_conditions_digest",
            "reconciliation_procedure_digest",
            "outcome",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ProductionAdmissionError("bound artifact fields differ")
        try:
            role = BoundArtifactRole(value["role"])
        except (TypeError, ValueError) as exc:
            raise ProductionAdmissionError("bound artifact role differs") from exc
        return cls.build(
            role=role,
            artifact_digest=value["artifact_digest"],  # type: ignore[arg-type]
            freeze=FreezeIdentity(
                _git_sha(value["exact_main_sha"], "exact_main_sha"),
                _git_sha(value["exact_main_tree"], "exact_main_tree"),
            ),
            operational_manifest_digest=value["operational_manifest_digest"],  # type: ignore[arg-type]
            identity_set_digest=value["identity_set_digest"],  # type: ignore[arg-type]
            deployment_bytes_digest=value["deployment_bytes_digest"],  # type: ignore[arg-type]
            store_identity_digest=value["store_identity_digest"],  # type: ignore[arg-type]
            stop_conditions_digest=value["stop_conditions_digest"],  # type: ignore[arg-type]
            reconciliation_procedure_digest=value["reconciliation_procedure_digest"],  # type: ignore[arg-type]
            outcome=_token(value["outcome"], "outcome"),
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "artifact_digest": self.artifact_digest,
            **self.freeze.canonical_value(),
            "operational_manifest_digest": self.operational_manifest_digest,
            "identity_set_digest": self.identity_set_digest,
            "deployment_bytes_digest": self.deployment_bytes_digest,
            "store_identity_digest": self.store_identity_digest,
            "stop_conditions_digest": self.stop_conditions_digest,
            "reconciliation_procedure_digest": (self.reconciliation_procedure_digest),
            "outcome": self.outcome,
        }


@dataclass(frozen=True, slots=True)
class ProductionEvidenceManifest:
    identity_set: ProductionIdentitySet
    gate_artifact_digests: Mapping[ProductionGateId, str]
    bound_artifacts: tuple[BoundArtifact, ...]
    accepted_publication_spec_digests: Mapping[str, str]
    fixture_admission_digest: str
    fixture_admission_inherited: bool
    readiness_provider_calls: int
    readiness_publication_effects: int
    readiness_production_mutations: int
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        identity_set: ProductionIdentitySet,
        gate_artifact_digests: Mapping[ProductionGateId, str],
        bound_artifacts: Sequence[BoundArtifact],
        accepted_publication_spec_digests: Mapping[str, str],
        fixture_admission_digest: str,
        fixture_admission_inherited: bool,
        readiness_provider_calls: int,
        readiness_publication_effects: int,
        readiness_production_mutations: int,
    ) -> ProductionEvidenceManifest:
        reconstructed = ProductionIdentitySet.from_canonical_bytes(
            identity_set.canonical_bytes
        )
        if reconstructed != identity_set:
            raise ProductionAdmissionError("production identity set is forged")
        checked_gate_artifacts: dict[ProductionGateId, str] = {}
        for raw_gate, raw_digest in gate_artifact_digests.items():
            if not isinstance(raw_gate, ProductionGateId):
                raise ProductionAdmissionError("gate artifact key differs")
            checked_gate_artifacts[raw_gate] = _digest(
                raw_digest, f"gate_artifact_digests.{raw_gate.value}"
            )
        checked_bound = tuple(sorted(bound_artifacts, key=lambda item: item.role.value))
        if len({item.role for item in checked_bound}) != len(checked_bound):
            raise ProductionAdmissionError("bound artifact roles must be unique")
        if any(
            BoundArtifact.from_value(item.canonical_value()) != item
            for item in checked_bound
        ):
            raise ProductionAdmissionError("bound artifact is forged")
        checked_publication_specs = _publication_spec_digests(
            accepted_publication_spec_digests
        )
        inherited = _boolean(fixture_admission_inherited, "fixture_admission_inherited")
        provider_calls = _nonnegative_integer(
            readiness_provider_calls, "readiness_provider_calls"
        )
        publication_effects = _nonnegative_integer(
            readiness_publication_effects, "readiness_publication_effects"
        )
        production_mutations = _nonnegative_integer(
            readiness_production_mutations, "readiness_production_mutations"
        )
        value = {
            "schema_version": "newsroom.production-evidence-manifest.v1",
            "identity_set": dict(identity_set.canonical_value()),
            "gate_artifact_digests": {
                gate_id.value: evidence_digest
                for gate_id, evidence_digest in sorted(
                    checked_gate_artifacts.items(), key=lambda item: item[0].value
                )
            },
            "bound_artifacts": [item.canonical_value() for item in checked_bound],
            "accepted_publication_spec_digests": dict(checked_publication_specs),
            "fixture_admission_digest": _digest(
                fixture_admission_digest, "fixture_admission_digest"
            ),
            "fixture_admission_inherited": inherited,
            "readiness_provider_calls": provider_calls,
            "readiness_publication_effects": publication_effects,
            "readiness_production_mutations": production_mutations,
        }
        raw = canonical_json_bytes(value)
        return cls(
            identity_set,
            MappingProxyType(checked_gate_artifacts),
            checked_bound,
            checked_publication_specs,
            str(value["fixture_admission_digest"]),
            inherited,
            provider_calls,
            publication_effects,
            production_mutations,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> ProductionEvidenceManifest:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "identity_set",
            "gate_artifact_digests",
            "bound_artifacts",
            "accepted_publication_spec_digests",
            "fixture_admission_digest",
            "fixture_admission_inherited",
            "readiness_provider_calls",
            "readiness_publication_effects",
            "readiness_production_mutations",
        }
        identity_value = value.get("identity_set")
        gate_values = value.get("gate_artifact_digests")
        bound_values = value.get("bound_artifacts")
        publication_spec_values = value.get("accepted_publication_spec_digests")
        if (
            set(value) != required
            or value["schema_version"] != "newsroom.production-evidence-manifest.v1"
            or not isinstance(identity_value, dict)
            or not isinstance(gate_values, dict)
            or not isinstance(bound_values, list)
            or not isinstance(publication_spec_values, dict)
        ):
            raise ProductionAdmissionError("production evidence manifest fields differ")
        identity_set = ProductionIdentitySet.from_canonical_bytes(
            canonical_json_bytes(identity_value)
        )
        checked_gates: dict[ProductionGateId, str] = {}
        for raw_gate, raw_digest in gate_values.items():
            try:
                gate_id = ProductionGateId(raw_gate)
            except (TypeError, ValueError) as exc:
                raise ProductionAdmissionError("gate artifact key differs") from exc
            checked_gates[gate_id] = _digest(
                raw_digest, f"gate_artifact_digests.{gate_id.value}"
            )
        rebuilt = cls.build(
            identity_set=identity_set,
            gate_artifact_digests=checked_gates,
            bound_artifacts=tuple(
                BoundArtifact.from_value(item) for item in bound_values
            ),
            accepted_publication_spec_digests=_publication_spec_digests(
                publication_spec_values
            ),
            fixture_admission_digest=_digest(
                value["fixture_admission_digest"], "fixture_admission_digest"
            ),
            fixture_admission_inherited=_boolean(
                value["fixture_admission_inherited"],
                "fixture_admission_inherited",
            ),
            readiness_provider_calls=_nonnegative_integer(
                value["readiness_provider_calls"], "readiness_provider_calls"
            ),
            readiness_publication_effects=_nonnegative_integer(
                value["readiness_publication_effects"],
                "readiness_publication_effects",
            ),
            readiness_production_mutations=_nonnegative_integer(
                value["readiness_production_mutations"],
                "readiness_production_mutations",
            ),
        )
        if rebuilt.canonical_bytes != raw:
            raise ProductionAdmissionError(
                "production evidence manifest is non-canonical"
            )
        return rebuilt

    def canonical_value(self) -> Mapping[str, object]:
        return _canonical_document(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class GateAttestation:
    gate_id: ProductionGateId
    evidence_manifest_digest: str
    gate_artifact_digest: str | None
    exact_main_sha: str
    exact_main_tree: str
    identity_set_digest: str
    status: ReadinessStatus
    blockers: tuple[str, ...]
    issuer_identity: str
    sealed_at: str
    signing_key_id: str
    signing_key_class: KeyClass
    seal: str
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        gate_id: ProductionGateId,
        evidence_manifest: ProductionEvidenceManifest,
        status: ReadinessStatus,
        blockers: Sequence[str],
        issuer_identity: str,
        sealed_at: str,
        signing_key: AuthenticationKey,
    ) -> GateAttestation:
        if signing_key.key_class is not KeyClass.EVIDENCE_AUTHORITY:
            raise ProductionAdmissionError("gate attestation key class differs")
        if not isinstance(gate_id, ProductionGateId):
            raise ProductionAdmissionError("gate attestation gate differs")
        if not isinstance(status, ReadinessStatus):
            raise ProductionAdmissionError("gate attestation status differs")
        checked_blockers = tuple(sorted({_token(item, "blocker") for item in blockers}))
        if status is ReadinessStatus.PASS and checked_blockers:
            raise ProductionAdmissionError("passing gate attestation has blockers")
        if status is ReadinessStatus.BLOCKED and not checked_blockers:
            raise ProductionAdmissionError("blocked gate attestation needs a blocker")
        artifact_digest = evidence_manifest.gate_artifact_digests.get(gate_id)
        if status is ReadinessStatus.PASS and artifact_digest is None:
            raise ProductionAdmissionError("passing gate attestation lacks evidence")
        unsigned = {
            "schema_version": "newsroom.production-gate-attestation.v1",
            "gate_id": gate_id.value,
            "evidence_manifest_digest": evidence_manifest.digest,
            "gate_artifact_digest": artifact_digest,
            **evidence_manifest.identity_set.freeze.canonical_value(),
            "identity_set_digest": evidence_manifest.identity_set.digest,
            "status": status.value,
            "blockers": list(checked_blockers),
            "issuer_identity": _token(issuer_identity, "issuer_identity"),
            "sealed_at": _timestamp(sealed_at, "sealed_at"),
            "signing_key_id": signing_key.key_id,
            "signing_key_class": signing_key.key_class.value,
        }
        seal = _seal(unsigned, signing_key.secret)
        value = {**unsigned, "seal": seal}
        raw = canonical_json_bytes(value)
        return cls(
            gate_id,
            evidence_manifest.digest,
            artifact_digest,
            evidence_manifest.identity_set.freeze.exact_main_sha,
            evidence_manifest.identity_set.freeze.exact_main_tree,
            evidence_manifest.identity_set.digest,
            status,
            checked_blockers,
            str(unsigned["issuer_identity"]),
            str(unsigned["sealed_at"]),
            signing_key.key_id,
            signing_key.key_class,
            seal,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> GateAttestation:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "gate_id",
            "evidence_manifest_digest",
            "gate_artifact_digest",
            "exact_main_sha",
            "exact_main_tree",
            "identity_set_digest",
            "status",
            "blockers",
            "issuer_identity",
            "sealed_at",
            "signing_key_id",
            "signing_key_class",
            "seal",
        }
        blockers = value.get("blockers")
        if (
            set(value) != required
            or value["schema_version"] != "newsroom.production-gate-attestation.v1"
            or not isinstance(value["gate_id"], str)
            or not isinstance(value["status"], str)
            or not isinstance(value["signing_key_class"], str)
            or not isinstance(blockers, list)
            or not all(isinstance(item, str) for item in blockers)
        ):
            raise ProductionAdmissionError("gate attestation fields differ")
        try:
            gate_id = ProductionGateId(value["gate_id"])
            status = ReadinessStatus(value["status"])
            key_class = KeyClass(value["signing_key_class"])
        except (TypeError, ValueError) as exc:
            raise ProductionAdmissionError("gate attestation value differs") from exc
        checked_blockers = tuple(sorted({_token(item, "blocker") for item in blockers}))
        if checked_blockers != tuple(blockers):
            raise ProductionAdmissionError(
                "gate attestation blockers are non-canonical"
            )
        if status is ReadinessStatus.PASS and checked_blockers:
            raise ProductionAdmissionError("passing gate attestation has blockers")
        if status is ReadinessStatus.BLOCKED and not checked_blockers:
            raise ProductionAdmissionError("blocked gate attestation needs a blocker")
        seal = value["seal"]
        if not isinstance(seal, str):
            raise ProductionAdmissionError("gate attestation seal differs")
        return cls(
            gate_id,
            _digest(value["evidence_manifest_digest"], "evidence_manifest_digest"),
            _optional_digest(value["gate_artifact_digest"], "gate_artifact_digest"),
            _git_sha(value["exact_main_sha"], "exact_main_sha"),
            _git_sha(value["exact_main_tree"], "exact_main_tree"),
            _digest(value["identity_set_digest"], "identity_set_digest"),
            status,
            checked_blockers,
            _token(value["issuer_identity"], "issuer_identity"),
            _timestamp(value["sealed_at"], "sealed_at"),
            _token(value["signing_key_id"], "signing_key_id"),
            key_class,
            seal,
            raw,
            digest_bytes(raw),
        )

    def verify(self, trusted_keys: Mapping[str, AuthenticationKey]) -> None:
        reconstructed = GateAttestation.from_canonical_bytes(self.canonical_bytes)
        if reconstructed != self:
            raise ProductionAdmissionError("gate attestation is forged")
        key = trusted_keys.get(self.signing_key_id)
        if (
            key is None
            or key.key_id != self.signing_key_id
            or key.key_class is not KeyClass.EVIDENCE_AUTHORITY
            or self.signing_key_class is not KeyClass.EVIDENCE_AUTHORITY
        ):
            raise ProductionAdmissionError("gate attestation key is untrusted")
        _verify_seal(_canonical_document(self.canonical_bytes), secret=key.secret)


@dataclass(frozen=True, slots=True)
class ReadinessGateResult:
    gate_id: ProductionGateId
    status: ReadinessStatus
    blockers: tuple[str, ...]
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.gate_id, ProductionGateId):
            raise ProductionAdmissionError("readiness gate differs")
        if not isinstance(self.status, ReadinessStatus):
            raise ProductionAdmissionError("readiness status differs")
        for blocker in self.blockers:
            _token(blocker, "readiness blocker")
        _optional_digest(self.evidence_digest, "evidence_digest")
        if self.status is ReadinessStatus.PASS and self.blockers:
            raise ProductionAdmissionError("passing readiness gate has blockers")
        if self.status is ReadinessStatus.BLOCKED and not self.blockers:
            raise ProductionAdmissionError("blocked readiness gate needs a blocker")
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise ProductionAdmissionError("readiness blockers must be canonical")

    def canonical_value(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id.value,
            "status": self.status.value,
            "blockers": list(self.blockers),
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class ProductionReadinessReport:
    freeze: FreezeIdentity
    gates: tuple[ReadinessGateResult, ...]
    evidence_manifest_digest: str | None
    operational_manifest_digest: str | None
    identity_set_digest: str | None
    relational_schema_version: int | None
    migration_history_digest: str | None
    schema_fingerprint: str | None
    projection_generation_digest: str | None
    contiguous_projection_watermark: int | None
    handoff_max_attempts: int | None
    ready_for_admission: bool
    canonical_bytes: bytes
    digest: str
    provider_calls: int = 0
    publication_effects: int = 0
    production_mutations: int = 0
    production_activation_authorised: bool = False

    @classmethod
    def build(
        cls,
        *,
        freeze: FreezeIdentity,
        gates: Sequence[ReadinessGateResult],
        evidence_manifest_digest: str | None = None,
        operational_manifest_digest: str | None = None,
        identity_set_digest: str | None = None,
        relational_schema_version: int | None = None,
        migration_history_digest: str | None = None,
        schema_fingerprint: str | None = None,
        projection_generation_digest: str | None = None,
        contiguous_projection_watermark: int | None = None,
        handoff_max_attempts: int | None = None,
    ) -> ProductionReadinessReport:
        checked = tuple(gates)
        if tuple(item.gate_id for item in checked) != PRODUCTION_GATE_IDS:
            raise ProductionAdmissionError("readiness gate inventory differs")
        facts = (
            relational_schema_version,
            migration_history_digest,
            schema_fingerprint,
            projection_generation_digest,
            contiguous_projection_watermark,
            handoff_max_attempts,
        )
        if identity_set_digest is None:
            if any(item is not None for item in facts):
                raise ProductionAdmissionError(
                    "readiness identity facts require an identity set"
                )
        elif any(item is None for item in facts):
            raise ProductionAdmissionError("readiness identity facts are incomplete")
        if relational_schema_version is not None:
            _positive_integer(relational_schema_version, "relational_schema_version")
        if contiguous_projection_watermark is not None:
            _positive_integer(
                contiguous_projection_watermark,
                "contiguous_projection_watermark",
            )
        if handoff_max_attempts is not None:
            _positive_integer(handoff_max_attempts, "handoff_max_attempts")
        checked_evidence_manifest_digest = _optional_digest(
            evidence_manifest_digest, "evidence_manifest_digest"
        )
        checked_operational_manifest_digest = _optional_digest(
            operational_manifest_digest, "operational_manifest_digest"
        )
        checked_identity_set_digest = _optional_digest(
            identity_set_digest, "identity_set_digest"
        )
        checked_migration_history_digest = _optional_digest(
            migration_history_digest, "migration_history_digest"
        )
        checked_schema_fingerprint = _optional_digest(
            schema_fingerprint, "schema_fingerprint"
        )
        checked_projection_generation_digest = _optional_digest(
            projection_generation_digest, "projection_generation_digest"
        )
        ready = all(item.status is ReadinessStatus.PASS for item in checked)
        value = {
            "schema_version": "newsroom.production-readiness-report.v1",
            **freeze.canonical_value(),
            "evidence_manifest_digest": checked_evidence_manifest_digest,
            "operational_manifest_digest": checked_operational_manifest_digest,
            "identity_set_digest": checked_identity_set_digest,
            "relational_schema_version": relational_schema_version,
            "migration_history_digest": checked_migration_history_digest,
            "schema_fingerprint": checked_schema_fingerprint,
            "projection_generation_digest": checked_projection_generation_digest,
            "contiguous_projection_watermark": contiguous_projection_watermark,
            "handoff_max_attempts": handoff_max_attempts,
            "gates": [item.canonical_value() for item in checked],
            "ready_for_admission": ready,
            "provider_calls": 0,
            "publication_effects": 0,
            "production_mutations": 0,
            "production_activation_authorised": False,
        }
        raw = canonical_json_bytes(value)
        return cls(
            freeze,
            checked,
            checked_evidence_manifest_digest,
            checked_operational_manifest_digest,
            checked_identity_set_digest,
            relational_schema_version,
            checked_migration_history_digest,
            checked_schema_fingerprint,
            checked_projection_generation_digest,
            contiguous_projection_watermark,
            handoff_max_attempts,
            ready,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> ProductionReadinessReport:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "exact_main_sha",
            "exact_main_tree",
            "evidence_manifest_digest",
            "operational_manifest_digest",
            "identity_set_digest",
            "relational_schema_version",
            "migration_history_digest",
            "schema_fingerprint",
            "projection_generation_digest",
            "contiguous_projection_watermark",
            "handoff_max_attempts",
            "gates",
            "ready_for_admission",
            "provider_calls",
            "publication_effects",
            "production_mutations",
            "production_activation_authorised",
        }
        if set(value) != required or value["schema_version"] != (
            "newsroom.production-readiness-report.v1"
        ):
            raise ProductionAdmissionError("readiness report fields differ")
        gate_values = value["gates"]
        if not isinstance(gate_values, list):
            raise ProductionAdmissionError("readiness gate inventory differs")
        gates: list[ReadinessGateResult] = []
        for gate_value in gate_values:
            if not isinstance(gate_value, dict) or set(gate_value) != {
                "gate_id",
                "status",
                "blockers",
                "evidence_digest",
            }:
                raise ProductionAdmissionError("readiness gate fields differ")
            blockers = gate_value["blockers"]
            if not isinstance(blockers, list) or not all(
                isinstance(item, str) for item in blockers
            ):
                raise ProductionAdmissionError("readiness blockers differ")
            try:
                gate_id = ProductionGateId(gate_value["gate_id"])
                status = ReadinessStatus(gate_value["status"])
            except (TypeError, ValueError) as exc:
                raise ProductionAdmissionError("readiness gate value differs") from exc
            evidence_digest = gate_value["evidence_digest"]
            if evidence_digest is not None and not isinstance(evidence_digest, str):
                raise ProductionAdmissionError("readiness evidence digest differs")
            gates.append(
                ReadinessGateResult(
                    gate_id,
                    status,
                    tuple(blockers),
                    evidence_digest,
                )
            )
        rebuilt = cls.build(
            freeze=FreezeIdentity(
                _git_sha(value["exact_main_sha"], "exact_main_sha"),
                _git_sha(value["exact_main_tree"], "exact_main_tree"),
            ),
            gates=gates,
            evidence_manifest_digest=_optional_digest(
                value["evidence_manifest_digest"], "evidence_manifest_digest"
            ),
            operational_manifest_digest=_optional_digest(
                value["operational_manifest_digest"],
                "operational_manifest_digest",
            ),
            identity_set_digest=_optional_digest(
                value["identity_set_digest"], "identity_set_digest"
            ),
            relational_schema_version=(
                None
                if value["relational_schema_version"] is None
                else _positive_integer(
                    value["relational_schema_version"],
                    "relational_schema_version",
                )
            ),
            migration_history_digest=_optional_digest(
                value["migration_history_digest"], "migration_history_digest"
            ),
            schema_fingerprint=_optional_digest(
                value["schema_fingerprint"], "schema_fingerprint"
            ),
            projection_generation_digest=_optional_digest(
                value["projection_generation_digest"],
                "projection_generation_digest",
            ),
            contiguous_projection_watermark=(
                None
                if value["contiguous_projection_watermark"] is None
                else _positive_integer(
                    value["contiguous_projection_watermark"],
                    "contiguous_projection_watermark",
                )
            ),
            handoff_max_attempts=(
                None
                if value["handoff_max_attempts"] is None
                else _positive_integer(
                    value["handoff_max_attempts"], "handoff_max_attempts"
                )
            ),
        )
        if rebuilt.canonical_bytes != raw:
            raise ProductionAdmissionError("readiness report semantics differ")
        return rebuilt


class ProductionAdmissionVerdict(StrEnum):
    PRODUCTION_OPERATIONAL_ADMITTED = "PRODUCTION_OPERATIONAL_ADMITTED"


def _bound_artifact(
    manifest: ProductionEvidenceManifest, role: BoundArtifactRole
) -> BoundArtifact:
    matches = tuple(item for item in manifest.bound_artifacts if item.role is role)
    if len(matches) != 1:
        raise ProductionAdmissionError(f"bound artifact {role.value} is not exact")
    return matches[0]


@dataclass(frozen=True, slots=True)
class OwnerAdmissionInstruction:
    instruction_id: str
    authority_issue_number: int
    authority_issue_url: str
    owner_identity: str
    issued_at: str
    exact_main_sha: str
    exact_main_tree: str
    evidence_manifest_digest: str
    readiness_report_digest: str
    operational_manifest_digest: str
    identity_set_digest: str
    shadow_closeout_digest: str
    canary_closeout_digest: str
    production_signing_key_id: str
    owner_signing_key_id: str
    owner_signing_key_class: KeyClass
    seal: str
    canonical_bytes: bytes
    digest: str
    admission_scope: str = "production"
    maximum_admissions: int = 1
    increment11r_authorised: bool = False
    production_activation_authorised: bool = False

    @classmethod
    def build(
        cls,
        *,
        authority_issue_number: int,
        owner_identity: str,
        issued_at: str,
        report: ProductionReadinessReport,
        evidence_manifest: ProductionEvidenceManifest,
        production_signing_key_id: str,
        owner_signing_key: AuthenticationKey,
    ) -> OwnerAdmissionInstruction:
        if type(authority_issue_number) is not int or authority_issue_number <= 0:
            raise ProductionAdmissionError("authority issue number must be positive")
        if authority_issue_number in _NON_INSTRUCTION_ISSUES:
            raise ProductionAdmissionError(
                "production admission requires a dedicated owner instruction issue"
            )
        if owner_signing_key.key_class is not KeyClass.HUMAN_ACCOUNTABLE_OWNER:
            raise ProductionAdmissionError("owner instruction key class differs")
        if not report.ready_for_admission:
            raise ProductionAdmissionError("owner instruction requires ready evidence")
        if (
            report.evidence_manifest_digest != evidence_manifest.digest
            or report.identity_set_digest != evidence_manifest.identity_set.digest
            or report.operational_manifest_digest
            != evidence_manifest.identity_set.operational_manifest_digest
            or report.freeze != evidence_manifest.identity_set.freeze
        ):
            raise ProductionAdmissionError("owner instruction evidence differs")
        shadow = _bound_artifact(evidence_manifest, BoundArtifactRole.SHADOW_CLOSEOUT)
        canary = _bound_artifact(
            evidence_manifest,
            BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT,
        )
        base = {
            "schema_version": "newsroom.owner-production-admission-instruction.v1",
            "authority_issue_number": authority_issue_number,
            "authority_issue_url": (
                f"https://github.com/fol2/newsroom/issues/{authority_issue_number}"
            ),
            "owner_identity": _token(owner_identity, "owner_identity"),
            "issued_at": _timestamp(issued_at, "issued_at"),
            **report.freeze.canonical_value(),
            "evidence_manifest_digest": evidence_manifest.digest,
            "readiness_report_digest": report.digest,
            "operational_manifest_digest": (
                evidence_manifest.identity_set.operational_manifest_digest
            ),
            "identity_set_digest": evidence_manifest.identity_set.digest,
            "shadow_closeout_digest": shadow.artifact_digest,
            "canary_closeout_digest": canary.artifact_digest,
            "production_signing_key_id": _token(
                production_signing_key_id, "production_signing_key_id"
            ),
            "production_signing_key_class": (
                KeyClass.PRODUCTION_OPERATIONAL_ADMISSION.value
            ),
            "owner_signing_key_id": owner_signing_key.key_id,
            "owner_signing_key_class": owner_signing_key.key_class.value,
            "admission_scope": "production",
            "maximum_admissions": 1,
            "increment11r_authorised": False,
            "production_activation_authorised": False,
        }
        instruction_id = digest_bytes(canonical_json_bytes(base))
        unsigned = {**base, "instruction_id": instruction_id}
        seal = _seal(unsigned, owner_signing_key.secret)
        value = {**unsigned, "seal": seal}
        raw = canonical_json_bytes(value)
        return cls(
            instruction_id,
            authority_issue_number,
            str(base["authority_issue_url"]),
            str(base["owner_identity"]),
            str(base["issued_at"]),
            report.freeze.exact_main_sha,
            report.freeze.exact_main_tree,
            evidence_manifest.digest,
            report.digest,
            evidence_manifest.identity_set.operational_manifest_digest,
            evidence_manifest.identity_set.digest,
            shadow.artifact_digest,
            canary.artifact_digest,
            str(base["production_signing_key_id"]),
            owner_signing_key.key_id,
            owner_signing_key.key_class,
            seal,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> OwnerAdmissionInstruction:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "instruction_id",
            "authority_issue_number",
            "authority_issue_url",
            "owner_identity",
            "issued_at",
            "exact_main_sha",
            "exact_main_tree",
            "evidence_manifest_digest",
            "readiness_report_digest",
            "operational_manifest_digest",
            "identity_set_digest",
            "shadow_closeout_digest",
            "canary_closeout_digest",
            "production_signing_key_id",
            "production_signing_key_class",
            "owner_signing_key_id",
            "owner_signing_key_class",
            "admission_scope",
            "maximum_admissions",
            "increment11r_authorised",
            "production_activation_authorised",
            "seal",
        }
        issue_number = value.get("authority_issue_number")
        if (
            set(value) != required
            or value["schema_version"]
            != "newsroom.owner-production-admission-instruction.v1"
            or type(issue_number) is not int
            or issue_number <= 0
            or issue_number in _NON_INSTRUCTION_ISSUES
            or value["authority_issue_url"]
            != f"https://github.com/fol2/newsroom/issues/{issue_number}"
            or value["production_signing_key_class"]
            != KeyClass.PRODUCTION_OPERATIONAL_ADMISSION.value
            or not isinstance(value["owner_signing_key_class"], str)
            or value["admission_scope"] != "production"
            or value["maximum_admissions"] != 1
            or value["increment11r_authorised"] is not False
            or value["production_activation_authorised"] is not False
        ):
            raise ProductionAdmissionError("owner instruction fields differ")
        try:
            owner_key_class = KeyClass(value["owner_signing_key_class"])
        except (TypeError, ValueError) as exc:
            raise ProductionAdmissionError(
                "owner instruction key class differs"
            ) from exc
        base = {
            name: item
            for name, item in value.items()
            if name not in {"instruction_id", "seal"}
        }
        expected_instruction_id = digest_bytes(canonical_json_bytes(base))
        if value["instruction_id"] != expected_instruction_id:
            raise ProductionAdmissionError("owner instruction identity differs")
        seal = value["seal"]
        if not isinstance(seal, str):
            raise ProductionAdmissionError("owner instruction seal differs")
        return cls(
            expected_instruction_id,
            issue_number,
            _token(value["authority_issue_url"], "authority_issue_url"),
            _token(value["owner_identity"], "owner_identity"),
            _timestamp(value["issued_at"], "issued_at"),
            _git_sha(value["exact_main_sha"], "exact_main_sha"),
            _git_sha(value["exact_main_tree"], "exact_main_tree"),
            _digest(value["evidence_manifest_digest"], "evidence_manifest_digest"),
            _digest(value["readiness_report_digest"], "readiness_report_digest"),
            _digest(
                value["operational_manifest_digest"],
                "operational_manifest_digest",
            ),
            _digest(value["identity_set_digest"], "identity_set_digest"),
            _digest(value["shadow_closeout_digest"], "shadow_closeout_digest"),
            _digest(value["canary_closeout_digest"], "canary_closeout_digest"),
            _token(value["production_signing_key_id"], "production_signing_key_id"),
            _token(value["owner_signing_key_id"], "owner_signing_key_id"),
            owner_key_class,
            seal,
            raw,
            digest_bytes(raw),
        )

    def verify(self, trusted_keys: Mapping[str, AuthenticationKey]) -> None:
        reconstructed = OwnerAdmissionInstruction.from_canonical_bytes(
            self.canonical_bytes
        )
        if reconstructed != self:
            raise ProductionAdmissionError("owner instruction is forged")
        key = trusted_keys.get(self.owner_signing_key_id)
        if (
            key is None
            or key.key_id != self.owner_signing_key_id
            or key.key_class is not KeyClass.HUMAN_ACCOUNTABLE_OWNER
            or self.owner_signing_key_class is not KeyClass.HUMAN_ACCOUNTABLE_OWNER
        ):
            raise ProductionAdmissionError("owner instruction key is untrusted")
        _verify_seal(_canonical_document(self.canonical_bytes), secret=key.secret)


def _verify_owner_instruction_binding(
    *,
    instruction: OwnerAdmissionInstruction,
    report: ProductionReadinessReport,
    evidence_manifest: ProductionEvidenceManifest,
    trusted_owner_keys: Mapping[str, AuthenticationKey],
) -> None:
    instruction.verify(trusted_owner_keys)
    shadow = _bound_artifact(evidence_manifest, BoundArtifactRole.SHADOW_CLOSEOUT)
    canary = _bound_artifact(
        evidence_manifest,
        BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT,
    )
    if (
        instruction.exact_main_sha != report.freeze.exact_main_sha
        or instruction.exact_main_tree != report.freeze.exact_main_tree
        or instruction.evidence_manifest_digest != evidence_manifest.digest
        or instruction.readiness_report_digest != report.digest
        or instruction.operational_manifest_digest
        != evidence_manifest.identity_set.operational_manifest_digest
        or instruction.identity_set_digest != evidence_manifest.identity_set.digest
        or instruction.shadow_closeout_digest != shadow.artifact_digest
        or instruction.canary_closeout_digest != canary.artifact_digest
    ):
        raise ProductionAdmissionError("owner instruction binding differs")


def inspect_readiness(
    *,
    freeze: FreezeIdentity,
    evidence_manifest: ProductionEvidenceManifest | None,
    attestations: Sequence[GateAttestation],
    trusted_evidence_keys: Mapping[str, AuthenticationKey],
) -> ProductionReadinessReport:
    """Build a provider-free report; absent evidence remains a visible blocker."""

    if evidence_manifest is None:
        gates = tuple(
            ReadinessGateResult(
                gate_id=gate_id,
                status=ReadinessStatus.BLOCKED,
                blockers=("MISSING_PRODUCTION_EVIDENCE_MANIFEST",),
            )
            for gate_id in PRODUCTION_GATE_IDS
        )
        return ProductionReadinessReport.build(freeze=freeze, gates=gates)

    manifest_reconstructed = ProductionEvidenceManifest.from_canonical_bytes(
        evidence_manifest.canonical_bytes
    )
    manifest_forged = manifest_reconstructed != evidence_manifest
    identity_set = evidence_manifest.identity_set
    identities = {item.identity_class: item for item in identity_set.identities}
    bound = {item.role: item for item in evidence_manifest.bound_artifacts}

    attestation_groups: dict[ProductionGateId, list[GateAttestation]] = {
        gate_id: [] for gate_id in PRODUCTION_GATE_IDS
    }
    for attestation in attestations:
        if not isinstance(attestation, GateAttestation):
            raise ProductionAdmissionError("gate attestation type differs")
        attestation_groups[attestation.gate_id].append(attestation)

    global_manifest_drift = identity_set.freeze != freeze or any(
        (
            item.freeze != freeze
            or item.operational_manifest_digest
            != identity_set.operational_manifest_digest
            or item.identity_set_digest != identity_set.digest
            or item.deployment_bytes_digest != identity_set.deployment_bytes_digest
        )
        for item in evidence_manifest.bound_artifacts
    )

    gate_blockers: dict[ProductionGateId, set[str]] = {
        gate_id: set() for gate_id in PRODUCTION_GATE_IDS
    }
    if manifest_forged:
        for blockers in gate_blockers.values():
            blockers.add("FORGED_PRODUCTION_EVIDENCE_MANIFEST")
    if global_manifest_drift:
        for blockers in gate_blockers.values():
            blockers.add("PRODUCTION_EVIDENCE_IDENTITY_DRIFT")

    for identity_class in IdentityClass:
        gate_id = identity_class.gate_id
        identity = identities.get(identity_class)
        if identity is None:
            gate_blockers[gate_id].add(f"MISSING_IDENTITY:{identity_class.value}")
            continue
        if not identity.production_scope:
            gate_blockers[gate_id].add(
                f"IDENTITY_NOT_PRODUCTION_SCOPE:{identity_class.value}"
            )
        if (
            identity.evaluated_sha != freeze.exact_main_sha
            or identity.evaluated_tree != freeze.exact_main_tree
        ):
            gate_blockers[gate_id].add(
                f"IDENTITY_EVALUATION_DRIFT:{identity_class.value}"
            )
        if (
            identity.operational_manifest_digest
            != identity_set.operational_manifest_digest
        ):
            gate_blockers[gate_id].add(
                f"IDENTITY_MANIFEST_DRIFT:{identity_class.value}"
            )
        if (
            evidence_manifest.gate_artifact_digests.get(gate_id)
            != identity.evaluation_evidence_digest
        ):
            gate_blockers[gate_id].add(
                f"IDENTITY_EVALUATION_EVIDENCE_DRIFT:{identity_class.value}"
            )

    for role, expected_outcome in _BOUND_OUTCOMES.items():
        artifact = bound.get(role)
        affected = {
            BoundArtifactRole.SHADOW_CLOSEOUT: (
                ProductionGateId.LIVE_EVIDENCE_INTAKE_CURRENT,
            ),
            BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT: (
                ProductionGateId.LIVE_EVIDENCE_INTAKE_CURRENT,
                ProductionGateId.CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND,
            ),
            BoundArtifactRole.BACKUP: (
                ProductionGateId.STORAGE_BACKUP_RESTORE_ROLLBACK_CURRENT,
            ),
            BoundArtifactRole.RESTORE: (
                ProductionGateId.STORAGE_BACKUP_RESTORE_ROLLBACK_CURRENT,
                ProductionGateId.CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND,
            ),
            BoundArtifactRole.ROLLBACK: (
                ProductionGateId.STORAGE_BACKUP_RESTORE_ROLLBACK_CURRENT,
                ProductionGateId.CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND,
            ),
        }[role]
        if artifact is None:
            for gate_id in affected:
                gate_blockers[gate_id].add(f"MISSING_BOUND_ARTIFACT:{role.value}")
        elif artifact.outcome != expected_outcome:
            for gate_id in affected:
                gate_blockers[gate_id].add(
                    f"NON_QUALIFYING_BOUND_ARTIFACT:{role.value}"
                )

    canary = bound.get(BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT)
    if canary is not None:
        live_gate = IdentityClass.LIVE_EVIDENCE_INTAKE.gate_id
        live_identity = identities.get(IdentityClass.LIVE_EVIDENCE_INTAKE)
        if live_identity is not None and (
            live_identity.evaluation_evidence_digest != canary.artifact_digest
            or evidence_manifest.gate_artifact_digests.get(live_gate)
            != canary.artifact_digest
        ):
            gate_blockers[live_gate].add("LIVE_CANARY_IDENTITY_DRIFT")

    cross_bound = tuple(
        bound.get(role)
        for role in (
            BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT,
            BoundArtifactRole.RESTORE,
            BoundArtifactRole.ROLLBACK,
        )
    )
    if all(item is not None for item in cross_bound):
        present = tuple(item for item in cross_bound if item is not None)
        if (
            len(
                {
                    (
                        item.identity_set_digest,
                        item.deployment_bytes_digest,
                        item.store_identity_digest,
                        item.stop_conditions_digest,
                        item.reconciliation_procedure_digest,
                        item.freeze,
                    )
                    for item in present
                }
            )
            != 1
        ):
            gate_blockers[ProductionGateId.CANARY_ROLLBACK_RESTORE_IDENTITY_BOUND].add(
                "CANARY_ROLLBACK_RESTORE_IDENTITY_DRIFT"
            )

    if evidence_manifest.fixture_admission_inherited:
        gate_blockers[ProductionGateId.HANDOFF_NON_EFFECT_IDENTITIES_CURRENT].add(
            "FIXTURE_OPERATIONAL_ADMISSION_INHERITED"
        )

    publication_spec_set_digest = digest_bytes(
        canonical_json_bytes(dict(evidence_manifest.accepted_publication_spec_digests))
    )
    if (
        evidence_manifest.gate_artifact_digests.get(
            ProductionGateId.PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED
        )
        != publication_spec_set_digest
    ):
        gate_blockers[
            ProductionGateId.PUBLICATION_LIFECYCLE_SPECIFICATIONS_ACCEPTED
        ].add("PUBLICATION_SPEC_EVIDENCE_DRIFT")

    if (
        evidence_manifest.readiness_provider_calls != 0
        or evidence_manifest.readiness_publication_effects != 0
        or evidence_manifest.readiness_production_mutations != 0
    ):
        gate_blockers[ProductionGateId.READINESS_INSPECTION_NON_EFFECT].add(
            "READINESS_INSPECTION_CREATED_EFFECT"
        )

    evidence_digests: dict[ProductionGateId, str | None] = {}
    for gate_id in PRODUCTION_GATE_IDS:
        expected_artifact = evidence_manifest.gate_artifact_digests.get(gate_id)
        if expected_artifact is None:
            gate_blockers[gate_id].add("MISSING_GATE_EVIDENCE")
        candidates = attestation_groups[gate_id]
        if not candidates:
            gate_blockers[gate_id].add("MISSING_GATE_ATTESTATION")
            evidence_digests[gate_id] = None
            continue
        if len(candidates) != 1:
            gate_blockers[gate_id].add("DUPLICATE_GATE_ATTESTATION")
            evidence_digests[gate_id] = None
            continue
        attestation = candidates[0]
        evidence_digests[gate_id] = attestation.digest
        try:
            attestation.verify(trusted_evidence_keys)
        except ProductionAdmissionError:
            gate_blockers[gate_id].add("INVALID_GATE_ATTESTATION_SEAL")
        if (
            attestation.evidence_manifest_digest != evidence_manifest.digest
            or attestation.gate_artifact_digest != expected_artifact
            or attestation.exact_main_sha != freeze.exact_main_sha
            or attestation.exact_main_tree != freeze.exact_main_tree
            or attestation.identity_set_digest != identity_set.digest
        ):
            gate_blockers[gate_id].add("GATE_ATTESTATION_IDENTITY_DRIFT")
        if attestation.status is not ReadinessStatus.PASS:
            gate_blockers[gate_id].update(attestation.blockers)

    gates = tuple(
        ReadinessGateResult(
            gate_id=gate_id,
            status=(
                ReadinessStatus.BLOCKED
                if gate_blockers[gate_id]
                else ReadinessStatus.PASS
            ),
            blockers=tuple(sorted(gate_blockers[gate_id])),
            evidence_digest=evidence_digests[gate_id],
        )
        for gate_id in PRODUCTION_GATE_IDS
    )
    return ProductionReadinessReport.build(
        freeze=freeze,
        gates=gates,
        evidence_manifest_digest=evidence_manifest.digest,
        operational_manifest_digest=identity_set.operational_manifest_digest,
        identity_set_digest=identity_set.digest,
        relational_schema_version=identity_set.relational_schema_version,
        migration_history_digest=identity_set.migration_history_digest,
        schema_fingerprint=identity_set.schema_fingerprint,
        projection_generation_digest=identity_set.projection_generation_digest,
        contiguous_projection_watermark=(identity_set.contiguous_projection_watermark),
        handoff_max_attempts=identity_set.handoff_max_attempts,
    )


def _canonical_digest_mapping(
    value: object, field: str, *, expected_keys: set[str]
) -> Mapping[str, str]:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ProductionAdmissionError(f"{field} inventory differs")
    return MappingProxyType(
        {name: _digest(value[name], f"{field}.{name}") for name in sorted(value)}
    )


@dataclass(frozen=True, slots=True)
class ProductionOperationalAdmission:
    verdict: ProductionAdmissionVerdict
    exact_main_sha: str
    exact_main_tree: str
    operational_manifest_digest: str
    identity_set_digest: str
    deployment_bytes_digest: str
    evidence_manifest_digest: str
    readiness_report_digest: str
    identity_digests: Mapping[str, str]
    identity_evaluation_evidence_digests: Mapping[str, str]
    gate_attestation_digests: Mapping[str, str]
    bound_evidence_digests: Mapping[str, str]
    accepted_publication_spec_digests: Mapping[str, str]
    fixture_admission_digest: str
    owner_instruction_id: str
    owner_instruction_digest: str
    authority_issue_number: int
    authority_issue_url: str
    issuer_identity: str
    issued_at: str
    signing_key_id: str
    signing_key_class: KeyClass
    seal: str
    canonical_bytes: bytes
    digest: str
    admission_scope: str = "production"
    increment11r_authorised: bool = False
    production_activation_authorised: bool = False
    publication_authorised: bool = False
    public_dispatch_authorised: bool = False
    production_mutation_authorised: bool = False

    @classmethod
    def from_canonical_bytes(
        cls,
        raw: bytes,
        *,
        report: ProductionReadinessReport,
        evidence_manifest: ProductionEvidenceManifest,
        owner_instruction: OwnerAdmissionInstruction,
        trusted_owner_keys: Mapping[str, AuthenticationKey],
        trusted_production_keys: Mapping[str, AuthenticationKey],
    ) -> ProductionOperationalAdmission:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "verdict",
            "admission_scope",
            "exact_main_sha",
            "exact_main_tree",
            "operational_manifest_digest",
            "identity_set_digest",
            "deployment_bytes_digest",
            "evidence_manifest_digest",
            "readiness_report_digest",
            "identity_digests",
            "identity_evaluation_evidence_digests",
            "gate_attestation_digests",
            "bound_evidence_digests",
            "accepted_publication_spec_digests",
            "fixture_admission_digest",
            "owner_instruction_id",
            "owner_instruction_digest",
            "authority_issue_number",
            "authority_issue_url",
            "issuer_identity",
            "issued_at",
            "signing_key_id",
            "signing_key_class",
            "increment11r_authorised",
            "production_activation_authorised",
            "publication_authorised",
            "public_dispatch_authorised",
            "production_mutation_authorised",
            "seal",
        }
        if (
            set(value) != required
            or value["schema_version"] != "newsroom.production-operational-admission.v1"
            or value["verdict"]
            != ProductionAdmissionVerdict.PRODUCTION_OPERATIONAL_ADMITTED.value
            or value["admission_scope"] != "production"
            or value["signing_key_class"]
            != KeyClass.PRODUCTION_OPERATIONAL_ADMISSION.value
            or any(
                value[name] is not False
                for name in (
                    "increment11r_authorised",
                    "production_activation_authorised",
                    "publication_authorised",
                    "public_dispatch_authorised",
                    "production_mutation_authorised",
                )
            )
        ):
            raise ProductionAdmissionError("production admission fields differ")
        identity_names = {item.value for item in IdentityClass}
        gate_names = {item.value for item in PRODUCTION_GATE_IDS}
        bound_names = {item.value for item in BoundArtifactRole}
        identity_digests = _canonical_digest_mapping(
            value["identity_digests"],
            "identity_digests",
            expected_keys=identity_names,
        )
        identity_evidence = _canonical_digest_mapping(
            value["identity_evaluation_evidence_digests"],
            "identity_evaluation_evidence_digests",
            expected_keys=identity_names,
        )
        gate_evidence = _canonical_digest_mapping(
            value["gate_attestation_digests"],
            "gate_attestation_digests",
            expected_keys=gate_names,
        )
        bound_evidence = _canonical_digest_mapping(
            value["bound_evidence_digests"],
            "bound_evidence_digests",
            expected_keys=bound_names,
        )
        publication_spec_evidence = _publication_spec_digests(
            value["accepted_publication_spec_digests"]
        )
        issue_number = value["authority_issue_number"]
        seal = value["seal"]
        if (
            type(issue_number) is not int
            or issue_number <= 0
            or value["authority_issue_url"]
            != f"https://github.com/fol2/newsroom/issues/{issue_number}"
            or not isinstance(seal, str)
        ):
            raise ProductionAdmissionError("production admission authority differs")
        record = cls(
            ProductionAdmissionVerdict.PRODUCTION_OPERATIONAL_ADMITTED,
            _git_sha(value["exact_main_sha"], "exact_main_sha"),
            _git_sha(value["exact_main_tree"], "exact_main_tree"),
            _digest(
                value["operational_manifest_digest"],
                "operational_manifest_digest",
            ),
            _digest(value["identity_set_digest"], "identity_set_digest"),
            _digest(value["deployment_bytes_digest"], "deployment_bytes_digest"),
            _digest(value["evidence_manifest_digest"], "evidence_manifest_digest"),
            _digest(value["readiness_report_digest"], "readiness_report_digest"),
            identity_digests,
            identity_evidence,
            gate_evidence,
            bound_evidence,
            publication_spec_evidence,
            _digest(value["fixture_admission_digest"], "fixture_admission_digest"),
            _digest(value["owner_instruction_id"], "owner_instruction_id"),
            _digest(value["owner_instruction_digest"], "owner_instruction_digest"),
            issue_number,
            _token(value["authority_issue_url"], "authority_issue_url"),
            _token(value["issuer_identity"], "issuer_identity"),
            _timestamp(value["issued_at"], "issued_at"),
            _token(value["signing_key_id"], "signing_key_id"),
            KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
            seal,
            raw,
            digest_bytes(raw),
        )
        expected_identity_digests = {
            item.identity_class.value: item.identity_digest
            for item in evidence_manifest.identity_set.identities
        }
        expected_identity_evidence = {
            item.identity_class.value: item.evaluation_evidence_digest
            for item in evidence_manifest.identity_set.identities
        }
        expected_gate_evidence = {
            result.gate_id.value: result.evidence_digest for result in report.gates
        }
        expected_bound = {
            item.role.value: item.artifact_digest
            for item in evidence_manifest.bound_artifacts
        }
        if any(item is None for item in expected_gate_evidence.values()):
            raise ProductionAdmissionError("ready report gate evidence differs")
        _verify_owner_instruction_binding(
            instruction=owner_instruction,
            report=report,
            evidence_manifest=evidence_manifest,
            trusted_owner_keys=trusted_owner_keys,
        )
        if (
            not report.ready_for_admission
            or record.exact_main_sha != report.freeze.exact_main_sha
            or record.exact_main_tree != report.freeze.exact_main_tree
            or record.operational_manifest_digest
            != evidence_manifest.identity_set.operational_manifest_digest
            or record.identity_set_digest != evidence_manifest.identity_set.digest
            or record.deployment_bytes_digest
            != evidence_manifest.identity_set.deployment_bytes_digest
            or record.evidence_manifest_digest != evidence_manifest.digest
            or record.readiness_report_digest != report.digest
            or dict(record.identity_digests) != expected_identity_digests
            or dict(record.identity_evaluation_evidence_digests)
            != expected_identity_evidence
            or dict(record.gate_attestation_digests) != expected_gate_evidence
            or dict(record.bound_evidence_digests) != expected_bound
            or dict(record.accepted_publication_spec_digests)
            != dict(evidence_manifest.accepted_publication_spec_digests)
            or record.fixture_admission_digest
            != evidence_manifest.fixture_admission_digest
            or record.owner_instruction_id != owner_instruction.instruction_id
            or record.owner_instruction_digest != owner_instruction.digest
            or record.authority_issue_number != owner_instruction.authority_issue_number
            or record.authority_issue_url != owner_instruction.authority_issue_url
            or record.issuer_identity != owner_instruction.owner_identity
            or record.issued_at != owner_instruction.issued_at
            or record.signing_key_id != owner_instruction.production_signing_key_id
        ):
            raise ProductionAdmissionError("production admission binding differs")
        key = trusted_production_keys.get(record.signing_key_id)
        if (
            key is None
            or key.key_id != record.signing_key_id
            or key.key_class is not KeyClass.PRODUCTION_OPERATIONAL_ADMISSION
        ):
            raise ProductionAdmissionError("production admission key is untrusted")
        _verify_seal(value, secret=key.secret)
        return record


def mint_production_operational_admission(
    *,
    freeze: FreezeIdentity,
    report: ProductionReadinessReport,
    evidence_manifest: ProductionEvidenceManifest,
    attestations: Sequence[GateAttestation],
    trusted_evidence_keys: Mapping[str, AuthenticationKey],
    owner_instruction: OwnerAdmissionInstruction,
    trusted_owner_keys: Mapping[str, AuthenticationKey],
    production_signing_key: AuthenticationKey,
) -> ProductionOperationalAdmission:
    """Mint one deterministic admission only under the exact owner instruction."""

    reconstructed_report = inspect_readiness(
        freeze=freeze,
        evidence_manifest=evidence_manifest,
        attestations=attestations,
        trusted_evidence_keys=trusted_evidence_keys,
    )
    if reconstructed_report != report or not report.ready_for_admission:
        raise ProductionAdmissionError("production readiness report is not current")
    _verify_owner_instruction_binding(
        instruction=owner_instruction,
        report=report,
        evidence_manifest=evidence_manifest,
        trusted_owner_keys=trusted_owner_keys,
    )
    if (
        production_signing_key.key_class
        is not KeyClass.PRODUCTION_OPERATIONAL_ADMISSION
        or production_signing_key.key_id != owner_instruction.production_signing_key_id
    ):
        raise ProductionAdmissionError("production signing key differs")
    lowered_key_id = production_signing_key.key_id.lower()
    if any(marker in lowered_key_id for marker in ("fixture", "synthetic", "9q")):
        raise ProductionAdmissionError("fixture signing key is ineligible")

    identity_digests = {
        item.identity_class.value: item.identity_digest
        for item in evidence_manifest.identity_set.identities
    }
    identity_evidence = {
        item.identity_class.value: item.evaluation_evidence_digest
        for item in evidence_manifest.identity_set.identities
    }
    gate_evidence = {
        result.gate_id.value: result.evidence_digest for result in report.gates
    }
    if any(item is None for item in gate_evidence.values()):
        raise ProductionAdmissionError("ready report gate evidence differs")
    bound_evidence = {
        item.role.value: item.artifact_digest
        for item in evidence_manifest.bound_artifacts
    }
    unsigned = {
        "schema_version": "newsroom.production-operational-admission.v1",
        "verdict": (ProductionAdmissionVerdict.PRODUCTION_OPERATIONAL_ADMITTED.value),
        "admission_scope": "production",
        **freeze.canonical_value(),
        "operational_manifest_digest": (
            evidence_manifest.identity_set.operational_manifest_digest
        ),
        "identity_set_digest": evidence_manifest.identity_set.digest,
        "deployment_bytes_digest": (
            evidence_manifest.identity_set.deployment_bytes_digest
        ),
        "evidence_manifest_digest": evidence_manifest.digest,
        "readiness_report_digest": report.digest,
        "identity_digests": identity_digests,
        "identity_evaluation_evidence_digests": identity_evidence,
        "gate_attestation_digests": gate_evidence,
        "bound_evidence_digests": bound_evidence,
        "accepted_publication_spec_digests": dict(
            evidence_manifest.accepted_publication_spec_digests
        ),
        "fixture_admission_digest": evidence_manifest.fixture_admission_digest,
        "owner_instruction_id": owner_instruction.instruction_id,
        "owner_instruction_digest": owner_instruction.digest,
        "authority_issue_number": owner_instruction.authority_issue_number,
        "authority_issue_url": owner_instruction.authority_issue_url,
        "issuer_identity": owner_instruction.owner_identity,
        "issued_at": owner_instruction.issued_at,
        "signing_key_id": production_signing_key.key_id,
        "signing_key_class": production_signing_key.key_class.value,
        "increment11r_authorised": False,
        "production_activation_authorised": False,
        "publication_authorised": False,
        "public_dispatch_authorised": False,
        "production_mutation_authorised": False,
    }
    seal = _seal(unsigned, production_signing_key.secret)
    raw = canonical_json_bytes({**unsigned, "seal": seal})
    return ProductionOperationalAdmission.from_canonical_bytes(
        raw,
        report=report,
        evidence_manifest=evidence_manifest,
        owner_instruction=owner_instruction,
        trusted_owner_keys=trusted_owner_keys,
        trusted_production_keys={production_signing_key.key_id: production_signing_key},
    )
