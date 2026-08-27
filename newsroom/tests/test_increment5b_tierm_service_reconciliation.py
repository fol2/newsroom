from pathlib import Path

from scripts.sdlc.workflow_lane import (
    _OPTIONAL_CORE_TEST_IDS,
    _SERVICE_CONFIGURATION,
)

EXPECTED = {'newsroom.tests.test_increment5b4_neo4j_service::test_increment5b4_fixed_port_excludes_future_observations', 'newsroom.tests.test_increment5b4_neo4j_service::test_increment5b4_fixed_port_reads_only_exact_generation_and_allowed_state'}


def test_increment5b4_authenticated_tests_are_core_optional() -> None:
    assert EXPECTED <= set(_OPTIONAL_CORE_TEST_IDS)


def test_full_health_workflow_does_not_host_the_service_lane() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "evidence.yml"
    ).read_text(encoding="utf-8")
    assert "name: Full Repository Health" in workflow
    assert "\n  full-health:\n" in workflow
    assert "--lane service" not in workflow
    assert "NEWSROOM_NEO4J_PROJECTOR_USERNAME" not in workflow
    assert "NEWSROOM_NEO4J_PROJECTOR_PASSWORD" not in workflow

def test_service_contract_exposes_generic_projector_identity_without_secret() -> None:
    assert _SERVICE_CONFIGURATION["NEWSROOM_NEO4J_USER"] == "newsroom_projector"
    assert _SERVICE_CONFIGURATION["NEWSROOM_NEO4J_PROJECTOR_USERNAME"] == (
        "newsroom_projector"
    )
    assert "NEWSROOM_NEO4J_PASSWORD" not in _SERVICE_CONFIGURATION
