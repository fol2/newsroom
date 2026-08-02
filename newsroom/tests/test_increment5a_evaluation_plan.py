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
    MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES,
    ZERO_TOLERANCE_GATE_NAMES,
    Increment5EvaluationPlanError,
    load_increment5_evaluation_plan,
)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {name: _plain(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


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


def test_all_mandatory_graphrag_use_case_families_are_preregistered() -> None:
    families = INCREMENT_5_EVALUATION_PLAN["mandatory_query_families"]
    assert tuple(family["family_id"] for family in families) == (
        MANDATORY_QUERY_FAMILY_IDS
    )

    by_id = {family["family_id"]: family for family in families}
    assert set(by_id["EVENT_AND_DEVELOPMENT_PRECISION"]["required_case_types"]) == {
        "DEVELOPMENT_OF_EXISTING_EVENT",
        "RELATED_BUT_DISTINCT_EVENT",
        "SAME_EVENT_STATE",
    }
    assert set(by_id["SOURCE_REVISION_IMPACT"]["required_case_types"]) == {
        "CORRECTION_IMPACT",
        "DOWNSTREAM_CANDIDATE_IMPACT",
        "SUPERSESSION_IMPACT",
    }
    assert set(
        by_id["LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE"][
            "required_case_types"
        ]
    ) == {
        "CORRECTION",
        "ORDERED_DEVELOPMENT",
        "SUPERSESSION",
        "TEMPORAL_CUTOFF",
    }
    assert all(family["required_metrics"] for family in families)
    assert all(family["required_slices"] for family in families)


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
    assert exposure["cross_family_case_reuse_allowed"] is False
    assert exposure["calibration_cases_count_toward_minima"] is False
    assert exposure["insufficient_exposure_outcome"] == "NOT_EVALUATED"
    assert "post-freeze cases do not count" in exposure["case_counting_rule"]

    family_minima = exposure["minimum_cases_by_query_family"]
    assert sum(family_minima.values()) == (
        MINIMUM_TOTAL_UNIQUE_QUALIFICATION_CASES
    )


def test_temporal_and_rebuild_gates_are_blocking_at_zero() -> None:
    gates = INCREMENT_5_EVALUATION_PLAN["zero_tolerance_gates"]
    assert tuple(sorted(gates)) == tuple(sorted(ZERO_TOLERANCE_GATE_NAMES))

    temporal = gates["temporal_correctness_error_count"]
    assert temporal["blocking"] is True
    assert temporal["maximum"] == 0
    assert temporal["required_slice"] == "TEMPORAL_CUTOFF"
    assert "post-cutoff" in temporal["definition"]

    rebuild = gates["rebuild_reproducibility_mismatch_count"]
    assert rebuild["blocking"] is True
    assert rebuild["maximum"] == 0
    assert rebuild["required_experiment"] == "RIGHTS_PURGE_AND_REBUILD"
    assert "ordering" in rebuild["definition"]


def test_evaluation_plan_is_immutable() -> None:
    with pytest.raises(TypeError):
        INCREMENT_5_EVALUATION_PLAN["contract_digest"] = "sha256:00"  # type: ignore[index]
    with pytest.raises(TypeError):
        INCREMENT_5_EVALUATION_PLAN["zero_tolerance_gates"][
            "temporal_correctness_error_count"
        ]["maximum"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        INCREMENT_5_EVALUATION_PLAN["exposure_minima"][
            "minimum_total_unique_qualification_cases"
        ] = 1  # type: ignore[index]


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
