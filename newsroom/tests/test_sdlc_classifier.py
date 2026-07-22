from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.sdlc.classify_change import (
    ChangedPath,
    classify_paths,
    matches_repository_glob,
    parse_name_status,
)
from scripts.sdlc.contracts import load_contract


REPO_ROOT = Path(__file__).parents[2]
BASE_SHA = "0" * 40
HEAD_SHA = "1" * 40
BASE_TREE_SHA = "2" * 40
HEAD_TREE_SHA = "3" * 40


def _route(*paths: str) -> dict[str, object]:
    contract = load_contract(REPO_ROOT)
    return classify_paths(
        contract,
        (ChangedPath(path) for path in paths),
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        base_tree_sha=BASE_TREE_SHA,
        head_tree_sha=HEAD_TREE_SHA,
    )


def test_repository_globs_treat_double_star_as_zero_or_more_segments() -> None:
    assert matches_repository_glob("newsroom/migrations.py", "newsroom/**/migrations.py")
    assert matches_repository_glob(
        "newsroom/authority/deep/object_migrations.py",
        "newsroom/**/*_migrations.py",
    )
    assert matches_repository_glob("docs/README.md", "docs/**")
    assert not matches_repository_glob("other/docs/README.md", "docs/**")


def test_risk_routing_uses_maximum_triggered_tier() -> None:
    assert _route("README.md")["risk_tier"] == "R0_DOCUMENTATION"
    assert _route("newsroom/pure_helper.py")["risk_tier"] == "R1_LOCAL_CODE"
    assert _route("newsroom/authority/transaction.py")["risk_tier"] == (
        "R2_STATEFUL_CONTRACT"
    )
    assert _route("newsroom/projection/policy.py")["risk_tier"] == (
        "R3_EXTERNAL_SERVICE_SECURITY"
    )
    assert _route("release/production.yml")["risk_tier"] == (
        "R4_RELEASE_OPERATIONAL"
    )


def test_projection_policy_and_workflow_changes_require_actual_service() -> None:
    policy = _route("newsroom/projection/policy.py")
    workflow = _route(".github/workflows/evidence.yml")

    assert policy["service_required"] is True
    assert workflow["service_required"] is True
    assert policy["service_tests"] == [
        "newsroom/tests/test_projection_b2_neo4j_service.py"
    ]


def test_unknown_path_fails_closed_to_r3() -> None:
    route = _route("unexpected-surface/config.bin")

    assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
    assert route["service_required"] is True
    assert route["reasons"] == [
        "unknown_path:unexpected-surface/config.bin:R3_EXTERNAL_SERVICE_SECURITY"
    ]


def test_clustering_change_selects_the_clustering_gate_without_over_escalation() -> None:
    route = _route("newsroom/event_manager.py")

    assert route["risk_tier"] == "R1_LOCAL_CODE"
    assert route["clustering_required"] is True
    assert route["service_required"] is False


def test_adding_a_path_never_lowers_risk_metamorphic() -> None:
    contract = load_contract(REPO_ROOT)
    ranks = contract.risk_rank
    paths = (
        "README.md",
        "newsroom/pure_helper.py",
        "newsroom/authority/transaction.py",
        "newsroom/projection/policy.py",
        "release/production.yml",
    )
    previous_rank = -1
    for count in range(1, len(paths) + 1):
        route = _route(*paths[:count])
        current_rank = ranks[str(route["risk_tier"])]
        assert current_rank >= previous_rank
        previous_rank = current_rank


def test_route_is_deterministic_and_matches_the_json_schema() -> None:
    first = _route("newsroom/projection/policy.py", "README.md")
    second = _route("README.md", "newsroom/projection/policy.py")
    schema = json.loads(
        (REPO_ROOT / ".sdlc" / "route.schema.json").read_text(encoding="utf-8")
    )

    assert first == second
    assert first["selected_test_manifest_digest"].startswith("sha256:")
    Draft202012Validator(schema).validate(first)


def test_rename_classifies_both_old_and_new_paths() -> None:
    changes = parse_name_status(
        b"R100\x00newsroom/pure_helper.py\x00release/production.yml\x00"
    )
    contract = load_contract(REPO_ROOT)
    route = classify_paths(
        contract,
        changes,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        base_tree_sha=BASE_TREE_SHA,
        head_tree_sha=HEAD_TREE_SHA,
    )

    assert changes == (
        ChangedPath(
            "release/production.yml",
            "R100",
            "newsroom/pure_helper.py",
        ),
    )
    assert route["risk_tier"] == "R4_RELEASE_OPERATIONAL"
    assert route["owner_authority_required"] is True


def test_empty_diff_still_returns_an_always_reporting_core_route() -> None:
    route = _route()

    assert route["risk_tier"] == "R0_DOCUMENTATION"
    assert route["core_required"] is True
    assert route["service_required"] is False
    assert route["reasons"] == ["no_changes"]
