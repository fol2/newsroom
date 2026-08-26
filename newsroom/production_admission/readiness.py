"""Provider-free production readiness evaluation and canonical reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from ._shared import (
    AuthenticationKey,
    FreezeIdentity,
    ProductionAdmissionError,
    _canonical_document,
    _git_sha,
    _optional_digest,
    _positive_integer,
    _token,
)
from .evidence import GateAttestation, ProductionEvidenceManifest
from .identities import (
    _BOUND_OUTCOMES,
    PRODUCTION_GATE_IDS,
    BoundArtifactRole,
    IdentityClass,
    ProductionGateId,
    ReadinessStatus,
)


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


def blocked_readiness_report(
    *, freeze: FreezeIdentity, blocker: str
) -> ProductionReadinessReport:
    checked_blocker = _token(blocker, "readiness blocker")
    return ProductionReadinessReport.build(
        freeze=freeze,
        gates=tuple(
            ReadinessGateResult(
                gate_id=gate_id,
                status=ReadinessStatus.BLOCKED,
                blockers=(checked_blocker,),
            )
            for gate_id in PRODUCTION_GATE_IDS
        ),
    )


def inspect_readiness(
    *,
    freeze: FreezeIdentity,
    evidence_manifest: ProductionEvidenceManifest | None,
    attestations: Sequence[GateAttestation],
    trusted_evidence_keys: Mapping[str, AuthenticationKey],
) -> ProductionReadinessReport:
    """Build a provider-free report; absent evidence remains a visible blocker."""

    if evidence_manifest is None:
        return blocked_readiness_report(
            freeze=freeze,
            blocker="MISSING_PRODUCTION_EVIDENCE_MANIFEST",
        )

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
        if (
            live_identity is not None
            and live_identity.evaluation_evidence_digest != canary.artifact_digest
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
        else:
            gate_blockers[gate_id].update(
                evidence_manifest.gate_evidence[gate_id].blockers
            )
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
