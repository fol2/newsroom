"""Load the exact reviewed Increment 5 retrieval evaluation plan."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
)

from .contract_types import Increment5ContractError, freeze
from .decision import INCREMENT_5A_CONTRACT


class Increment5EvaluationPlanError(ValueError):
    """The checked evaluation plan is not the reviewed v1 content."""


EVALUATION_PLAN_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5_retrieval_evaluation_plan_v1.json"
)
EVALUATION_PLAN_DIGEST = (
    "sha256:c9d169c46a939573ffc6563704adfae973655f6394293ce591ec689f76a30959"
)
MANDATORY_QUERY_FAMILY_IDS = (
    "EVENT_AND_DEVELOPMENT_PRECISION",
    "SOURCE_REVISION_IMPACT",
    "LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE",
)
TRIAGE_ERROR_CLASS_IDS = (
    "FALSE_MERGE",
    "FRAGMENTATION",
    "SNOWBALL_ABSORPTION",
    "FALSE_OR_MISSED_DEVELOPMENT",
    "DUPLICATE_CANDIDATE_CREATION",
    "UNNECESSARY_CANDIDATE_CREATION",
)
ZERO_TOLERANCE_GATE_NAMES = (
    "rebuild_reproducibility_mismatch_count",
    "temporal_correctness_error_count",
)
MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES = 100
MINIMUM_CASES_PER_REQUIRED_CASE_TYPE = 10
MINIMUM_RELEVANT_CASES_PER_REQUIRED_SLICE = 20
MINIMUM_RELEVANT_CASES_PER_FAMILY_REQUIRED_SLICE = 10
MINIMUM_RELEVANT_CASES_PER_TRIAGE_ERROR_CLASS = 10

_QUALIFICATION_TARGET = "HYBRID"
_COMPARATIVE_ABLATIONS = (
    "ADMITTED_GRAPH_ONLY",
    "EXACT_ONLY",
    "FULL_TEXT_ONLY",
    "VECTOR_ONLY",
)
_DECISION_SCOPE = {
    "comparative_ablations": list(_COMPARATIVE_ABLATIONS),
    "comparative_quality_results_are_decision_bearing": False,
    "comparative_quality_results_can_rescue_target": False,
    "comparative_results_reported_separately": True,
    "contract_thresholds_apply_to": _QUALIFICATION_TARGET,
    "cross_system_quality_pooling_allowed": False,
    "mandatory_query_family_criteria_apply_to": _QUALIFICATION_TARGET,
    "qualification_target": _QUALIFICATION_TARGET,
    "safety_or_rights_violation_in_any_executed_system_blocks": True,
    "target_failure_outcome": "FAIL",
    "zero_tolerance_temporal_and_rebuild_gates_apply_to": _QUALIFICATION_TARGET,
}
_EPOCH_PROTOCOL = {
    "cross_epoch_pooling_allowed": False,
    "epoch_identity_algorithm": "SHA256_CANONICAL_JSON_V1",
    "epoch_record_required_before_run": True,
    "epoch_record_schema_version": (
        "newsroom.increment5.retrieval-evaluation-epoch.v1"
    ),
    "frozen_identity_fields": [
        "contract_digest",
        "evaluation_plan_digest",
        "component_digests",
        "source_inventory_digest",
        "source_provider_versions_digest",
        "adapter_parser_versions_digest",
        "query_set_digest",
        "threshold_set_digest",
        "policy_set_digest",
        "dataset_manifest_digest",
        "label_adjudication_policy_digest",
        "code_tree_sha",
        "generation_id",
    ],
    "material_change_categories": [
        "COMPONENT",
        "SOURCE",
        "QUERY",
        "THRESHOLD",
        "POLICY",
    ],
    "material_change_detection_rule": "ANY_FROZEN_IDENTITY_DIFFERENCE",
    "material_change_starts_new_epoch": True,
    "missing_or_mismatched_epoch_outcome": "NOT_EVALUATED",
    "run_binds_exact_epoch_digest": True,
    "same_epoch_requires_all_frozen_identities_equal": True,
    "superseded_epoch_runs_retained": True,
}
_TRIAGE_PROTOCOL_POLICY = {
    "applies_to": _QUALIFICATION_TARGET,
    "candidate_effect_mode": "READ_ONLY_EXPECTED_CANDIDATE_DISPOSITION",
    "cross_class_rate_pooling_allowed": False,
    "each_class_reported_separately": True,
    "missing_class_outcome": "NOT_EVALUATED",
    "report_counts_denominators_and_rates": True,
}
_SECTION_DIGESTS = {
    "epoch_protocol": (
        "sha256:1fe1e831225ebcc55fb5baa6c3f05f6fc405c25fae2af0dbe4de7c302a68ef53"
    ),
    "mandatory_query_families": (
        "sha256:29cbf3f2c651fa485889d4e457bb99be6633a2d32bcf7f5cac7be624853b5249"
    ),
    "exposure_minima": (
        "sha256:7730701abddaaaa1cdfa8836972f849926d1304c3a188f0d1fbb2fb7a6f2c06b"
    ),
    "zero_tolerance_gates": (
        "sha256:fce9129015299fa6844cc56a63bfc4a9479f7a04b2d9b35a382dce61b8ccb9e2"
    ),
}
_TRIAGE_CLASS_DIGESTS = {
    "FALSE_MERGE": (
        "sha256:0a3c296f7358c73c09402445b93a166ce23acb67b63653bfd36befd2993c600a"
    ),
    "FRAGMENTATION": (
        "sha256:a3a5753db2a4645d30e1c138c1155a5f78668d4d780a18fcd29997bc775df910"
    ),
    "SNOWBALL_ABSORPTION": (
        "sha256:d35abe93fa4c2453015703eee7adf4584db2ffd639a2c72392bbd05d5d648dea"
    ),
    "FALSE_OR_MISSED_DEVELOPMENT": (
        "sha256:a859ce327998c605f71b24eae2735f38b57e8f8544022c4d44bfe47f65a56020"
    ),
    "DUPLICATE_CANDIDATE_CREATION": (
        "sha256:b141e48a51679bfdf6178c67d5abbf640a80c619edf6c3ac27cd4ce556b05112"
    ),
    "UNNECESSARY_CANDIDATE_CREATION": (
        "sha256:d0a374de9b8978b7f4590c2d337b9644f734d49fe72fec8ff7b6fba694948cbf"
    ),
}


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise Increment5EvaluationPlanError(f"duplicate object name: {name}")
        result[name] = value
    return result


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {name: _thaw(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Increment5EvaluationPlanError(f"{field} must be an object")
    return value


def _semantic_digest(value: object) -> str:
    return digest_bytes(canonical_json_bytes(value))


def _validate_decision_scope(record: dict[str, Any], contract: dict[str, Any]) -> None:
    scope = _require_mapping(record["decision_scope"], "decision_scope")
    if scope != _DECISION_SCOPE:
        raise Increment5EvaluationPlanError(
            "evaluation decision scope differs from reviewed v1"
        )
    systems = tuple(contract["ablations"])
    if set(systems) != {
        scope["qualification_target"],
        *scope["comparative_ablations"],
    }:
        raise Increment5EvaluationPlanError(
            "decision target and comparative ablations do not partition the contract"
        )


def _validate_epoch_protocol(record: dict[str, Any]) -> None:
    protocol = _require_mapping(record["epoch_protocol"], "epoch_protocol")
    if protocol != _EPOCH_PROTOCOL:
        raise Increment5EvaluationPlanError(
            "evaluation Epoch protocol differs from reviewed v1"
        )
    required_categories = {"COMPONENT", "SOURCE", "QUERY", "THRESHOLD", "POLICY"}
    if (
        set(protocol["material_change_categories"]) != required_categories
        or protocol["material_change_detection_rule"]
        != "ANY_FROZEN_IDENTITY_DIFFERENCE"
        or protocol["material_change_starts_new_epoch"] is not True
        or protocol["same_epoch_requires_all_frozen_identities_equal"] is not True
        or protocol["run_binds_exact_epoch_digest"] is not True
        or protocol["cross_epoch_pooling_allowed"] is not False
        or protocol["missing_or_mismatched_epoch_outcome"] != "NOT_EVALUATED"
    ):
        raise Increment5EvaluationPlanError(
            "material change can reuse or pool a qualification Epoch"
        )


def _validate_families(record: dict[str, Any]) -> None:
    families = record["mandatory_query_families"]
    if not isinstance(families, list) or tuple(
        family.get("family_id") for family in families if isinstance(family, dict)
    ) != MANDATORY_QUERY_FAMILY_IDS:
        raise Increment5EvaluationPlanError(
            "mandatory GraphRAG query families differ from reviewed v1"
        )
    if _semantic_digest(families) != _SECTION_DIGESTS["mandatory_query_families"]:
        raise Increment5EvaluationPlanError(
            "mandatory query-family pass criteria differ from reviewed v1"
        )


def _validate_triage_protocol(record: dict[str, Any]) -> None:
    protocol = _require_mapping(
        record["triage_error_protocol"], "triage_error_protocol"
    )
    classes = protocol.get("error_classes")
    if not isinstance(classes, list) or tuple(
        item.get("class_id") for item in classes if isinstance(item, dict)
    ) != TRIAGE_ERROR_CLASS_IDS:
        raise Increment5EvaluationPlanError(
            "triage error classes differ from DEVAL-046"
        )
    policy = {name: value for name, value in protocol.items() if name != "error_classes"}
    if policy != _TRIAGE_PROTOCOL_POLICY:
        raise Increment5EvaluationPlanError(
            "triage error measurement policy differs from reviewed v1"
        )
    for item in classes:
        class_id = item["class_id"]
        if _semantic_digest(item) != _TRIAGE_CLASS_DIGESTS[class_id]:
            raise Increment5EvaluationPlanError(
                f"triage error class differs: {class_id}"
            )


def _validate_section_digests(record: dict[str, Any]) -> None:
    for name, expected in _SECTION_DIGESTS.items():
        if _semantic_digest(record[name]) != expected:
            raise Increment5EvaluationPlanError(
                f"{name.replace('_', ' ')} differs from reviewed v1"
            )


def _validate_cross_section_invariants(record: dict[str, Any]) -> None:
    exposure = _require_mapping(record["exposure_minima"], "exposure_minima")
    if (
        exposure["minimum_total_unique_qualification_cases"]
        != MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES
        or exposure["minimum_cases_per_required_case_type"]
        != MINIMUM_CASES_PER_REQUIRED_CASE_TYPE
        or exposure["minimum_relevant_cases_per_family_required_slice"]
        != MINIMUM_RELEVANT_CASES_PER_FAMILY_REQUIRED_SLICE
        or exposure["minimum_relevant_cases_per_triage_error_class"]
        != MINIMUM_RELEVANT_CASES_PER_TRIAGE_ERROR_CLASS
        or set(exposure["minimum_relevant_cases_by_required_slice"].values())
        != {MINIMUM_RELEVANT_CASES_PER_REQUIRED_SLICE}
    ):
        raise Increment5EvaluationPlanError(
            "evaluation exposure policy differs from reviewed v1"
        )
    gates = _require_mapping(record["zero_tolerance_gates"], "zero_tolerance_gates")
    if tuple(sorted(gates)) != tuple(sorted(ZERO_TOLERANCE_GATE_NAMES)):
        raise Increment5EvaluationPlanError(
            "zero-tolerance gates differ from reviewed v1"
        )


def load_increment5_evaluation_plan(path: Path) -> Mapping[str, Any]:
    """Return an immutable view only when bytes equal the reviewed v1 plan."""

    if not isinstance(path, Path):
        raise Increment5EvaluationPlanError(
            "evaluation plan path must be a pathlib.Path"
        )
    try:
        raw = path.read_bytes()
        record = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
        canonical = canonical_json_bytes(record)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
    ) as exc:
        raise Increment5EvaluationPlanError(
            "cannot read canonical Increment 5 evaluation plan"
        ) from exc
    if raw != canonical:
        raise Increment5EvaluationPlanError(
            "evaluation plan must use exact canonical JSON"
        )
    if digest_bytes(raw) != EVALUATION_PLAN_DIGEST:
        raise Increment5EvaluationPlanError(
            "evaluation plan bytes differ from reviewed v1"
        )
    if not isinstance(record, dict) or set(record) != {
        "contract_digest",
        "contract_evaluation_summary",
        "decision_scope",
        "epoch_protocol",
        "exposure_minima",
        "mandatory_query_families",
        "schema_version",
        "triage_error_protocol",
        "zero_tolerance_gates",
    }:
        raise Increment5EvaluationPlanError(
            "evaluation plan top-level fields differ from reviewed v1"
        )

    try:
        contract = _thaw(INCREMENT_5A_CONTRACT.payload["evaluation_plan"])
        if (
            record["schema_version"]
            != "newsroom.increment5.retrieval-evaluation-plan.v1"
            or record["contract_digest"] != INCREMENT_5A_CONTRACT.contract_digest
            or record["contract_evaluation_summary"] != contract
        ):
            raise Increment5EvaluationPlanError(
                "evaluation plan differs from the reviewed contract summary"
            )
        _validate_decision_scope(record, contract)
        _validate_epoch_protocol(record)
        _validate_families(record)
        _validate_triage_protocol(record)
        _validate_section_digests(record)
        _validate_cross_section_invariants(record)
    except Increment5EvaluationPlanError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise Increment5EvaluationPlanError(
            "evaluation plan shape differs from reviewed v1"
        ) from exc

    return freeze(record)


try:
    INCREMENT_5_EVALUATION_PLAN = load_increment5_evaluation_plan(
        EVALUATION_PLAN_PATH
    )
except Increment5ContractError as exc:
    raise Increment5EvaluationPlanError(str(exc)) from exc
