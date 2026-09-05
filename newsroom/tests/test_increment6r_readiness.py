from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import zipfile

import pytest

import newsroom.authority.migrations as authority_migrations
import newsroom.increment6.readiness as readiness_module
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.migrations import (
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.increment6 import (
    INCREMENT_6_READINESS,
    INCREMENT_6_READINESS_DIGEST,
    READINESS_CONTRACT_PATH,
    GateTier,
    Increment6ReadinessError,
    load_increment6_readiness_contract,
    validate_interface_inventory,
)


_BASE_COMMIT = "ba0832b4d0ac7b9a65f318beb266889c9dcd9f2e"
_BASE_TREE = "069f19698f8bfe6d0f8453219ccd961c89be94c4"
_BASE_FINGERPRINT = (
    "sha256:b5a6d2afc78838cdeb648e7cd34b66452f2e0a0f7dab4773dd17a4cc28e3b5d8"
)
_CHILD_ISSUES = tuple(range(354, 369))
_MIGRATION_SLOTS = {
    357: 17,
    358: 18,
    362: 19,
    361: 20,
    363: 21,
    364: 22,
    365: 23,
    366: 24,
    367: 25,
}
_WAVES = {
    0: (354,),
    1: (355, 356, 357, 360),
    2: (358, 359, 362),
    3: (361, 363),
    4: (364,),
    5: (365,),
    6: (366,),
    7: (367,),
    8: (368,),
}


def _record() -> dict[str, object]:
    value = json.loads(READINESS_CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_readiness_is_bound_to_the_exact_final_increment5_head() -> None:
    readiness = INCREMENT_6_READINESS

    assert readiness.issue_number == 354
    assert readiness.parent_issue_number == 146
    assert readiness.accepted_base_commit == _BASE_COMMIT
    assert readiness.accepted_base_tree == _BASE_TREE
    assert readiness.accepted_schema_version == 16
    assert readiness.accepted_schema_fingerprint == _BASE_FINGERPRINT
    assert readiness.accepted_migration_history == (
        authority_migrations.EXPECTED_MIGRATION_HISTORY[:16]
    )
    assert readiness.effective_when == "PRESENT_ON_MAIN_AFTER_REVIEWED_6R_MERGE"
    assert readiness.production_activation_authorised is False
    assert readiness.contract_digest == INCREMENT_6_READINESS_DIGEST
    assert readiness.contract_digest == digest_bytes(READINESS_CONTRACT_PATH.read_bytes())


def test_current_head_interface_inventory_resolves_exact_symbols_and_digests() -> None:
    inventory = INCREMENT_6_READINESS.interface_inventory

    assert tuple(item.interface_id for item in inventory) == (
        "increment5.retrieval-context",
        "increment5.current-collision-receipt",
        "integrated.fixture-identities",
        "discovery.lead-disposition-and-watch",
        "authority.checked-schema",
    )
    assert validate_interface_inventory(INCREMENT_6_READINESS) == ()

    retrieval = inventory[0]
    assert retrieval.module == "newsroom.increment5.retrieval_context"
    assert retrieval.symbol_digests == {
        "RETRIEVAL_CONTEXT_CONTRACT_DIGEST": (
            "sha256:5572125c1c78ed409e68cfc6a0ad2f2048f707e43b389b03094053c9fa243450"
        ),
        "GOVERNED_CAS_HYDRATOR_CONTRACT_DIGEST": (
            "sha256:9550a4fbad491fce4bf9b62be501cbdf8b7735beb56c038f65e346f1a3d9c3af"
        ),
    }
    discovery = inventory[3]
    assert {
        "DecisionTerminality",
        "NextAction",
        "NextActionKind",
        "ReasonBasisClass",
        "StructuredReason",
    } <= set(discovery.symbols)


def test_every_increment6_atom_has_one_disjoint_public_and_schema_owner() -> None:
    readiness = INCREMENT_6_READINESS
    allocations = readiness.allocations

    assert tuple(item.issue_number for item in allocations) == _CHILD_ISSUES
    assert set(readiness.allocation_by_issue) == set(_CHILD_ISSUES)
    assert all(item.public_modules for item in allocations)
    assert all(item.schema_ids for item in allocations)

    modules = [name for item in allocations for name in item.public_modules]
    schema_ids = [name for item in allocations for name in item.schema_ids]
    tables = [name for item in allocations for name in item.table_names]
    interfaces = [
        name for item in allocations for name in item.interface_ownership
    ]
    migration_modules = [
        item.migration_module
        for item in allocations
        if item.migration_module is not None
    ]
    assert len(modules) == len(set(modules))
    assert len(schema_ids) == len(set(schema_ids))
    assert len(tables) == len(set(tables))
    assert len(interfaces) == len(set(interfaces))
    assert len(migration_modules) == len(set(migration_modules))

    assert readiness.allocation_by_issue[355].public_modules == (
        "newsroom.increment6.outcomes",
    )
    assert readiness.allocation_by_issue[356].public_modules == (
        "newsroom.increment6.proposals",
    )
    assert readiness.allocation_by_issue[357].public_modules == (
        "newsroom.increment6.handoffs",
    )
    assert {
        "CANONICAL_NEXT_ACTION",
        "DECISION_TERMINALITY",
        "WATCH_CONDITION_MAPPING",
        "SUPPLEMENTAL_ACTION_MAPPING",
    } <= set(readiness.allocation_by_issue[355].interface_ownership)
    assert "SUPPLEMENTAL_DISCOVERY_REENTRY" in (
        readiness.allocation_by_issue[358].interface_ownership
    )
    assert "SUPPLEMENTAL_DISCOVERY_REENTRY_PROOF" in (
        readiness.allocation_by_issue[368].interface_ownership
    )


def test_migration_slots_are_reserved_contiguously_and_never_multiply_owned() -> None:
    readiness = INCREMENT_6_READINESS
    observed = {
        item.issue_number: item.migration_version
        for item in readiness.allocations
        if item.migration_version is not None
    }

    assert observed == _MIGRATION_SLOTS
    assert tuple(sorted(observed.values())) == tuple(range(17, 26))
    assert len(observed.values()) == len(set(observed.values()))
    assert all(
        readiness.allocation_by_issue[issue].migration_version is None
        for issue in {354, 355, 356, 359, 360, 368}
    )


def test_dependency_graph_is_acyclic_and_matches_safe_parallel_waves() -> None:
    readiness = INCREMENT_6_READINESS

    assert readiness.parallel_waves == _WAVES
    wave_by_issue = {
        issue: wave for wave, issues in readiness.parallel_waves.items() for issue in issues
    }
    wave_issues = tuple(
        issue for issues in readiness.parallel_waves.values() for issue in issues
    )
    assert len(wave_issues) == len(set(wave_issues))
    assert tuple(sorted(wave_issues)) == _CHILD_ISSUES
    assert set(wave_by_issue) == set(_CHILD_ISSUES)
    for allocation in readiness.allocations:
        for dependency in allocation.dependencies:
            if dependency in wave_by_issue:
                assert wave_by_issue[dependency] < wave_by_issue[allocation.issue_number]

    assert readiness.allocation_by_issue[363].dependencies == (354, 358, 362)
    assert readiness.allocation_by_issue[366].dependencies == (360, 364, 365)
    assert readiness.allocation_by_issue[367].dependencies == (357, 366)
    assert readiness.allocation_by_issue[368].dependencies == tuple(range(354, 368))


def test_gate_tiers_and_effect_boundaries_are_explicit() -> None:
    readiness = INCREMENT_6_READINESS

    assert readiness.allocation_by_issue[354].gate_tier is GateTier.S
    assert readiness.allocation_by_issue[355].gate_tier is GateTier.L
    assert readiness.allocation_by_issue[356].gate_tier is GateTier.L
    assert readiness.allocation_by_issue[359].gate_tier is GateTier.L
    assert readiness.allocation_by_issue[368].gate_tier is GateTier.M
    assert all(
        item.gate_tier is GateTier.S
        for item in readiness.allocations
        if item.issue_number not in {354, 355, 356, 359, 368}
    )

    assert readiness.exclusions == (
        "EVIDENCE_ACQUISITION",
        "INCREMENT_7_OR_8_RUNTIME",
        "LIVE_MODEL_OR_PROVIDER",
        "PRODUCTION_ACTIVATION",
        "PUBLICATION_OR_PUBLIC_EFFECT",
        "PUBLICATION_CREDENTIAL",
        "SHADOW_OR_CANARY",
    )
    assert readiness.rollback["history_rewrite_allowed"] is False
    assert readiness.rollback["destructive_down_migration_allowed"] is False
    assert readiness.rollback["pre_migration_backup_required"] is True
    assert readiness.rollback["newer_schema_must_fail_closed"] is True

    assert set(readiness.gate_requirements) == {GateTier.L, GateTier.S, GateTier.M}
    assert "FOCUSED_TESTS" in readiness.gate_requirements[GateTier.L]
    assert "CHECKED_MIGRATION_UPGRADE_AND_ROLLBACK" in readiness.gate_requirements[GateTier.S]
    assert "SAME_EXACT_MAIN_SHA" in readiness.gate_requirements[GateTier.M]
    assert (
        "SUPPLEMENTAL_DISCOVERY_REENTRY_PATH"
        in readiness.gate_requirements[GateTier.M]
    )
    assert "ZERO_P1_OR_MATERIAL_P2" in readiness.gate_requirements[GateTier.M]


def test_readiness_contract_is_canonical_and_duplicate_or_changed_bytes_fail_closed(
    tmp_path: Path,
) -> None:
    raw = READINESS_CONTRACT_PATH.read_bytes()
    assert raw == canonical_json_bytes(json.loads(raw.decode("utf-8")))

    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(_record(), indent=2), encoding="utf-8")
    with pytest.raises(Increment6ReadinessError, match="exact canonical JSON"):
        load_increment6_readiness_contract(pretty)

    duplicate = raw.decode("utf-8").replace(
        '"schema_version":"newsroom.increment6.readiness.v1"',
        '"schema_version":"newsroom.increment6.readiness.v1",'
        '"schema_version":"newsroom.increment6.readiness.v1"',
        1,
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(Increment6ReadinessError, match="duplicate object name"):
        load_increment6_readiness_contract(duplicate_path)

    changed = _record()
    payload = changed["payload"]
    assert isinstance(payload, dict)
    payload["production_activation_authorised"] = True
    changed_path = tmp_path / "changed.json"
    changed_path.write_bytes(canonical_json_bytes(changed))
    with pytest.raises(Increment6ReadinessError, match="reviewed v1"):
        load_increment6_readiness_contract(changed_path)


def test_inherited_symbol_shape_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness_module._authority_execution,
        "NamedAuthorityExecutionReceipt",
        object,
    )
    for symbol in (
        "DecisionTerminality",
        "NextAction",
        "NextActionKind",
        "ReasonBasisClass",
        "StructuredReason",
    ):
        monkeypatch.setattr(readiness_module._discovery, symbol, object)
    monkeypatch.setattr(
        readiness_module._receipt_validation_core,
        "validate_named_authority_receipt",
        lambda **_: None,
    )

    errors = validate_interface_inventory(INCREMENT_6_READINESS)
    assert any("NamedAuthorityExecutionReceipt" in error for error in errors)
    assert all(any(symbol in error for error in errors) for symbol in (
        "DecisionTerminality",
        "NextAction",
        "NextActionKind",
        "ReasonBasisClass",
        "StructuredReason",
    ))
    assert any(
        "_named_tool_authority_receipt_validation_core:"
        "validate_named_authority_receipt" in error
        for error in errors
    )


def test_accepted_v16_history_is_a_prefix_not_a_future_migration_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_history = authority_migrations.EXPECTED_MIGRATION_HISTORY
    future_history = INCREMENT_6_READINESS.accepted_migration_history + (
        (17, "evaluation_handoff_authority_v17", "sha256:" + "f" * 64),
    )
    monkeypatch.setattr(authority_migrations, "SCHEMA_VERSION", 17)
    monkeypatch.setattr(
        authority_migrations,
        "EXPECTED_MIGRATION_HISTORY",
        future_history,
    )
    monkeypatch.setattr(
        authority_migrations,
        "EXPECTED_SCHEMA_FINGERPRINT",
        "sha256:" + "e" * 64,
    )

    assert validate_interface_inventory(INCREMENT_6_READINESS) == ()

    monkeypatch.setattr(authority_migrations, "SCHEMA_VERSION", 18)
    monkeypatch.setattr(
        authority_migrations,
        "EXPECTED_MIGRATION_HISTORY",
        INCREMENT_6_READINESS.accepted_migration_history
        + ((18, "wrong_and_skipped_v17", "not-a-digest"),),
    )
    errors = validate_interface_inventory(INCREMENT_6_READINESS)
    assert any("central suffix versions differ" in error for error in errors)

    monkeypatch.setattr(authority_migrations, "SCHEMA_VERSION", 35)
    monkeypatch.setattr(
        authority_migrations,
        "EXPECTED_MIGRATION_HISTORY",
        (
            *current_history[:-1],
            (33, "unexpected_isolated_v33", "sha256:" + "f" * 64),
            current_history[-1],
        ),
    )
    errors = validate_interface_inventory(INCREMENT_6_READINESS)
    assert any("central suffix versions differ" in error for error in errors)


def test_6r_preserves_the_accepted_history_and_validates_the_live_schema() -> None:
    accepted = INCREMENT_6_READINESS.accepted_migration_history
    assert authority_migrations.SCHEMA_VERSION >= 16
    assert authority_migrations.EXPECTED_MIGRATION_HISTORY[: len(accepted)] == accepted
    assert accepted[-1][0] == 16
    assert accepted[-1][1] == "graphiti_proposal_adapter_v16"

    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        apply_pending_migrations(
            conn,
            applied_at="2042-08-09T12:00:00.000000Z",
        )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == (
            authority_migrations.SCHEMA_VERSION
        )
        assert schema_fingerprint(conn) == (
            authority_migrations.EXPECTED_SCHEMA_FINGERPRINT
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_readiness_views_are_deeply_immutable() -> None:
    with pytest.raises(TypeError):
        INCREMENT_6_READINESS.rollback["history_rewrite_allowed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        INCREMENT_6_READINESS.migration_policy["reserved_versions"][0] = 99  # type: ignore[index]
    with pytest.raises(TypeError):
        INCREMENT_6_READINESS.interface_inventory[0].symbol_digests[
            "RETRIEVAL_CONTEXT_CONTRACT_DIGEST"
        ] = "sha256:00"  # type: ignore[index]


def test_built_wheel_contains_and_loads_all_readiness_resources(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    wheel_dir = tmp_path / "wheel"
    completed = subprocess.run(
        ["uv", "build", "--out-dir", str(wheel_dir)],
        cwd=repository_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    wheels = tuple(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1

    install_root = tmp_path / "installed"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        assert "newsroom/increment6/increment6_readiness_v1.json" in names
        assert "newsroom/increment5/data/increment5a_retrieval_contract_v1.json" in names
        archive.extractall(install_root)

    smoke = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(install_root)!r}); "
                "import newsroom.increment6 as value; "
                "assert value.READINESS_CONTRACT_PATH.is_file(); "
                "assert value.validate_interface_inventory("
                "value.INCREMENT_6_READINESS) == ()"
            ),
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert smoke.returncode == 0, smoke.stderr.decode("utf-8")
