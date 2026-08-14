from __future__ import annotations

import json
from pathlib import Path

import pytest

import newsroom.increment8.readiness as readiness_module
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5._traceability_model import DEFERRED_TO_INCREMENT_8_REQUIREMENTS
from newsroom.increment8 import (
    INCREMENT_8_READINESS,
    INCREMENT_8_READINESS_DIGEST,
    PRIOR_READINESS_CONTRACT_PATH,
    READINESS_CONTRACT_PATH,
    Increment8ReadinessError,
    load_increment8_readiness_contract,
)

BASE_COMMIT = "2805bd44b234879c3a4b4ee6cab5f700708f7d3a"
BASE_TREE = "522ca79b85e9c879623bbb4d58bbd433e9d6c826"
BASE_FINGERPRINT = (
    "sha256:68194825ecc7c429b283204dbc1332a43481e04ca2681fcbf75886a984ea6f55"
)
PRIOR_READINESS_DIGEST = (
    "sha256:52ad9f2d6022e95d738fe24913db2f379a91f6c945319db613b1b50cdea07d4c"
)

EXPECTED_REQUIRED_SLICES = (
    {
        "slice_id": "GEOGRAPHY_GLOBAL",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.geography",
            "operator": "EQ",
            "value": "GLOBAL",
        },
    },
    {
        "slice_id": "GEOGRAPHY_HONG_KONG",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.geography",
            "operator": "EQ",
            "value": "HONG_KONG",
        },
    },
    {
        "slice_id": "GEOGRAPHY_UNITED_KINGDOM",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.geography",
            "operator": "EQ",
            "value": "UNITED_KINGDOM",
        },
    },
    {
        "slice_id": "LANGUAGE_EN_GB",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.language",
            "operator": "EQ",
            "value": "EN_GB",
        },
    },
    {
        "slice_id": "LANGUAGE_MIXED_EN_GB_ZH_HANT_HK",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.language",
            "operator": "EQ",
            "value": "MIXED_EN_GB_ZH_HANT_HK",
        },
    },
    {
        "slice_id": "LANGUAGE_ZH_HANT_HK",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.language",
            "operator": "EQ",
            "value": "ZH_HANT_HK",
        },
    },
    {
        "slice_id": "SOURCE_MULTI_DOMAIN_CORROBORATED",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "source_evidence.distinct_domain_count",
            "operator": "GTE",
            "value": 2,
        },
    },
    {
        "slice_id": "TRANSITION_FAILURE_HEAVY",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "fixture.injected_failure_count",
            "operator": "GTE",
            "value": 2,
        },
    },
    {
        "slice_id": "URGENCY_URGENT",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "case_metadata.urgency",
            "operator": "EQ",
            "value": "URGENT",
        },
    },
)

EXPECTED_CASE_STRATA = (
    {
        "stratum_id": "NEGATIVE",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "expected.candidate_outcome",
            "operator": "EQ",
            "value": "NO_CANDIDATE",
        },
    },
    {
        "stratum_id": "UNCHANGED",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "expected.transition_outcome",
            "operator": "EQ",
            "value": "UNCHANGED",
        },
    },
    {
        "stratum_id": "FAILURE_HEAVY",
        "minimum_completed_cases": 12,
        "membership_rule": {
            "field": "fixture.injected_failure_count",
            "operator": "GTE",
            "value": 2,
        },
    },
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


def test_corrective_contract_is_additive_and_preserves_the_reviewed_v1_record() -> None:
    readiness = INCREMENT_8_READINESS
    assert readiness.schema_version == "newsroom.increment8.readiness.v2"
    assert readiness.contract_version == "increment8-readiness-v2"
    assert digest_bytes(PRIOR_READINESS_CONTRACT_PATH.read_bytes()) == (
        PRIOR_READINESS_DIGEST
    )
    assert readiness.superseded_contract_digest == PRIOR_READINESS_DIGEST
    assert readiness.correction_base_commit == (
        "1c03102dde3a666cf72ee97197bbf339e42f5b4e"
    )
    assert readiness.correction_base_tree == (
        "6ea8893cb1f5a0a33d6bf94abced81c9cea9a59c"
    )
    assert readiness.correction_base_schema_version == 32
    allocation = readiness.allocation_by_issue[462]
    assert allocation.schema_ids == (
        "newsroom.increment8.8r.v1",
        "newsroom.increment8.8r.v2",
    )
    assert "FROZEN_SLICE_AND_STRATUM_POLICY" in allocation.interface_ownership
    assert "MIGRATION_HISTORY_POLICY" in allocation.interface_ownership


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


def test_required_slice_and_case_stratum_membership_is_exact_and_pre_result() -> None:
    plan = INCREMENT_8_READINESS.evaluation_plan
    assert plan["required_slice_manifest"] == EXPECTED_REQUIRED_SLICES
    assert plan["case_strata_manifest"] == EXPECTED_CASE_STRATA
    assert plan["required_slice_policy"] == {
        "all_manifest_slices_required_for_release": True,
        "case_may_match_multiple_slices": True,
        "counting_unit": "DISTINCT_CASE_DIGEST_PER_SLICE",
        "invented_slices_allowed": False,
        "membership_changes_after_first_result_allowed": False,
        "membership_evaluated_from": "FROZEN_CASE_INPUT_MANIFEST_BEFORE_RESULT",
        "policy_changes_after_first_result_allowed": False,
    }
    assert plan["case_strata_policy"] == {
        "all_manifest_strata_required_for_release": True,
        "case_may_match_multiple_strata": True,
        "counting_unit": "DISTINCT_CASE_DIGEST_PER_STRATUM",
        "invented_strata_allowed": False,
        "membership_changes_after_first_result_allowed": False,
        "membership_evaluated_from": "FROZEN_CASE_INPUT_MANIFEST_BEFORE_RESULT",
        "policy_changes_after_first_result_allowed": False,
    }
    # The original lower bound remains frozen, but never waives any named slice.
    assert plan["qualification_exposure"]["minimum_completed_required_slices"] == 8
    assert len(plan["required_slice_manifest"]) == 9


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
    assert (
        INCREMENT_8_READINESS.migration_policy["additive_migrations_only"] is True
    )
    assert (
        INCREMENT_8_READINESS.migration_policy["history_preservation_required"]
        is True
    )
    assert INCREMENT_8_READINESS.migration_policy["policy_versions"] == (30, 31, 32)


def _load_changed_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, object],
) -> None:
    changed = canonical_json_bytes(document)
    path = tmp_path / "changed-contract.json"
    path.write_bytes(changed)
    monkeypatch.setattr(
        readiness_module, "EXPECTED_READINESS_DIGEST", digest_bytes(changed)
    )
    load_increment8_readiness_contract(path)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (
        ("missing_slice", "required slice manifest differs"),
        ("altered_slice", "required slice manifest differs"),
        ("duplicate_slice", "required slice manifest differs"),
        ("invented_slice", "required slice manifest differs"),
        ("missing_stratum", "Case stratum manifest differs"),
        ("altered_stratum", "Case stratum manifest differs"),
        ("duplicate_stratum", "Case stratum manifest differs"),
        ("invented_stratum", "Case stratum manifest differs"),
        ("post_result_slice_policy", "required slice policy differs"),
        ("post_result_stratum_policy", "Case stratum policy differs"),
        ("destructive_migration", "migration policy must remain additive"),
        ("history_rewrite", "migration history preservation is required"),
    ),
)
def test_slice_stratum_timing_and_migration_policy_tamper_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_error: str,
) -> None:
    document = json.loads(READINESS_CONTRACT_PATH.read_bytes())
    plan = document["payload"]["evaluation_plan"]
    slices = plan["required_slice_manifest"]
    strata = plan["case_strata_manifest"]
    if mutation == "missing_slice":
        slices.pop()
    elif mutation == "altered_slice":
        slices[0]["membership_rule"]["value"] = "AFTER_RESULTS"
    elif mutation == "duplicate_slice":
        slices.append(slices[0])
    elif mutation == "invented_slice":
        slices.append(
            {
                "slice_id": "INVENTED_PASSING_SLICE",
                "minimum_completed_cases": 12,
                "membership_rule": {
                    "field": "result.passed",
                    "operator": "EQ",
                    "value": True,
                },
            }
        )
    elif mutation == "missing_stratum":
        strata.pop()
    elif mutation == "altered_stratum":
        strata[0]["membership_rule"]["value"] = "PASS"
    elif mutation == "duplicate_stratum":
        strata.append(strata[0])
    elif mutation == "invented_stratum":
        strata.append(
            {
                "stratum_id": "POST_RESULT_PASS",
                "minimum_completed_cases": 12,
                "membership_rule": {
                    "field": "result.passed",
                    "operator": "EQ",
                    "value": True,
                },
            }
        )
    elif mutation == "post_result_slice_policy":
        plan["required_slice_policy"][
            "policy_changes_after_first_result_allowed"
        ] = True
    elif mutation == "post_result_stratum_policy":
        plan["case_strata_policy"][
            "membership_changes_after_first_result_allowed"
        ] = True
    elif mutation == "destructive_migration":
        document["payload"]["migration_policy"]["additive_migrations_only"] = False
    elif mutation == "history_rewrite":
        document["payload"]["migration_policy"][
            "history_preservation_required"
        ] = False
    with pytest.raises(Increment8ReadinessError, match=expected_error):
        _load_changed_document(tmp_path, monkeypatch, document)


@pytest.mark.parametrize(
    ("section", "path", "value", "expected_error"),
    (
        (
            "evaluation_plan",
            ("case_universe_size",),
            121,
            "accepted numerical Evaluation Plan differs",
        ),
        (
            "operational_profile",
            ("execution", "queue_capacity_items"),
            1001,
            "accepted numerical Operational Profile differs",
        ),
    ),
)
def test_previously_accepted_numerical_values_cannot_be_reselected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    path: tuple[str, ...],
    value: int,
    expected_error: str,
) -> None:
    document = json.loads(READINESS_CONTRACT_PATH.read_bytes())
    target = document["payload"][section]
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(Increment8ReadinessError, match=expected_error):
        _load_changed_document(tmp_path, monkeypatch, document)


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
        '"schema_version":"newsroom.increment8.readiness.v2"',
        '"schema_version":"newsroom.increment8.readiness.v2","schema_version":"newsroom.increment8.readiness.v2"',
        1,
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(Increment8ReadinessError, match="duplicate object name"):
        load_increment8_readiness_contract(duplicate_path)

    document["payload"]["authority"]["live_shadow_authorised"] = True
    changed = tmp_path / "changed.json"
    changed.write_bytes(canonical_json_bytes(document))
    with pytest.raises(Increment8ReadinessError, match="reviewed v2"):
        load_increment8_readiness_contract(changed)
