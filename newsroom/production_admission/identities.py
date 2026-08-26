"""Exact production identities and deployment-bound authority artefacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from ._shared import (
    FreezeIdentity,
    ProductionAdmissionError,
    _boolean,
    _canonical_document,
    _digest,
    _git_sha,
    _positive_integer,
    _token,
)


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


def _publication_spec_digests(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(PUBLICATION_SPEC_PATHS):
        raise ProductionAdmissionError("publication spec inventory differs")
    return MappingProxyType(
        {
            path: _digest(value[path], f"accepted_publication_spec_digests.{path}")
            for path in PUBLICATION_SPEC_PATHS
        }
    )


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
