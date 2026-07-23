from __future__ import annotations

from pathlib import Path

LANE = Path("scripts/sdlc/workflow_lane.py")
LANE_TEST = Path("newsroom/tests/test_sdlc_workflow_lane.py")
CLASSIFIER_TEST = Path("newsroom/tests/test_sdlc_classifier.py")

lane = LANE.read_text(encoding="utf-8")
old_optional = '''_OPTIONAL_CORE_TEST_IDS = (
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_public_round_trip_duplicate_and_generation_isolation",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_requires_explicit_authentication_configuration",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_wrong_projector_credential_fails_closed_without_secret",
)
'''
new_optional = '''_OPTIONAL_CORE_TEST_IDS = (
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_public_round_trip_duplicate_and_generation_isolation",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_requires_explicit_authentication_configuration",
    "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_wrong_projector_credential_fails_closed_without_secret",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_graph_loss_and_process_restart_rebuild_from_authority",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace",
)
'''
if lane.count(old_optional) != 1:
    raise SystemExit("optional service test topology mismatch")
lane = lane.replace(old_optional, new_optional)
LANE.write_text(lane, encoding="utf-8")

lane_test = LANE_TEST.read_text(encoding="utf-8")
old_lane_test = '''def test_optional_core_skips_are_exact_actual_service_cases() -> None:
    assert lane_module._OPTIONAL_CORE_TEST_IDS == tuple(
        sorted(lane_module._OPTIONAL_CORE_TEST_IDS)
    )
    assert len(lane_module._OPTIONAL_CORE_TEST_IDS) == 4
    assert all(
        value.startswith("newsroom.tests.test_projection_b2_neo4j_service::")
        for value in lane_module._OPTIONAL_CORE_TEST_IDS
    )
'''
new_lane_test = '''def test_optional_core_skips_are_exact_actual_service_cases() -> None:
    expected = (
        "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_private_adapter_exact_duplicate_and_digest_conflict",
        "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_public_round_trip_duplicate_and_generation_isolation",
        "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_requires_explicit_authentication_configuration",
        "newsroom.tests.test_projection_b2_neo4j_service::test_actual_service_wrong_projector_credential_fails_closed_without_secret",
        "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_graph_loss_and_process_restart_rebuild_from_authority",
        "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace",
    )
    assert lane_module._OPTIONAL_CORE_TEST_IDS == expected
    assert lane_module._OPTIONAL_CORE_TEST_IDS == tuple(sorted(expected))
'''
if lane_test.count(old_lane_test) != 1:
    raise SystemExit("optional service test assertion mismatch")
lane_test = lane_test.replace(old_lane_test, new_lane_test)
LANE_TEST.write_text(lane_test, encoding="utf-8")

classifier_test = CLASSIFIER_TEST.read_text(encoding="utf-8")
old_classifier = '''        assert route["service_tests"] == [
            "newsroom/tests/test_projection_b2_neo4j_service.py"
        ]
'''
new_classifier = '''        assert route["service_tests"] == [
            "newsroom/tests/test_projection_b2_neo4j_service.py",
            "newsroom/tests/test_projection_b3_neo4j_service.py",
        ]
'''
if classifier_test.count(old_classifier) != 1:
    raise SystemExit("classifier service topology assertion mismatch")
classifier_test = classifier_test.replace(old_classifier, new_classifier)
CLASSIFIER_TEST.write_text(classifier_test, encoding="utf-8")
