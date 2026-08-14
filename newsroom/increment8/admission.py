"""Exact fixture qualification packet and non-activating Operational Admission."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, validate_sha256_digest
from newsroom.increment8.evaluation import ReleaseEvidenceDecision, ReleaseVerdict
from newsroom.increment8.metrics import MeasurementStatus, MetricReport
from newsroom.increment8.observability import HealthPosture, HealthVerdict, ObservabilityRecord, SecurityAdmission
from newsroom.increment8.operations import CapacityEvidence, HandoffAnchorKind, HandoffRegistrationAnchor
from newsroom.increment8.readiness import INCREMENT_8_READINESS_DIGEST
from newsroom.increment8.recovery import BackupManifest, FaultInjectionRun, FaultScenario, ReconciliationRun, RecoveryStatus, RestoreRun


class AdmissionError(ValueError):
    """Qualification evidence is incomplete, stale or outside the frozen boundary."""


class OperationalAdmissionVerdict(StrEnum):
    FIXTURE_OPERATIONAL_ADMITTED = "FIXTURE_OPERATIONAL_ADMITTED"
    NOT_ADMITTED = "NOT_ADMITTED"


class Increment9Eligibility(StrEnum):
    ELIGIBLE_FOR_SEPARATE_PLAN = "ELIGIBLE_FOR_SEPARATE_PLAN"
    BLOCKED = "BLOCKED"


FINAL_SCHEMA_VERSION = 32
FINAL_SCHEMA_FINGERPRINT = "sha256:3439b82ec6d212116e54765d50cace4d7f147b6ecc3e6ff84146b523c6fd5676"
FINAL_MIGRATION_HISTORY_DIGEST = "sha256:5a48fd76cd11f266e19a4b48174d0c009f320a8d00d3eeb281a558fc2d561910"
_REQUIRED_LICENCE_COMPONENTS = ("neo4j-community", "python-runtime", "repository-components")


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AdmissionError(f"{field} must be an integer >= {minimum}")
    return value


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > 256:
        raise AdmissionError(f"{field} must be bounded text")
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-/")
    if any(character not in allowed for character in value):
        raise AdmissionError(f"{field} contains unsupported characters")
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise AdmissionError(f"{field} must be a canonical digest") from exc


def _record(schema: str, payload: Mapping[str, object]) -> tuple[bytes, str]:
    raw = canonical_json_bytes({"schema_version": schema, "payload": dict(payload)})
    return raw, digest_bytes(raw)


def _exact_record(record: object, cls: type, field: str) -> None:
    if not isinstance(record, cls) or cls.from_canonical_bytes(record.canonical_bytes) != record:  # type: ignore[attr-defined]
        raise AdmissionError(f"{field} is forged or non-canonical")


@dataclass(frozen=True, slots=True)
class IntendedHardwareEvidence:
    target_id: str
    cpu_cores: int
    memory_mib: int
    free_disk_mib: int
    capacity_digest: str
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        target_id: str,
        cpu_cores: int,
        memory_mib: int,
        free_disk_mib: int,
        capacity: CapacityEvidence,
        inventory_digest: str,
        measured_at_digest: str,
    ) -> IntendedHardwareEvidence:
        _exact_record(capacity, CapacityEvidence, "capacity evidence")
        checked = (
            _integer(cpu_cores, "cpu_cores"),
            _integer(memory_mib, "memory_mib"),
            _integer(free_disk_mib, "free_disk_mib"),
        )
        if capacity.payload["status"] != "PASS" or checked != (
            int(capacity.payload["cpu_cores"]), int(capacity.payload["memory_mib"]), int(capacity.payload["free_disk_mib"])
        ):
            raise AdmissionError("hardware and capacity evidence differ")
        payload = {
            "target_id": _token(target_id, "target_id"),
            "cpu_cores": checked[0], "memory_mib": checked[1], "free_disk_mib": checked[2],
            "capacity_digest": capacity.digest, "inventory_digest": _digest(inventory_digest, "inventory_digest"),
            "measured_at_digest": _digest(measured_at_digest, "measured_at_digest"),
            "status": "PASS", "fixture_execution_only": True, "production_activation_authorised": False,
        }
        raw, record_digest = _record("newsroom.increment8.intended-hardware-evidence.v1", payload)
        return cls(str(payload["target_id"]), *checked, capacity.digest, raw, record_digest)


@dataclass(frozen=True, slots=True)
class CostLicenceEvidence:
    external_spend_pence: int
    licence_review_digests: Mapping[str, str]
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        external_spend_pence: int,
        internal_fixture_cost_pence: int,
        licence_review_digests: Mapping[str, str],
        terms_review_digest: str,
        pricing_review_digest: str,
        replacement_path_digest: str,
    ) -> CostLicenceEvidence:
        spend = _integer(external_spend_pence, "external_spend_pence")
        internal = _integer(internal_fixture_cost_pence, "internal_fixture_cost_pence")
        if spend != 0 or tuple(sorted(licence_review_digests)) != _REQUIRED_LICENCE_COMPONENTS:
            raise AdmissionError("cost or licence inventory differs")
        reviews = {name: _digest(licence_review_digests[name], name) for name in _REQUIRED_LICENCE_COMPONENTS}
        payload = {
            "external_spend_pence": spend, "internal_fixture_cost_pence": internal,
            "licence_review_digests": reviews, "terms_review_digest": _digest(terms_review_digest, "terms_review_digest"),
            "pricing_review_digest": _digest(pricing_review_digest, "pricing_review_digest"),
            "replacement_path_digest": _digest(replacement_path_digest, "replacement_path_digest"),
            "status": "PASS", "live_credentials": 0, "network_egress_destinations": 0,
            "production_activation_authorised": False,
        }
        raw, record_digest = _record("newsroom.increment8.cost-licence-evidence.v1", payload)
        return cls(spend, MappingProxyType(reviews), raw, record_digest)


@dataclass(frozen=True, slots=True)
class QualificationPacket:
    evidence_digests: Mapping[str, object]
    canonical_bytes: bytes
    digest: str


@dataclass(frozen=True, slots=True)
class OperationalAdmissionDecision:
    verdict: OperationalAdmissionVerdict
    increment9_eligibility: Increment9Eligibility
    canonical_bytes: bytes
    digest: str


def _metric_report_exact(report: MetricReport) -> bool:
    return (
        isinstance(report, MetricReport)
        and report.digest == digest_bytes(report.canonical_bytes)
        and report.overall_status is MeasurementStatus.PASS
        and report.case_count >= 120
        and report.payload["production_activation_authorised"] is False
        and report.payload["live_shadow_execution_authorised"] is False
        and report.canonical_bytes
        == canonical_json_bytes(
            {"schema_version": "newsroom.increment8.metric-report.v1", "payload": dict(report.payload)}
        )
    )


def build_qualification_packet(
    *,
    release_decision: ReleaseEvidenceDecision,
    metric_report: MetricReport,
    capacity: CapacityEvidence,
    health_postures: Sequence[HealthPosture],
    observability: ObservabilityRecord,
    security: SecurityAdmission,
    reconciliation: ReconciliationRun,
    backup: BackupManifest,
    restore: RestoreRun,
    restore_reconciliation: ReconciliationRun,
    fault_runs: Sequence[FaultInjectionRun],
    handoff_anchor: HandoffRegistrationAnchor,
    expected_handoff_anchor_digest: str,
    hardware: IntendedHardwareEvidence,
    cost_licence: CostLicenceEvidence,
    runbook_version_digest: str,
    rollback_evidence_digest: str,
    independent_verification_digest: str,
    p1_finding_count: int,
    material_p2_finding_count: int,
) -> QualificationPacket:
    _exact_record(release_decision, ReleaseEvidenceDecision, "release decision")
    _exact_record(capacity, CapacityEvidence, "capacity evidence")
    _exact_record(reconciliation, ReconciliationRun, "reconciliation")
    _exact_record(backup, BackupManifest, "backup")
    _exact_record(restore, RestoreRun, "restore")
    _exact_record(restore_reconciliation, ReconciliationRun, "restore reconciliation")
    _exact_record(handoff_anchor, HandoffRegistrationAnchor, "Handoff anchor")
    if release_decision.payload["verdict"] != ReleaseVerdict.PASS.value or release_decision.payload["report_digest"] != metric_report.digest:
        raise AdmissionError("release evidence does not bind the passing metric report")
    if not _metric_report_exact(metric_report) or capacity.payload["status"] != "PASS":
        raise AdmissionError("evaluation or capacity evidence did not pass")
    if not health_postures or any(
        not isinstance(item, HealthPosture) or item.digest != digest_bytes(item.canonical_bytes)
        or item.verdict not in {HealthVerdict.HEALTHY_CHANGED, HealthVerdict.HEALTHY_UNCHANGED}
        for item in health_postures
    ):
        raise AdmissionError("health evidence is not complete-success healthy")
    if not isinstance(observability, ObservabilityRecord) or observability.digest != digest_bytes(observability.canonical_bytes):
        raise AdmissionError("observability evidence differs")
    if not isinstance(security, SecurityAdmission) or not security.eligible:
        raise AdmissionError("security admission is blocked")
    if reconciliation.payload["status"] != RecoveryStatus.PASS.value or restore_reconciliation.payload["status"] != RecoveryStatus.PASS.value:
        raise AdmissionError("reconciliation evidence did not pass")
    if restore.payload["status"] != "RECONCILIATION_REQUIRED" or restore.payload["automatic_operation_resumed"] is not False:
        raise AdmissionError("restore boundary differs")
    if backup.payload["integrity_status"] != RecoveryStatus.PASS.value:
        raise AdmissionError("backup integrity evidence did not pass")
    expected_scenarios = tuple(sorted(scenario.value for scenario in FaultScenario))
    observed_scenarios = tuple(sorted(str(item.payload["scenario"]) for item in fault_runs if isinstance(item, FaultInjectionRun)))
    if observed_scenarios != expected_scenarios or any(
        FaultInjectionRun.from_canonical_bytes(item.canonical_bytes) != item or item.payload["status"] != RecoveryStatus.PASS.value
        for item in fault_runs
    ):
        raise AdmissionError("fault-injection inventory differs")
    pinned_anchor = _digest(expected_handoff_anchor_digest, "expected_handoff_anchor_digest")
    if (
        handoff_anchor.digest != pinned_anchor
        or handoff_anchor.payload["anchor_kind"] != HandoffAnchorKind.ORIGINAL_REGISTRATION.value
        or handoff_anchor.payload["operational_eligible"] is not True
    ):
        raise AdmissionError("Handoff registration is not exactly anchored")
    if (
        not isinstance(hardware, IntendedHardwareEvidence)
        or hardware.digest != digest_bytes(hardware.canonical_bytes)
        or not isinstance(cost_licence, CostLicenceEvidence)
        or cost_licence.digest != digest_bytes(cost_licence.canonical_bytes)
    ):
        raise AdmissionError("hardware, cost or licence evidence differs")
    if hardware.capacity_digest != capacity.digest or cost_licence.external_spend_pence != 0:
        raise AdmissionError("hardware/capacity or spend binding differs")
    if _integer(p1_finding_count, "p1_finding_count") or _integer(material_p2_finding_count, "material_p2_finding_count"):
        raise AdmissionError("substantive review contains a blocking finding")
    evidence: dict[str, object] = {
        "readiness_digest": INCREMENT_8_READINESS_DIGEST,
        "release_decision_digest": release_decision.digest, "metric_report_digest": metric_report.digest,
        "capacity_digest": capacity.digest, "health_digests": sorted(item.digest for item in health_postures),
        "observability_digest": observability.digest, "security_digest": security.digest,
        "reconciliation_digest": reconciliation.digest, "backup_digest": backup.digest, "restore_digest": restore.digest,
        "restore_reconciliation_digest": restore_reconciliation.digest,
        "fault_run_digests": sorted(item.digest for item in fault_runs), "handoff_anchor_digest": pinned_anchor,
        "hardware_digest": hardware.digest, "cost_licence_digest": cost_licence.digest,
        "runbook_version_digest": _digest(runbook_version_digest, "runbook_version_digest"),
        "rollback_evidence_digest": _digest(rollback_evidence_digest, "rollback_evidence_digest"),
        "independent_verification_digest": _digest(independent_verification_digest, "independent_verification_digest"),
        "schema_version": FINAL_SCHEMA_VERSION, "schema_fingerprint": FINAL_SCHEMA_FINGERPRINT,
        "migration_history_digest": FINAL_MIGRATION_HISTORY_DIGEST,
        "p1_finding_count": 0, "material_p2_finding_count": 0,
        "qualification_scope": "DETERMINISTIC_FIXTURE_REPLAY_AND_DISPOSABLE_ACTUAL_SERVICE_ONLY",
        "live_shadow_execution_authorised": False, "canary_authorised": False,
        "production_activation_authorised": False,
    }
    raw, record_digest = _record("newsroom.increment8.qualification-packet.v1", evidence)
    return QualificationPacket(MappingProxyType(evidence), raw, record_digest)


def build_operational_admission_decision(
    *,
    packet: QualificationPacket,
    owner_identity_digest: str,
    decision_recorded_at_digest: str,
) -> OperationalAdmissionDecision:
    if not isinstance(packet, QualificationPacket) or packet.digest != digest_bytes(packet.canonical_bytes):
        raise AdmissionError("qualification packet differs")
    payload = {
        "qualification_packet_digest": packet.digest,
        "owner_identity_digest": _digest(owner_identity_digest, "owner_identity_digest"),
        "decision_recorded_at_digest": _digest(decision_recorded_at_digest, "decision_recorded_at_digest"),
        "verdict": OperationalAdmissionVerdict.FIXTURE_OPERATIONAL_ADMITTED.value,
        "increment9_eligibility": Increment9Eligibility.ELIGIBLE_FOR_SEPARATE_PLAN.value,
        "increment9_requires_separate_owner_approved_plan": True,
        "operational_admission_is_activation": False,
        "live_shadow_execution_authorised": False,
        "canary_authorised": False,
        "production_activation_authorised": False,
    }
    raw, record_digest = _record("newsroom.increment8.operational-admission-decision.v1", payload)
    return OperationalAdmissionDecision(
        OperationalAdmissionVerdict.FIXTURE_OPERATIONAL_ADMITTED,
        Increment9Eligibility.ELIGIBLE_FOR_SEPARATE_PLAN,
        raw,
        record_digest,
    )


__all__ = [
    "CostLicenceEvidence", "FINAL_MIGRATION_HISTORY_DIGEST", "FINAL_SCHEMA_FINGERPRINT",
    "FINAL_SCHEMA_VERSION", "Increment9Eligibility", "IntendedHardwareEvidence", "OperationalAdmissionDecision",
    "OperationalAdmissionVerdict", "QualificationPacket", "AdmissionError", "build_operational_admission_decision",
    "build_qualification_packet",
]
