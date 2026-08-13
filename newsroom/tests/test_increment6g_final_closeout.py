from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from newsroom.increment6.closeout import (
    INCREMENT6_FINAL_REQUIREMENTS,
    INCREMENT6G_FINAL_CLOSEOUT_CASES,
    INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST,
    INCREMENT6G_FINAL_MIGRATION_HISTORY_DIGEST,
    INCREMENT6G_FINAL_NON_EFFECTS,
    INCREMENT6G_FINAL_SCHEMA_FINGERPRINT,
    INCREMENT6G_FINAL_SCHEMA_VERSION,
    Increment6CloseoutCategory,
    Increment6CloseoutLane,
    increment6g_final_migration_history,
    validate_increment6g_final_closeout_inventory,
)
from scripts.sdlc.workflow_lane import (
    _OPTIONAL_CORE_TEST_IDS,
    _core_node_shards,
    _repository_service_tests,
)

ROOT = Path(__file__).resolve().parents[2]


def test_final_closeout_inventory_is_content_addressed_and_exact() -> None:
    validate_increment6g_final_closeout_inventory()
    assert len(INCREMENT6G_FINAL_CLOSEOUT_CASES) == 59
    assert INCREMENT6G_FINAL_CLOSEOUT_INVENTORY_DIGEST == (
        "sha256:afc556ba5785f84eb691af903f24c81ac43d50bbe6c02a3ad23eb08dca8dff5f"
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
    inherited_handoff_boundary = next(
        case
        for case in INCREMENT6G_FINAL_CLOSEOUT_CASES
        if case.case_id == "F03_AUTHORITY"
    )
    assert inherited_handoff_boundary.test_id == (
        "newsroom.tests.test_increment6f2_feedback_system::"
        "test_accept_replay_snapshot_and_direct_tamper_fail_closed"
    )
    retained_after_head_advance = next(
        case
        for case in INCREMENT6G_FINAL_CLOSEOUT_CASES
        if case.case_id == "F04_RETAINED_AFTER_HEAD_ADVANCE"
    )
    assert retained_after_head_advance.test_id == (
        "newsroom.tests.test_increment6f2_feedback_system::"
        "test_disposition_is_generic_ledger_anchored_and_replay_precedes_ports"
    )
    assert set(retained_after_head_advance.requirements) == {
        "COLLISION_CANDIDATE_EQUIVALENT_DISTINCT_ADMISSION",
        "FEEDBACK_OBLIGATION_RECONCILIATION_VISIBILITY",
    }
    assert INCREMENT6G_FINAL_NON_EFFECTS == tuple(sorted(INCREMENT6G_FINAL_NON_EFFECTS))


def test_closeout_test_functions_are_permanent_repository_tests() -> None:
    for case in INCREMENT6G_FINAL_CLOSEOUT_CASES:
        module_name, function_name = case.test_id.split("::", 1)
        function_name = function_name.split("[", 1)[0]
        module = importlib.import_module(module_name)
        assert callable(getattr(module, function_name))


def test_expensive_lineage_cases_concentration_is_bounded() -> None:
    from newsroom.tests.test_increment6d3_lineage_store import (
        _EXPECTED_PROBE_IDS,
        _bound_or_collected_core_inventory,
    )

    prefix = (
        "newsroom/tests/test_increment6d3_lineage_store.py::"
        "test_real_v23_store_passes_required_conformance_probe["
    )
    shards = _core_node_shards(_bound_or_collected_core_inventory())
    counts = tuple(
        sum(node_id.startswith(prefix) for node_id in shard) for shard in shards
    )

    assert sum(counts) == len(_EXPECTED_PROBE_IDS)
    assert max(counts) <= 7


def test_increment6_closeout_migration_identity_accepts_only_an_exact_prefix() -> None:
    from newsroom.authority.migrations import EXPECTED_MIGRATION_HISTORY

    prefix = increment6g_final_migration_history(EXPECTED_MIGRATION_HISTORY)
    assert len(prefix) == INCREMENT6G_FINAL_SCHEMA_VERSION == 25
    assert INCREMENT6G_FINAL_SCHEMA_FINGERPRINT == (
        "sha256:353900bf5804f0b770489982541f3cff4fd30ea36fc75d19b9c63315d1b6ec06"
    )
    assert INCREMENT6G_FINAL_MIGRATION_HISTORY_DIGEST == (
        "sha256:bea793377d065d3073e6dfa8d40139fedfd377d5e24d9812d12cdb1ad52e9a0f"
    )

    appended = (*EXPECTED_MIGRATION_HISTORY, (26, "future_authorised", "sha256:x"))
    assert increment6g_final_migration_history(appended) == prefix

    changed = list(EXPECTED_MIGRATION_HISTORY)
    changed[0] = (1, "changed", changed[0][2])
    with pytest.raises(RuntimeError, match="migration history prefix"):
        increment6g_final_migration_history(tuple(changed))


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
