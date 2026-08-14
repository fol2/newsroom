"""Exact Increment 8 Tier-M closeout inventory and non-effect boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment8.admission import FINAL_MIGRATION_HISTORY_DIGEST, FINAL_SCHEMA_FINGERPRINT, FINAL_SCHEMA_VERSION

INCREMENT8_FINAL_SCHEMA_VERSION = FINAL_SCHEMA_VERSION
INCREMENT8_FINAL_SCHEMA_FINGERPRINT = FINAL_SCHEMA_FINGERPRINT
INCREMENT8_FINAL_MIGRATION_HISTORY_DIGEST = FINAL_MIGRATION_HISTORY_DIGEST


class Increment8CloseoutError(ValueError):
    """Increment 8 closeout inventory differs from the reviewed contract."""


class Increment8CloseoutLane(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    ACTUAL_NEO4J = "ACTUAL_NEO4J"


INCREMENT8_FINAL_NON_EFFECTS = tuple(sorted({
    "EXTERNAL_NETWORK_EGRESS", "EXTERNAL_SPEND", "LIVE_CREDENTIAL", "LIVE_MODEL_OR_PROVIDER",
    "PERMANENT_LOCALITY_ACTIVATION", "PRODUCTION_ACTIVATION", "PUBLICATION_OR_PUBLIC_EFFECT",
    "SHADOW_OR_CANARY",
}))
INCREMENT8_FINAL_REQUIREMENTS = frozenset({
    "ACTUAL_GRAPH_SERVICE", "BACKUP_RESTORE", "EVALUATION_RELEASE", "EXACT_MAIN_RECEIPT",
    "FAULT_PURGE_REPLAY", "HANDOFF_REGISTRATION_ANCHOR", "HARDWARE_COST_LICENCE",
    "HEALTH_SECURITY", "OBSERVABILITY_INCIDENT", "OPERATIONAL_ADMISSION", "OPERATIONS_CAPACITY",
    "PROSPECTIVE_METRICS", "RECOVERY_MIGRATION",
})


@dataclass(frozen=True, slots=True)
class Increment8CloseoutCase:
    case_id: str
    lane: Increment8CloseoutLane
    test_id: str
    requirement: str

    def __post_init__(self) -> None:
        if not self.case_id or not self.case_id.isascii():
            raise Increment8CloseoutError("case identity differs")
        if not self.test_id.startswith("newsroom.tests.test_") or "::test_" not in self.test_id:
            raise Increment8CloseoutError("test identity differs")
        if self.requirement not in INCREMENT8_FINAL_REQUIREMENTS:
            raise Increment8CloseoutError("requirement differs")

    def canonical_value(self) -> dict[str, str]:
        return {"case_id": self.case_id, "lane": self.lane.value, "requirement": self.requirement, "test_id": self.test_id}


def _case(case_id: str, lane: Increment8CloseoutLane, module: str, test: str, requirement: str) -> Increment8CloseoutCase:
    return Increment8CloseoutCase(case_id, lane, f"newsroom.tests.{module}::{test}", requirement)


_D = Increment8CloseoutLane.DETERMINISTIC
_S = Increment8CloseoutLane.ACTUAL_NEO4J
INCREMENT8F_FINAL_CLOSEOUT_CASES = tuple(sorted((
    _case("A01_EVALUATION_RELEASE", _D, "test_increment8a_evaluation_authority", "test_pass_requires_full_exposure_primary_labels_and_second_review_sample", "EVALUATION_RELEASE"),
    _case("B01_METRICS", _D, "test_increment8b_metrics", "test_complete_report_is_canonical_bounded_and_non_activating", "PROSPECTIVE_METRICS"),
    _case("C01_OPERATIONS", _D, "test_increment8c_operations", "test_capacity_evidence_covers_all_scenarios_and_frozen_limits", "OPERATIONS_CAPACITY"),
    _case("C02_HANDOFF", _D, "test_increment8c_operations", "test_self_consistent_anchor_rewrite_fails_against_pinned_registration_digest", "HANDOFF_REGISTRATION_ANCHOR"),
    _case("D01_HEALTH_SECURITY", _D, "test_increment8d_observability", "test_security_admission_is_exact_versioned_and_never_activation", "HEALTH_SECURITY"),
    _case("D02_INCIDENT", _D, "test_increment8d_observability", "test_incident_lifecycle_is_append_only_and_integrity_close_requires_regression_case", "OBSERVABILITY_INCIDENT"),
    _case("E01_MIGRATION", _D, "test_increment8e_recovery", "test_v31_to_v32_requires_exact_backup_and_preserves_prefix", "RECOVERY_MIGRATION"),
    _case("E02_BACKUP_RESTORE", _D, "test_increment8e_recovery", "test_checked_backup_restore_preserves_authority_and_requires_reconciliation", "BACKUP_RESTORE"),
    _case("E03_FAULT_RECOVERY", _D, "test_increment8e_recovery", "test_fault_injection_is_fixture_only_and_verifies_fail_closed_outcomes", "FAULT_PURGE_REPLAY"),
    _case("F01_HARDWARE_COST", _D, "test_increment8f_admission", "test_hardware_cost_and_licence_values_are_exact_and_non_activating", "HARDWARE_COST_LICENCE"),
    _case("F02_ADMISSION", _D, "test_increment8f_admission", "test_complete_packet_binds_every_gate_and_admits_only_fixture_operation", "OPERATIONAL_ADMISSION"),
    _case("G01_INVENTORY", _D, "test_increment8f_closeout_receipt", "test_increment8_closeout_inventory_and_contract_are_exact", "EXACT_MAIN_RECEIPT"),
    _case("S01_EXISTING_SERVICE", _S, "test_increment6g_neo4j_service", "test_actual_service_increment6g_identity_and_closeout_inventory", "ACTUAL_GRAPH_SERVICE"),
), key=lambda item: item.case_id))


def _values() -> list[dict[str, str]]:
    return [case.canonical_value() for case in INCREMENT8F_FINAL_CLOSEOUT_CASES]


INCREMENT8_FINAL_CLOSEOUT_INVENTORY_DIGEST = digest_bytes(canonical_json_bytes(_values()))


def increment8_final_migration_history(
    history: tuple[tuple[int, str, str], ...],
) -> tuple[tuple[int, str, str], ...]:
    prefix = tuple(history[:INCREMENT8_FINAL_SCHEMA_VERSION])
    if (
        len(prefix) != INCREMENT8_FINAL_SCHEMA_VERSION
        or tuple(item[0] for item in prefix) != tuple(range(1, INCREMENT8_FINAL_SCHEMA_VERSION + 1))
        or digest_bytes(canonical_json_bytes([list(item) for item in prefix]))
        != INCREMENT8_FINAL_MIGRATION_HISTORY_DIGEST
    ):
        raise Increment8CloseoutError("migration history differs")
    return prefix


def validate_increment8_closeout_inventory() -> None:
    cases = INCREMENT8F_FINAL_CLOSEOUT_CASES
    if tuple(case.case_id for case in cases) != tuple(sorted(case.case_id for case in cases)):
        raise Increment8CloseoutError("case order differs")
    if len({case.case_id for case in cases}) != len(cases) or len({case.test_id for case in cases}) != len(cases):
        raise Increment8CloseoutError("case inventory is not unique")
    if {case.lane for case in cases} != set(Increment8CloseoutLane):
        raise Increment8CloseoutError("lane inventory differs")
    if {case.requirement for case in cases} != INCREMENT8_FINAL_REQUIREMENTS:
        raise Increment8CloseoutError("requirement inventory differs")
    if INCREMENT8_FINAL_CLOSEOUT_INVENTORY_DIGEST != digest_bytes(canonical_json_bytes(_values())):
        raise Increment8CloseoutError("inventory digest differs")


validate_increment8_closeout_inventory()

__all__ = [
    "FINAL_MIGRATION_HISTORY_DIGEST", "FINAL_SCHEMA_FINGERPRINT", "FINAL_SCHEMA_VERSION",
    "INCREMENT8_FINAL_CLOSEOUT_INVENTORY_DIGEST", "INCREMENT8_FINAL_NON_EFFECTS",
    "INCREMENT8_FINAL_REQUIREMENTS", "INCREMENT8F_FINAL_CLOSEOUT_CASES", "Increment8CloseoutCase",
    "Increment8CloseoutError", "Increment8CloseoutLane", "validate_increment8_closeout_inventory",
    "increment8_final_migration_history",
]
