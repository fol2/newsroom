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
    "sha256:79bd07c69a69933d3a8fc1c218d638101d3c10e4a15cb482a8ee724ee973127b"
)
MANDATORY_QUERY_FAMILY_IDS = (
    "EVENT_AND_DEVELOPMENT_PRECISION",
    "SOURCE_REVISION_IMPACT",
    "LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE",
)
ZERO_TOLERANCE_GATE_NAMES = (
    "rebuild_reproducibility_mismatch_count",
    "temporal_correctness_error_count",
)
MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES = 100
MINIMUM_CASES_PER_REQUIRED_CASE_TYPE = 10
MINIMUM_RELEVANT_CASES_PER_REQUIRED_SLICE = 20
MINIMUM_RELEVANT_CASES_PER_FAMILY_REQUIRED_SLICE = 10

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
_EXPOSURE_CASE_COUNTING_RULE = (
    "Each pre-registered qualification case_id counts once in exactly one "
    "mandatory query family; it may satisfy multiple independently labelled "
    "required slices. Duplicate, invalid, withdrawn, calibration or post-freeze "
    "cases do not count."
)
_MINIMUM_CASES_BY_QUERY_FAMILY = {
    "EVENT_AND_DEVELOPMENT_PRECISION": 30,
    "SOURCE_REVISION_IMPACT": 30,
    "LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE": 40,
}
_ACCEPTANCE_CRITERIA_BY_QUERY_FAMILY = {
    "EVENT_AND_DEVELOPMENT_PRECISION": {
        "blocking": True,
        "distractor_false_merge_precision_ppm": 1_000_000,
        "failure_outcome": "FAIL",
        "minimum_precision_ppm": 900_000,
        "minimum_recall_ppm": 800_000,
        "minimum_required_slice_recall_ppm": 800_000,
    },
    "SOURCE_REVISION_IMPACT": {
        "blocking": True,
        "failure_outcome": "FAIL",
        "minimum_precision_ppm": 800_000,
        "minimum_provenance_completeness_ppm": 1_000_000,
        "minimum_recall_ppm": 800_000,
        "minimum_required_slice_recall_ppm": 800_000,
    },
    "LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE": {
        "blocking": True,
        "failure_outcome": "FAIL",
        "minimum_precision_ppm": 800_000,
        "minimum_recall_ppm": 800_000,
        "minimum_required_slice_recall_ppm": 800_000,
        "temporal_correctness_error_count_max": 0,
    },
}


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise Increment5EvaluationPlanError(f"duplicate object name: {name}")
        value[name] = item
    return value


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


def _validate_decision_scope(
    record: dict[str, Any],
    contract_summary: dict[str, Any],
) -> None:
    scope = _require_mapping(record["decision_scope"], "decision_scope")
    if scope != _DECISION_SCOPE:
        raise Increment5EvaluationPlanError(
            "evaluation decision scope differs from reviewed v1"
        )

    target = scope["qualification_target"]
    comparatives = tuple(scope["comparative_ablations"])
    contract_systems = tuple(contract_summary["ablations"])
    if (
        target in comparatives
        or len(set(contract_systems)) != len(contract_systems)
        or set(contract_systems) != {target, *comparatives}
    ):
        raise Increment5EvaluationPlanError(
            "decision target and comparative ablations do not partition the contract"
        )
    if (
        scope["contract_thresholds_apply_to"] != target
        or scope["mandatory_query_family_criteria_apply_to"] != target
        or scope[
            "zero_tolerance_temporal_and_rebuild_gates_apply_to"
        ]
        != target
        or scope["comparative_quality_results_are_decision_bearing"] is not False
        or scope["comparative_quality_results_can_rescue_target"] is not False
        or scope["cross_system_quality_pooling_allowed"] is not False
        or scope["comparative_results_reported_separately"] is not True
        or scope[
            "safety_or_rights_violation_in_any_executed_system_blocks"
        ]
        is not True
        or scope["target_failure_outcome"] != "FAIL"
    ):
        raise Increment5EvaluationPlanError(
            "comparative ablations can alter the reviewed hybrid decision"
        )


def _validate_families(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    families = record["mandatory_query_families"]
    if not isinstance(families, list) or tuple(
        family["family_id"] for family in families
    ) != MANDATORY_QUERY_FAMILY_IDS:
        raise Increment5EvaluationPlanError(
            "mandatory GraphRAG query families differ from reviewed v1"
        )
    family_by_id = {family["family_id"]: family for family in families}
    for family_id, expected_criteria in (
        _ACCEPTANCE_CRITERIA_BY_QUERY_FAMILY.items()
    ):
        family = family_by_id[family_id]
        if set(family) != {
            "acceptance_criteria",
            "family_id",
            "required_case_types",
            "required_metrics",
            "required_slices",
        }:
            raise Increment5EvaluationPlanError(
                f"mandatory query-family fields differ: {family_id}"
            )
        if (
            not family["required_case_types"]
            or not family["required_metrics"]
            or not family["required_slices"]
        ):
            raise Increment5EvaluationPlanError(
                f"mandatory query family is incomplete: {family_id}"
            )
        criteria = family["acceptance_criteria"]
        if not isinstance(criteria, dict) or criteria != expected_criteria:
            raise Increment5EvaluationPlanError(
                f"mandatory query-family pass criteria differ: {family_id}"
            )
        if (
            criteria["blocking"] is not True
            or criteria["failure_outcome"] != "FAIL"
        ):
            raise Increment5EvaluationPlanError(
                f"mandatory query-family failure is not blocking: {family_id}"
            )
    return family_by_id


def _validate_exposure(
    record: dict[str, Any],
    contract_summary: dict[str, Any],
    family_by_id: dict[str, dict[str, Any]],
) -> None:
    exposure = _require_mapping(record["exposure_minima"], "exposure_minima")
    expected_names = {
        "calibration_cases_count_toward_minima",
        "case_counting_rule",
        "cross_family_case_reuse_allowed",
        "insufficient_exposure_outcome",
        "minimum_cases_by_query_family",
        "minimum_cases_per_required_case_type",
        "minimum_relevant_cases_by_required_slice",
        "minimum_relevant_cases_per_family_required_slice",
        "minimum_total_unique_qualification_cases",
    }
    if set(exposure) != expected_names:
        raise Increment5EvaluationPlanError(
            "evaluation exposure fields differ from reviewed v1"
        )
    if (
        exposure["calibration_cases_count_toward_minima"] is not False
        or exposure["cross_family_case_reuse_allowed"] is not False
        or exposure["insufficient_exposure_outcome"] != "NOT_EVALUATED"
        or exposure["case_counting_rule"] != _EXPOSURE_CASE_COUNTING_RULE
        or exposure["minimum_total_unique_qualification_cases"]
        != MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES
        or exposure["minimum_cases_per_required_case_type"]
        != MINIMUM_CASES_PER_REQUIRED_CASE_TYPE
        or exposure["minimum_relevant_cases_per_family_required_slice"]
        != MINIMUM_RELEVANT_CASES_PER_FAMILY_REQUIRED_SLICE
    ):
        raise Increment5EvaluationPlanError(
            "evaluation exposure policy differs from reviewed v1"
        )

    family_minima = exposure["minimum_cases_by_query_family"]
    if (
        not isinstance(family_minima, dict)
        or family_minima != _MINIMUM_CASES_BY_QUERY_FAMILY
    ):
        raise Increment5EvaluationPlanError(
            "query-family exposure minima differ from reviewed v1"
        )
    for family_id, minimum in _MINIMUM_CASES_BY_QUERY_FAMILY.items():
        case_types = family_by_id[family_id]["required_case_types"]
        if minimum != len(case_types) * MINIMUM_CASES_PER_REQUIRED_CASE_TYPE:
            raise Increment5EvaluationPlanError(
                f"query-family exposure does not cover each case type: {family_id}"
            )
    if sum(family_minima.values()) != MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES:
        raise Increment5EvaluationPlanError(
            "query-family minima do not equal the frozen unique-case floor"
        )

    expected_slice_minima = {
        slice_id: MINIMUM_RELEVANT_CASES_PER_REQUIRED_SLICE
        for slice_id in contract_summary["required_slices"]
    }
    slice_minima = exposure["minimum_relevant_cases_by_required_slice"]
    if not isinstance(slice_minima, dict) or slice_minima != expected_slice_minima:
        raise Increment5EvaluationPlanError(
            "required-slice exposure minima differ from reviewed v1"
        )
    for family_id, family in family_by_id.items():
        if (
            MINIMUM_RELEVANT_CASES_PER_FAMILY_REQUIRED_SLICE
            > _MINIMUM_CASES_BY_QUERY_FAMILY[family_id]
        ):
            raise Increment5EvaluationPlanError(
                f"family-slice exposure floor exceeds family floor: {family_id}"
            )
        if family["acceptance_criteria"][
            "minimum_required_slice_recall_ppm"
        ] != contract_summary["thresholds"][
            "required_slice_recall_at_12_min_ppm"
        ]:
            raise Increment5EvaluationPlanError(
                f"family slice threshold differs from contract: {family_id}"
            )


def _validate_zero_tolerance_gates(record: dict[str, Any]) -> None:
    gates = _require_mapping(
        record["zero_tolerance_gates"],
        "zero_tolerance_gates",
    )
    if tuple(sorted(gates)) != tuple(sorted(ZERO_TOLERANCE_GATE_NAMES)):
        raise Increment5EvaluationPlanError(
            "zero-tolerance gates differ from reviewed v1"
        )
    for name in ZERO_TOLERANCE_GATE_NAMES:
        gate = gates[name]
        if (
            not isinstance(gate, dict)
            or gate.get("blocking") is not True
            or gate.get("maximum") != 0
            or not gate.get("definition")
        ):
            raise Increment5EvaluationPlanError(
                f"zero-tolerance gate is not blocking at zero: {name}"
            )
    if gates["temporal_correctness_error_count"].get("required_slice") != (
        "TEMPORAL_CUTOFF"
    ):
        raise Increment5EvaluationPlanError(
            "temporal correctness is not bound to TEMPORAL_CUTOFF"
        )
    if gates["rebuild_reproducibility_mismatch_count"].get(
        "required_experiment"
    ) != "RIGHTS_PURGE_AND_REBUILD":
        raise Increment5EvaluationPlanError(
            "rebuild reproducibility is not bound to rebuild qualification"
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
    if not isinstance(record, dict):
        raise Increment5EvaluationPlanError("evaluation plan must be an object")
    if set(record) != {
        "contract_digest",
        "contract_evaluation_summary",
        "decision_scope",
        "exposure_minima",
        "mandatory_query_families",
        "schema_version",
        "zero_tolerance_gates",
    }:
        raise Increment5EvaluationPlanError(
            "evaluation plan top-level fields differ from reviewed v1"
        )

    try:
        contract_summary = _thaw(INCREMENT_5A_CONTRACT.payload["evaluation_plan"])
        if (
            record["schema_version"]
            != "newsroom.increment5.retrieval-evaluation-plan.v1"
            or record["contract_digest"] != INCREMENT_5A_CONTRACT.contract_digest
            or record["contract_evaluation_summary"] != contract_summary
        ):
            raise Increment5EvaluationPlanError(
                "evaluation plan differs from the reviewed contract summary"
            )
        _validate_decision_scope(record, contract_summary)
        family_by_id = _validate_families(record)
        _validate_exposure(record, contract_summary, family_by_id)
        _validate_zero_tolerance_gates(record)
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
