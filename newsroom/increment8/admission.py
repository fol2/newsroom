"""Exact fixture qualification packet and non-activating Operational Admission."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment8.evaluation import ReleaseEvidenceDecision, ReleaseVerdict
from newsroom.increment8.metrics import MeasurementStatus, MetricReport
from newsroom.increment8.observability import (
    DimensionState,
    HealthPosture,
    HealthVerdict,
    ObservabilityRecord,
    ObservationOutcome,
    SecurityAdmission,
)
from newsroom.increment8.operations import (
    CapacityEvidence,
    HandoffAnchorKind,
    HandoffRegistrationAnchor,
    _handoff_anchor,
    build_capacity_evidence,
)
from newsroom.increment8.readiness import (
    INCREMENT_8_READINESS,
    INCREMENT_8_READINESS_DIGEST,
    CorrectiveGate,
    corrective_gate_authorised,
)
from newsroom.increment8.recovery import (
    BackupManifest,
    FaultInjectionRun,
    FaultScenario,
    ReconciliationRun,
    RecoveryStatus,
    RestoreRun,
    build_reconciliation_run,
)


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


def _time(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AdmissionError(f"{field} must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise AdmissionError(f"{field} must be canonical UTC text") from exc
    if parsed.utcoffset() != timedelta(0):
        raise AdmissionError(f"{field} must be UTC")
    return value


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _record(schema: str, payload: Mapping[str, object]) -> tuple[bytes, str]:
    raw = canonical_json_bytes({"schema_version": schema, "payload": dict(payload)})
    return raw, digest_bytes(raw)


def _payload(raw: bytes, schema: str) -> Mapping[str, object]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AdmissionError("evidence bytes are not canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise AdmissionError("evidence bytes are not canonical JSON")
    payload = value.get("payload")
    if set(value) != {"schema_version", "payload"} or value["schema_version"] != schema or not isinstance(payload, dict):
        raise AdmissionError("evidence envelope differs")
    return MappingProxyType(payload)


def _document(raw: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AdmissionError("evidence bytes are not canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise AdmissionError("evidence bytes are not canonical JSON")
    return MappingProxyType(value)


def _digest_inventory(value: object, field: str, *, minimum: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AdmissionError(f"{field} must be a canonical list")
    result = tuple(_digest(item, field) for item in value)
    if len(result) < minimum or result != tuple(sorted(set(result))):
        raise AdmissionError(f"{field} must be sorted, unique and complete")
    return result


def _exact_record(record: object, cls: type, field: str) -> object:
    if not isinstance(record, cls):
        raise AdmissionError(f"{field} is forged or non-canonical")
    try:
        reconstructed = cls.from_canonical_bytes(record.canonical_bytes)  # type: ignore[attr-defined]
    except (TypeError, ValueError) as exc:
        raise AdmissionError(f"{field} is forged or non-canonical") from exc
    if reconstructed != record:
        raise AdmissionError(f"{field} is forged or non-canonical")
    return reconstructed


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
    def from_canonical_bytes(cls, raw: bytes) -> IntendedHardwareEvidence:
        payload = _payload(raw, "newsroom.increment8.intended-hardware-evidence.v1")
        required = {
            "target_id", "cpu_cores", "memory_mib", "free_disk_mib",
            "capacity_digest", "inventory_digest", "measured_at_digest", "status",
            "fixture_execution_only", "production_activation_authorised",
        }
        if set(payload) != required:
            raise AdmissionError("hardware evidence payload differs")
        target = _token(payload["target_id"], "target_id")
        checked = (
            _integer(payload["cpu_cores"], "cpu_cores"),
            _integer(payload["memory_mib"], "memory_mib"),
            _integer(payload["free_disk_mib"], "free_disk_mib"),
        )
        capacity_digest = _digest(payload["capacity_digest"], "capacity_digest")
        _digest(payload["inventory_digest"], "inventory_digest")
        _digest(payload["measured_at_digest"], "measured_at_digest")
        if (
            payload["status"] != "PASS"
            or payload["fixture_execution_only"] is not True
            or payload["production_activation_authorised"] is not False
        ):
            raise AdmissionError("hardware evidence semantics differ")
        return cls(target, *checked, capacity_digest, raw, digest_bytes(raw))

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
    def from_canonical_bytes(cls, raw: bytes) -> CostLicenceEvidence:
        payload = _payload(raw, "newsroom.increment8.cost-licence-evidence.v1")
        required = {
            "external_spend_pence", "internal_fixture_cost_pence",
            "licence_review_digests", "terms_review_digest", "pricing_review_digest",
            "replacement_path_digest", "status", "live_credentials",
            "network_egress_destinations", "production_activation_authorised",
        }
        if set(payload) != required or not isinstance(payload["licence_review_digests"], Mapping):
            raise AdmissionError("cost or licence evidence payload differs")
        rebuilt = cls.build(
            external_spend_pence=_integer(payload["external_spend_pence"], "external_spend_pence"),
            internal_fixture_cost_pence=_integer(payload["internal_fixture_cost_pence"], "internal_fixture_cost_pence"),
            licence_review_digests=payload["licence_review_digests"],  # type: ignore[arg-type]
            terms_review_digest=_digest(payload["terms_review_digest"], "terms_review_digest"),
            pricing_review_digest=_digest(payload["pricing_review_digest"], "pricing_review_digest"),
            replacement_path_digest=_digest(payload["replacement_path_digest"], "replacement_path_digest"),
        )
        if (
            rebuilt.canonical_bytes != raw
            or payload["status"] != "PASS"
            or payload["live_credentials"] != 0
            or payload["network_egress_destinations"] != 0
            or payload["production_activation_authorised"] is not False
        ):
            raise AdmissionError("cost or licence evidence semantics differ")
        return rebuilt

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
    retained_evidence: Mapping[str, object]
    canonical_bytes: bytes
    digest: str

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> QualificationPacket:
        packet_payload = _payload(raw, "newsroom.increment8.qualification-packet.v1")
        if (
            set(packet_payload) != {"evidence_digests", "retained_evidence"}
            or not isinstance(packet_payload["evidence_digests"], Mapping)
            or not isinstance(packet_payload["retained_evidence"], Mapping)
        ):
            raise AdmissionError("qualification packet payload differs")
        evidence = packet_payload["evidence_digests"]
        retained = packet_payload["retained_evidence"]
        required = {
            "readiness_digest", "release_decision_digest", "metric_report_digest",
            "capacity_digest", "health_digests", "observability_digest", "security_digest",
            "reconciliation_digest", "backup_digest", "restore_digest",
            "restore_reconciliation_digest", "fault_run_digests", "handoff_anchor_digest",
            "hardware_digest", "cost_licence_digest", "runbook_version_digest",
            "rollback_evidence_digest", "independent_verification_digest", "schema_version",
            "schema_fingerprint", "migration_history_digest", "p1_finding_count",
            "material_p2_finding_count", "qualification_scope",
            "live_shadow_execution_authorised", "canary_authorised",
            "production_activation_authorised",
        }
        if set(evidence) != required:
            raise AdmissionError("qualification packet evidence inventory differs")
        retained_required = {
            "release_decision", "metric_report", "capacity", "health_postures",
            "observability", "security", "reconciliation", "backup", "restore",
            "restore_reconciliation", "fault_runs", "handoff_anchor", "hardware",
            "cost_licence",
        }
        if set(retained) != retained_required:
            raise AdmissionError("qualification packet retained evidence differs")
        digest_fields = required - {
            "health_digests", "fault_run_digests", "schema_version", "p1_finding_count",
            "material_p2_finding_count", "qualification_scope",
            "live_shadow_execution_authorised", "canary_authorised",
            "production_activation_authorised",
        }
        for field in digest_fields:
            _digest(evidence[field], field)
        health = _digest_inventory(evidence["health_digests"], "health_digests", minimum=1)
        faults = _digest_inventory(
            evidence["fault_run_digests"], "fault_run_digests", minimum=len(FaultScenario)
        )
        if (
            len(faults) != len(FaultScenario)
            or evidence["readiness_digest"] != INCREMENT_8_READINESS_DIGEST
            or evidence["schema_version"] != FINAL_SCHEMA_VERSION
            or evidence["schema_fingerprint"] != FINAL_SCHEMA_FINGERPRINT
            or evidence["migration_history_digest"] != FINAL_MIGRATION_HISTORY_DIGEST
            or _integer(evidence["p1_finding_count"], "p1_finding_count") != 0
            or _integer(
                evidence["material_p2_finding_count"], "material_p2_finding_count"
            )
            != 0
            or evidence["qualification_scope"]
            != "DETERMINISTIC_FIXTURE_REPLAY_AND_DISPOSABLE_ACTUAL_SERVICE_ONLY"
            or evidence["live_shadow_execution_authorised"] is not False
            or evidence["canary_authorised"] is not False
            or evidence["production_activation_authorised"] is not False
        ):
            raise AdmissionError("qualification packet semantics differ")
        try:
            metric = MetricReport.from_canonical_bytes(
                canonical_json_bytes(retained["metric_report"])
            )
            release = ReleaseEvidenceDecision.from_canonical_bytes(
                canonical_json_bytes(retained["release_decision"])
            )
            capacity = CapacityEvidence.from_canonical_bytes(
                canonical_json_bytes(retained["capacity"])
            )
            observability = _observability_reconstructed_from_bytes(
                canonical_json_bytes(retained["observability"])
            )
            security = _security_reconstructed_from_bytes(
                canonical_json_bytes(retained["security"])
            )
            reconciliation = ReconciliationRun.from_canonical_bytes(
                canonical_json_bytes(retained["reconciliation"])
            )
            backup = BackupManifest.from_canonical_bytes(
                canonical_json_bytes(retained["backup"])
            )
            restore = RestoreRun.from_canonical_bytes(
                canonical_json_bytes(retained["restore"])
            )
            restore_reconciliation = ReconciliationRun.from_canonical_bytes(
                canonical_json_bytes(retained["restore_reconciliation"])
            )
            anchor = HandoffRegistrationAnchor.from_canonical_bytes(
                canonical_json_bytes(retained["handoff_anchor"])
            )
            hardware = IntendedHardwareEvidence.from_canonical_bytes(
                canonical_json_bytes(retained["hardware"])
            )
            cost = CostLicenceEvidence.from_canonical_bytes(
                canonical_json_bytes(retained["cost_licence"])
            )
        except (TypeError, ValueError) as exc:
            raise AdmissionError("qualification packet retained evidence is invalid") from exc
        health_docs = retained["health_postures"]
        fault_docs = retained["fault_runs"]
        if not isinstance(health_docs, list) or not isinstance(fault_docs, list):
            raise AdmissionError("qualification packet retained evidence lists differ")
        health_records = tuple(
            _health_reconstructed_from_bytes(canonical_json_bytes(item))
            for item in health_docs
        )
        fault_records = tuple(
            FaultInjectionRun.from_canonical_bytes(canonical_json_bytes(item))
            for item in fault_docs
        )
        release = _release_reconstructed(release, _metric_report_reconstructed(metric))
        capacity = _capacity_reconstructed(capacity)
        observability = _observability_reconstructed(observability)
        security = _security_reconstructed(security)
        reconciliation = _reconciliation_reconstructed(reconciliation, "reconciliation")
        backup = _backup_reconstructed(backup)
        restore = _restore_reconstructed(restore)
        restore_reconciliation = _reconciliation_reconstructed(
            restore_reconciliation, "restore reconciliation"
        )
        anchor = _anchor_reconstructed(anchor)
        expected_scenarios = tuple(sorted(scenario.value for scenario in FaultScenario))
        observed_scenarios = tuple(
            sorted(str(item.payload["scenario"]) for item in fault_records)
        )
        observability_payload = _payload(
            observability.canonical_bytes,
            "newsroom.increment8.observability-record.v1",
        )
        security_payload = _payload(
            security.canonical_bytes,
            "newsroom.increment8.security-admission.v1",
        )
        profile_digests = {
            str(reconciliation.payload["profile_digest"]),
            str(restore_reconciliation.payload["profile_digest"]),
            str(backup.payload["profile_digest"]),
            str(observability_payload["profile_digest"]),
            *(str(item.payload["profile_digest"]) for item in fault_records),
        }
        authority_version_digests = {
            str(reconciliation.payload["authority_version_digest"]),
            str(restore_reconciliation.payload["authority_version_digest"]),
            str(backup.payload["authority_version_digest"]),
        }
        if (
            evidence["release_decision_digest"] != release.digest
            or evidence["metric_report_digest"] != metric.digest
            or evidence["capacity_digest"] != capacity.digest
            or evidence["health_digests"] != sorted(item.digest for item in health_records)
            or evidence["observability_digest"] != observability.digest
            or evidence["security_digest"] != security.digest
            or evidence["reconciliation_digest"] != reconciliation.digest
            or evidence["backup_digest"] != backup.digest
            or evidence["restore_digest"] != restore.digest
            or evidence["restore_reconciliation_digest"] != restore_reconciliation.digest
            or evidence["fault_run_digests"] != sorted(item.digest for item in fault_records)
            or evidence["handoff_anchor_digest"] != anchor.digest
            or evidence["hardware_digest"] != hardware.digest
            or evidence["cost_licence_digest"] != cost.digest
            or restore.payload["backup_id"] != backup.identifier
            or restore.payload["backup_manifest_digest"] != backup.digest
            or restore.payload["restored_logical_digest"]
            != backup.payload["authority_logical_digest"]
            or hardware.capacity_digest != capacity.digest
            or (hardware.cpu_cores, hardware.memory_mib, hardware.free_disk_mib)
            != (
                capacity.payload["cpu_cores"],
                capacity.payload["memory_mib"],
                capacity.payload["free_disk_mib"],
            )
            or not _metric_report_exact(metric)
            or capacity.payload["status"] != "PASS"
            or not health_records
            or len({item.digest for item in health_records}) != len(health_records)
            or any(
                item.verdict
                not in {HealthVerdict.HEALTHY_CHANGED, HealthVerdict.HEALTHY_UNCHANGED}
                for item in health_records
            )
            or not security.eligible
            or reconciliation.payload["status"] != RecoveryStatus.PASS.value
            or restore_reconciliation.payload["status"] != RecoveryStatus.PASS.value
            or backup.payload["integrity_status"] != RecoveryStatus.PASS.value
            or restore.payload["status"] != "RECONCILIATION_REQUIRED"
            or restore.payload["automatic_operation_resumed"] is not False
            or observed_scenarios != expected_scenarios
            or any(
                item.payload["status"] != RecoveryStatus.PASS.value
                for item in fault_records
            )
            or anchor.payload["anchor_kind"]
            != HandoffAnchorKind.ORIGINAL_REGISTRATION.value
            or anchor.payload["operational_eligible"] is not True
            or cost.external_spend_pence != 0
            or len(profile_digests) != 1
            or len(authority_version_digests) != 1
            or observability_payload["runbook_version_digest"]
            != evidence["runbook_version_digest"]
            or security_payload["runbook_version_digest"]
            != evidence["runbook_version_digest"]
        ):
            raise AdmissionError("qualification packet evidence binding differs")
        canonical_evidence = dict(evidence)
        canonical_evidence["health_digests"] = list(health)
        canonical_evidence["fault_run_digests"] = list(faults)
        canonical_retained = dict(retained)
        rebuilt, record_digest = _record(
            "newsroom.increment8.qualification-packet.v1",
            {
                "evidence_digests": canonical_evidence,
                "retained_evidence": canonical_retained,
            },
        )
        if rebuilt != raw:
            raise AdmissionError("qualification packet canonical bytes differ")
        return cls(
            MappingProxyType(canonical_evidence),
            MappingProxyType(canonical_retained),
            raw,
            record_digest,
        )


@dataclass(frozen=True, slots=True)
class OperationalAdmissionDecision:
    verdict: OperationalAdmissionVerdict
    increment9_eligibility: Increment9Eligibility
    canonical_bytes: bytes
    digest: str

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> OperationalAdmissionDecision:
        payload = _payload(raw, "newsroom.increment8.operational-admission-decision.v1")
        required = {
            "qualification_packet_digest", "owner_identity_digest",
            "decision_recorded_at_digest", "verdict", "increment9_eligibility",
            "increment9_requires_separate_owner_approved_plan",
            "operational_admission_is_activation", "live_shadow_execution_authorised",
            "canary_authorised", "production_activation_authorised",
        }
        if set(payload) != required:
            raise AdmissionError("Operational Admission payload differs")
        for field in (
            "qualification_packet_digest", "owner_identity_digest", "decision_recorded_at_digest"
        ):
            _digest(payload[field], field)
        if (
            payload["verdict"] != OperationalAdmissionVerdict.FIXTURE_OPERATIONAL_ADMITTED.value
            or payload["increment9_eligibility"]
            != Increment9Eligibility.ELIGIBLE_FOR_SEPARATE_PLAN.value
            or payload["increment9_requires_separate_owner_approved_plan"] is not True
            or payload["operational_admission_is_activation"] is not False
            or payload["live_shadow_execution_authorised"] is not False
            or payload["canary_authorised"] is not False
            or payload["production_activation_authorised"] is not False
        ):
            raise AdmissionError("Operational Admission semantics differ")
        return cls(
            OperationalAdmissionVerdict.FIXTURE_OPERATIONAL_ADMITTED,
            Increment9Eligibility.ELIGIBLE_FOR_SEPARATE_PLAN,
            raw,
            digest_bytes(raw),
        )


def _metric_report_reconstructed(report: MetricReport) -> MetricReport:
    if not isinstance(report, MetricReport):
        raise AdmissionError("metric report is forged or non-canonical")
    try:
        rebuilt = MetricReport.from_canonical_bytes(report.canonical_bytes)
    except (TypeError, ValueError) as exc:
        raise AdmissionError("metric report is forged or non-canonical") from exc
    if rebuilt != report:
        raise AdmissionError("metric report is forged or non-canonical")
    return rebuilt


def _release_reconstructed(
    decision: ReleaseEvidenceDecision, report: MetricReport
) -> ReleaseEvidenceDecision:
    rebuilt = _exact_record(decision, ReleaseEvidenceDecision, "release decision")
    assert isinstance(rebuilt, ReleaseEvidenceDecision)
    payload = rebuilt.payload
    required = {
        "run_id", "run_digest", "report_digest", "metric_report",
        "evidence_manifest_digest", "verdict", "owner_identity_digest", "decided_at",
        "metrics_passed", "required_slices_passed", "zero_tolerance_failure_count",
        "early_stopped", "production_activation_authorised",
    }
    try:
        report_document = json.loads(report.canonical_bytes.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AdmissionError("metric report bytes differ") from exc
    if (
        set(payload) != required
        or _token(payload["run_id"], "run_id") != report.run_id
        or _digest(payload["run_digest"], "run_digest")
        != report.payload["run_digest"]
        or payload["report_digest"] != report.digest
        or payload["metric_report"] != report_document
        or payload["evidence_manifest_digest"]
        != _digest(payload["evidence_manifest_digest"], "evidence_manifest_digest")
        or payload["evidence_manifest_digest"]
        != report.payload["sampling_manifest_digest"]
        or payload["evidence_manifest_digest"]
        != report.payload["label_manifest_digest"]
        or payload["verdict"] != ReleaseVerdict.PASS.value
        or payload["owner_identity_digest"]
        != _digest(payload["owner_identity_digest"], "owner_identity_digest")
        or payload["decided_at"] != _time(payload["decided_at"], "decided_at")
        or payload["metrics_passed"] is not True
        or payload["required_slices_passed"] is not True
        or _integer(
            payload["zero_tolerance_failure_count"], "zero_tolerance_failure_count"
        )
        != 0
        or payload["early_stopped"] is not False
        or payload["production_activation_authorised"] is not False
    ):
        raise AdmissionError("release decision semantics differ")
    return rebuilt


def _capacity_reconstructed(capacity: CapacityEvidence) -> CapacityEvidence:
    rebuilt = _exact_record(capacity, CapacityEvidence, "capacity evidence")
    assert isinstance(rebuilt, CapacityEvidence)
    payload = rebuilt.payload
    required = {
        "scenario_counts", "cpu_cores", "memory_mib", "free_disk_mib",
        "peak_queue_items", "urgent_capacity_items", "worker_throughput_per_minute",
        "operator_minutes", "queue_capacity_items", "observed_headroom_percent",
        "required_headroom_percent", "status", "live_execution_authorised",
    }
    if set(payload) != required or not isinstance(payload["scenario_counts"], Mapping):
        raise AdmissionError("capacity evidence payload differs")
    try:
        semantic = build_capacity_evidence(
            scenario_counts=payload["scenario_counts"],  # type: ignore[arg-type]
            cpu_cores=payload["cpu_cores"],  # type: ignore[arg-type]
            memory_mib=payload["memory_mib"],  # type: ignore[arg-type]
            free_disk_mib=payload["free_disk_mib"],  # type: ignore[arg-type]
            peak_queue_items=payload["peak_queue_items"],  # type: ignore[arg-type]
            urgent_capacity_items=payload["urgent_capacity_items"],  # type: ignore[arg-type]
            worker_throughput_per_minute=payload["worker_throughput_per_minute"],  # type: ignore[arg-type]
            operator_minutes=payload["operator_minutes"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise AdmissionError("capacity evidence semantics differ") from exc
    if semantic != rebuilt:
        raise AdmissionError("capacity evidence semantics differ")
    return rebuilt


def _health_reconstructed_from_bytes(raw: bytes) -> HealthPosture:
    payload = _payload(raw, "newsroom.increment8.health-posture.v1")
    required = {
        "scope_id", "dimension_states", "observation_outcome",
        "last_complete_success_at", "last_source_change_at", "observed_at",
        "complete_success_age_seconds", "freshness_objective_seconds", "verdict",
        "freshness_uses_last_success",
    }
    if set(payload) != required or not isinstance(payload["dimension_states"], Mapping):
        raise AdmissionError("health evidence payload differs")
    try:
        dimensions = {
            str(name): DimensionState(value)
            for name, value in payload["dimension_states"].items()
        }
        semantic = HealthPosture.build(
            scope_id=payload["scope_id"],  # type: ignore[arg-type]
            dimension_states=dimensions,
            observation_outcome=ObservationOutcome(payload["observation_outcome"]),
            last_complete_success_at=payload["last_complete_success_at"],  # type: ignore[arg-type]
            last_source_change_at=payload["last_source_change_at"],  # type: ignore[arg-type]
            observed_at=payload["observed_at"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise AdmissionError("health evidence semantics differ") from exc
    if semantic.canonical_bytes != raw or semantic.digest != digest_bytes(raw):
        raise AdmissionError("health evidence retained bytes differ")
    return semantic


def _health_reconstructed(posture: HealthPosture) -> HealthPosture:
    if not isinstance(posture, HealthPosture):
        raise AdmissionError("health evidence is forged or non-canonical")
    semantic = _health_reconstructed_from_bytes(posture.canonical_bytes)
    if semantic != posture:
        raise AdmissionError("health evidence is forged or non-canonical")
    return semantic


def _observability_reconstructed_from_bytes(raw: bytes) -> ObservabilityRecord:
    payload = _payload(raw, "newsroom.increment8.observability-record.v1")
    required = {
        "readiness_digest", "source_version_digest", "component_version_digest",
        "profile_digest", "provider_version_digest", "policy_version_digest", "metrics",
        "path_correlation", "prohibited_data_logged", "coverage_blocked",
        "integrity_uncertain", "urgent", "alert_priority", "owner_digest",
        "escalation_digest", "runbook_version_digest",
    }
    if (
        set(payload) != required
        or not isinstance(payload["metrics"], Mapping)
        or not isinstance(payload["path_correlation"], Mapping)
        or payload["readiness_digest"] != INCREMENT_8_READINESS_DIGEST
        or payload["prohibited_data_logged"] is not False
    ):
        raise AdmissionError("observability evidence payload differs")
    try:
        semantic = ObservabilityRecord.build(
            source_version_digest=payload["source_version_digest"],  # type: ignore[arg-type]
            component_version_digest=payload["component_version_digest"],  # type: ignore[arg-type]
            profile_digest=payload["profile_digest"],  # type: ignore[arg-type]
            provider_version_digest=payload["provider_version_digest"],  # type: ignore[arg-type]
            policy_version_digest=payload["policy_version_digest"],  # type: ignore[arg-type]
            metrics=payload["metrics"],  # type: ignore[arg-type]
            path_correlation=payload["path_correlation"],  # type: ignore[arg-type]
            coverage_blocked=payload["coverage_blocked"],  # type: ignore[arg-type]
            integrity_uncertain=payload["integrity_uncertain"],  # type: ignore[arg-type]
            urgent=payload["urgent"],  # type: ignore[arg-type]
            owner_digest=payload["owner_digest"],  # type: ignore[arg-type]
            escalation_digest=payload["escalation_digest"],  # type: ignore[arg-type]
            runbook_version_digest=payload["runbook_version_digest"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise AdmissionError("observability evidence semantics differ") from exc
    if semantic.canonical_bytes != raw or semantic.digest != digest_bytes(raw):
        raise AdmissionError("observability evidence retained bytes differ")
    return semantic


def _observability_reconstructed(record: ObservabilityRecord) -> ObservabilityRecord:
    if not isinstance(record, ObservabilityRecord):
        raise AdmissionError("observability evidence is forged or non-canonical")
    semantic = _observability_reconstructed_from_bytes(record.canonical_bytes)
    if semantic != record:
        raise AdmissionError("observability evidence is forged or non-canonical")
    return semantic


def _security_reconstructed_from_bytes(raw: bytes) -> SecurityAdmission:
    payload = _payload(raw, "newsroom.increment8.security-admission.v1")
    flags = (
        "exact_version_approved", "rights_current", "terms_current", "pricing_current",
        "credential_scope_current", "rollback_tested", "scoped_disable_tested",
        "graph_capability_admitted",
    )
    required = {
        "access_contract_digest", *flags, "blocking_reasons", "runbook_version_digest",
        "canary_supported", "canary_authorised", "production_activation_authorised",
        "live_credentials", "network_egress_destinations", "external_spend_pence",
        "eligible",
    }
    if set(payload) != required or any(not isinstance(payload[name], bool) for name in flags):
        raise AdmissionError("security evidence payload differs")
    reasons = tuple(sorted(name for name in flags if payload[name] is False))
    if (
        _digest(payload["access_contract_digest"], "access_contract_digest")
        != payload["access_contract_digest"]
        or _digest(payload["runbook_version_digest"], "runbook_version_digest")
        != payload["runbook_version_digest"]
        or payload["blocking_reasons"] != list(reasons)
        or payload["eligible"] is not (not reasons)
        or payload["canary_supported"] is not True
        or payload["canary_authorised"] is not False
        or payload["production_activation_authorised"] is not False
        or _integer(payload["live_credentials"], "live_credentials") != 0
        or _integer(
            payload["network_egress_destinations"], "network_egress_destinations"
        )
        != 0
        or _integer(payload["external_spend_pence"], "external_spend_pence") != 0
    ):
        raise AdmissionError("security evidence semantics differ")
    return SecurityAdmission(not reasons, reasons, raw, digest_bytes(raw))


def _security_reconstructed(record: SecurityAdmission) -> SecurityAdmission:
    if not isinstance(record, SecurityAdmission):
        raise AdmissionError("security evidence is forged or non-canonical")
    semantic = _security_reconstructed_from_bytes(record.canonical_bytes)
    if semantic != record:
        raise AdmissionError("security evidence is forged or non-canonical")
    return semantic


def _reconciliation_reconstructed(record: ReconciliationRun, field: str) -> ReconciliationRun:
    rebuilt = _exact_record(record, ReconciliationRun, field)
    assert isinstance(rebuilt, ReconciliationRun)
    payload = rebuilt.payload
    required = {
        "profile_digest", "authority_version_digest", "finding_counts",
        "replay_item_count", "maximum_replay_items", "started_at", "completed_at",
        "status", "automatic_operation_blocked", "model_decision_used",
    }
    if set(payload) != required or not isinstance(payload["finding_counts"], Mapping):
        raise AdmissionError(f"{field} payload differs")
    try:
        semantic = build_reconciliation_run(
            profile_digest=payload["profile_digest"],  # type: ignore[arg-type]
            authority_version_digest=payload["authority_version_digest"],  # type: ignore[arg-type]
            finding_counts=payload["finding_counts"],  # type: ignore[arg-type]
            replay_item_count=payload["replay_item_count"],  # type: ignore[arg-type]
            started_at=payload["started_at"],  # type: ignore[arg-type]
            completed_at=payload["completed_at"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise AdmissionError(f"{field} semantics differ") from exc
    if semantic != rebuilt:
        raise AdmissionError(f"{field} semantics differ")
    return rebuilt


def _backup_reconstructed(record: BackupManifest) -> BackupManifest:
    rebuilt = _exact_record(record, BackupManifest, "backup")
    assert isinstance(rebuilt, BackupManifest)
    payload = rebuilt.payload
    required = {
        "profile_digest", "authority_version_digest", "audit_state_digest",
        "authority_logical_digest", "backup_file_digest", "created_at", "retain_until",
        "rpo_seconds", "included_state", "integrity_status", "live_effect_authorised",
    }
    if set(payload) != required:
        raise AdmissionError("backup payload differs")
    created = _time(payload["created_at"], "created_at")
    retained = _time(payload["retain_until"], "retain_until")
    for field in (
        "profile_digest", "authority_version_digest", "audit_state_digest",
        "authority_logical_digest", "backup_file_digest",
    ):
        _digest(payload[field], field)
    expected_state = ["AUDIT", "AUTHORITY", "BASELINE", "DEDUPE", "PENDING_WORK"]
    retention_days = int(INCREMENT_8_READINESS.operational_profile["recovery"]["backup_retention_days"])  # type: ignore[index]
    if (
        _dt(retained) < _dt(created) + timedelta(days=retention_days)
        or payload["rpo_seconds"]
        != int(INCREMENT_8_READINESS.operational_profile["recovery"]["backup_rpo_seconds"])  # type: ignore[index]
        or payload["included_state"] != expected_state
        or payload["integrity_status"] != RecoveryStatus.PASS.value
        or payload["live_effect_authorised"] is not False
    ):
        raise AdmissionError("backup semantics differ")
    return rebuilt


def _restore_reconstructed(record: RestoreRun) -> RestoreRun:
    rebuilt = _exact_record(record, RestoreRun, "restore")
    assert isinstance(rebuilt, RestoreRun)
    payload = rebuilt.payload
    required = {
        "backup_id", "backup_manifest_digest", "restored_logical_digest",
        "completed_at", "status", "automatic_operation_resumed",
        "baselines_reconciled", "leases_reconciled", "queues_reconciled",
        "handoffs_reconciled", "coverage_reconciled",
    }
    false_fields = (
        "automatic_operation_resumed", "baselines_reconciled", "leases_reconciled",
        "queues_reconciled", "handoffs_reconciled", "coverage_reconciled",
    )
    if (
        set(payload) != required
        or _token(payload["backup_id"], "backup_id") != payload["backup_id"]
        or _digest(payload["backup_manifest_digest"], "backup_manifest_digest")
        != payload["backup_manifest_digest"]
        or _digest(payload["restored_logical_digest"], "restored_logical_digest")
        != payload["restored_logical_digest"]
        or _time(payload["completed_at"], "completed_at") != payload["completed_at"]
        or payload["status"] != "RECONCILIATION_REQUIRED"
        or any(payload[name] is not False for name in false_fields)
    ):
        raise AdmissionError("restore semantics differ")
    return rebuilt


def _anchor_reconstructed(record: HandoffRegistrationAnchor) -> HandoffRegistrationAnchor:
    rebuilt = _exact_record(record, HandoffRegistrationAnchor, "Handoff anchor")
    assert isinstance(rebuilt, HandoffRegistrationAnchor)
    payload = rebuilt.payload
    required = {
        "handoff_id", "candidate_version_id", "governing_manifest_digest", "sink_id",
        "max_attempts", "handoff_identity_digest", "anchor_kind", "recorded_at",
        "operational_eligible", "original_value_claimed",
        "production_activation_authorised",
    }
    if set(payload) != required:
        raise AdmissionError("Handoff anchor payload differs")
    try:
        semantic = _handoff_anchor(
            handoff_id=payload["handoff_id"],  # type: ignore[arg-type]
            candidate_version_id=payload["candidate_version_id"],  # type: ignore[arg-type]
            governing_manifest_digest=payload["governing_manifest_digest"],  # type: ignore[arg-type]
            sink_id=payload["sink_id"],  # type: ignore[arg-type]
            max_attempts=payload["max_attempts"],  # type: ignore[arg-type]
            kind=HandoffAnchorKind(payload["anchor_kind"]),
            recorded_at=payload["recorded_at"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise AdmissionError("Handoff anchor semantics differ") from exc
    if semantic != rebuilt:
        raise AdmissionError("Handoff anchor semantics differ")
    return rebuilt


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
    if not corrective_gate_authorised(
        CorrectiveGate.QUALIFICATION_EVIDENCE_ACCEPTANCE
    ):
        raise AdmissionError(
            "qualification packet construction is blocked by corrective readiness"
        )
    metric_report = _metric_report_reconstructed(metric_report)
    release_decision = _release_reconstructed(release_decision, metric_report)
    capacity = _capacity_reconstructed(capacity)
    health_postures = tuple(_health_reconstructed(item) for item in health_postures)
    observability = _observability_reconstructed(observability)
    security = _security_reconstructed(security)
    reconciliation = _reconciliation_reconstructed(reconciliation, "reconciliation")
    backup = _backup_reconstructed(backup)
    restore = _restore_reconstructed(restore)
    restore_reconciliation = _reconciliation_reconstructed(
        restore_reconciliation, "restore reconciliation"
    )
    handoff_anchor = _anchor_reconstructed(handoff_anchor)
    checked_faults: list[FaultInjectionRun] = []
    for item in fault_runs:
        rebuilt_fault = _exact_record(item, FaultInjectionRun, "fault injection")
        assert isinstance(rebuilt_fault, FaultInjectionRun)
        checked_faults.append(rebuilt_fault)
    fault_runs = tuple(checked_faults)
    if not isinstance(hardware, IntendedHardwareEvidence):
        raise AdmissionError("hardware evidence is forged or non-canonical")
    hardware_rebuilt = IntendedHardwareEvidence.from_canonical_bytes(
        hardware.canonical_bytes
    )
    if hardware_rebuilt != hardware:
        raise AdmissionError("hardware evidence is forged or non-canonical")
    hardware = hardware_rebuilt
    if not isinstance(cost_licence, CostLicenceEvidence):
        raise AdmissionError("cost or licence evidence is forged or non-canonical")
    cost_rebuilt = CostLicenceEvidence.from_canonical_bytes(
        cost_licence.canonical_bytes
    )
    if cost_rebuilt != cost_licence:
        raise AdmissionError("cost or licence evidence is forged or non-canonical")
    cost_licence = cost_rebuilt
    if release_decision.payload["verdict"] != ReleaseVerdict.PASS.value or release_decision.payload["report_digest"] != metric_report.digest:
        raise AdmissionError("release evidence does not bind the passing metric report")
    if not _metric_report_exact(metric_report) or capacity.payload["status"] != "PASS":
        raise AdmissionError("evaluation or capacity evidence did not pass")
    if (
        not health_postures
        or len({item.digest for item in health_postures}) != len(health_postures)
        or any(
            item.verdict
            not in {HealthVerdict.HEALTHY_CHANGED, HealthVerdict.HEALTHY_UNCHANGED}
            for item in health_postures
        )
    ):
        raise AdmissionError("health evidence is not complete-success healthy")
    if not security.eligible:
        raise AdmissionError("security admission is blocked")
    if reconciliation.payload["status"] != RecoveryStatus.PASS.value or restore_reconciliation.payload["status"] != RecoveryStatus.PASS.value:
        raise AdmissionError("reconciliation evidence did not pass")
    if restore.payload["status"] != "RECONCILIATION_REQUIRED" or restore.payload["automatic_operation_resumed"] is not False:
        raise AdmissionError("restore boundary differs")
    if backup.payload["integrity_status"] != RecoveryStatus.PASS.value:
        raise AdmissionError("backup integrity evidence did not pass")
    if (
        restore.payload["backup_id"] != backup.identifier
        or restore.payload["backup_manifest_digest"] != backup.digest
        or restore.payload["restored_logical_digest"]
        != backup.payload["authority_logical_digest"]
    ):
        raise AdmissionError("restore does not bind the exact backup")
    expected_scenarios = tuple(sorted(scenario.value for scenario in FaultScenario))
    observed_scenarios = tuple(sorted(str(item.payload["scenario"]) for item in fault_runs if isinstance(item, FaultInjectionRun)))
    if observed_scenarios != expected_scenarios or any(
        item.payload["status"] != RecoveryStatus.PASS.value for item in fault_runs
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
        hardware.capacity_digest != capacity.digest
        or (hardware.cpu_cores, hardware.memory_mib, hardware.free_disk_mib)
        != (
            capacity.payload["cpu_cores"],
            capacity.payload["memory_mib"],
            capacity.payload["free_disk_mib"],
        )
        or cost_licence.external_spend_pence != 0
    ):
        raise AdmissionError("hardware/capacity or spend binding differs")
    runbook = _digest(runbook_version_digest, "runbook_version_digest")
    profile_digests = {
        str(reconciliation.payload["profile_digest"]),
        str(restore_reconciliation.payload["profile_digest"]),
        str(backup.payload["profile_digest"]),
        str(_payload(
            observability.canonical_bytes,
            "newsroom.increment8.observability-record.v1",
        )["profile_digest"]),
        *(str(item.payload["profile_digest"]) for item in fault_runs),
    }
    authority_version_digests = {
        str(reconciliation.payload["authority_version_digest"]),
        str(restore_reconciliation.payload["authority_version_digest"]),
        str(backup.payload["authority_version_digest"]),
    }
    observability_payload = _payload(
        observability.canonical_bytes,
        "newsroom.increment8.observability-record.v1",
    )
    security_payload = _payload(
        security.canonical_bytes, "newsroom.increment8.security-admission.v1"
    )
    if (
        len(profile_digests) != 1
        or len(authority_version_digests) != 1
        or observability_payload["runbook_version_digest"] != runbook
        or security_payload["runbook_version_digest"] != runbook
    ):
        raise AdmissionError("profile or runbook evidence is contradictory")
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
        "runbook_version_digest": runbook,
        "rollback_evidence_digest": _digest(rollback_evidence_digest, "rollback_evidence_digest"),
        "independent_verification_digest": _digest(independent_verification_digest, "independent_verification_digest"),
        "schema_version": FINAL_SCHEMA_VERSION, "schema_fingerprint": FINAL_SCHEMA_FINGERPRINT,
        "migration_history_digest": FINAL_MIGRATION_HISTORY_DIGEST,
        "p1_finding_count": 0, "material_p2_finding_count": 0,
        "qualification_scope": "DETERMINISTIC_FIXTURE_REPLAY_AND_DISPOSABLE_ACTUAL_SERVICE_ONLY",
        "live_shadow_execution_authorised": False, "canary_authorised": False,
        "production_activation_authorised": False,
    }
    retained_evidence: dict[str, object] = {
        "release_decision": dict(_document(release_decision.canonical_bytes)),
        "metric_report": dict(_document(metric_report.canonical_bytes)),
        "capacity": dict(_document(capacity.canonical_bytes)),
        "health_postures": [
            dict(_document(item.canonical_bytes)) for item in health_postures
        ],
        "observability": dict(_document(observability.canonical_bytes)),
        "security": dict(_document(security.canonical_bytes)),
        "reconciliation": dict(_document(reconciliation.canonical_bytes)),
        "backup": dict(_document(backup.canonical_bytes)),
        "restore": dict(_document(restore.canonical_bytes)),
        "restore_reconciliation": dict(
            _document(restore_reconciliation.canonical_bytes)
        ),
        "fault_runs": [dict(_document(item.canonical_bytes)) for item in fault_runs],
        "handoff_anchor": dict(_document(handoff_anchor.canonical_bytes)),
        "hardware": dict(_document(hardware.canonical_bytes)),
        "cost_licence": dict(_document(cost_licence.canonical_bytes)),
    }
    raw, record_digest = _record(
        "newsroom.increment8.qualification-packet.v1",
        {
            "evidence_digests": evidence,
            "retained_evidence": retained_evidence,
        },
    )
    packet = QualificationPacket(
        MappingProxyType(evidence),
        MappingProxyType(retained_evidence),
        raw,
        record_digest,
    )
    if QualificationPacket.from_canonical_bytes(packet.canonical_bytes) != packet:
        raise AdmissionError("qualification packet reconstruction differs")
    return packet


def build_operational_admission_decision(
    *,
    packet: QualificationPacket,
    owner_identity_digest: str,
    decision_recorded_at_digest: str,
) -> OperationalAdmissionDecision:
    if not corrective_gate_authorised(CorrectiveGate.OPERATIONAL_ADMISSION):
        raise AdmissionError(
            "Operational Admission is blocked by corrective readiness"
        )
    if not isinstance(packet, QualificationPacket):
        raise AdmissionError("qualification packet differs")
    try:
        reconstructed = QualificationPacket.from_canonical_bytes(
            packet.canonical_bytes
        )
    except (TypeError, ValueError) as exc:
        raise AdmissionError("qualification packet differs") from exc
    if reconstructed != packet:
        raise AdmissionError("qualification packet differs")
    packet = reconstructed
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
    decision = OperationalAdmissionDecision(
        OperationalAdmissionVerdict.FIXTURE_OPERATIONAL_ADMITTED,
        Increment9Eligibility.ELIGIBLE_FOR_SEPARATE_PLAN,
        raw,
        record_digest,
    )
    if OperationalAdmissionDecision.from_canonical_bytes(decision.canonical_bytes) != decision:
        raise AdmissionError("Operational Admission decision differs")
    return decision


__all__ = [
    "FINAL_MIGRATION_HISTORY_DIGEST",
    "FINAL_SCHEMA_FINGERPRINT",
    "FINAL_SCHEMA_VERSION",
    "AdmissionError",
    "CostLicenceEvidence",
    "Increment9Eligibility",
    "IntendedHardwareEvidence",
    "OperationalAdmissionDecision",
    "OperationalAdmissionVerdict",
    "QualificationPacket",
    "build_operational_admission_decision",
    "build_qualification_packet",
]
