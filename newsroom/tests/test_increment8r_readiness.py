from __future__ import annotations

import json
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5._traceability_model import DEFERRED_TO_INCREMENT_8_REQUIREMENTS
from newsroom.increment8 import (
    INCREMENT_8_READINESS,
    INCREMENT_8_READINESS_DIGEST,
    READINESS_CONTRACT_PATH,
    Increment8ReadinessError,
    load_increment8_readiness_contract,
)

BASE_COMMIT = "2805bd44b234879c3a4b4ee6cab5f700708f7d3a"
BASE_TREE = "522ca79b85e9c879623bbb4d58bbd433e9d6c826"
BASE_FINGERPRINT = (
    "sha256:68194825ecc7c429b283204dbc1332a43481e04ca2681fcbf75886a984ea6f55"
)


def test_readiness_binds_exact_increment7_closeout_and_v29_schema() -> None:
    readiness = INCREMENT_8_READINESS
    assert readiness.issue_number == 462
    assert readiness.parent_issue_number == 148
    assert readiness.accepted_base_commit == BASE_COMMIT
    assert readiness.accepted_base_tree == BASE_TREE
    assert readiness.accepted_schema_version == 29
    assert readiness.accepted_schema_fingerprint == BASE_FINGERPRINT
    assert readiness.contract_digest == INCREMENT_8_READINESS_DIGEST
    assert readiness.contract_digest == digest_bytes(
        READINESS_CONTRACT_PATH.read_bytes()
    )


def test_all_110_increment8_requirements_have_one_owner() -> None:
    owned = [
        requirement
        for allocation in INCREMENT_8_READINESS.allocations
        for requirement in allocation.requirement_ids
    ]
    assert len(owned) == 110
    assert len(owned) == len(set(owned))
    assert set(owned) == set(DEFERRED_TO_INCREMENT_8_REQUIREMENTS)
    assert tuple(
        item.issue_number for item in INCREMENT_8_READINESS.allocations
    ) == tuple(range(462, 469))


def test_numerical_decisions_are_frozen_before_qualification() -> None:
    plan = INCREMENT_8_READINESS.evaluation_plan
    assert plan["case_universe_size"] == 120
    assert plan["required_slice_minimum_cases"] == 12
    assert plan["ordinary_independent_second_review_percent"] == 20
    assert plan["maximum_unresolved_release_disagreements"] == 0
    assert plan["zero_tolerance_counts"]["public_effect"] == 0
    assert plan["thresholds_ppm"]["grouping_precision_min"] == 950_000
    profile = INCREMENT_8_READINESS.operational_profile
    assert profile["schedule"]["interval_seconds"] == 300
    assert profile["retry"]["maximum_attempts"] == 3
    assert profile["execution"]["queue_capacity_items"] == 1000
    assert profile["capacity"]["maximum_external_spend_pence"] == 0


def test_authority_and_dependency_boundaries_are_fail_closed() -> None:
    authority = INCREMENT_8_READINESS.authority
    assert (
        authority["qualification_scope"]
        == "DETERMINISTIC_FIXTURE_REPLAY_AND_DISPOSABLE_ACTUAL_SERVICE_ONLY"
    )
    assert all(
        authority[name] is False
        for name in (
            "production_activation_authorised",
            "live_shadow_authorised",
            "provider_execution_authorised",
            "external_egress_authorised",
            "credential_use_authorised",
        )
    )
    assert authority["external_spend_pence"] == 0
    admission = INCREMENT_8_READINESS.allocation_by_issue[468]
    assert admission.dependencies == (463, 464, 465, 466, 467, 428)
    assert 428 in INCREMENT_8_READINESS.parallel_waves[4]
    assert set(INCREMENT_8_READINESS.exclusions) >= {
        "LIVE_PROVIDER",
        "PRODUCTION_EQUIVALENT_SHADOW",
        "CANARY",
        "PRODUCTION_ACTIVATION",
        "EXTERNAL_NETWORK_EGRESS",
        "LIVE_CREDENTIAL",
    }


def test_migration_reservations_are_contiguous_and_owned() -> None:
    reservations = {
        allocation.issue_number: allocation.migration_version
        for allocation in INCREMENT_8_READINESS.allocations
        if allocation.migration_version is not None
    }
    assert reservations == {463: 30, 465: 31, 467: 32}
    assert (
        INCREMENT_8_READINESS.migration_policy["reservation_is_not_a_migration"] is True
    )
    assert INCREMENT_8_READINESS.migration_policy["merge_order"] == (30, 31, 32)


def test_canonical_bytes_and_any_changed_or_duplicate_record_fail(
    tmp_path: Path,
) -> None:
    raw = READINESS_CONTRACT_PATH.read_bytes()
    document = json.loads(raw)
    assert raw == canonical_json_bytes(document)

    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(document, indent=2), encoding="utf-8")
    with pytest.raises(Increment8ReadinessError, match="canonical JSON"):
        load_increment8_readiness_contract(pretty)

    duplicate = raw.decode().replace(
        '"schema_version":"newsroom.increment8.readiness.v1"',
        '"schema_version":"newsroom.increment8.readiness.v1","schema_version":"newsroom.increment8.readiness.v1"',
        1,
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(Increment8ReadinessError, match="duplicate object name"):
        load_increment8_readiness_contract(duplicate_path)

    document["payload"]["authority"]["live_shadow_authorised"] = True
    changed = tmp_path / "changed.json"
    changed.write_bytes(canonical_json_bytes(document))
    with pytest.raises(Increment8ReadinessError, match="reviewed v1"):
        load_increment8_readiness_contract(changed)
