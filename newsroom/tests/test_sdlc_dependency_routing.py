from __future__ import annotations

from pathlib import Path

from scripts.sdlc.classify_change import ChangedPath, classify_paths
from scripts.sdlc.contracts import SdlcContract, load_contract


REPO_ROOT = Path(__file__).parents[2]
BASE_SHA = "0" * 40
HEAD_SHA = "1" * 40
BASE_TREE_SHA = "2" * 40
HEAD_TREE_SHA = "3" * 40


def _route(contract: SdlcContract, *changes: ChangedPath) -> dict[str, object]:
    return classify_paths(
        contract,
        changes,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        base_tree_sha=BASE_TREE_SHA,
        head_tree_sha=HEAD_TREE_SHA,
    )


def test_real_authority_dependency_escalates_to_neo4j_service() -> None:
    contract = load_contract(REPO_ROOT)
    route = _route(contract, ChangedPath("newsroom/authority/canonical.py"))

    assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
    assert route["service_required"] is True
    assert any(
        reason.startswith(
            "dependency:newsroom/authority/canonical.py->"
            "newsroom/authority/_neo4j_projection_system.py:"
        )
        for reason in route["reasons"]
    )


def test_unrelated_test_only_change_does_not_enter_production_dependency_graph() -> None:
    contract = load_contract(REPO_ROOT)
    route = _route(contract, ChangedPath("newsroom/tests/test_unrelated.py"))

    assert route["risk_tier"] == "R1_LOCAL_CODE"
    assert route["service_required"] is False


def test_deleted_python_module_fails_closed_to_service_evidence() -> None:
    contract = load_contract(REPO_ROOT)
    route = _route(contract, ChangedPath("newsroom/deleted_module.py", "D"))

    assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
    assert route["service_required"] is True
    assert any(
        reason.startswith("unknown_dependency_edge:changed Python module is absent")
        for reason in route["reasons"]
    )


def test_unresolved_repository_import_emits_fail_closed_route(tmp_path: Path) -> None:
    source = load_contract(REPO_ROOT)
    (tmp_path / "newsroom" / "tests").mkdir(parents=True)
    (tmp_path / "newsroom" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "newsroom" / "core.py").write_text(
        "import newsroom.missing\n",
        encoding="utf-8",
    )
    (tmp_path / "newsroom" / "tests" / "test_projection_x_neo4j_service.py").write_text(
        "def test_service(): pass\n",
        encoding="utf-8",
    )
    contract = SdlcContract(tmp_path, source.source_path, source.data)

    route = _route(contract, ChangedPath("newsroom/core.py"))

    assert route["risk_tier"] == "R3_EXTERNAL_SERVICE_SECURITY"
    assert route["service_required"] is True
    assert any(
        reason.startswith("unknown_dependency_edge:unresolved internal import")
        for reason in route["reasons"]
    )
