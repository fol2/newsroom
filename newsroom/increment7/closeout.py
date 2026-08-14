"""Closed-world Increment 7 fixture proof and Tier-M evidence inventory.

This module binds already-retained authority records into one deterministic
proof.  It does not execute a provider, schedule work, infer a locality, or
grant any product authority.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes


INCREMENT7_CLOSEOUT_RECEIPT = "newsroom.increment7.closeout-receipt.v1"
MAX_INCREMENT7_CLOSEOUT_BYTES = 1_048_576
INCREMENT7_FINAL_SCHEMA_VERSION = 29
INCREMENT7_FINAL_SCHEMA_FINGERPRINT = (
    "sha256:68194825ecc7c429b283204dbc1332a43481e04ca2681fcbf75886a984ea6f55"
)
INCREMENT7_FINAL_MIGRATION_HISTORY_DIGEST = (
    "sha256:02e531a9279e316e7f131beabfef5b2f5d02f6b825b7312f4c6296028ffee4ff"
)

INCREMENT7_FINAL_NON_EFFECTS = tuple(
    sorted(
        {
            "CREDENTIAL_OR_SPEND",
            "EVIDENCE_ACQUISITION",
            "EXTERNAL_NETWORK_EGRESS",
            "LIVE_MODEL_OR_PROVIDER",
            "NAMED_OR_PERMANENT_LOCALITY_ACTIVATION",
            "PRODUCTION_ACTIVATION",
            "PUBLICATION_OR_PUBLIC_EFFECT",
            "RECURRING_QUERY_OR_CLOCK_EFFECT",
            "SHADOW_OR_CANARY",
        }
    )
)
INCREMENT7_FINAL_REQUIREMENTS = frozenset(
    {
        "AGENDA_LIFECYCLE",
        "AGENDA_NO_CLOCK_EFFECT",
        "AGENDA_SEARCH_AUDIT_WATCH_REENTRY_PATH",
        "BOUNDED_SEARCH_CHAIN",
        "BOUNDED_WATCH_LIFECYCLE",
        "CLOSED_WORLD_EXACT_MAIN_RECEIPT",
        "EXPLICIT_EXPIRY_NO_CLOCK_EFFECT",
        "INTEGRATED_ACTUAL_SERVICE_EVIDENCE",
        "PRIVACY_BUDGET_LIMITS",
        "PROSPECTIVE_ASSESSMENT",
        "REVIEWED_GAP_AUTHORITY",
    }
)


class Increment7CloseoutError(ValueError):
    """Raised when an Increment 7 closed-world proof differs."""


class Increment7ProofStage(StrEnum):
    AGENDA = "AGENDA"
    SEARCH_PURPOSE = "SEARCH_PURPOSE"
    SEARCH_REQUEST = "SEARCH_REQUEST"
    SEARCH_ATTEMPT = "SEARCH_ATTEMPT"
    SEARCH_OUTCOME = "SEARCH_OUTCOME"
    COVERAGE_AUDIT = "COVERAGE_AUDIT"
    REVIEWED_GAP = "REVIEWED_GAP"
    EVENT_SCOPED_LOCAL_WATCH = "EVENT_SCOPED_LOCAL_WATCH"
    WATCH_CLOSURE = "WATCH_CLOSURE"
    GOVERNED_INCREMENT6_REENTRY = "GOVERNED_INCREMENT6_REENTRY"


INCREMENT7_FINAL_STAGE_ORDER = tuple(Increment7ProofStage)


@dataclass(frozen=True, slots=True)
class Increment7ProofRecord:
    stage: Increment7ProofStage
    schema_id: str
    record_id: str
    record_digest: str

    def __post_init__(self) -> None:
        if not self.schema_id.startswith("newsroom.") or len(self.schema_id) > 160:
            raise Increment7CloseoutError("proof schema identity differs")
        if not self.record_id or len(self.record_id) > 256:
            raise Increment7CloseoutError("proof record identity differs")
        _require_digest(self.record_digest, "proof record digest")

    def canonical_value(self) -> dict[str, str]:
        return {
            "record_digest": self.record_digest,
            "record_id": self.record_id,
            "schema_id": self.schema_id,
            "stage": self.stage.value,
        }


@dataclass(frozen=True, slots=True)
class Increment7CloseoutReceipt:
    proof_id: str
    records: tuple[Increment7ProofRecord, ...]
    retained_authority_database_digest: str
    migration_history_digest: str
    schema_fingerprint: str
    inventory_digest: str
    non_effects: tuple[str, ...]
    recorded_at: str

    def __post_init__(self) -> None:
        if not self.proof_id or len(self.proof_id) > 128:
            raise Increment7CloseoutError("proof identity differs")
        if (
            tuple(record.stage for record in self.records)
            != INCREMENT7_FINAL_STAGE_ORDER
        ):
            raise Increment7CloseoutError("proof stage order differs")
        if len({record.record_digest for record in self.records}) != len(self.records):
            raise Increment7CloseoutError("proof records are not distinct")
        _require_digest(
            self.retained_authority_database_digest,
            "retained authority database digest",
        )
        if self.migration_history_digest != INCREMENT7_FINAL_MIGRATION_HISTORY_DIGEST:
            raise Increment7CloseoutError("migration history differs")
        if self.schema_fingerprint != INCREMENT7_FINAL_SCHEMA_FINGERPRINT:
            raise Increment7CloseoutError("schema fingerprint differs")
        if self.inventory_digest != INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST:
            raise Increment7CloseoutError("closeout inventory differs")
        if self.non_effects != INCREMENT7_FINAL_NON_EFFECTS:
            raise Increment7CloseoutError("non-effect inventory differs")
        if not self.recorded_at.endswith("Z") or len(self.recorded_at) != 27:
            raise Increment7CloseoutError("recorded-at precision differs")

    def canonical_value(self) -> dict[str, object]:
        return {
            "inventory_digest": self.inventory_digest,
            "migration_history_digest": self.migration_history_digest,
            "non_effects": list(self.non_effects),
            "proof_id": self.proof_id,
            "recorded_at": self.recorded_at,
            "records": [record.canonical_value() for record in self.records],
            "retained_authority_database_digest": (
                self.retained_authority_database_digest
            ),
            "schema_fingerprint": self.schema_fingerprint,
            "schema_version": INCREMENT7_CLOSEOUT_RECEIPT,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def receipt_identity(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> Increment7CloseoutReceipt:
        if not payload or len(payload) > MAX_INCREMENT7_CLOSEOUT_BYTES:
            raise Increment7CloseoutError("receipt size differs")

        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            value: dict[str, object] = {}
            for key, item in pairs:
                if key in value:
                    raise Increment7CloseoutError("duplicate object name")
                value[key] = item
            return value

        try:
            value = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=unique_object,
                parse_constant=lambda constant: (_ for _ in ()).throw(
                    Increment7CloseoutError(f"non-finite value: {constant}")
                ),
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise Increment7CloseoutError("receipt JSON differs") from exc
        if not isinstance(value, dict):
            raise Increment7CloseoutError("receipt must be an object")
        expected = {
            "inventory_digest",
            "migration_history_digest",
            "non_effects",
            "proof_id",
            "recorded_at",
            "records",
            "retained_authority_database_digest",
            "schema_fingerprint",
            "schema_version",
        }
        if (
            set(value) != expected
            or value.get("schema_version") != INCREMENT7_CLOSEOUT_RECEIPT
        ):
            raise Increment7CloseoutError("receipt fields or schema differ")
        raw_records = value.get("records")
        if not isinstance(raw_records, list):
            raise Increment7CloseoutError("proof records differ")
        records: list[Increment7ProofRecord] = []
        for raw in raw_records:
            if not isinstance(raw, dict) or set(raw) != {
                "record_digest",
                "record_id",
                "schema_id",
                "stage",
            }:
                raise Increment7CloseoutError("proof record fields differ")
            try:
                records.append(
                    Increment7ProofRecord(
                        stage=Increment7ProofStage(raw["stage"]),
                        schema_id=raw["schema_id"],
                        record_id=raw["record_id"],
                        record_digest=raw["record_digest"],
                    )
                )
            except (TypeError, ValueError) as exc:
                raise Increment7CloseoutError("proof record differs") from exc
        try:
            receipt = cls(
                proof_id=value["proof_id"],
                records=tuple(records),
                retained_authority_database_digest=value[
                    "retained_authority_database_digest"
                ],
                migration_history_digest=value["migration_history_digest"],
                schema_fingerprint=value["schema_fingerprint"],
                inventory_digest=value["inventory_digest"],
                non_effects=tuple(value["non_effects"]),
                recorded_at=value["recorded_at"],
            )
        except (TypeError, ValueError) as exc:
            raise Increment7CloseoutError("receipt value differs") from exc
        if receipt.canonical_bytes != payload:
            raise Increment7CloseoutError("receipt is not canonical JSON")
        return receipt


class Increment7CloseoutLane(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    ACTUAL_NEO4J = "ACTUAL_NEO4J"


@dataclass(frozen=True, slots=True)
class Increment7CloseoutCase:
    case_id: str
    lane: Increment7CloseoutLane
    test_id: str
    requirement: str

    def __post_init__(self) -> None:
        if not self.case_id or not self.case_id.isascii():
            raise Increment7CloseoutError("closeout case identity differs")
        if (
            not self.test_id.startswith("newsroom.tests.test_")
            or "::test_" not in self.test_id
            or len(self.test_id) > 512
        ):
            raise Increment7CloseoutError("closeout test identity differs")
        if self.requirement not in INCREMENT7_FINAL_REQUIREMENTS:
            raise Increment7CloseoutError("closeout requirement differs")

    def canonical_value(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "lane": self.lane.value,
            "requirement": self.requirement,
            "test_id": self.test_id,
        }


def _case(
    case_id: str,
    lane: Increment7CloseoutLane,
    module: str,
    test_name: str,
    requirement: str,
) -> Increment7CloseoutCase:
    return Increment7CloseoutCase(
        case_id,
        lane,
        f"newsroom.tests.{module}::{test_name}",
        requirement,
    )


_D = Increment7CloseoutLane.DETERMINISTIC
_S = Increment7CloseoutLane.ACTUAL_NEO4J
INCREMENT7G_FINAL_CLOSEOUT_CASES = tuple(
    sorted(
        (
            _case(
                "A01_AGENDA",
                _D,
                "test_increment7a2_exact_immutable_read_port",
                "test_create_replay_read_port_restart_and_no_effects",
                "AGENDA_LIFECYCLE",
            ),
            _case(
                "A02_MISS",
                _D,
                "test_increment7a2_exact_immutable_read_port",
                "test_explicit_miss_then_late_occurrence_is_retained_and_terminal",
                "AGENDA_NO_CLOCK_EFFECT",
            ),
            _case(
                "B01_SEARCH_CHAIN",
                _D,
                "test_increment7b2_budget_privacy_authority",
                "test_exact_chain_replays_across_restart_without_provider_authority",
                "BOUNDED_SEARCH_CHAIN",
            ),
            _case(
                "B02_SEARCH_LIMITS",
                _D,
                "test_increment7b2_budget_privacy_authority",
                "test_gross_budget_attempt_order_and_result_limits_fail_closed",
                "PRIVACY_BUDGET_LIMITS",
            ),
            _case(
                "C01_ASSESSMENT",
                _D,
                "test_increment7c2_coverage_audit_authority",
                "test_deterministic_assessment_derives_state_and_exact_limitations",
                "PROSPECTIVE_ASSESSMENT",
            ),
            _case(
                "C02_GAP",
                _D,
                "test_increment7c2_coverage_audit_authority",
                "test_authority_persists_exact_replay_restart_and_rejects_tamper",
                "REVIEWED_GAP_AUTHORITY",
            ),
            _case(
                "D01_WATCH",
                _D,
                "test_increment7d2_local_watch_authority",
                "test_checked_lifecycle_replays_restarts_expires_and_governed_reenters",
                "BOUNDED_WATCH_LIFECYCLE",
            ),
            _case(
                "D02_EXPIRY",
                _D,
                "test_increment7d2_local_watch_authority",
                "test_expiry_has_no_clock_effect_and_cas_terminal_boundaries_fail_closed",
                "EXPLICIT_EXPIRY_NO_CLOCK_EFFECT",
            ),
            _case(
                "G01_COMPLETE_PATH",
                _D,
                "test_increment7g_final_closeout",
                "test_complete_fixture_path_replays_from_one_shared_authority_database",
                "AGENDA_SEARCH_AUDIT_WATCH_REENTRY_PATH",
            ),
            _case(
                "G02_INVENTORY",
                _D,
                "test_increment7g_final_closeout",
                "test_increment7_closeout_inventory_and_contract_are_exact",
                "CLOSED_WORLD_EXACT_MAIN_RECEIPT",
            ),
            _case(
                "S01_EXISTING_SERVICE",
                _S,
                "test_increment6g_neo4j_service",
                "test_actual_service_increment6g_identity_and_closeout_inventory",
                "INTEGRATED_ACTUAL_SERVICE_EVIDENCE",
            ),
        ),
        key=lambda item: item.case_id,
    )
)


def _inventory_values() -> list[dict[str, str]]:
    return [case.canonical_value() for case in INCREMENT7G_FINAL_CLOSEOUT_CASES]


INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST = digest_bytes(
    canonical_json_bytes(_inventory_values())
)


def increment7_final_migration_history(
    history: Sequence[tuple[int, str, str]],
) -> tuple[tuple[int, str, str], ...]:
    prefix = tuple(history[:INCREMENT7_FINAL_SCHEMA_VERSION])
    if (
        len(prefix) != INCREMENT7_FINAL_SCHEMA_VERSION
        or tuple(item[0] for item in prefix)
        != tuple(range(1, INCREMENT7_FINAL_SCHEMA_VERSION + 1))
        or digest_bytes(canonical_json_bytes([list(item) for item in prefix]))
        != INCREMENT7_FINAL_MIGRATION_HISTORY_DIGEST
    ):
        raise Increment7CloseoutError("Increment 7 migration history differs")
    return prefix


def build_increment7_closeout_receipt(
    *,
    proof_id: str,
    records: Iterable[Increment7ProofRecord],
    retained_authority_database: bytes,
    recorded_at: str,
) -> Increment7CloseoutReceipt:
    return Increment7CloseoutReceipt(
        proof_id=proof_id,
        records=tuple(records),
        retained_authority_database_digest=digest_bytes(retained_authority_database),
        migration_history_digest=INCREMENT7_FINAL_MIGRATION_HISTORY_DIGEST,
        schema_fingerprint=INCREMENT7_FINAL_SCHEMA_FINGERPRINT,
        inventory_digest=INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST,
        non_effects=INCREMENT7_FINAL_NON_EFFECTS,
        recorded_at=recorded_at,
    )


def validate_increment7_final_closeout_inventory() -> None:
    cases = INCREMENT7G_FINAL_CLOSEOUT_CASES
    if tuple(case.case_id for case in cases) != tuple(
        sorted(case.case_id for case in cases)
    ):
        raise Increment7CloseoutError("closeout inventory order differs")
    if len({case.case_id for case in cases}) != len(cases):
        raise Increment7CloseoutError("duplicate closeout case identity")
    if len({case.test_id for case in cases}) != len(cases):
        raise Increment7CloseoutError("duplicate closeout test identity")
    if {case.lane for case in cases} != set(Increment7CloseoutLane):
        raise Increment7CloseoutError("closeout lanes differ")
    if {case.requirement for case in cases} != INCREMENT7_FINAL_REQUIREMENTS:
        raise Increment7CloseoutError("closeout requirements differ")
    if INCREMENT7_FINAL_CLOSEOUT_INVENTORY_DIGEST != digest_bytes(
        canonical_json_bytes(_inventory_values())
    ):
        raise Increment7CloseoutError("closeout inventory digest differs")


def _require_digest(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise Increment7CloseoutError(f"{label} differs")


validate_increment7_final_closeout_inventory()
