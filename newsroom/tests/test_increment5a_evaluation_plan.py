from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import (
    EVALUATION_PLAN_DIGEST,
    EVALUATION_PLAN_PATH,
    INCREMENT_5A_CONTRACT,
    INCREMENT_5_EVALUATION_PLAN,
    MANDATORY_QUERY_FAMILY_IDS,
    MINIMUM_CASES_PER_REQUIRED_CASE_TYPE,
    MINIMUM_RELEVANT_CASES_PER_REQUIRED_SLICE,
    MINIMUM_RELEVANT_CASES_PER_TRIAGE_ERROR_CLASS,
    MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES,
    TRIAGE_ERROR_CLASS_IDS,
    ZERO_TOLERANCE_GATE_NAMES,
    Increment5EvaluationPlanError,
    load_increment5_evaluation_plan,
)
from newsroom.increment5 import evaluation_plan as evaluation_plan_module


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {name: _plain(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _resigned_plan(tmp_path: Path, mutate: object, name: str) -> Path:
    plan = json.loads(EVALUATION_PLAN_PATH.read_text(encoding="utf-8"))
    mutate(plan)  # type: ignore[operator]
    raw = canonical_json_bytes(plan)
    path = tmp_path / name
    path.write_bytes(raw)
    return path


def test_evaluation_plan_is_canonical_digest_bound_and_contract_bound() -> None:
    raw = EVALUATION_PLAN_PATH.read_bytes()
    value = json.loads(raw.decode("utf-8"))

    assert raw == canonical_json_bytes(value)
    assert digest_bytes(raw) == EVALUATION_PLAN_DIGEST
    assert INCREMENT_5_EVALUATION_PLAN["contract_digest"] == (
        INCREMENT_5A_CONTRACT.contract_digest
    )
    assert _plain(INCREMENT_5_EVALUATION_PLAN["contract_evaluation_summary"]) == (
        _plain(INCREMENT_5A_CONTRACT.payload["evaluation_plan"])
    )


def test_hybrid_is_the_only_decision_bearing_system() -> None:
    scope = INCREMENT_5_EVALUATION_PLAN["decision_scope"]
    assert _plain(scope) == {
        "comparative_ablations": [
            "ADMITTED_GRAPH_ONLY",
            "EXACT_ONLY",
            "FULL_TEXT_ONLY",
            "VECTOR_ONLY",
        ],
        "comparative_quality_results_are_decision_bearing": False,
        "comparative_quality_results_can_rescue_target": False,
        "comparative_results_reported_separately": True,
        "contract_thresholds_apply_to": "HYBRID",
        "cross_system_quality_pooling_allowed": False,
        "mandatory_query_family_criteria_apply_to": "HYBRID",
        "qualification_target": "HYBRID",
        "safety_or_rights_violation_in_any_executed_system_blocks": True,
        "target_failure_outcome": "FAIL",
        "zero_tolerance_temporal_and_rebuild_gates_apply_to": "HYBRID",
    }
    contract_systems = set(
        INCREMENT_5A_CONTRACT.payload["evaluation_plan"]["ablations"]
    )
    assert contract_systems == {
        scope["qualification_target"],
        *scope["comparative_ablations"],
    }


def test_epoch_protocol_forces_material_change_rollover() -> None:
    epoch = INCREMENT_5_EVALUATION_PLAN["epoch_protocol"]

    assert epoch["epoch_record_schema_version"] == (
        "newsroom.increment5.retrieval-evaluation-epoch.v1"
    )
    assert epoch["epoch_identity_algorithm"] == "SHA256_CANONICAL_JSON_V1"
    assert epoch["epoch_record_required_before_run"] is True
    assert epoch["material_change_categories"] == (
        "COMPONENT",
        "SOURCE",
        "QUERY",
        "THRESHOLD",
        "POLICY",
    )
    assert epoch["material_change_detection_rule"] == (
        "ANY_FROZEN_IDENTITY_DIFFERENCE"
    )
    assert epoch["material_change_starts_new_epoch"] is True
    assert epoch["same_epoch_requires_all_frozen_identities_equal"] is True
    assert epoch["run_binds_exact_epoch_digest"] is True
    assert epoch["cross_epoch_pooling_allowed"] is False
    assert epoch["missing_or_mismatched_epoch_outcome"] == "NOT_EVALUATED"
    assert epoch["superseded_epoch_runs_retained"] is True

    assert set(epoch["frozen_identity_fields"]) == {
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
    }


def test_mandatory_query_families_have_independent_blocking_criteria() -> None:
    families = INCREMENT_5_EVALUATION_PLAN["mandatory_query_families"]
    assert tuple(family["family_id"] for family in families) == (
        MANDATORY_QUERY_FAMILY_IDS
    )

    by_id = {family["family_id"]: family for family in families}
    event = by_id["EVENT_AND_DEVELOPMENT_PRECISION"]
    assert set(event["required_case_types"]) == {
        "DEVELOPMENT_OF_EXISTING_EVENT",
        "RELATED_BUT_DISTINCT_EVENT",
        "SAME_EVENT_STATE",
    }
    assert event["acceptance_criteria"]["minimum_precision_ppm"] == 900_000
    assert (
        event["acceptance_criteria"]["distractor_false_merge_precision_ppm"]
        == 1_000_000
    )

    revision = by_id["SOURCE_REVISION_IMPACT"]
    assert set(revision["required_case_types"]) == {
        "CORRECTION_IMPACT",
        "DOWNSTREAM_CANDIDATE_IMPACT",
        "SUPERSESSION_IMPACT",
    }
    assert (
        revision["acceptance_criteria"]["minimum_provenance_completeness_ppm"]
        == 1_000_000
    )

    timeline = by_id["LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE"]
    assert set(timeline["required_case_types"]) == {
        "CORRECTION",
        "ORDERED_DEVELOPMENT",
        "SUPERSESSION",
        "TEMPORAL_CUTOFF",
    }
    assert timeline["acceptance_criteria"][
        "temporal_correctness_error_count_max"
    ] == 0

    assert all(
        family["acceptance_criteria"]["blocking"] is True
        and family["acceptance_criteria"]["failure_outcome"] == "FAIL"
        for family in families
    )


def test_all_deval_046_triage_error_classes_are_preregistered() -> None:
    protocol = INCREMENT_5_EVALUATION_PLAN["triage_error_protocol"]
    classes = protocol["error_classes"]

    assert tuple(item["class_id"] for item in classes) == TRIAGE_ERROR_CLASS_IDS
    assert protocol["applies_to"] == "HYBRID"
    assert protocol["candidate_effect_mode"] == (
        "READ_ONLY_EXPECTED_CANDIDATE_DISPOSITION"
    )
    assert protocol["each_class_reported_separately"] is True
    assert protocol["cross_class_rate_pooling_allowed"] is False
    assert protocol["report_counts_denominators_and_rates"] is True
    assert protocol["missing_class_outcome"] == "NOT_EVALUATED"

    by_id = {item["class_id"]: item for item in classes}
    assert by_id["FALSE_MERGE"]["automatic_blocker"] is True
    assert by_id["FRAGMENTATION"]["error_count_metrics"] == (
        "fragmentation_count",
    )
    assert by_id["SNOWBALL_ABSORPTION"]["error_count_metrics"] == (
        "snowball_absorption_count",
    )
    assert by_id["FALSE_OR_MISSED_DEVELOPMENT"]["error_count_metrics"] == (
        "false_development_count",
        "missed_development_count",
    )
    assert "SINGLE_CANDIDATE_EXPECTED" in by_id[
        "DUPLICATE_CANDIDATE_CREATION"
    ]["eligible_case_labels"]
    assert "NO_CANDIDATE_EXPECTED" in by_id[
        "UNNECESSARY_CANDIDATE_CREATION"
    ]["eligible_case_labels"]
    assert all(item["opportunity_count_metric"] for item in classes)
    assert all(item["rate_metric"].endswith("_ppm") for item in classes)


def test_exposure_minima_are_frozen_before_outcomes() -> None:
    exposure = INCREMENT_5_EVALUATION_PLAN["exposure_minima"]
    assert exposure["minimum_total_unique_qualification_cases"] == (
        MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES
    )
    assert exposure["minimum_cases_per_required_case_type"] == (
        MINIMUM_CASES_PER_REQUIRED_CASE_TYPE
    )
    assert exposure["minimum_cases_by_query_family"] == {
        "EVENT_AND_DEVELOPMENT_PRECISION": 30,
        "SOURCE_REVISION_IMPACT": 30,
        "LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE": 40,
    }
    assert exposure["minimum_relevant_cases_by_required_slice"] == {
        slice_id: MINIMUM_RELEVANT_CASES_PER_REQUIRED_SLICE
        for slice_id in INCREMENT_5A_CONTRACT.payload["evaluation_plan"][
            "required_slices"
        ]
    }
    assert exposure["minimum_relevant_cases_per_family_required_slice"] == 10
    assert exposure["minimum_relevant_cases_per_triage_error_class"] == (
        MINIMUM_RELEVANT_CASES_PER_TRIAGE_ERROR_CLASS
    )
    assert exposure["cross_family_case_reuse_allowed"] is False
    assert exposure["calibration_cases_count_toward_minima"] is False
    assert exposure["insufficient_exposure_outcome"] == "NOT_EVALUATED"
    assert sum(exposure["minimum_cases_by_query_family"].values()) == (
        MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES
    )


def test_temporal_and_rebuild_gates_are_blocking_at_zero() -> None:
    gates = INCREMENT_5_EVALUATION_PLAN["zero_tolerance_gates"]
    assert tuple(sorted(gates)) == tuple(sorted(ZERO_TOLERANCE_GATE_NAMES))

    temporal = gates["temporal_correctness_error_count"]
    assert temporal["blocking"] is True
    assert temporal["maximum"] == 0
    assert temporal["required_slice"] == "TEMPORAL_CUTOFF"

    rebuild = gates["rebuild_reproducibility_mismatch_count"]
    assert rebuild["blocking"] is True
    assert rebuild["maximum"] == 0
    assert rebuild["required_experiment"] == "RIGHTS_PURGE_AND_REBUILD"


def test_evaluation_plan_is_immutable() -> None:
    with pytest.raises(TypeError):
        INCREMENT_5_EVALUATION_PLAN["contract_digest"] = (  # type: ignore[index]
            "sha256:00"
        )
    with pytest.raises(TypeError):
        INCREMENT_5_EVALUATION_PLAN["epoch_protocol"][
            "material_change_starts_new_epoch"
        ] = False  # type: ignore[index]
    with pytest.raises(TypeError):
        INCREMENT_5_EVALUATION_PLAN["triage_error_protocol"]["error_classes"][0][
            "class_id"
        ] = "OTHER"  # type: ignore[index]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("qualification_target", "EXACT_ONLY"),
        ("comparative_quality_results_can_rescue_target", True),
        ("cross_system_quality_pooling_allowed", True),
    ),
)
def test_changed_decision_scope_fails_semantically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    changed = _resigned_plan(
        tmp_path,
        lambda plan: plan["decision_scope"].__setitem__(field, value),
        f"changed-{field}.json",
    )
    monkeypatch.setattr(
        evaluation_plan_module,
        "EVALUATION_PLAN_DIGEST",
        digest_bytes(changed.read_bytes()),
    )
    with pytest.raises(Increment5EvaluationPlanError, match="decision scope differs"):
        evaluation_plan_module.load_increment5_evaluation_plan(changed)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("material_change_starts_new_epoch", False),
        ("cross_epoch_pooling_allowed", True),
        ("material_change_detection_rule", "OWNER_JUDGEMENT"),
    ),
)
def test_changed_epoch_protocol_fails_semantically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    changed = _resigned_plan(
        tmp_path,
        lambda plan: plan["epoch_protocol"].__setitem__(field, value),
        f"changed-epoch-{field}.json",
    )
    monkeypatch.setattr(
        evaluation_plan_module,
        "EVALUATION_PLAN_DIGEST",
        digest_bytes(changed.read_bytes()),
    )
    with pytest.raises(Increment5EvaluationPlanError, match="Epoch protocol differs"):
        evaluation_plan_module.load_increment5_evaluation_plan(changed)


def test_changed_triage_error_protocol_fails_semantically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = _resigned_plan(
        tmp_path,
        lambda plan: plan["triage_error_protocol"]["error_classes"][1].__setitem__(
            "error_count_metrics",
            ["other_count"],
        ),
        "changed-triage.json",
    )
    monkeypatch.setattr(
        evaluation_plan_module,
        "EVALUATION_PLAN_DIGEST",
        digest_bytes(changed.read_bytes()),
    )
    with pytest.raises(
        Increment5EvaluationPlanError,
        match="triage error class differs: FRAGMENTATION",
    ):
        evaluation_plan_module.load_increment5_evaluation_plan(changed)


def test_changed_or_noncanonical_plan_fails_closed(tmp_path: Path) -> None:
    value = json.loads(EVALUATION_PLAN_PATH.read_text(encoding="utf-8"))
    value["exposure_minima"]["minimum_total_unique_qualification_cases"] = 1
    changed = tmp_path / "changed.json"
    changed.write_bytes(canonical_json_bytes(value))
    with pytest.raises(
        Increment5EvaluationPlanError,
        match="bytes differ from reviewed v1",
    ):
        load_increment5_evaluation_plan(changed)

    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(value, indent=2), encoding="utf-8")
    with pytest.raises(
        Increment5EvaluationPlanError,
        match="exact canonical JSON",
    ):
        load_increment5_evaluation_plan(pretty)
