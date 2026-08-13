from __future__ import annotations

import importlib
import re
from pathlib import Path

from newsroom.increment6.closeout import (
    INCREMENT6_FINAL_REQUIREMENTS,
    INCREMENT6G_FINAL_CLOSEOUT_CASES,
    INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT6G_FINAL_NON_EFFECTS,
    Increment6CloseoutCategory,
    Increment6CloseoutLane,
    validate_increment6g_final_closeout_inventory,
)
from scripts.sdlc.workflow_lane import (
    _OPTIONAL_CORE_TEST_IDS,
    _repository_service_tests,
)

ROOT = Path(__file__).resolve().parents[2]


def test_final_closeout_inventory_is_content_addressed_and_exact() -> None:
    validate_increment6g_final_closeout_inventory()
    assert len(INCREMENT6G_FINAL_CLOSEOUT_CASES) == 58
    assert INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST == (
        "sha256:67ae4fdba2d9bda2280896a2e2de38a95a211cfe1f80dd505ccd646cdc2b4b4f"
    )
    assert {
        requirement
        for case in INCREMENT6G_FINAL_CLOSEOUT_CASES
        for requirement in case.requirements
    } == INCREMENT6_FINAL_REQUIREMENTS
    assert {case.category for case in INCREMENT6G_FINAL_CLOSEOUT_CASES} == set(
        Increment6CloseoutCategory
    )
    assert {case.lane for case in INCREMENT6G_FINAL_CLOSEOUT_CASES} == set(
        Increment6CloseoutLane
    )
    assert INCREMENT6G_FINAL_NON_EFFECTS == tuple(sorted(INCREMENT6G_FINAL_NON_EFFECTS))


def test_closeout_test_functions_are_permanent_repository_tests() -> None:
    for case in INCREMENT6G_FINAL_CLOSEOUT_CASES:
        module_name, function_name = case.test_id.split("::", 1)
        function_name = function_name.split("[", 1)[0]
        module = importlib.import_module(module_name)
        assert callable(getattr(module, function_name))


def test_actual_service_case_is_in_both_permanent_service_routes() -> None:
    actual = {
        case.test_id
        for case in INCREMENT6G_FINAL_CLOSEOUT_CASES
        if case.lane is Increment6CloseoutLane.ACTUAL_NEO4J
    }
    assert actual <= set(_OPTIONAL_CORE_TEST_IDS)

    selected_files = set(_repository_service_tests(ROOT))
    for test_id in actual:
        module_name = test_id.split("::", 1)[0]
        assert module_name.replace(".", "/") + ".py" in selected_files

    workflow = (ROOT / ".github" / "workflows" / "projection-b2-neo4j.yml").read_text(
        encoding="utf-8"
    )
    patterns = set(re.findall(r"newsroom/tests/test_[^\\\s]+\.py", workflow))
    selected = {
        path.relative_to(ROOT).as_posix()
        for pattern in patterns
        for path in ROOT.glob(pattern)
    }
    required = {
        case.test_id.split("::", 1)[0].replace(".", "/") + ".py"
        for case in INCREMENT6G_FINAL_CLOSEOUT_CASES
        if case.lane is Increment6CloseoutLane.ACTUAL_NEO4J
    }
    assert required <= selected


def test_actual_service_target_binds_every_frozen_identity() -> None:
    source = (
        ROOT / "newsroom" / "tests" / "test_increment6g_neo4j_service.py"
    ).read_text(encoding="utf-8")
    for identity in (
        "increment6g_source_head_sha",
        "increment6g_source_tree_sha",
        "increment6g_schema_version",
        "increment6g_schema_fingerprint",
        "increment6g_migration_history_json",
        "increment6g_closeout_inventory_digest",
        "increment6g_closeout_case_count",
        "increment6g_non_effects",
        "increment6g_neo4j_image",
        "increment6g_neo4j_server_version",
        "increment6g_neo4j_edition",
        "increment6g_neo4j_driver_version",
        "increment6g_neo4j_database",
        "increment6g_neo4j_projector_username",
        "increment6g_service_compatibility_digest",
    ):
        assert identity in source
