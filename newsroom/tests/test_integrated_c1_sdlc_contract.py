from __future__ import annotations

from pathlib import Path

from scripts.sdlc.classify_change import ChangedPath, classify_paths
from scripts.sdlc.contracts import load_contract
import scripts.sdlc.workflow_lane as lane_module


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
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


def _route(path: str) -> dict[str, object]:
    return classify_paths(
        load_contract(_REPOSITORY_ROOT),
        (ChangedPath(path),),
        base_sha=_BASE_SHA,
        head_sha=_HEAD_SHA,
        base_tree_sha=_BASE_TREE_SHA,
        head_tree_sha=_HEAD_TREE_SHA,
    )


def test_increment_1c_native_graph_paths_require_actual_service_evidence() -> None:
    expected_tests = [
        _INTEGRATED_SERVICE_TEST,
        "newsroom/tests/test_projection_b2_neo4j_service.py",
        "newsroom/tests/test_projection_b3_neo4j_service.py",
    ]
    for path in (
        "newsroom/authority/_integrated_system.py",
        "newsroom/authority/integrated_system.py",
        "newsroom/integrated/proof.py",
        _INTEGRATED_SERVICE_TEST,
    ):
        route = _route(path)
        assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
        assert route["service_required"] is True
        assert route["service_tests"] == expected_tests


def test_increment_1c_contract_models_are_stateful_even_without_service_execution() -> None:
    for path in (
        "newsroom/integrated/models.py",
        "newsroom/integrated/policy.py",
        "newsroom/integrated/traceability.py",
    ):
        route = _route(path)
        assert route["risk_tier"] == "R2_STATEFUL_CONTRACT"
        assert route["core_required"] is True


def test_integrated_actual_service_case_is_the_only_new_optional_core_skip() -> None:
    optional = lane_module._OPTIONAL_CORE_TEST_IDS
    assert _INTEGRATED_SERVICE_TEST_ID in optional
    assert optional == tuple(sorted(optional))
    assert len(optional) == 11
