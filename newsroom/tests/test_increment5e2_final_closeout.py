from __future__ import annotations

import importlib
import re
from pathlib import Path

from newsroom.increment5._traceability_model import (
    RETRIEVAL_QUALIFICATION_REQUIREMENTS,
)
from newsroom.increment5.final_closeout import (
    INCREMENT5_FINAL_REQUIREMENTS,
    INCREMENT5E2_FINAL_CLOSEOUT_CASES,
    INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT5E2_FINAL_NON_EFFECTS,
    FinalCloseoutCategory,
    FinalCloseoutLane,
    validate_increment5e2_final_closeout_inventory,
)
from scripts.sdlc.workflow_lane import (
    _OPTIONAL_CORE_TEST_IDS,
    _repository_service_tests,
)

ROOT = Path(__file__).resolve().parents[2]


def test_final_closeout_inventory_is_content_addressed_and_exact() -> None:
    validate_increment5e2_final_closeout_inventory()
    assert len(INCREMENT5E2_FINAL_CLOSEOUT_CASES) == 64
    assert INCREMENT5E2_FINAL_CLOSEOUT_INVENTORY_DIGEST == (
        "sha256:7cdb2c769c4f312f0e2f670fd3c4084025d7cbe247788993d5b50841b0a5be95"
    )
    assert {
        requirement
        for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES
        for requirement in case.requirements
    } == INCREMENT5_FINAL_REQUIREMENTS
    assert INCREMENT5_FINAL_REQUIREMENTS is RETRIEVAL_QUALIFICATION_REQUIREMENTS
    assert INCREMENT5E2_FINAL_NON_EFFECTS == tuple(
        sorted(INCREMENT5E2_FINAL_NON_EFFECTS)
    )


def test_every_closeout_category_has_deterministic_and_actual_service_proof() -> None:
    for category in FinalCloseoutCategory:
        assert {
            case.lane
            for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES
            if case.category is category
        } == set(FinalCloseoutLane)


def test_closeout_test_functions_are_permanent_repository_tests() -> None:
    for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES:
        module_name, function_name = case.test_id.split("::", 1)
        function_name = function_name.split("[", 1)[0]
        module = importlib.import_module(module_name)
        assert callable(getattr(module, function_name))


def test_actual_service_closeout_cases_are_closed_world_sdlc_cases() -> None:
    actual = {
        case.test_id
        for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES
        if case.lane is FinalCloseoutLane.ACTUAL_NEO4J
    }
    assert actual <= set(_OPTIONAL_CORE_TEST_IDS)

    selected_files = set(_repository_service_tests(ROOT))
    for test_id in actual:
        module_name = test_id.split("::", 1)[0]
        relative = module_name.replace(".", "/") + ".py"
        assert relative in selected_files


def test_permanent_neo4j_workflow_selects_every_actual_closeout_module() -> None:
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
        for case in INCREMENT5E2_FINAL_CLOSEOUT_CASES
        if case.lane is FinalCloseoutLane.ACTUAL_NEO4J
    }
    assert required <= selected


def test_final_actual_service_receipt_binds_every_frozen_identity() -> None:
    source = (
        ROOT / "newsroom" / "tests" / "test_projection_b2_increment5e2_neo4j_service.py"
    ).read_text(encoding="utf-8")
    for identity in (
        "increment5e2_epoch_json",
        "increment5e2_epoch_digest",
        "increment5e2_report_json",
        "increment5e2_report_digest",
        "increment5e2_closeout_inventory_digest",
        "increment5e2_closeout_case_count",
        "increment5e2_non_effects",
        "increment5e2_source_head_sha",
        "increment5e2_source_tree_sha",
        "increment5e2_neo4j_image",
        "increment5e2_neo4j_server_version",
        "increment5e2_neo4j_edition",
        "increment5e2_neo4j_driver_version",
        "increment5e2_neo4j_database",
        "increment5e2_neo4j_projector_username",
        "increment5e2_service_compatibility_digest",
    ):
        assert identity in source
