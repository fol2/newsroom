from __future__ import annotations

from pathlib import Path

from scripts.sdlc.classify_change import ChangedPath, classify_paths
from scripts.sdlc.contracts import load_contract
import scripts.sdlc.workflow_lane as lane_module


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = load_contract(_REPOSITORY_ROOT)
_BASE_SHA = "a" * 40
_HEAD_SHA = "b" * 40
_BASE_TREE_SHA = "c" * 40
_HEAD_TREE_SHA = "d" * 40
_INTEGRATED_SERVICE_TEST = (
    "newsroom/tests/test_integrated_c1_neo4j_service.py"
)
_INTEGRATED_SERVICE_TEST_ID = (
    "newsroom.tests.test_integrated_c1_neo4j_service::"
    "test_actual_service_integrated_foundation_replay_recovery_and_tombstone"
)


def _route(*paths: str) -> dict[str, object]:
    return classify_paths(
        _CONTRACT,
        tuple(ChangedPath(path) for path in paths),
        base_sha=_BASE_SHA,
        head_sha=_HEAD_SHA,
        base_tree_sha=_BASE_TREE_SHA,
        head_tree_sha=_HEAD_TREE_SHA,
    )


def test_increment_1c_native_graph_paths_require_actual_service_evidence() -> None:
    expected_tests = [
        "newsroom/tests/test_complete_projection_2b_neo4j_service.py",
        _INTEGRATED_SERVICE_TEST,
        "newsroom/tests/test_projection_b2_neo4j_service.py",
        "newsroom/tests/test_projection_b3_neo4j_service.py",
        "newsroom/tests/test_retrieval_2c_neo4j_service.py",
    ]
    paths = (
        "newsroom/authority/_integrated_system.py",
        "newsroom/authority/integrated_system.py",
        "newsroom/integrated/proof.py",
        _INTEGRATED_SERVICE_TEST,
    )
    route = _route(*paths)
    assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
    assert route["service_required"] is True
    assert route["service_tests"] == expected_tests
    for path in paths:
        assert any(
            reason.startswith(f"path:{path}:")
            and reason.endswith(":R3_EXTERNAL_SERVICE_SECURITY")
            for reason in route["reasons"]
        )


def test_increment_1c_contract_models_are_stateful_and_service_qualified() -> None:
    paths = (
        "newsroom/integrated/models.py",
        "newsroom/integrated/policy.py",
        "newsroom/integrated/traceability.py",
    )
    route = _route(*paths)
    assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
    assert route["core_required"] is True
    assert route["service_required"] is True
    for path in paths:
        assert (
            f"path:{path}:stateful_contract:R2_STATEFUL_CONTRACT"
            in route["reasons"]
        )
        assert any(
            reason.startswith(f"dependency:{path}->")
            and reason.endswith(":R3_EXTERNAL_SERVICE_SECURITY")
            for reason in route["reasons"]
        )


def test_complete_actual_service_cases_are_optional_only_in_core() -> None:
    optional = lane_module._OPTIONAL_CORE_TEST_IDS
    complete = {
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_complete_generation_queries_and_promotes_exact_state',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[deleted-document]',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[missing-vector-index]',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[wrong-fulltext-analyzer]',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_partial_or_contract_mismatched_state_fails_closed[wrong-vector-dimensions]',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_replacement_generation_recovers_from_authority_only',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_revocation_and_tombstone_remove_current_derivatives',
        'newsroom.tests.test_complete_projection_2b_neo4j_service::test_actual_service_wrong_watermark_generation_and_vector_dimension_fail_closed',
        'newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_executes_all_four_branches_and_hydrates_authority',
        'newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_missing_admitted_relation_is_incomplete_not_no_match',
        'newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_missing_fulltext_index_is_unavailable_not_no_match',
        'newsroom.tests.test_retrieval_2c_neo4j_service::test_actual_service_missing_vector_index_is_unavailable_not_no_match',
    }
    assert _INTEGRATED_SERVICE_TEST_ID in optional
    assert complete <= set(optional)
    assert optional == tuple(sorted(optional))
    assert len(optional) == 23

    route = _route("newsroom/projection/neo4j/_complete_adapter.py")
    assert route["service_required"] is True
    assert "newsroom/tests/test_complete_projection_2b_neo4j_service.py" in (
        route["service_tests"]
    )
    assert "newsroom/tests/test_retrieval_2c_neo4j_service.py" in (
        route["service_tests"]
    )
