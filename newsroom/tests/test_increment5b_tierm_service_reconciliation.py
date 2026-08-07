from pathlib import Path

from scripts.sdlc.workflow_lane import _OPTIONAL_CORE_TEST_IDS

EXPECTED = {'newsroom.tests.test_increment5b4_neo4j_service::test_increment5b4_fixed_port_excludes_future_observations', 'newsroom.tests.test_increment5b4_neo4j_service::test_increment5b4_fixed_port_reads_only_exact_generation_and_allowed_state'}


def test_increment5b4_authenticated_tests_are_core_optional() -> None:
    assert EXPECTED <= set(_OPTIONAL_CORE_TEST_IDS)


def test_service_lane_aliases_projector_credentials() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "evidence.yml"
    ).read_text(encoding="utf-8")
    user_alias = 'export NEWSROOM_NEO4J_USER="${NEWSROOM_NEO4J_PROJECTOR_USERNAME}"'
    password_alias = (
        'export NEWSROOM_NEO4J_PASSWORD="${NEWSROOM_NEO4J_PROJECTOR_PASSWORD}"'
    )
    service = workflow.index("  service:")
    execute = workflow.index("--lane service", service)
    assert service < workflow.index(user_alias, service) < execute
    assert service < workflow.index(password_alias, service) < execute
