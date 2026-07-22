from __future__ import annotations

import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator
import pytest

from scripts.sdlc.classify_change import (
    ChangedPath,
    changed_paths,
    classify_paths,
    matches_repository_glob,
    parse_name_status,
)
from scripts.sdlc.contracts import ContractError, SdlcContract, load_contract


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


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_repository_globs_treat_double_star_as_zero_or_more_segments() -> None:
    assert matches_repository_glob("newsroom/migrations.py", "newsroom/**/migrations.py")
    assert matches_repository_glob(
        "newsroom/authority/deep/object_migrations.py",
        "newsroom/**/*_migrations.py",
    )
    assert matches_repository_glob("docs/README.md", "docs/**")
    assert not matches_repository_glob("other/docs/README.md", "docs/**")
    assert not matches_repository_glob("../release/production.yml", "release/**")


def test_risk_routing_uses_maximum_triggered_tier() -> None:
    assert _route("README.md")["risk_tier"] == "R0_DOCUMENTATION"
    assert _route("newsroom/tests/test_unrelated.py")["risk_tier"] == (
        "R1_LOCAL_CODE"
    )
    assert _route("newsroom/authority/transaction.py")["risk_tier"] == (
        "R2_STATEFUL_CONTRACT"
    )
    assert _route("newsroom/projection/policy.py")["risk_tier"] == (
        "R3_EXTERNAL_SERVICE_SECURITY"
    )
    assert _route("release/production.yml")["risk_tier"] == (
        "R4_RELEASE_OPERATIONAL"
    )


def test_classifier_source_tests_policy_and_workflows_require_service() -> None:
    paths = (
        "scripts/sdlc/classify_change.py",
        "newsroom/tests/test_sdlc_classifier.py",
        "newsroom/projection/policy.py",
        ".github/workflows/evidence.yml",
    )

    for path in paths:
        route = _route(path)
        assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
        assert route["service_required"] is True
        assert route["service_tests"] == [
            "newsroom/tests/test_projection_b2_neo4j_service.py"
        ]


def test_service_route_fails_closed_when_actual_service_test_is_absent(
    tmp_path: Path,
) -> None:
    source = load_contract(REPO_ROOT)
    contract = SdlcContract(tmp_path, source.source_path, source.data)

    with pytest.raises(ContractError, match="no actual-service test"):
        classify_paths(
            contract,
            (ChangedPath("newsroom/projection/policy.py"),),
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            base_tree_sha=BASE_TREE_SHA,
            head_tree_sha=HEAD_TREE_SHA,
        )


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
        "newsroom/tests/test_unrelated.py",
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


def test_invalid_identity_cannot_be_serialized_as_route_evidence() -> None:
    contract = load_contract(REPO_ROOT)

    with pytest.raises(ContractError, match="base_sha"):
        classify_paths(
            contract,
            (),
            base_sha="main",
            head_sha=HEAD_SHA,
            base_tree_sha=BASE_TREE_SHA,
            head_tree_sha=HEAD_TREE_SHA,
        )


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


def test_exact_base_to_head_diff_does_not_hide_diverged_base_changes(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "SDLC Test")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")

    _git(tmp_path, "checkout", "-b", "head")
    (tmp_path / "newsroom").mkdir()
    (tmp_path / "newsroom" / "pure_helper.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "head change")
    head = _git(tmp_path, "rev-parse", "HEAD")

    _git(tmp_path, "checkout", "main")
    (tmp_path / "release").mkdir()
    (tmp_path / "release" / "production.yml").write_text(
        "enabled: false\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base advanced")
    base = _git(tmp_path, "rev-parse", "HEAD")

    changed = changed_paths(tmp_path, base, head)
    assert {item.path for item in changed} == {
        "newsroom/pure_helper.py",
        "release/production.yml",
    }


def test_empty_diff_still_returns_an_always_reporting_core_route() -> None:
    route = _route()

    assert route["risk_tier"] == "R0_DOCUMENTATION"
    assert route["core_required"] is True
    assert route["service_required"] is False
    assert route["reasons"] == ["no_changes"]
